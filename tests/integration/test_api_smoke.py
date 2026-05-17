"""version: 1.7.0
description: Smoke tests for API, bot, worker, package startup, web login, and navigation.
updated: 2026-05-17
"""

import importlib.util
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.bot.main import create_dispatcher
from app.core.config import Settings
from app.core.db import get_session
from app.models.enums import UserStatus
from app.services.web_auth_service import WEB_SESSION_COOKIE
from app.services.web_dashboard_service import DashboardData, build_dashboard_filters
from app.web.routes import dashboard_compat, double_web_compat, login
from app.workers.settings import WorkerSettings


class FakeAsyncSession:
    async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return EmptyResult()

    async def get(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return None

    def add(self, _value) -> None:  # type: ignore[no-untyped-def]
        return None

    async def flush(self) -> None:
        return None

    async def refresh(self, *_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class EmptyResult:
    def scalar_one_or_none(self):  # type: ignore[no-untyped-def]
        return None

    def scalar_one(self) -> int:
        return 0

    def scalars(self):  # type: ignore[no-untyped-def]
        return self

    def all(self) -> list[object]:
        return []

    def first(self):  # type: ignore[no-untyped-def]
        return None


def test_create_app() -> None:
    app = create_app()

    assert app.title == "Seller Profit Bot API"
    assert app.version == "1.6.3"


def test_web_shell_contains_material_design_tokens() -> None:
    from app.web.rendering import page

    html = page("Дашборд", "Артем", '<section class="kpi-grid"></section>')

    assert "--primary" in html
    assert "--surface" in html
    assert "kpi-grid" in html
    assert "dashboard-grid" in html
    assert "table-wrap" in html


def test_web_routes_are_registered() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/web/login" in paths
    assert "/web/" in paths
    assert "/web/orders" in paths
    assert "/web/orders/{order_id}" in paths
    assert "/web/profit" in paths
    assert "/web/sales" in paths
    assert "/web/returns" in paths
    assert "/web/products" in paths
    assert "/web/products/{master_product_id}" in paths
    assert "/web/product-matching" in paths
    assert "/web/costs" in paths
    assert "/web/costs/{product_id}" in paths
    assert "/web/plan-fact" in paths
    assert "/web/break-even" in paths
    assert "/web/stocks" in paths
    assert "/web/alerts" in paths
    assert "/web/analytics" in paths
    assert "/web/control" in paths
    assert "/web/data-quality" in paths
    assert "/web/profile" in paths
    assert "/web/subscription" in paths
    assert "/web/accounts" in paths
    assert "/web/settings" in paths
    assert "/web/web/login" in paths
    assert "/web/web" in paths
    assert "/web/web/" in paths
    assert "/web/logout" in paths


def test_web_login_token_flow_renders_empty_free_dashboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()

    async def fake_get_session():  # type: ignore[no-untyped-def]
        yield FakeAsyncSession()

    async def fake_consume(self, token, *, ip_address, user_agent):  # type: ignore[no-untyped-def]
        assert token == "valid-token"
        return SimpleNamespace(
            token="web-session-token",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        )

    async def fake_active_session_user(self, session_hash):  # type: ignore[no-untyped-def]
        assert session_hash
        return SimpleNamespace(
            id=1,
            telegram_id=123456789,
            username="seller",
            first_name="Артем",
            timezone="Europe/Moscow",
            language="ru",
            status=UserStatus.ACTIVE,
            notifications_enabled=True,
            low_margin_threshold_percent=10,
            created_at=datetime(2026, 5, 17, tzinfo=UTC),
        )

    async def fake_dashboard(
        self,
        *,
        user_id,
        timezone,
        period,
        marketplace,
        sale_model,
        date_from,
        date_to,
    ):  # type: ignore[no-untyped-def]
        assert user_id == 1
        filters = build_dashboard_filters(
            timezone=timezone,
            period=period,
            marketplace=marketplace,
            sale_model=sale_model,
            date_from=date_from,
            date_to=date_to,
        )
        return DashboardData(
            filters=filters,
            metrics=[],
            points=[],
            marketplace_breakdown=[],
            actual_profit=Decimal("0"),
        )

    app.dependency_overrides[get_session] = fake_get_session
    monkeypatch.setattr(
        "app.services.web_auth_service.WebAuthService.consume_login_token",
        fake_consume,
    )
    monkeypatch.setattr(
        "app.repositories.web_auth.WebAuthRepository.get_active_session_user",
        fake_active_session_user,
    )
    monkeypatch.setattr(
        "app.services.web_dashboard_service.WebDashboardService.dashboard",
        fake_dashboard,
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        login_response = client.get("/web/login?token=valid-token", follow_redirects=False)

        assert login_response.status_code == 303
        assert login_response.headers["location"] == "/web/"
        assert WEB_SESSION_COOKIE in login_response.cookies

        dashboard_response = client.get("/web/")

    app.dependency_overrides.clear()

    assert dashboard_response.status_code == 200
    assert "Добро пожаловать, Артем" in dashboard_response.text
    assert "FREE" in dashboard_response.text
    assert "Пульс бизнеса" in dashboard_response.text
    assert "Wildberries / Ozon" in dashboard_response.text
    assert "Internal Server Error" not in dashboard_response.text
    assert "Раздел подготовлен" not in dashboard_response.text


def test_web_unhandled_exception_returns_controlled_html_error() -> None:
    app = create_app()

    @app.get("/web-login-crash")
    async def web_test_crash() -> None:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/web-login-crash")

    assert response.status_code == 500
    assert "Ошибка web-кабинета" in response.text
    assert "Internal Server Error" not in response.text


@pytest.mark.asyncio
async def test_web_login_without_token_returns_russian_error() -> None:
    response = await login(request=SimpleNamespace(), session=FakeAsyncSession(), token=None)

    assert response.status_code == 400
    assert "Ссылка недействительна" in response.body.decode()


@pytest.mark.asyncio
async def test_web_login_valid_token_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_consume(self, token, *, ip_address, user_agent):  # type: ignore[no-untyped-def]
        assert token == "valid-token"
        return SimpleNamespace(
            token="web-session-token",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        )

    monkeypatch.setattr(
        "app.services.web_auth_service.WebAuthService.consume_login_token",
        fake_consume,
    )

    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )
    response = await login(request=request, session=FakeAsyncSession(), token="valid-token")

    assert response.status_code == 303
    assert response.headers["location"] == "/web/"
    assert response.headers["location"] != "/web/web"
    assert "Path=/" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_legacy_double_web_dashboard_route_renders_not_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_dashboard(*args, **kwargs):  # type: ignore[no-untyped-def]
        return "<html>Кабинет</html>"

    monkeypatch.setattr("app.web.routes.dashboard", fake_dashboard)

    response = await dashboard_compat(user=object(), session=object())

    assert "Кабинет" in response


@pytest.mark.asyncio
async def test_legacy_double_web_sections_are_served_for_old_proxy_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sales_page(*args, **kwargs):  # type: ignore[no-untyped-def]
        return "<html>Продажи без заглушки</html>"

    monkeypatch.setattr("app.web.routes.sales_page", fake_sales_page)

    user = SimpleNamespace(
        id=1,
        timezone="Europe/Moscow",
        first_name="Тест",
        username="seller",
        telegram_id=123456,
    )
    request = SimpleNamespace(url=SimpleNamespace(path="/web/web/sales"), query_params={})

    response = await double_web_compat(
        section="sales",
        request=request,
        user=user,
        session=object(),
    )

    assert response.status_code == 200
    body = response.body.decode()
    assert "Продажи" in body
    assert "Раздел подготовлен" not in body


@pytest.mark.asyncio
async def test_unknown_double_web_section_returns_russian_404() -> None:
    user = SimpleNamespace(
        id=1,
        timezone="Europe/Moscow",
        first_name="Тест",
        username="seller",
        telegram_id=123456,
    )
    request = SimpleNamespace(
        url=SimpleNamespace(path="/web/web/missing-section"),
        query_params={},
    )

    with pytest.raises(HTTPException) as exc_info:
        await double_web_compat(
            section="missing-section",
            request=request,
            user=user,
            session=object(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Раздел не найден"


def test_app_package_discovery_includes_utility_package() -> None:
    assert importlib.util.find_spec("app") is not None
    assert importlib.util.find_spec("app.utils") is not None


def test_bot_dispatcher_factory_registers_routers_without_polling() -> None:
    dispatcher = create_dispatcher()

    assert [router.name for router in dispatcher.sub_routers] == [
        "accounts",
        "costs",
        "subscription",
        "common",
    ]


def test_worker_settings_register_expected_tasks() -> None:
    function_names = {function.__name__ for function in WorkerSettings.functions}

    assert "poll_new_orders" in function_names
    assert "process_history_backfills" in function_names
    assert WorkerSettings.cron_jobs


def test_settings_expose_history_backfill_defaults() -> None:
    settings = Settings()

    assert settings.backfill_default_days == 30
    assert settings.backfill_chunk_days == 7
