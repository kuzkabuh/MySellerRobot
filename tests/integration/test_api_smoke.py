"""version: 1.7.0
description: Smoke tests for API, bot, worker, package startup, web login, and navigation.
updated: 2026-05-17
"""

import importlib.util
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.bot.main import create_dispatcher
from app.core.config import Settings
from app.core.db import get_session
from app.models.enums import Marketplace, UserStatus
from app.services.web_auth_service import WEB_SESSION_COOKIE
from app.services.web_dashboard_service import DashboardData, build_dashboard_filters
from app.services.web_orders_profit_service import (
    ProfitPageData,
    ProfitSummary,
    build_order_web_filters,
)
from app.web.dependencies import current_web_user
from app.web.routes import double_web_compat, login
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


def _web_user() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        telegram_id=123456789,
        username="seller",
        first_name="Артем",
        timezone="Europe/Moscow",
        language="ru",
        status=UserStatus.ACTIVE,
        notifications_enabled=True,
        low_margin_threshold_percent=Decimal("10"),
        created_at=datetime(2026, 5, 17, tzinfo=UTC),
    )


def _free_tier() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        code="free",
        name="FREE",
        description="Бесплатный тариф",
        price_monthly=Decimal("0"),
        price_yearly=Decimal("0"),
        max_marketplace_accounts=1,
        max_orders_per_month=100,
        max_products=100,
        feature_web_cabinet=True,
        feature_analytics=False,
        feature_plan_fact=False,
        feature_break_even=False,
        feature_stock_forecast=False,
        feature_alerts=False,
        feature_api_access=False,
        feature_priority_support=False,
    )


def _redirect_chain(
    client: TestClient,
    path: str,
    *,
    limit: int = 8,
) -> list[tuple[str, int, str | None]]:
    chain: list[tuple[str, int, str | None]] = []
    current = path
    seen: set[str] = set()
    for _ in range(limit):
        response = client.get(current, follow_redirects=False)
        location = response.headers.get("location")
        chain.append((current, response.status_code, location))
        if response.status_code not in {301, 302, 303, 307, 308} or not location:
            break
        if location in seen:
            chain.append((location, 0, "LOOP"))
            break
        seen.add(location)
        current = location
    return chain


def _patch_empty_web_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_dashboard(self, **kwargs):  # type: ignore[no-untyped-def]
        filters = build_dashboard_filters(
            timezone=kwargs["timezone"],
            period=kwargs["period"],
            marketplace=kwargs["marketplace"],
            sale_model=kwargs["sale_model"],
            date_from=kwargs.get("date_from"),
            date_to=kwargs.get("date_to"),
        )
        return DashboardData(
            filters=filters,
            metrics=[],
            points=[],
            marketplace_breakdown=[],
            actual_profit=Decimal("0"),
        )

    async def fake_subscription_page(self, user_id, timezone="Europe/Moscow"):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            tier=_free_tier(),
            active_subscription=None,
            payments=[],
            used_accounts=0,
            used_orders_month=0,
            used_products=0,
        )

    async def fake_accounts_page(self, user_id, timezone="Europe/Moscow"):  # type: ignore[no-untyped-def]
        return SimpleNamespace(tier=_free_tier(), active_accounts=0, rows=[])

    async def fake_get_all_tiers(self):  # type: ignore[no-untyped-def]
        return [_free_tier()]

    async def fake_list_orders(self, **kwargs):  # type: ignore[no-untyped-def]
        filters = build_order_web_filters(
            timezone=kwargs["timezone"],
            period=kwargs["period"],
            marketplace=kwargs["marketplace"],
            sale_model=kwargs["sale_model"],
            date_from=kwargs.get("date_from"),
            date_to=kwargs.get("date_to"),
            economy=kwargs.get("economy", "all"),
            status=kwargs.get("status", "all"),
            sku=kwargs.get("sku", ""),
            sort=kwargs.get("sort", "date"),
            direction=kwargs.get("direction", "desc"),
        )
        return filters, []

    async def fake_profit_by_sku(self, **kwargs):  # type: ignore[no-untyped-def]
        filters = build_order_web_filters(
            timezone=kwargs["timezone"],
            period=kwargs["period"],
            marketplace=kwargs["marketplace"],
            sale_model=kwargs["sale_model"],
            date_from=kwargs.get("date_from"),
            date_to=kwargs.get("date_to"),
            economy=kwargs.get("economy", "all"),
            status="all",
            sku=kwargs.get("sku", ""),
            sort=kwargs.get("sort", "profit"),
            direction=kwargs.get("direction", "desc"),
        )
        return ProfitPageData(
            filters=filters,
            summary=ProfitSummary(
                estimated_profit=Decimal("0"),
                actual_profit=Decimal("0"),
                deviation=Decimal("0"),
                average_unit_profit=Decimal("0"),
                average_margin=Decimal("0"),
                roi_percent=None,
            ),
            rows=[],
        )

    async def fake_list_analytics(self, user_id):  # type: ignore[no-untyped-def]
        return []

    async def fake_costs_page(self, user_id):  # type: ignore[no-untyped-def]
        return SimpleNamespace(rows=[], missing_count=0, configured_count=0)

    monkeypatch.setattr(
        "app.services.web_dashboard_service.WebDashboardService.dashboard",
        fake_dashboard,
    )
    monkeypatch.setattr(
        "app.services.web_cabinet_service.WebCabinetService.subscription_page",
        fake_subscription_page,
    )
    monkeypatch.setattr(
        "app.services.web_cabinet_service.WebCabinetService.accounts_page",
        fake_accounts_page,
    )
    monkeypatch.setattr(
        "app.services.subscription_service.SubscriptionService.get_all_tiers",
        fake_get_all_tiers,
    )
    monkeypatch.setattr(
        "app.services.web_orders_profit_service.WebOrdersProfitService.list_orders",
        fake_list_orders,
    )
    monkeypatch.setattr(
        "app.services.web_orders_profit_service.WebOrdersProfitService.profit_by_sku",
        fake_profit_by_sku,
    )
    monkeypatch.setattr(
        "app.services.master_product_service.MasterProductService.list_analytics",
        fake_list_analytics,
    )
    monkeypatch.setattr(
        "app.services.web_cabinet_service.WebCabinetService.costs_page",
        fake_costs_page,
    )


def test_create_app() -> None:
    app = create_app()

    assert app.title == "Seller Profit Bot API"
    assert app.version == "1.7.0"


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

        assert login_response.status_code == 200
        assert "Вход выполнен" in login_response.text
        assert 'href="/web/"' in login_response.text
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


def test_web_login_cookie_allows_internal_navigation_without_redirect_loop(
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
        return _web_user()

    _patch_empty_web_pages(monkeypatch)
    app.dependency_overrides[get_session] = fake_get_session
    monkeypatch.setattr(
        "app.services.web_auth_service.WebAuthService.consume_login_token",
        fake_consume,
    )
    monkeypatch.setattr(
        "app.repositories.web_auth.WebAuthRepository.get_active_session_user",
        fake_active_session_user,
    )

    internal_paths = [
        "/web/accounts",
        "/web/profile",
        "/web/subscription",
        "/web/orders",
        "/web/products",
        "/web/profit",
        "/web/costs",
        "/web/settings",
    ]
    with TestClient(app, raise_server_exceptions=True) as client:
        login_response = client.get("/web/login?token=valid-token", follow_redirects=False)
        assert login_response.status_code == 200
        assert "Вход выполнен" in login_response.text
        assert WEB_SESSION_COOKIE in login_response.cookies

        dashboard_response = client.get("/web/", follow_redirects=False)
        assert dashboard_response.status_code == 200

        for path in internal_paths:
            chain = _redirect_chain(client, path)
            assert chain == [(path, 200, None)]
            response = client.get(path, follow_redirects=False)
            assert "/web/web/" not in response.text

    app.dependency_overrides.clear()


def test_web_unauthorized_internal_route_does_not_loop() -> None:
    app = create_app()

    with TestClient(app, raise_server_exceptions=True) as client:
        chain = _redirect_chain(client, "/web/accounts")

    assert chain == [("/web/accounts", 401, None)]


@pytest.mark.parametrize("path", ["/web/accounts", "/web/accounts/"])
def test_web_trailing_slash_routes_do_not_loop(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()

    async def fake_get_session():  # type: ignore[no-untyped-def]
        yield FakeAsyncSession()

    async def fake_current_web_user():  # type: ignore[no-untyped-def]
        return _web_user()

    async def fake_accounts_page(self, user_id, timezone="Europe/Moscow"):  # type: ignore[no-untyped-def]
        return SimpleNamespace(tier=_free_tier(), active_accounts=0, rows=[])

    app.dependency_overrides[get_session] = fake_get_session
    app.dependency_overrides[current_web_user] = fake_current_web_user
    monkeypatch.setattr(
        "app.services.web_cabinet_service.WebCabinetService.accounts_page",
        fake_accounts_page,
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        chain = _redirect_chain(client, path)

    app.dependency_overrides.clear()

    locations = [location for _, _, location in chain if location is not None]
    assert len(locations) == len(set(locations))
    assert len(chain) <= 2


def test_web_profit_and_analytics_pages_render_with_canonical_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    user = SimpleNamespace(
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

    async def fake_get_session():  # type: ignore[no-untyped-def]
        yield FakeAsyncSession()

    async def fake_current_web_user():  # type: ignore[no-untyped-def]
        return user

    async def fake_profit_by_sku(
        self,
        *,
        user_id,
        timezone,
        period,
        marketplace,
        sale_model,
        date_from,
        date_to,
        economy="all",
        sku="",
        sort="profit",
        direction="desc",
        limit=100,
    ):  # type: ignore[no-untyped-def]
        order_filters = build_order_web_filters(
            timezone=timezone,
            period=period,
            marketplace=marketplace,
            sale_model=sale_model,
            date_from=date_from,
            date_to=date_to,
            economy=economy,
            status="all",
            sku=sku,
            sort=sort,
            direction=direction,
        )
        return ProfitPageData(
            filters=order_filters,
            summary=ProfitSummary(
                estimated_profit=Decimal("0"),
                actual_profit=Decimal("0"),
                deviation=Decimal("0"),
                average_unit_profit=Decimal("0"),
                average_margin=Decimal("0"),
                roi_percent=None,
            ),
            rows=[],
        )

    async def fake_dashboard(
        self,
        *,
        user_id,
        timezone,
        period,
        marketplace,
        sale_model,
        date_from=None,
        date_to=None,
    ):  # type: ignore[no-untyped-def]
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
    app.dependency_overrides[current_web_user] = fake_current_web_user
    monkeypatch.setattr(
        "app.services.web_orders_profit_service.WebOrdersProfitService.profit_by_sku",
        fake_profit_by_sku,
    )
    monkeypatch.setattr(
        "app.services.web_dashboard_service.WebDashboardService.dashboard",
        fake_dashboard,
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        profit_response = client.get("/web/profit")
        analytics_response = client.get("/web/analytics")

    app.dependency_overrides.clear()

    assert profit_response.status_code == 200
    assert analytics_response.status_code == 200
    assert "Прибыль по SKU" in profit_response.text
    assert "Аналитика" in analytics_response.text
    assert "/web/web/" not in profit_response.text
    assert "/web/web/" not in analytics_response.text


def test_web_settings_and_cost_pages_render_canonical_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    user = SimpleNamespace(
        id=1,
        telegram_id=123456789,
        username="seller",
        first_name="Артем",
        timezone="Europe/Moscow",
        language="ru",
        status=UserStatus.ACTIVE,
        notifications_enabled=True,
        low_margin_threshold_percent=Decimal("10"),
        created_at=datetime(2026, 5, 17, tzinfo=UTC),
    )
    product = SimpleNamespace(
        id=97,
        title="Тестовый товар",
        seller_article="SKU-97",
        marketplace_article="123",
        external_product_id="123",
        marketplace=Marketplace.WB,
    )
    cost = SimpleNamespace(
        cost_price=Decimal("100"),
        package_cost=Decimal("10"),
        additional_cost=Decimal("5"),
        tax_rate=Decimal("0.0600"),
        valid_from=datetime(2026, 5, 17, tzinfo=UTC),
        valid_to=None,
        comment="Тест",
    )

    async def fake_get_session():  # type: ignore[no-untyped-def]
        yield FakeAsyncSession()

    async def fake_current_web_user():  # type: ignore[no-untyped-def]
        return user

    async def fake_costs_page(self, user_id):  # type: ignore[no-untyped-def]
        row = SimpleNamespace(
            product=product,
            account_name="Основной",
            cost=cost,
            stock_quantity=3,
            orders_count=2,
        )
        return SimpleNamespace(rows=[row], missing_count=0, configured_count=1)

    async def fake_product_cost_detail(self, *, user_id, product_id):  # type: ignore[no-untyped-def]
        return SimpleNamespace(product=product, account_name="Основной", history=[cost])

    app.dependency_overrides[get_session] = fake_get_session
    app.dependency_overrides[current_web_user] = fake_current_web_user
    monkeypatch.setattr(
        "app.services.web_cabinet_service.WebCabinetService.costs_page",
        fake_costs_page,
    )
    monkeypatch.setattr(
        "app.services.web_cabinet_service.WebCabinetService.product_cost_detail",
        fake_product_cost_detail,
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        settings_response = client.get("/web/settings")
        costs_response = client.get("/web/costs")
        cost_edit_response = client.get("/web/costs/97")

    app.dependency_overrides.clear()

    for response in (settings_response, costs_response, cost_edit_response):
        assert response.status_code == 200
        assert 'href="/web/web/' not in response.text
        assert 'action="/web/web/' not in response.text
        assert "/web/web/" not in response.text
    assert 'action="/web/costs/97"' in cost_edit_response.text


def test_web_cost_save_accepts_canonical_and_legacy_double_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    user = SimpleNamespace(
        id=1,
        telegram_id=123456789,
        username="seller",
        first_name="Артем",
        timezone="Europe/Moscow",
        language="ru",
        status=UserStatus.ACTIVE,
        notifications_enabled=True,
        low_margin_threshold_percent=Decimal("10"),
        created_at=datetime(2026, 5, 17, tzinfo=UTC),
    )
    product = SimpleNamespace(id=97)
    saved: list[object] = []

    async def fake_get_session():  # type: ignore[no-untyped-def]
        yield FakeAsyncSession()

    async def fake_current_web_user():  # type: ignore[no-untyped-def]
        return user

    async def fake_product_cost_detail(self, *, user_id, product_id):  # type: ignore[no-untyped-def]
        return SimpleNamespace(product=product, account_name="Основной", history=[])

    async def fake_add_cost(self, data):  # type: ignore[no-untyped-def]
        saved.append(data)
        return SimpleNamespace(id=len(saved), **data.model_dump())

    app.dependency_overrides[get_session] = fake_get_session
    app.dependency_overrides[current_web_user] = fake_current_web_user
    monkeypatch.setattr(
        "app.services.web_cabinet_service.WebCabinetService.product_cost_detail",
        fake_product_cost_detail,
    )
    monkeypatch.setattr("app.repositories.products.ProductCostRepository.add_cost", fake_add_cost)
    form = {
        "cost_price": "123.45",
        "package_cost": "10",
        "additional_cost": "5",
        "tax_rate": "6",
        "valid_from": "2026-05-17",
        "comment": "WEB test",
    }

    with TestClient(app, raise_server_exceptions=True) as client:
        canonical = client.post("/web/costs/97", data=form, follow_redirects=False)
        legacy = client.post("/web/web/costs/97", data=form, follow_redirects=False)

    app.dependency_overrides.clear()

    assert canonical.status_code == 303
    assert canonical.headers["location"] == "/web/costs/97?saved=1"
    assert legacy.status_code == 303
    assert legacy.headers["location"] == "/web/costs/97?saved=1"
    assert len(saved) == 2
    assert saved[0].product_id == 97
    assert saved[0].cost_price == Decimal("123.45")
    assert saved[0].tax_rate == Decimal("0.0600")


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
async def test_web_login_valid_token_renders_opening_page(monkeypatch: pytest.MonkeyPatch) -> None:
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

    assert response.status_code == 200
    assert "Вход выполнен" in response.body.decode()
    assert "/web/web" not in response.body.decode()
    assert "Path=/" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_legacy_double_web_dashboard_serves_content() -> None:
    """Compatibility route should serve the dashboard directly, not redirect."""
    from collections import OrderedDict
    from types import SimpleNamespace

    class FakeQP(OrderedDict):
        def get(self, key, default=""):
            return super().get(key, default)

    request = SimpleNamespace(
        url=SimpleNamespace(path="/web/web", query="period=today"),
        query_params=FakeQP([("period", "today")]),
    )

    async def fake_dashboard(*args, **kwargs):
        return "<html>Кабинет</html>"

    import pytest

    import app.web.routes as facade
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(facade, "dashboard", fake_dashboard)
        response = await double_web_compat(
            section="", request=request, user=object(), session=object(),
        )

    assert response.status_code == 200
    assert "Кабинет" in response.body.decode()


@pytest.mark.asyncio
async def test_legacy_double_web_orders_serves_content() -> None:
    """Compatibility route should serve orders directly, not redirect."""
    from collections import OrderedDict
    from types import SimpleNamespace

    class FakeQP(OrderedDict):
        def get(self, key, default=""):
            return super().get(key, default)

    request = SimpleNamespace(
        url=SimpleNamespace(path="/web/web/orders", query="period=30d"),
        query_params=FakeQP([("period", "30d")]),
    )

    async def fake_orders_page(*args, **kwargs):
        return "<html>Orders page</html>"

    import pytest

    import app.web.routes as facade
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(facade, "orders_page", fake_orders_page)
        response = await double_web_compat(
            section="orders", request=request, user=object(), session=object(),
        )

    assert response.status_code == 200
    assert "Orders page" in response.body.decode()


@pytest.mark.asyncio
async def test_legacy_double_web_orders_passes_page_number_correctly() -> None:
    """Compatibility route must pass page_number (not page) to avoid name conflict."""
    from collections import OrderedDict
    from types import SimpleNamespace

    class FakeQP(OrderedDict):
        def get(self, key, default=""):
            return super().get(key, default)

    request = SimpleNamespace(
        url=SimpleNamespace(path="/web/web/orders", query="page=3&per_page=20"),
        query_params=FakeQP([("page", "3"), ("per_page", "20")]),
    )

    captured_kwargs = {}

    async def fake_orders_page(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return "<html>Orders page=3</html>"

    import pytest

    import app.web.routes as facade
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(facade, "orders_page", fake_orders_page)
        response = await double_web_compat(
            section="orders", request=request, user=object(), session=object(),
        )

    assert response.status_code == 200
    assert "page_number" in captured_kwargs, "Must use page_number parameter"
    assert captured_kwargs["page_number"] == 3
    assert captured_kwargs["per_page"] == 20
    assert "page" not in captured_kwargs or "page_number" in captured_kwargs, (
        "Must not pass bare 'page' kwarg that could shadow render helper"
    )


@pytest.mark.asyncio
async def test_legacy_double_web_unknown_section_returns_404() -> None:
    """Unknown sections should return a 404 HTML response, not redirect."""
    from collections import OrderedDict
    from types import SimpleNamespace

    request = SimpleNamespace(
        url=SimpleNamespace(path="/web/web/unknown", query=""),
        query_params=OrderedDict(),
    )
    response = await double_web_compat(
        section="unknown", request=request, user=object(), session=object(),
    )
    assert response.status_code == 404
    assert "Раздел не найден" in response.body.decode()


@pytest.mark.asyncio
async def test_legacy_double_web_login_serves_content() -> None:
    from collections import OrderedDict
    from types import SimpleNamespace

    from app.web.route_modules.auth import login_compat

    class FakeQP(OrderedDict):
        def get(self, key, default=""):
            return super().get(key, default)

    request = SimpleNamespace(
        url=SimpleNamespace(path="/web/web/login", query="token=abc123"),
        query_params=FakeQP([("token", "abc123")]),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "test"},
    )

    async def fake_login(request, session, token):
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f"<html>Login token={token}</html>")

    import pytest

    import app.web.route_modules.auth as auth_module
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(auth_module, "login", fake_login)
        response = await login_compat(request=request, session=object())

    assert response.status_code == 200
    assert "token=abc123" in response.body.decode()


def test_app_package_discovery_includes_utility_package() -> None:
    assert importlib.util.find_spec("app") is not None
    assert importlib.util.find_spec("app.utils") is not None


def test_bot_dispatcher_factory_registers_routers_without_polling() -> None:
    dispatcher = create_dispatcher()

    assert [router.name for router in dispatcher.sub_routers] == [
        "navigation",
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
