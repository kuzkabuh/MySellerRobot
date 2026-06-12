# ruff: noqa: E501, F401, F403, F405

import logging
from datetime import UTC, date, datetime
from decimal import Decimal

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


@router.get("/sales", response_class=HTMLResponse)
async def sales_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="30d"),
    marketplace: str = Query(default="all"),
    sku: str = Query(default=""),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    page_number: int = Query(default=1, ge=1, alias="page"),
    per_page: int = Query(default=50, ge=10, le=200),
) -> str:
    data = await WebCabinetService(session).sales_page(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sku=sku,
        date_from=date_from,
        date_to=date_to,
        page=page_number,
        per_page=per_page,
    )
    return page(
        "Продажи",
        _user_display_name(user),
        _sales_content(data, user.timezone, sku),
        active_path="/web/sales",
    )


@router.get("/returns", response_class=HTMLResponse)
async def returns_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="30d"),
    marketplace: str = Query(default="all"),
    sku: str = Query(default=""),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    data = await WebCabinetService(session).returns_page(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sku=sku,
        date_from=date_from,
        date_to=date_to,
    )
    return page(
        "Возвраты",
        _user_display_name(user),
        _returns_content(data, user.timezone, sku),
        active_path="/web/returns",
    )


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    result = await session.execute(
        select(AlertEvent)
        .where(AlertEvent.user_id == user.id)
        .order_by(AlertEvent.created_at.desc())
        .limit(50)
    )
    content = _alerts_content(list(result.scalars().all()), user.timezone)
    return page(
        "Алерты",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/alerts",
    )


@router.get("/data-quality", response_class=HTMLResponse)
async def data_quality_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.DATA_QUALITY)
    if not access.allowed:
        from html import escape as _esc

        reason = _esc(access.reason or "") if access.reason else ""
        required = _esc(access.required_plan or "Pro")
        locked = f"""
        <div class="locked-feature">
            <h2>🔒 Раздел недоступен</h2>
            <p>{reason}</p>
            <p>Для доступа обновите тариф до <b>{required}</b> или выше.</p>
            <a class="btn btn-primary" href="/web/settings?tab=subscription">Перейти к подписке</a>
        </div>"""
        return page(
            "Проблемы данных", _user_display_name(user), locked, active_path="/web/data-quality"
        )

    report = await DataQualityService(session).report(user_id=user.id)
    content = _data_quality_content(report)
    return page(
        "Проблемы данных",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/data-quality",
    )


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="30d"),
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    access = await FeatureAccessService(session).can_use_feature(
        user.id, FeatureCode.MASTER_PRODUCT_ANALYTICS
    )
    if not access.allowed:
        from html import escape as _esc

        reason = _esc(access.reason or "") if access.reason else ""
        required = _esc(access.required_plan or "Pro")
        locked = f"""
        <div class="locked-feature">
            <h2>🔒 Раздел недоступен</h2>
            <p>{reason}</p>
            <p>Для доступа обновите тариф до <b>{required}</b> или выше.</p>
            <a class="btn btn-primary" href="/web/settings?tab=subscription">Перейти к подписке</a>
        </div>"""
        return page("Аналитика", _user_display_name(user), locked, active_path="/web/analytics")

    dashboard_data = await WebDashboardService(session).dashboard(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
    )
    profit_data = await WebOrdersProfitService(session).profit_by_sku(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
    )
    return page(
        "Аналитика",
        _user_display_name(user),
        _analytics_content(dashboard_data, profit_data),
        active_path="/web/analytics",
    )


@router.get("/control", response_class=HTMLResponse)
async def control_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    data = await WebCabinetService(session).control_page(user.id)
    return page(
        "Контроль ошибок",
        _user_display_name(user),
        _control_content(data),
        active_path="/web/control",
    )
