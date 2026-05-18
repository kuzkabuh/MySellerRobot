# ruff: noqa: E501, F401, F403, F405

import logging
from datetime import UTC, date, datetime
from decimal import Decimal

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

@router.get("/costs", response_class=HTMLResponse)
async def costs_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    data = await WebCabinetService(session).costs_page(user.id)
    return page(
        "Себестоимость",
        _user_display_name(user),
        _costs_content(data),
        active_path="/web/costs",
    )


@router.get("/costs/{product_id}", response_class=HTMLResponse)
async def cost_edit_page(
    product_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    detail = await WebCabinetService(session).product_cost_detail(
        user_id=user.id,
        product_id=product_id,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return page(
        "Редактирование себестоимости",
        _user_display_name(user),
        _cost_edit_content(detail),
        active_path="/web/costs",
    )


@router.post("/costs/{product_id}")
async def save_product_cost(
    product_id: int,
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    form = await _urlencoded_form(request)
    try:
        detail = await WebCabinetService(session).product_cost_detail(
            user_id=user.id,
            product_id=product_id,
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="Товар не найден")
        await ProductCostRepository(session).add_cost(
            CostUpdate(
                product_id=product_id,
                cost_price=_decimal_from_query(_form_value(form, "cost_price", "0"), Decimal("0")),
                package_cost=_decimal_from_query(
                    _form_value(form, "package_cost", "0"), Decimal("0")
                ),
                additional_cost=_decimal_from_query(
                    _form_value(form, "additional_cost", "0"), Decimal("0")
                ),
                tax_rate=(
                    _decimal_from_query(_form_value(form, "tax_rate", "0"), Decimal("0"))
                    / Decimal("100")
                ).quantize(Decimal("0.0001")),
                valid_from=_datetime_from_form(_form_value(form, "valid_from", "")),
                comment=_form_value(form, "comment", ""),
            )
        )
        await session.commit()
    except CostManagementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/web/costs/{product_id}?saved=1", status_code=303)


@router.post("/web/costs/{product_id}", include_in_schema=False)
async def save_product_cost_legacy_double_web(
    product_id: int,
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Accept cost saves from old /web/web/costs/{id} tabs and redirect canonically."""

    return await save_product_cost(
        product_id=product_id,
        request=request,
        user=user,
        session=session,
    )


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    subscription = await WebCabinetService(session).subscription_page(user.id)
    return page(
        "Профиль",
        _user_display_name(user),
        _profile_content(user, subscription),
        active_path="/web/profile",
    )


@router.post("/profile")
async def save_profile_settings(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    form = await _urlencoded_form(request)
    db_user = await session.get(User, user.id)
    if db_user is not None:
        db_user.timezone = _form_value(form, "timezone", "Europe/Moscow")[:64]
        db_user.notifications_enabled = _form_value(form, "notifications_enabled", "off") == "on"
        db_user.low_margin_threshold_percent = _decimal_from_query(
            _form_value(form, "low_margin_threshold_percent", "10"),
            Decimal("10"),
        )
    await session.commit()
    return RedirectResponse(url="/web/profile?saved=1", status_code=303)


@router.get("/subscription", response_class=HTMLResponse)
async def subscription_page_web(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    data = await WebCabinetService(session).subscription_page(user.id)
    tiers = await SubscriptionService(session).get_all_tiers()
    return page(
        "Подписка и тариф",
        _user_display_name(user),
        _subscription_content(data, tiers),
        active_path="/web/subscription",
    )


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page_web(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    data = await WebCabinetService(session).accounts_page(user.id)
    return page(
        "Кабинеты маркетплейсов",
        _user_display_name(user),
        _accounts_content(data),
        active_path="/web/accounts",
    )


@router.post("/sync/{sync_type}")
async def request_web_sync(
    sync_type: str,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> RedirectResponse:
    result = await WebSyncService().request_sync(sync_type, user.id)
    return RedirectResponse(
        url=f"/web/accounts?sync={'queued' if result.queued else 'skipped'}",
        status_code=303,
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(user: User = CURRENT_WEB_USER_DEPENDENCY) -> str:
    return page(
        "Настройки",
        user.first_name or user.username or str(user.telegram_id),
        _settings_content(user),
        active_path="/web/settings",
    )


@router.post("/settings/low-margin")
async def save_low_margin_settings(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    form = await _urlencoded_form(request)
    threshold = (form.get("threshold") or ["10"])[0]
    value = _decimal_from_query(threshold, Decimal("10"))
    if value < 0 or value > 100:
        raise HTTPException(status_code=400, detail="Порог должен быть от 0 до 100%")
    db_user = await session.get(User, user.id)
    if db_user is not None:
        db_user.low_margin_threshold_percent = value
    await session.commit()
    return RedirectResponse(url="/web/settings", status_code=303)

