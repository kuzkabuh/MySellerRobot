"""Web cabinet router facade.

The endpoint implementations live in app.web.route_modules.*. This module keeps the
historic public import path (`app.web.routes`) stable for FastAPI registration and tests.
"""

# ruff: noqa: F401, F403

from fastapi import APIRouter

from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY, current_web_user
from app.web.route_modules import (
    account_settings,
    auth,
    catalog,
    commissions_admin,
    compatibility,
    mrc_pricing,
    operations,
    orders_profit,
    planning,
    pricing,
    tariffs_admin,
)
from app.web.route_modules import (
    dashboard as dashboard_routes,
)
from app.web.route_modules.account_settings import (
    accounts_page_web,
    cost_edit_page,
    costs_page,
    profile_page,
    request_web_sync,
    save_low_margin_settings,
    save_product_cost,
    save_product_cost_legacy_double_web,
    save_profile_settings,
    settings_page,
    subscription_page_web,
)
from app.web.route_modules.auth import login, login_compat, login_required, logout
from app.web.route_modules.catalog import (
    product_detail_page,
    product_matching_create,
    product_matching_page,
    product_matching_unlink,
    products_page,
    stocks_page,
)
from app.web.route_modules.commissions_admin import (
    check_ozon_commissions_web,
    check_ozon_status_json,
    check_ozon_status_page,
    commissions_admin_page,
    import_ozon_commissions_web,
    sync_wb_commissions_web,
)
from app.web.route_modules.compatibility import double_web_compat, placeholder
from app.web.route_modules.dashboard import dashboard, dashboard_compat
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
from app.web.route_modules.planning import (
    break_even_page,
    delete_plan_fact_plan,
    plan_fact_page,
    save_plan_fact_plan,
)
from app.web.route_modules.pricing import pricing_page
from app.web.views import *

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
    commissions_admin.router,
    tariffs_admin.router,
    mrc_pricing.router,
    compatibility.router,
):
    router.include_router(module_router)
