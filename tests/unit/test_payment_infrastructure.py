"""version: 1.0.2
description: Tests for subscription and payment infrastructure.
updated: 2026-05-17
"""

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.bot.main import create_bot, create_dispatcher


def test_api_imports_successfully() -> None:
    """API module should import without errors."""
    app = create_app()
    assert app is not None
    assert app.title == "Seller Profit Bot API"
    assert app.version == "1.6.3"


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
    app = create_app()
    client = TestClient(app)
    response = client.get("/web/payment/success")
    assert response.status_code == 200
    assert "Платёж принят" in response.text
    assert "подписка активируется автоматически" in response.text.lower()


def test_webhook_route_structure() -> None:
    """Webhook route should be properly structured."""
    from app.api.webhooks import router as webhooks_router

    assert webhooks_router.prefix == "/webhooks"
    routes = [route.path for route in webhooks_router.routes]
    assert "/webhooks/yookassa" in routes


def test_middleware_registered() -> None:
    """Logging middleware should be registered."""
    app = create_app()
    # Middleware is registered if app has user_middleware
    assert hasattr(app, "user_middleware")
    assert len(app.user_middleware) > 0
