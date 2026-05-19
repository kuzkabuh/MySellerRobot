# ruff: noqa: E501, F401, F403, F405

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

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


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="today"),
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    service = WebDashboardService(session)
    data = await service.dashboard(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
    )
    subscription = await WebCabinetService(session).subscription_page(user.id)
    accounts = await WebCabinetService(session).accounts_page(user.id)
    content = _dashboard_welcome(user, subscription, accounts, data) + _dashboard_content(data)
    return page("Главная", _user_display_name(user), content)


@router.get("/web", response_class=HTMLResponse, include_in_schema=False)
@router.get("/web/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_compat(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="today"),
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    """Render cabinet dashboard for legacy double-/web upstream paths."""

    return cast(
        str,
        await _facade().dashboard(
            user=user,
            session=session,
            period=period,
            marketplace=marketplace,
            sale_model=sale_model,
            date_from=date_from,
            date_to=date_to,
        ),
    )
