"""version: 1.0.2
description: Tests for subscription and payment infrastructure.
updated: 2026-05-17
"""

from pathlib import Path
from types import SimpleNamespace

from pydantic import SecretStr

from app.api.main import create_app
from app.bot.main import create_bot, create_dispatcher
from app.core.config import Settings
from app.models.subscriptions import Payment


class FakeAsyncSession:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakeRequest:
    def __init__(
        self,
        payload: dict | None = None,
        *,
        headers: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload or {}
        self.headers = headers or {}
        self.query_params = query_params or {}
        self.client = SimpleNamespace(host="127.0.0.1")

    async def json(self) -> dict:
        return self._payload


def test_api_imports_successfully() -> None:
    """API module should import without errors."""
    app = create_app()
    assert app is not None
    assert app.title == "Seller Profit Bot API"
    assert app.version == Path("VERSION").read_text(encoding="utf-8").strip()


def test_bot_imports_successfully() -> None:
    """Bot module should import without errors."""
    dispatcher = create_dispatcher()
    assert dispatcher is not None


def test_bot_uses_html_parse_mode_by_default() -> None:
    """Telegram HTML templates should render as markup, not raw tags."""
    bot = create_bot()
    assert str(bot.default.parse_mode) == "ParseMode.HTML"


def test_subscription_router_registered() -> None:
    """Subscription router should be registered in bot."""
    from app.bot.handlers.subscription import router as subscription_router

    assert subscription_router is not None
    assert subscription_router.name == "subscription"


def test_webhooks_router_registered() -> None:
    """Webhooks router should be registered in API."""
    app = create_app()
    routes = [route.path for route in app.routes]
    assert "/webhooks/yookassa" in routes


def test_payment_success_page_exists() -> None:
    """Payment success return URL should exist and return 200."""
    import asyncio

    from app.web.route_modules.payment_public import payment_success

    response = asyncio.run(
        payment_success(request=FakeRequest(), session=FakeAsyncSession(), payment_id=None)
    )

    assert response.status_code == 200
    text = response.body.decode("utf-8")
    assert "Платёж принят" in text
    assert "активируется автоматически" in text.lower()


def test_payment_cancel_page_exists() -> None:
    """Payment cancel return URL should exist and return 200."""
    import asyncio

    from app.web.route_modules.payment_public import payment_cancel

    response = asyncio.run(
        payment_cancel(request=FakeRequest(), session=FakeAsyncSession(), payment_id=None)
    )

    assert response.status_code == 200
    assert "Платёж отменён" in response.body.decode("utf-8")


def test_public_payment_routes_not_under_web_prefix() -> None:
    """Payment return routes must be public (outside /web prefix)."""
    app = create_app()
    routes = [route.path for route in app.routes]
    assert "/payment/success" in routes
    assert "/payment/cancel" in routes


def test_webhook_route_structure() -> None:
    """Webhook route should be properly structured."""
    from app.api.webhooks import router as webhooks_router

    assert webhooks_router.prefix == "/webhooks"
    routes = [route.path for route in webhooks_router.routes]
    assert "/webhooks/yookassa" in routes


def test_yookassa_webhook_rejects_invalid_secret(monkeypatch) -> None:
    """Configured YooKassa webhook secret must be provided by caller."""
    import asyncio

    import pytest

    from app.api import webhooks as webhooks_module

    monkeypatch.setattr(
        webhooks_module,
        "get_settings",
        lambda: Settings(yookassa_webhook_secret=SecretStr("expected-secret")),
    )

    with pytest.raises(webhooks_module.HTTPException) as exc_info:
        asyncio.run(
            webhooks_module.yookassa_webhook(
                request=FakeRequest(
                    {
                        "type": "notification",
                        "event": "payment.succeeded",
                        "object": {"id": "yk-test-123", "status": "succeeded", "paid": True},
                    },
                    headers={"x-yookassa-webhook-secret": "wrong-secret"},
                ),
                session=FakeAsyncSession(),
            )
        )

    assert exc_info.value.status_code == 403


def test_yookassa_webhook_rejects_missing_secret_by_default(monkeypatch) -> None:
    """YooKassa webhook без настроенного секрета должен закрываться отказом."""
    import asyncio

    import pytest

    from app.api import webhooks as webhooks_module

    monkeypatch.setattr(webhooks_module, "get_settings", lambda: Settings())

    with pytest.raises(webhooks_module.HTTPException) as exc_info:
        asyncio.run(
            webhooks_module.yookassa_webhook(
                request=FakeRequest(
                    {
                        "type": "notification",
                        "event": "payment.succeeded",
                        "object": {"id": "yk-test-123", "status": "succeeded", "paid": True},
                    }
                ),
                session=FakeAsyncSession(),
            )
        )

    assert exc_info.value.status_code == 403


def test_yookassa_webhook_allows_explicit_insecure_dev_mode(monkeypatch) -> None:
    """Dev/test insecure mode работает только при явном включении."""
    import asyncio

    from app.api import webhooks as webhooks_module

    handled: list[dict] = []

    async def fake_handle_success(self, payment_data):
        handled.append(payment_data)

    monkeypatch.setattr(
        webhooks_module,
        "get_settings",
        lambda: Settings(app_env="local", webhook_allow_insecure_dev=True),
    )
    monkeypatch.setattr(
        "app.services.payment_service.PaymentService.handle_payment_success",
        fake_handle_success,
    )

    response = asyncio.run(
        webhooks_module.yookassa_webhook(
            request=FakeRequest(
                {
                    "type": "notification",
                    "event": "payment.succeeded",
                    "object": {"id": "yk-test-123", "status": "succeeded", "paid": True},
                }
            ),
            session=FakeAsyncSession(),
        )
    )

    assert response == {"status": "ok"}
    assert handled[0]["id"] == "yk-test-123"


def test_yookassa_webhook_does_not_accept_query_secret(monkeypatch) -> None:
    """Секрет webhook должен приниматься только из header."""
    import asyncio

    import pytest

    from app.api import webhooks as webhooks_module

    monkeypatch.setattr(
        webhooks_module,
        "get_settings",
        lambda: Settings(yookassa_webhook_secret=SecretStr("expected-secret")),
    )

    with pytest.raises(webhooks_module.HTTPException) as exc_info:
        asyncio.run(
            webhooks_module.yookassa_webhook(
                request=FakeRequest(
                    {
                        "type": "notification",
                        "event": "payment.succeeded",
                        "object": {"id": "yk-test-123", "status": "succeeded", "paid": True},
                    },
                    query_params={"secret": "expected-secret"},
                ),
                session=FakeAsyncSession(),
            )
        )

    assert exc_info.value.status_code == 403


def test_yookassa_webhook_accepts_valid_secret(monkeypatch) -> None:
    """Valid YooKassa webhook secret should allow normal payment handling."""
    import asyncio

    from app.api import webhooks as webhooks_module

    handled: list[dict] = []

    async def fake_handle_success(self, payment_data):
        handled.append(payment_data)

    monkeypatch.setattr(
        webhooks_module,
        "get_settings",
        lambda: Settings(yookassa_webhook_secret=SecretStr("expected-secret")),
    )
    monkeypatch.setattr(
        "app.services.payment_service.PaymentService.handle_payment_success",
        fake_handle_success,
    )

    response = asyncio.run(
        webhooks_module.yookassa_webhook(
            request=FakeRequest(
                {
                    "type": "notification",
                    "event": "payment.succeeded",
                    "object": {"id": "yk-test-123", "status": "succeeded", "paid": True},
                },
                headers={"x-yookassa-webhook-secret": "expected-secret"},
            ),
            session=FakeAsyncSession(),
        )
    )

    assert response == {"status": "ok"}
    assert handled[0]["id"] == "yk-test-123"


def test_middleware_registered() -> None:
    """Logging middleware should be registered."""
    app = create_app()
    # Middleware is registered if app has user_middleware
    assert hasattr(app, "user_middleware")
    assert len(app.user_middleware) > 0


def test_payment_model_and_corrective_migration_include_payment_metadata() -> None:
    """Production schema drift should be repaired by an idempotent migration."""

    assert "payment_metadata" in Payment.__table__.columns
    migration = "migrations/versions/20260517_0014_ensure_payment_metadata_column.py"
    with open(migration, encoding="utf-8") as file:
        text = file.read()
    assert "ADD COLUMN IF NOT EXISTS payment_metadata JSON" in text
    assert "non-destructive" in text
