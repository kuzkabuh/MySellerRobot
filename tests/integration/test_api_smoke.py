"""version: 1.7.0
description: Smoke tests for API, bot, worker, package startup, and web navigation.
updated: 2026-05-15
"""

import importlib.util
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.main import create_app
from app.bot.main import create_dispatcher
from app.core.config import Settings
from app.web.routes import dashboard_compat, double_web_compat, login
from app.workers.settings import WorkerSettings


class FakeAsyncSession:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def test_create_app() -> None:
    app = create_app()

    assert app.title == "Seller Profit Bot API"
    assert app.version == "1.6.2"


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
