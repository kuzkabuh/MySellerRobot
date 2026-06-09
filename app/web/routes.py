"""Web cabinet router facade.

The endpoint implementations live in app.web.route_modules.*. This module keeps the
historic public import path (`app.web.routes`) stable for FastAPI registration and tests.
"""

from fastapi import APIRouter

from app.web import views as _views
from app.web.route_modules import (
    account_settings,
    admin_logs,
    admin_visibility,
    auth,
    backup_admin,
    catalog,
    commissions_admin,
    compatibility,
    finances,
    mrc_pricing,
    operations,
    orders_profit,
    planning,
    pricing,
    promocodes_admin,
    support_admin,
    tariffs_admin,
    user_settings,
    wb_daily_reports,
    wb_logistics_admin,
)
from app.web.route_modules import (
    dashboard as dashboard_routes,
)
from app.web.route_modules.account_settings import (
    accounts_page_web,
    cost_edit_page,
    costs_page,
    profile_page,
    subscription_page_web,
)
from app.web.route_modules.auth import login
from app.web.route_modules.catalog import (
    product_detail_page,
    product_matching_page,
    products_page,
    stocks_page,
)
from app.web.route_modules.commissions_admin import (
    check_ozon_commissions_web,
    commissions_admin_page,
    import_ozon_commissions_web,
    sync_wb_commissions_web,
)
from app.web.route_modules.compatibility import double_web_compat
from app.web.route_modules.dashboard import dashboard
from app.web.route_modules.mrc_pricing import (
    auto_promo_import_page,
    auto_promo_prices_page,
    mrc_pricing_page,
)
from app.web.route_modules.operations import (
    alerts_page,
    analytics_page,
    control_page,
    data_quality_page,
    returns_page,
    sales_page,
)
from app.web.route_modules.orders_profit import order_detail_page, orders_page, profit_page
from app.web.route_modules.planning import break_even_page, plan_fact_page
from app.web.route_modules.pricing import pricing_page

__all__ = [
    "router",
    "accounts_page_web",
    "alerts_page",
    "analytics_page",
    "auto_promo_import_page",
    "auto_promo_prices_page",
    "break_even_page",
    "check_ozon_commissions_web",
    "commissions_admin_page",
    "control_page",
    "cost_edit_page",
    "costs_page",
    "dashboard",
    "data_quality_page",
    "double_web_compat",
    "import_ozon_commissions_web",
    "login",
    "mrc_pricing_page",
    "order_detail_page",
    "orders_page",
    "plan_fact_page",
    "pricing_page",
    "product_detail_page",
    "product_matching_page",
    "products_page",
    "profile_page",
    "profit_page",
    "returns_page",
    "sales_page",
    "stocks_page",
    "subscription_page_web",
    "sync_wb_commissions_web",
]
__all__.extend(_views.__all__)

for _name in _views.__all__:
    globals()[_name] = getattr(_views, _name)

router = APIRouter(prefix="/web", tags=["web"])
for module_router in (
    auth.router,
    dashboard_routes.router,
    orders_profit.router,
    planning.router,
    operations.router,
    pricing.router,
    catalog.router,
    account_settings.router,
    user_settings.router,
    commissions_admin.router,
    tariffs_admin.router,
    promocodes_admin.router,
    support_admin.router,
    admin_visibility.router,
    admin_logs.router,
    backup_admin.router,
    mrc_pricing.router,
    wb_logistics_admin.router,
    wb_daily_reports.router,
    finances.router,
    compatibility.router,
):
    router.include_router(module_router)
