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
from app.services.cost_management_service import CostManagementError
from app.services.data_quality_service import DataQualityService
from app.services.feature_access_service import FeatureAccessService
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


@router.get("/products", response_class=HTMLResponse)
async def products_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    rows = await MasterProductService(session).list_analytics(user.id)
    await session.commit()
    content = _products_content(rows)
    return page(
        "Товары",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/products",
    )


@router.get("/products/{master_product_id}", response_class=HTMLResponse)
async def product_detail_page(
    master_product_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    detail = await MasterProductService(session).detail(user.id, master_product_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return page(
        "Карточка товара",
        user.first_name or user.username or str(user.telegram_id),
        _master_product_detail_content(detail),
        active_path="/web/products",
    )


@router.get("/product-matching", response_class=HTMLResponse)
async def product_matching_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    data = await MasterProductService(session).matching_candidates(user.id)
    return page(
        "Сопоставление товаров",
        user.first_name or user.username or str(user.telegram_id),
        _product_matching_content(data),
        active_path="/web/products",
    )


@router.post("/product-matching/create")
async def product_matching_create(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    form = await _urlencoded_form(request)
    raw_ids = ",".join(form.get("product_ids", []))
    ids = _parse_int_list(raw_ids)
    await MasterProductService(session).create_manual_group(user.id, ids)
    await session.commit()
    return RedirectResponse(url="/web/product-matching", status_code=303)


@router.post("/product-matching/unlink")
async def product_matching_unlink(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    form = await _urlencoded_form(request)
    product_id = int((form.get("product_id") or ["0"])[0])
    await MasterProductService(session).unlink_product(user.id, product_id)
    await session.commit()
    return RedirectResponse(url="/web/product-matching", status_code=303)


@router.get("/stocks", response_class=HTMLResponse)
async def stocks_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    stock_status: str = Query(default="all"),
) -> str:
    access = await FeatureAccessService(session).can_use_feature(
        user.id, FeatureCode.STOCKOUT_FORECAST
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
        return page(
            "Остатки",
            user.first_name or user.username or str(user.telegram_id),
            locked,
            active_path="/web/stocks",
        )

    rows = await StockForecastService(session).forecast(user_id=user.id)
    content = _stocks_forecast_content(
        _filter_stock_rows(rows, marketplace, sale_model, stock_status),
        marketplace=marketplace,
        sale_model=sale_model,
        stock_status=stock_status,
    )
    return page(
        "Остатки",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/stocks",
    )
