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
from app.models.enums import FeatureCode, Marketplace
from app.models.subscriptions import SubscriptionTier
from app.repositories.products import ProductCostRepository
from app.schemas.products import CostUpdate
from app.services.unit_economics.cost_management_service import CostManagementError
from app.services.common.data_quality_service import DataQualityService
from app.services.subscriptions.feature_access_service import FeatureAccessService
from app.services.unit_economics.master_product_service import MasterProductService
from app.services.unit_economics.plan_fact_service import PlanFactService
from app.services.unit_economics.stock_forecast_service import StockForecastService
from app.services.subscriptions.subscription_service import SubscriptionService
from app.services.unit_economics.unit_economics_service import UnitEconomicsService
from app.services.account.web_auth_service import WEB_SESSION_COOKIE, WebAuthService
from app.services.account.web_cabinet_service import WebCabinetService
from app.services.common.web_dashboard_service import WebDashboardService
from app.services.common.web_orders_profit_service import WebOrdersProfitService
from app.services.common.web_sync_service import WebSyncService
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


@router.get("/plan-fact", response_class=HTMLResponse)
async def plan_fact_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="30d"),
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    sku: str = Query(default=""),
    sort: str = Query(default="deviation"),
    direction: str = Query(default="asc"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.PLAN_FACT)
    if not access.allowed:
        return page(
            "План/факт",
            user.first_name or user.username or str(user.telegram_id),
            _feature_locked_html(access),
            active_path="/web/plan-fact",
        )

    data = await PlanFactService(session).compare(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
        sku=sku,
        sort=sort,
        direction=direction,
    )
    content = _plan_fact_content(data)
    return page(
        "План/факт",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/plan-fact",
    )


@router.post("/plan-fact/plans")
async def save_plan_fact_plan(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    await _ensure_plan_fact_access(session, user.id)
    form = await _urlencoded_form(request)
    target_id = _optional_int((form.get("target_id") or [""])[0])
    period_start = date.fromisoformat((form.get("period_start") or [""])[0])
    period_end = date.fromisoformat((form.get("period_end") or [""])[0])
    marketplace = _plan_marketplace((form.get("marketplace") or ["all"])[0])
    await PlanFactService(session).save_plan(
        user_id=user.id,
        target_id=target_id,
        period_start=period_start,
        period_end=period_end,
        marketplace=marketplace,
        revenue_plan=_optional_decimal((form.get("revenue_plan") or [""])[0]),
        profit_plan=_optional_decimal((form.get("profit_plan") or [""])[0]),
        orders_plan=_optional_int((form.get("orders_plan") or [""])[0]),
        buyouts_plan=_optional_int((form.get("buyouts_plan") or [""])[0]),
    )
    await session.commit()
    return RedirectResponse(url="/web/plan-fact", status_code=303)


@router.post("/plan-fact/plans/{target_id}/delete")
async def delete_plan_fact_plan(
    target_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    await _ensure_plan_fact_access(session, user.id)
    await PlanFactService(session).delete_plan(user_id=user.id, target_id=target_id)
    await session.commit()
    return RedirectResponse(url="/web/plan-fact", status_code=303)


@router.post("/web/plan-fact/plans", include_in_schema=False)
async def save_plan_fact_plan_legacy_double_web(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Accept plan saves from legacy /web/web/plan-fact/plans and redirect canonically."""
    return await save_plan_fact_plan(
        request=request,
        user=user,
        session=session,
    )


@router.post("/web/plan-fact/plans/{target_id}/delete", include_in_schema=False)
async def delete_plan_fact_plan_legacy_double_web(
    target_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Accept plan deletes from legacy /web/web/plan-fact/plans/{id}/delete and redirect canonically."""
    return await delete_plan_fact_plan(
        target_id=target_id,
        user=user,
        session=session,
    )


@router.get("/break-even", response_class=HTMLResponse)
async def break_even_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    target_margin: str = Query(default="20"),
    price_delta: str = Query(default="0"),
) -> str:
    access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.BREAK_EVEN)
    if not access.allowed:
        return page(
            "Безубыточная цена",
            user.first_name or user.username or str(user.telegram_id),
            _feature_locked_html(access),
            active_path="/web/break-even",
        )

    rows = await UnitEconomicsService(session).rows(
        user_id=user.id,
        target_margin_percent=_decimal_from_query(target_margin, Decimal("20")),
        price_delta_percent=_decimal_from_query(price_delta, Decimal("0")),
    )
    content = _break_even_content(rows, target_margin, price_delta)
    return page(
        "Безубыточная цена",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/break-even",
    )


def _feature_locked_html(access: Any) -> str:
    from html import escape as _esc

    reason = _esc(access.reason or "") if access.reason else ""
    required = _esc(access.required_plan or "Pro")
    return f"""
    <div class="locked-feature">
        <h2>🔒 Раздел недоступен</h2>
        <p>{reason}</p>
        <p>Для доступа обновите тариф до <b>{required}</b> или выше.</p>
        <a class="btn btn-primary" href="/web/settings?tab=subscription">Перейти к подписке</a>
    </div>"""


async def _ensure_plan_fact_access(session: AsyncSession, user_id: int) -> None:
    access = await FeatureAccessService(session).can_use_feature(user_id, FeatureCode.PLAN_FACT)
    if not access.allowed:
        raise HTTPException(status_code=403, detail=access.reason or "Раздел недоступен")
