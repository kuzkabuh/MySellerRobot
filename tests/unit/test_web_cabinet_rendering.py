"""version: 1.1.0
description: Unit tests for web cabinet rendering helpers and anti-placeholder UI.
updated: 2026-05-19
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.models.enums import Marketplace
from app.web import routes
from app.web.dependencies import current_user_role, is_admin_user
from app.web.rendering import NAV_GROUPS, page


def test_web_routes_facade_keeps_router_and_helper_imports() -> None:
    paths = {route.path for route in routes.router.routes}

    assert "/web/login" in paths
    assert "/web/orders" in paths
    assert "/web/admin/worker-diagnostics" in paths
    assert "/web/web/{section:path}" in paths
    assert routes._rub(Decimal("1250")) == "1 250 ₽"


def test_navigation_contains_grouped_web_cabinet_sections() -> None:
    html = page(
        "Главная",
        "Артем",
        "<main></main>",
        active_path="/web/settings?tab=marketplaces",
    )

    assert "Продажи" in html
    assert "Цены и финансы" in html
    assert "Маркетплейсы" in html
    assert "Кабинеты МП" in html
    assert 'href="/web/settings?tab=subscription"' in html
    assert 'href="/web/settings?tab=profile"' in html
    assert "Профиль и настройки" not in html
    assert 'href="/web/web/' not in html
    assert "/web/web" not in html


def test_costs_content_escapes_product_names_and_has_edit_action() -> None:
    product = SimpleNamespace(
        id=10,
        title='<script>alert("x")</script>',
        seller_article="SKU<1>",
        marketplace=Marketplace.WB,
    )
    cost = SimpleNamespace(
        cost_price=Decimal("100.00"),
        package_cost=Decimal("10.00"),
        additional_cost=Decimal("5.00"),
        tax_rate=Decimal("0.0600"),
        valid_from=datetime(2026, 5, 17, tzinfo=UTC),
    )
    data = SimpleNamespace(
        rows=[
            SimpleNamespace(
                product=product,
                account_name="Основной <WB>",
                cost=cost,
                stock_quantity=3,
                orders_count=2,
            )
        ],
        configured_count=1,
        missing_count=0,
    )

    html = routes._costs_content(data)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Основной &lt;WB&gt;" in html
    assert 'href="/web/costs/10"' in html
    assert 'href="/web/web/' not in html
    assert "Раздел подготовлен" not in html


def test_cost_edit_form_uses_canonical_web_action() -> None:
    product = SimpleNamespace(
        id=97,
        title="Товар",
        seller_article="SKU-97",
        marketplace_article="123",
        external_product_id="123",
        marketplace=Marketplace.OZON,
    )
    history = [
        SimpleNamespace(
            valid_from=datetime(2026, 5, 17, tzinfo=UTC),
            valid_to=None,
            cost_price=Decimal("100.00"),
            package_cost=Decimal("10.00"),
            additional_cost=Decimal("5.00"),
            tax_rate=Decimal("0.0600"),
            comment="Тест",
        )
    ]
    detail = SimpleNamespace(product=product, account_name="Основной", history=history)

    html = routes._cost_edit_content(detail)

    assert 'action="/web/costs/97"' in html
    assert 'action="/web/web/costs/97"' not in html
    assert "/web/web/" not in html


def test_cost_dates_use_user_timezone() -> None:
    product = SimpleNamespace(
        id=11,
        title="Товар",
        seller_article="SKU-11",
        marketplace=Marketplace.WB,
    )
    cost = SimpleNamespace(
        cost_price=Decimal("100.00"),
        package_cost=Decimal("10.00"),
        additional_cost=Decimal("5.00"),
        tax_rate=Decimal("0.0600"),
        valid_from=datetime(2026, 5, 16, 22, 0, tzinfo=UTC),
    )
    data = SimpleNamespace(
        rows=[
            SimpleNamespace(
                product=product,
                account_name="Основной",
                cost=cost,
                stock_quantity=3,
                orders_count=2,
            )
        ],
        configured_count=1,
        missing_count=0,
    )

    html = routes._costs_content(data, "Europe/Moscow")

    assert "17.05.2026" in html
    assert routes._datetime_from_form("2026-05-17", "Europe/Moscow") == datetime(
        2026, 5, 16, 21, 0, tzinfo=UTC
    )


def test_subscription_content_shows_limits_features_and_payments_empty_state() -> None:
    tier = SimpleNamespace(
        code="pro",
        name="PRO",
        description="Профессиональный тариф",
        price_monthly=Decimal("1490.00"),
        max_marketplace_accounts=5,
        max_orders_per_month=None,
        max_products=None,
        feature_web_cabinet=True,
        feature_analytics=True,
        feature_plan_fact=True,
        feature_break_even=True,
        feature_stock_forecast=True,
        feature_alerts=True,
        feature_api_access=False,
    )
    data = SimpleNamespace(
        tier=tier,
        active_subscription=None,
        payments=[],
        used_accounts=2,
        used_orders_month=42,
        used_products=120,
    )

    html = routes._subscription_content(data, [tier])

    assert "Подписка и тариф" in html
    assert "2 / 5" in html
    assert "без ограничений" in html
    assert "Платежей пока нет" in html
    assert "Текущий тариф" in html


def test_control_content_is_real_work_screen_not_placeholder() -> None:
    data = SimpleNamespace(
        report=SimpleNamespace(score=75),
        error_accounts=[],
        open_alerts=[],
        preliminary_orders=3,
        missing_cost_products=2,
        low_stock_products=1,
    )

    html = routes._control_content(data)

    assert "Что требует внимания прямо сейчас" in html
    assert "Предварительная экономика" in html
    assert "Раздел подготовлен" not in html


def test_nav_groups_no_double_web_prefix() -> None:
    """Every href in NAV_GROUPS must start with /web/ but never /web/web/."""
    for _group_title, items in NAV_GROUPS:
        for _label, href in items:
            assert href.startswith("/web/"), f"Nav link {href!r} does not start with /web/"
            assert "/web/web/" not in href, f"Nav link {href!r} has double /web/web/ prefix"


def test_page_shell_logout_link_is_canonical() -> None:
    html = page("Test", "User", "<p>content</p>")
    assert 'href="/web/logout"' in html
    assert 'href="/web/web/logout"' not in html


def test_orders_content_links_are_canonical() -> None:
    from app.models.enums import Marketplace as MPEnum
    from app.services.web_orders_profit_service import OrderPageResult, OrderWebFilters

    row = SimpleNamespace(
        order_id=42,
        item_id=1,
        order_date=datetime(2026, 5, 19, tzinfo=UTC),
        marketplace=MPEnum.WB,
        sale_model="FBS",
        title="Test Order",
        seller_article="SKU-42",
        marketplace_article="MP-42",
        order_external_id="WB-123",
        posting_number=None,
        quantity=1,
        revenue=Decimal("1000.00"),
        estimated_profit=Decimal("200.00"),
        margin_percent=Decimal("20.00"),
        status="new",
        requires_action=False,
        missing_cost=False,
        economy_confidence="CONFIRMED",
        source_event_type="new_order",
    )
    filters = OrderWebFilters(
        period="today",
        marketplace=None,
        sale_model=None,
        local_date_from=datetime(2026, 5, 19).date(),
        local_date_to=datetime(2026, 5, 19).date(),
        date_from=datetime(2026, 5, 19, tzinfo=UTC),
        date_to=datetime(2026, 5, 19, tzinfo=UTC),
        economy="all",
        status="all",
        sku="",
        sort="date",
        direction="desc",
    )
    page_result = OrderPageResult(
        filters=filters,
        rows=[row],
        total_count=1,
        page=1,
        per_page=50,
        total_pages=1,
    )
    html = routes._orders_content(page_result, "Europe/Moscow")

    assert 'href="/web/orders/42"' in html
    assert 'href="/web/web/' not in html


def test_products_content_links_are_canonical() -> None:
    linked = SimpleNamespace(
        product_id=5,
        marketplace=Marketplace.WB,
        seller_article="SKU-5",
        marketplace_article="MP-5",
    )
    row = SimpleNamespace(
        master_product_id=1,
        title="Product",
        brand="Brand",
        category="Cat",
        canonical_sku="SKU-1",
        image_url=None,
        wb_products=1,
        ozon_products=0,
        orders=10,
        sales=5,
        revenue=Decimal("5000"),
        estimated_profit=Decimal("1000"),
        stock_quantity=20,
        marketplace_products=[linked],
    )
    html = routes._products_content([row])

    assert 'href="/web/products/1"' in html
    assert 'href="/web/costs/5"' in html
    assert 'href="/web/web/' not in html


def test_stocks_content_has_canonical_filter_form_action() -> None:
    html = routes._stocks_forecast_content(
        [], marketplace="all", sale_model="all", stock_status="all"
    )
    assert 'action="/web/stocks"' in html
    assert 'action="/web/web/' not in html


def test_sales_content_has_canonical_filter_form_action() -> None:
    from app.services.web_dashboard_service import DashboardFilters

    filters = DashboardFilters(
        period="30d",
        marketplace=None,
        sale_model=None,
        timezone="Europe/Moscow",
        local_date_from=datetime(2026, 4, 19).date(),
        local_date_to=datetime(2026, 5, 19).date(),
        date_from=datetime(2026, 4, 19, tzinfo=UTC),
        date_to=datetime(2026, 5, 19, tzinfo=UTC),
        previous_from=datetime(2026, 3, 20, tzinfo=UTC),
        previous_to=datetime(2026, 4, 18, tzinfo=UTC),
    )
    data = SimpleNamespace(
        filters=filters,
        rows=[],
        total_quantity=0,
        total_amount=Decimal("0"),
        total_profit=Decimal("0"),
    )
    html = routes._sales_content(data, "Europe/Moscow", sku="")

    assert 'action="/web/sales"' in html
    assert 'action="/web/web/' not in html


def test_plan_fact_content_has_canonical_form_actions() -> None:
    from app.models.enums import Marketplace as MPEnum
    from app.services.plan_fact_service import PlanFactSummary
    from app.services.web_orders_profit_service import OrderWebFilters

    plan = SimpleNamespace(
        id=1,
        marketplace=MPEnum.WB,
        period_start=datetime(2026, 5, 1).date(),
        period_end=datetime(2026, 5, 31).date(),
        revenue_plan=Decimal("10000"),
        profit_plan=Decimal("2000"),
        orders_plan=50,
        buyouts_plan=30,
    )
    summary = PlanFactSummary(
        orders=10,
        buyouts=5,
        estimated_profit=Decimal("500"),
        actual_profit=Decimal("400"),
        deviation=Decimal("-100"),
        deviation_percent=Decimal("-20.00"),
        pending_actual=2,
    )
    filters = OrderWebFilters(
        period="30d",
        marketplace=None,
        sale_model=None,
        local_date_from=datetime(2026, 4, 19).date(),
        local_date_to=datetime(2026, 5, 19).date(),
        date_from=datetime(2026, 4, 19, tzinfo=UTC),
        date_to=datetime(2026, 5, 19, tzinfo=UTC),
        economy="all",
        status="all",
        sku="",
        sort="deviation",
        direction="asc",
    )
    data = SimpleNamespace(
        summary=summary,
        rows=[],
        plan=plan,
        filters=filters,
    )
    html = routes._plan_fact_content(data)

    assert 'action="/web/plan-fact/plans"' in html
    assert 'action="/web/plan-fact/plans/1/delete"' in html
    assert "/web/web/" not in html
    assert 'action="/web/web/' not in html


def test_plan_fact_content_without_plan_has_canonical_form_action() -> None:
    """When no plan exists, the save form must still use canonical action."""
    from app.services.plan_fact_service import PlanFactSummary
    from app.services.web_orders_profit_service import OrderWebFilters

    summary = PlanFactSummary(
        orders=0,
        buyouts=0,
        estimated_profit=Decimal("0"),
        actual_profit=Decimal("0"),
        deviation=Decimal("0"),
        deviation_percent=Decimal("0"),
        pending_actual=0,
    )
    filters = OrderWebFilters(
        period="30d",
        marketplace=None,
        sale_model=None,
        local_date_from=datetime(2026, 5, 1).date(),
        local_date_to=datetime(2026, 5, 31).date(),
        date_from=datetime(2026, 5, 1, tzinfo=UTC),
        date_to=datetime(2026, 5, 31, tzinfo=UTC),
        economy="all",
        status="all",
        sku="",
        sort="deviation",
        direction="asc",
    )
    data = SimpleNamespace(
        summary=summary,
        rows=[],
        plan=None,
        filters=filters,
    )
    html = routes._plan_fact_content(data)

    assert 'action="/web/plan-fact/plans"' in html
    assert 'action="/web/plan-fact/plans//delete"' not in html
    assert "/web/web/" not in html
    assert 'action="/web/web/' not in html


def test_break_even_content_has_canonical_form_action() -> None:
    html = routes._break_even_content(rows=[], target_margin="20", price_delta="0")

    assert 'action="/web/break-even"' in html
    assert 'action="/web/web/' not in html


def test_product_matching_content_has_canonical_form_actions() -> None:
    candidate = SimpleNamespace(
        product_id=1,
        marketplace=Marketplace.WB,
        seller_article="SKU-1",
        marketplace_article="MP-1",
        title="Product",
        current_group=None,
    )
    html = routes._product_matching_content([candidate])

    assert 'action="/web/product-matching/create"' in html
    assert 'action="/web/product-matching/unlink"' in html
    assert 'action="/web/web/' not in html


def test_master_product_detail_content_has_canonical_links() -> None:
    mp_product = SimpleNamespace(
        product_id=10,
        marketplace=Marketplace.WB,
        seller_article="SKU-10",
        marketplace_article="MP-10",
        title="Product",
        brand="Brand",
    )
    comparison = SimpleNamespace(
        marketplace=Marketplace.WB,
        orders=5,
        sales=3,
        revenue=Decimal("3000"),
        estimated_profit=Decimal("500"),
        actual_profit=Decimal("400"),
        margin_percent=Decimal("16.67"),
        stock_quantity=10,
    )
    detail = SimpleNamespace(
        title="Product",
        brand="Brand",
        category="Cat",
        canonical_sku="SKU-1",
        image_url=None,
        marketplace_products=[mp_product],
        marketplace_comparison=[comparison],
        recommendations=["Check pricing"],
    )
    html = routes._master_product_detail_content(detail)

    assert 'href="/web/costs/10"' in html
    assert 'href="/web/web/' not in html


def test_orders_page_has_no_page_parameter_name_conflict() -> None:
    """The pagination parameter must not shadow the render helper.

    Regression test for TypeError: 'int' object is not callable
    caused by `page: int` parameter shadowing the `page` render function.
    """
    import inspect

    from app.web.route_modules.orders_profit import orders_page, profit_page

    sig = inspect.signature(orders_page)
    param_names = list(sig.parameters.keys())
    assert "page_number" in param_names, "orders_page should use page_number, not page"
    assert "page" not in param_names, "orders_page must not have a 'page' parameter"

    profit_sig = inspect.signature(profit_page)
    assert "page" not in profit_sig.parameters, "profit_page must not have a 'page' parameter"


def test_profit_page_uses_render_page_not_shadowed_page() -> None:
    """profit_page must call render_page, not a shadowed page name.

    The module imports `page as render_page`; calling bare `page()` would
    raise NameError (or TypeError if a local `page` int existed).
    """
    import ast
    import pathlib

    source = pathlib.Path("app/web/route_modules/orders_profit.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "profit_page":
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                    assert (
                        child.func.id != "page"
                    ), "profit_page must call render_page(), not bare page()"


def test_nav_links_cover_all_required_sections() -> None:
    """Navigation must contain hrefs for all key cabinet sections."""
    html = page("Главная", "Артем", "<main></main>")
    required_hrefs = [
        "/web/products",
        "/web/stocks",
        "/web/product-matching",
        "/web/plan-fact",
        "/web/break-even",
        "/web/costs",
        "/web/orders",
        "/web/sales",
        "/web/returns",
        "/web/profit",
        "/web/alerts",
        "/web/settings?tab=marketplaces",
        "/web/settings?tab=sync",
        "/web/settings?tab=subscription",
        "/web/settings?tab=profile",
        "/web/settings?tab=notifications",
        "/web/settings?tab=security",
        "/web/settings?tab=support",
    ]
    for href in required_hrefs:
        assert f'href="{href}"' in html, f"Missing nav link: {href}"


def test_nav_hides_admin_sections_for_regular_users() -> None:
    html = page("Главная", "Артем", "<main></main>")

    assert 'href="/web/admin"' not in html
    assert 'href="/web/admin/support"' not in html
    assert 'href="/web/control"' not in html
    assert 'href="/web/health"' not in html
    assert "Панель администратора" not in html
    assert "Контроль ошибок" not in html
    assert "Здоровье кабинетов" not in html


def test_nav_shows_admin_sections_for_admin_users() -> None:
    html = page("Главная", "Артем", "<main></main>", is_admin=True, user_role="admin")

    assert 'href="/web/admin"' in html
    assert 'href="/web/admin/support"' in html
    assert "Панель администратора" in html
    assert "Статус синхронизаций" in html
    assert "Диагностика воркеров" in html
    assert "Аудит действий" in html
    assert "Sync status" not in html
    assert "Worker diagnostics" not in html
    assert "Audit log" not in html


def test_is_admin_user_uses_role_before_render_name_suffix() -> None:
    admin = SimpleNamespace(id=1, telegram_id=123, role="admin")
    regular = SimpleNamespace(id=2, telegram_id=456, role="user")

    assert is_admin_user(admin) is True
    assert current_user_role(admin) == "admin"
    assert is_admin_user(regular) is False
    assert current_user_role(regular) == "user"


def test_nav_links_are_real_anchor_tags() -> None:
    """Every nav item must be a real <a href=...> tag, not a JS-driven element."""
    html = page("Главная", "Артем", "<main></main>", is_admin=True, user_role="admin")
    for _group_title, items in NAV_GROUPS:
        for _label, href in items:
            assert (
                f'<a href="{href}"' in html or f'<a class="active" href="{href}"' in html
            ), f"Nav item {_label!r} is not a real <a> tag with href={href!r}"


def test_page_html_contains_no_javascript_click_handlers() -> None:
    """Server-rendered pages must not contain JS click handlers that could block navigation."""
    html = page("Главная", "Артем", "<main></main>")
    assert "onclick" not in html
    assert "preventDefault" not in html
    assert "stopPropagation" not in html
    assert "data-href" not in html


def test_page_html_contains_no_blocking_overlays() -> None:
    """Server-rendered pages must not contain overlay/loader elements that block clicks."""
    html = page("Главная", "Артем", "<main></main>")
    assert "loading-overlay" not in html
    assert "page-loader" not in html
    assert "sidebar-overlay" not in html
    assert "modal-backdrop" not in html
    assert "drawer-backdrop" not in html


def test_page_html_contains_frontend_diagnostics_fallback() -> None:
    html = page("Главная", "Артем", "<main></main>")

    assert "/web/frontend-error" in html
    assert "unhandledrejection" in html
    assert "Не удалось загрузить интерфейс" in html


def test_nav_logout_link_is_real_anchor() -> None:
    """Logout link must be a real <a> tag, not a button with JS."""
    html = page("Главная", "Артем", "<main></main>")
    assert 'href="/web/logout"' in html


def test_pricing_web_routes_import_without_fastapi_error() -> None:
    """Regression: union return types like str | RedirectResponse crash FastAPI startup.

    FastAPI tries to build a response_model from the return annotation and fails
    with FastAPIError when the annotation contains non-Pydantic types like
    RedirectResponse in a union.
    """
    from app.web.route_modules.pricing import router

    paths = {route.path for route in router.routes}
    assert "/pricing" in paths
    assert "/pricing/auto-promotions/upload/preview" in paths
