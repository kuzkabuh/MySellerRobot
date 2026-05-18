# ruff: noqa: E501, F401, F403, F405

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import AlertEvent, MarketplaceAccount, User
from app.models.enums import Marketplace
from app.models.subscriptions import SubscriptionTier
from app.repositories.products import ProductCostRepository
from app.schemas.products import CostUpdate
from app.services.cost_management_service import CostManagementError
from app.services.data_quality_service import DataQualityService
from app.services.master_product_service import MasterProductService
from app.services.plan_fact_service import PlanFactService
from app.services.stock_forecast_service import StockForecastService
from app.services.subscription_service import SubscriptionService
from app.services.unit_economics_service import UnitEconomicsService
from app.services.web_auth_service import WEB_SESSION_COOKIE, WebAuthService
from app.services.web_cabinet_service import WebCabinetService
from app.services.web_dashboard_service import WebDashboardService
from app.services.web_orders_profit_service import WebOrdersProfitService
from app.services.web_sync_service import WebSyncService
from app.web.dependencies import (
    CURRENT_WEB_USER_DEPENDENCY,
    SESSION_DEPENDENCY,
    WEB_DASHBOARD_PATH,
    WEB_LOGIN_REQUIRED_PATH,
    WEB_SESSION_COOKIE_PATH,
)
from app.web.rendering import page
from app.web.views import *

logger = logging.getLogger(__name__)
router = APIRouter()


def _facade() -> Any:
    import app.web.routes as facade

    return facade

@router.get("/{section}", response_class=HTMLResponse)
async def placeholder(
    section: str,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> str:
    return _placeholder_page(section, user)


@router.get("/web/{section:path}", response_class=HTMLResponse, include_in_schema=False)
async def double_web_compat(
    section: str,
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> Response:
    """Serve cabinet pages when an old reverse proxy still prepends /web upstream."""

    normalized = section.strip("/")
    logger.warning(
        "legacy_double_web_path",
        extra={"path": _request_path(request), "section": normalized or "dashboard"},
    )
    if normalized == "":
        return HTMLResponse(
            await _facade().dashboard(
                user=user,
                session=session,
                period=_query_param(request, "period", "today"),
                marketplace=_query_param(request, "marketplace", "all"),
                sale_model=_query_param(request, "sale_model", "all"),
                date_from=_optional_query_param(request, "date_from"),
                date_to=_optional_query_param(request, "date_to"),
            )
        )
    if normalized == "orders":
        return HTMLResponse(
            await _facade().orders_page(
                user=user,
                session=session,
                period=_query_param(request, "period", "today"),
                marketplace=_query_param(request, "marketplace", "all"),
                sale_model=_query_param(request, "sale_model", "all"),
                economy=_query_param(request, "economy", "all"),
                status=_query_param(request, "status", "all"),
                sku=_query_param(request, "sku", ""),
                sort=_query_param(request, "sort", "date"),
                direction=_query_param(request, "direction", "desc"),
                date_from=_optional_query_param(request, "date_from"),
                date_to=_optional_query_param(request, "date_to"),
            )
        )
    if normalized.startswith("orders/"):
        try:
            order_id = int(normalized.split("/", 1)[1])
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Заказ не найден") from exc
        return HTMLResponse(await _facade().order_detail_page(order_id=order_id, user=user, session=session))
    if normalized == "profit":
        return HTMLResponse(
            await _facade().profit_page(
                user=user,
                session=session,
                period=_query_param(request, "period", "7d"),
                marketplace=_query_param(request, "marketplace", "all"),
                sale_model=_query_param(request, "sale_model", "all"),
                economy=_query_param(request, "economy", "all"),
                sku=_query_param(request, "sku", ""),
                sort=_query_param(request, "sort", "profit"),
                direction=_query_param(request, "direction", "desc"),
                date_from=_optional_query_param(request, "date_from"),
                date_to=_optional_query_param(request, "date_to"),
            )
        )
    if normalized == "plan-fact":
        return HTMLResponse(
            await _facade().plan_fact_page(
                user=user,
                session=session,
                period=_query_param(request, "period", "30d"),
                marketplace=_query_param(request, "marketplace", "all"),
                sale_model=_query_param(request, "sale_model", "all"),
                sku=_query_param(request, "sku", ""),
                sort=_query_param(request, "sort", "deviation"),
                direction=_query_param(request, "direction", "asc"),
                date_from=_optional_query_param(request, "date_from"),
                date_to=_optional_query_param(request, "date_to"),
            )
        )
    if normalized == "break-even":
        return HTMLResponse(
            await _facade().break_even_page(
                user=user,
                session=session,
                target_margin=_query_param(request, "target_margin", "20"),
                price_delta=_query_param(request, "price_delta", "0"),
            )
        )
    if normalized == "products":
        return HTMLResponse(await _facade().products_page(user=user, session=session))
    if normalized.startswith("products/"):
        try:
            product_id = int(normalized.split("/", 1)[1])
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Товар не найден") from exc
        return HTMLResponse(
            await _facade().product_detail_page(master_product_id=product_id, user=user, session=session)
        )
    if normalized == "product-matching":
        return HTMLResponse(await _facade().product_matching_page(user=user, session=session))
    if normalized == "stocks":
        return HTMLResponse(await _facade().stocks_page(user=user, session=session))
    if normalized == "alerts":
        return HTMLResponse(await _facade().alerts_page(user=user, session=session))
    if normalized == "data-quality":
        return HTMLResponse(await _facade().data_quality_page(user=user, session=session))
    if normalized == "sales":
        return HTMLResponse(
            await _facade().sales_page(
                user=user,
                session=session,
                period=_query_param(request, "period", "30d"),
                marketplace=_query_param(request, "marketplace", "all"),
                sku=_query_param(request, "sku", ""),
                date_from=_optional_query_param(request, "date_from"),
                date_to=_optional_query_param(request, "date_to"),
            )
        )
    if normalized == "returns":
        return HTMLResponse(
            await _facade().returns_page(
                user=user,
                session=session,
                period=_query_param(request, "period", "30d"),
                marketplace=_query_param(request, "marketplace", "all"),
                sku=_query_param(request, "sku", ""),
                date_from=_optional_query_param(request, "date_from"),
                date_to=_optional_query_param(request, "date_to"),
            )
        )
    if normalized == "analytics":
        return HTMLResponse(await _facade().analytics_page(user=user, session=session))
    if normalized == "control":
        return HTMLResponse(await _facade().control_page(user=user, session=session))
    if normalized == "costs":
        return HTMLResponse(await _facade().costs_page(user=user, session=session))
    if normalized.startswith("costs/"):
        try:
            product_id = int(normalized.split("/", 1)[1])
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Товар не найден") from exc
        return HTMLResponse(await _facade().cost_edit_page(product_id=product_id, user=user, session=session))
    if normalized == "profile":
        return HTMLResponse(await _facade().profile_page(user=user, session=session))
    if normalized == "subscription":
        return HTMLResponse(await _facade().subscription_page_web(user=user, session=session))
    if normalized == "accounts":
        return HTMLResponse(await _facade().accounts_page_web(user=user, session=session))
    if normalized == "settings":
        return HTMLResponse(await _facade().settings_page(user=user))
    raise HTTPException(status_code=404, detail="Раздел не найден")

