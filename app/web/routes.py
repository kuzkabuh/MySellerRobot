"""version: 3.0.0
description: FastAPI web cabinet routes with full seller workspace pages and forms.
updated: 2026-05-17
"""
# ruff: noqa: E501

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.models.domain import AlertEvent, MarketplaceAccount, User
from app.models.enums import Marketplace
from app.models.subscriptions import SubscriptionTier
from app.repositories.products import ProductCostRepository
from app.repositories.web_auth import WebAuthRepository
from app.schemas.products import CostUpdate
from app.services.cost_management_service import CostManagementError
from app.services.data_quality_service import DataQualityReport, DataQualityService
from app.services.master_product_service import (
    MasterProductAnalyticsRow,
    MasterProductDetail,
    MasterProductService,
    ProductMatchingCandidate,
)
from app.services.plan_fact_service import PlanFactPageData, PlanFactService
from app.services.stock_forecast_service import StockForecastRow, StockForecastService
from app.services.subscription_service import SubscriptionService
from app.services.unit_economics_service import BreakEvenRow, UnitEconomicsService
from app.services.web_auth_service import WEB_SESSION_COOKIE, WebAuthService
from app.services.web_cabinet_service import (
    AccountsPageData,
    ControlPageData,
    CostsPageData,
    ProductCostDetail,
    ReturnsPageData,
    SalesPageData,
    SubscriptionPageData,
    WebCabinetService,
    subscription_status,
)
from app.services.web_dashboard_service import (
    DailyPoint,
    DashboardData,
    DashboardFilters,
    KpiMetric,
    WebDashboardService,
)
from app.services.web_orders_profit_service import (
    OrderDetail,
    OrderRow,
    OrderWebFilters,
    ProfitPageData,
    WebOrdersProfitService,
    localized_order_date,
    order_state_label,
)
from app.web.rendering import page

router = APIRouter(prefix="/web", tags=["web"])
SESSION_DEPENDENCY = Depends(get_session)
WEB_DASHBOARD_PATH = "/web/"
WEB_LOGIN_REQUIRED_PATH = "/web/login-required"
WEB_SESSION_COOKIE_PATH = "/"
logger = logging.getLogger(__name__)
ZERO = Decimal("0")


async def current_web_user(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> User:
    raw_session = request.cookies.get(WEB_SESSION_COOKIE)
    if not raw_session:
        raise HTTPException(status_code=401, detail="Требуется вход в web-кабинет")
    user = await WebAuthRepository(session).get_active_session_user(
        WebAuthService.hash_secret(raw_session)
    )
    await session.commit()
    if user is None:
        raise HTTPException(status_code=401, detail="Сессия истекла")
    return user


CURRENT_WEB_USER_DEPENDENCY = Depends(current_web_user)


@router.get("/login")
async def login(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
    token: str | None = Query(default=None),
) -> Response:
    if not token:
        logger.info("web_login_missing_token", extra={"path": _request_path(request)})
        return HTMLResponse(
            "<h1>Ссылка недействительна</h1>"
            "<p>В ссылке входа отсутствует токен. Запросите новую ссылку в Telegram-боте.</p>",
            status_code=400,
        )
    masked_token = _mask_token(token)
    logger.info(
        "web_login_attempt",
        extra={"path": _request_path(request), "token": masked_token},
    )
    web_session = await WebAuthService(session).consume_login_token(
        token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    if web_session is None:
        await session.rollback()
        logger.info(
            "web_login_failed",
            extra={"path": _request_path(request), "token": masked_token},
        )
        return HTMLResponse(
            "<h1>Ссылка для входа недействительна</h1>"
            "<p>Срок действия ссылки истёк, ссылка уже использована или токен повреждён. "
            "Получите новую ссылку в Telegram-боте.</p>",
            status_code=400,
        )
    await session.commit()
    logger.info(
        "web_login_success",
        extra={"path": _request_path(request), "target": WEB_DASHBOARD_PATH},
    )
    response = RedirectResponse(url=WEB_DASHBOARD_PATH, status_code=303)
    response.set_cookie(
        WEB_SESSION_COOKIE,
        web_session.token,
        expires=web_session.expires_at,
        httponly=True,
        samesite="lax",
        path=WEB_SESSION_COOKIE_PATH,
        secure=(
            getattr(getattr(request, "url", None), "scheme", "http") == "https"
            or get_settings().app_env == "production"
        ),
    )
    return response


@router.get("/web/login")
async def login_compat(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
    token: str | None = Query(default=None),
) -> Response:
    return await login(request=request, session=session, token=token)


@router.get("/payment/success")
async def payment_success() -> HTMLResponse:
    """Payment return page after YooKassa redirect."""
    return HTMLResponse(
        """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Оплата принята</title>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    max-width: 600px; margin: 100px auto; padding: 20px; text-align: center;
                }
                h1 { color: #2ea043; }
                p { color: #57606a; line-height: 1.6; }
                .icon { font-size: 64px; margin-bottom: 20px; }
            </style>
        </head>
        <body>
            <div class="icon">✅</div>
            <h1>Платёж принят</h1>
            <p>Ваш платёж успешно обработан.</p>
            <p>Подписка активируется автоматически после подтверждения платёжной системой.</p>
            <p><strong>Вернитесь в Telegram-бот</strong>, чтобы продолжить работу.</p>
        </body>
        </html>
        """,
        status_code=200,
    )


@router.get("/logout")
async def logout(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    await WebAuthService(session).revoke_session(request.cookies.get(WEB_SESSION_COOKIE))
    await session.commit()
    response = RedirectResponse(url=WEB_LOGIN_REQUIRED_PATH, status_code=303)
    response.delete_cookie(WEB_SESSION_COOKIE, path=WEB_SESSION_COOKIE_PATH)
    response.delete_cookie(WEB_SESSION_COOKIE, path="/web")
    return response


@router.get("/login-required", response_class=HTMLResponse)
async def login_required() -> str:
    return (
        "<h1>Вход в web-кабинет</h1>"
        "<p>Откройте Telegram-бота и нажмите «🌐 Web-кабинет», чтобы получить новую ссылку.</p>"
    )


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
    content = _dashboard_welcome(user, subscription, accounts) + _dashboard_content(data)
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

    return await dashboard(
        user=user,
        session=session,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/orders", response_class=HTMLResponse)
async def orders_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="today"),
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    economy: str = Query(default="all"),
    status: str = Query(default="all"),
    sku: str = Query(default=""),
    sort: str = Query(default="date"),
    direction: str = Query(default="desc"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    filters, rows = await WebOrdersProfitService(session).list_orders(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
        economy=economy,
        status=status,
        sku=sku,
        sort=sort,
        direction=direction,
    )
    content = _orders_content(filters, rows, user.timezone)
    return page(
        "Заказы",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/orders",
    )


@router.get("/orders/{order_id}", response_class=HTMLResponse)
async def order_detail_page(
    order_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    detail = await WebOrdersProfitService(session).order_detail(user_id=user.id, order_id=order_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    content = _order_detail_content(detail, user.timezone)
    return page(
        "Карточка заказа",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/orders",
    )


@router.get("/profit", response_class=HTMLResponse)
async def profit_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="7d"),
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    economy: str = Query(default="all"),
    sku: str = Query(default=""),
    sort: str = Query(default="profit"),
    direction: str = Query(default="desc"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    data = await WebOrdersProfitService(session).profit_by_sku(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
        economy=economy,
        sku=sku,
        sort=sort,
        direction=direction,
    )
    content = _profit_content(data)
    return page(
        "Прибыль",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/profit",
    )


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


@router.get("/break-even", response_class=HTMLResponse)
async def break_even_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    target_margin: str = Query(default="20"),
    price_delta: str = Query(default="0"),
) -> str:
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


@router.get("/sales", response_class=HTMLResponse)
async def sales_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="30d"),
    marketplace: str = Query(default="all"),
    sku: str = Query(default=""),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    data = await WebCabinetService(session).sales_page(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sku=sku,
        date_from=date_from,
        date_to=date_to,
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
) -> str:
    rows = await StockForecastService(session).forecast(user_id=user.id)
    content = _stocks_forecast_content(rows)
    return page(
        "Остатки",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/stocks",
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
    content = _alerts_content(list(result.scalars().all()))
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
    report = await DataQualityService(session).report(user_id=user.id)
    content = _data_quality_content(report)
    return page(
        "Качество данных",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/data-quality",
    )


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    dashboard_data = await WebDashboardService(session).dashboard(
        user_id=user.id,
        timezone=user.timezone,
        period="30d",
        marketplace="all",
        sale_model="all",
    )
    profit_data = await WebOrdersProfitService(session).profit_by_sku(
        user_id=user.id,
        timezone=user.timezone,
        period="30d",
        marketplace="all",
        sale_model="all",
        date_from=None,
        date_to=None,
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
            await dashboard(
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
            await orders_page(
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
        return HTMLResponse(await order_detail_page(order_id=order_id, user=user, session=session))
    if normalized == "profit":
        return HTMLResponse(
            await profit_page(
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
            await plan_fact_page(
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
            await break_even_page(
                user=user,
                session=session,
                target_margin=_query_param(request, "target_margin", "20"),
                price_delta=_query_param(request, "price_delta", "0"),
            )
        )
    if normalized == "products":
        return HTMLResponse(await products_page(user=user, session=session))
    if normalized.startswith("products/"):
        try:
            product_id = int(normalized.split("/", 1)[1])
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Товар не найден") from exc
        return HTMLResponse(
            await product_detail_page(master_product_id=product_id, user=user, session=session)
        )
    if normalized == "product-matching":
        return HTMLResponse(await product_matching_page(user=user, session=session))
    if normalized == "stocks":
        return HTMLResponse(await stocks_page(user=user, session=session))
    if normalized == "alerts":
        return HTMLResponse(await alerts_page(user=user, session=session))
    if normalized == "data-quality":
        return HTMLResponse(await data_quality_page(user=user, session=session))
    if normalized == "sales":
        return HTMLResponse(
            await sales_page(
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
            await returns_page(
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
        return HTMLResponse(await analytics_page(user=user, session=session))
    if normalized == "control":
        return HTMLResponse(await control_page(user=user, session=session))
    if normalized == "costs":
        return HTMLResponse(await costs_page(user=user, session=session))
    if normalized.startswith("costs/"):
        try:
            product_id = int(normalized.split("/", 1)[1])
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Товар не найден") from exc
        return HTMLResponse(await cost_edit_page(product_id=product_id, user=user, session=session))
    if normalized == "profile":
        return HTMLResponse(await profile_page(user=user, session=session))
    if normalized == "subscription":
        return HTMLResponse(await subscription_page_web(user=user, session=session))
    if normalized == "accounts":
        return HTMLResponse(await accounts_page_web(user=user, session=session))
    if normalized == "settings":
        return HTMLResponse(await settings_page(user=user))
    raise HTTPException(status_code=404, detail="Раздел не найден")


def _placeholder_page(section: str, user: User) -> str:
    titles = {
        "orders": "Заказы",
        "profit": "Прибыль",
        "break-even": "Безубыточность",
        "sales": "Продажи",
        "returns": "Возвраты",
        "products": "Товары",
        "stocks": "Остатки",
        "alerts": "Алерты",
        "data-quality": "Качество данных",
        "analytics": "Аналитика",
        "control": "Контроль",
        "costs": "Себестоимость",
        "settings": "Настройки",
    }
    title = titles.get(section)
    if title is None:
        raise HTTPException(status_code=404, detail="Раздел не найден")
    content = (
        '<section class="band">'
        f"<h2>{title}</h2>"
        '<div class="empty-state">Откройте раздел через основное меню web-кабинета.</div>'
        "</section>"
    )
    return page(
        title,
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path=f"/web/{section}",
    )


def _orders_content(filters: OrderWebFilters, rows: list[OrderRow], timezone: str) -> str:
    table_rows = []
    for row in rows:
        profit = row.estimated_profit
        profit_badge = "bad" if profit is not None and profit < 0 else "good"
        cost_badge = '<span class="badge warn">без себестоимости</span>' if row.missing_cost else ""
        action_badge = (
            '<span class="badge action">требует действия</span>'
            if row.requires_action
            else '<span class="badge">инфо</span>'
        )
        confidence_badge = _confidence_badge(row.economy_confidence)
        profit_cell = (
            f'<td class="num"><span class="badge {profit_badge}">'
            f"{_rub_optional(profit)}</span></td>"
        )
        table_rows.append(
            "<tr>"
            f"<td>{localized_order_date(row.order_date, timezone)}</td>"
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f"<td>{escape(row.sale_model.value if row.sale_model else 'н/д')}</td>"
            f'<td><a href="/web/orders/{row.order_id}">{escape(row.title)}</a>'
            f'<div class="muted">{escape(row.seller_article)}</div>{cost_badge}</td>'
            f"<td>{escape(row.order_external_id)}"
            f'<div class="muted">{escape(row.posting_number or "")}</div></td>'
            f'<td class="num">{row.quantity}</td>'
            f'<td class="num">{_rub(row.revenue)}</td>'
            f"{profit_cell}"
            f'<td class="num">{_percent_optional(row.margin_percent)}</td>'
            f"<td>{escape(row.status)}<div>{action_badge} {confidence_badge}</div></td>"
            f"<td>{escape(row.source_event_type)}</td>"
            "</tr>"
        )
    body = (
        "".join(table_rows)
        if table_rows
        else '<tr><td colspan="11" class="muted">Заказов по выбранным фильтрам пока нет.</td></tr>'
    )
    return f"""
      {_section_subnav("orders")}
      {_orders_filters(filters)}
      <section class="band">
        <h2>Заказы и позиции</h2>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Дата</th><th>МП</th><th>Модель</th><th>Товар</th>
                <th>Заказ / отправление</th><th class="num">Кол-во</th>
                <th class="num">Цена</th><th class="num">Плановая прибыль</th>
                <th class="num">Маржа</th><th>Статус</th><th>Источник</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """


def _order_detail_content(detail: OrderDetail, timezone: str) -> str:
    order = detail.order
    item_rows = []
    for item_detail in detail.items:
        item = item_detail.item
        estimated = item_detail.estimated_snapshot
        actual = item_detail.actual_snapshot
        estimated_profit = estimated.profit if estimated else item.profit_estimated
        actual_profit = actual.profit if actual else None
        confidence = (
            estimated.economy_confidence
            if estimated and estimated.economy_confidence
            else item.economy_confidence
        )
        item_rows.append(
            "<tr>"
            f"<td>{escape(item.title or 'Без названия')}"
            f'<div class="muted">{escape(item.seller_article or "н/д")}</div></td>'
            f'<td class="num">{item.quantity}</td>'
            f'<td class="num">{_rub(item.discounted_price * item.quantity)}</td>'
            f'<td class="num">{_rub_optional(item.commission_estimated)}</td>'
            f'<td class="num">{_rub_optional(item.logistics_estimated)}</td>'
            f'<td class="num">{_rub_optional(item.cost_price_used)}</td>'
            f'<td class="num">{_rub_optional(item.package_cost_used)}</td>'
            f'<td class="num">{_rub_optional(item.tax_amount_estimated)}</td>'
            f'<td class="num">{_rub_optional(estimated_profit)}</td>'
            f'<td class="num">{_rub_optional(actual_profit)}</td>'
            f"<td>{_confidence_badge(confidence)}</td>"
            "</tr>"
        )
    raw_payload = escape(json.dumps(order.raw_payload or {}, ensure_ascii=False, indent=2))
    deadline = (
        localized_order_date(order.processing_deadline_at, timezone)
        if order.processing_deadline_at
        else "н/д"
    )
    sale_model = escape(order.sale_model.value if order.sale_model else "н/д")
    order_date = localized_order_date(order.order_date, timezone)
    order_state = escape(order_state_label(order.normalized_status, order.requires_seller_action))
    return f"""
      {_section_subnav("orders")}
      <section class="detail-grid">
        <section class="band">
          <h2>Информация</h2>
          <div class="kv">
            <span>Маркетплейс</span><strong>{_marketplace_label(order.marketplace)}</strong>
            <span>Модель</span><strong>{sale_model}</strong>
            <span>Статус</span><strong>{escape(order.normalized_status or order.status)}</strong>
            <span>Дата заказа</span><strong>{order_date}</strong>
            <span>Дедлайн</span><strong>{deadline}</strong>
            <span>Заказ</span><strong>{escape(order.order_external_id)}</strong>
            <span>Действие</span><strong>{order_state}</strong>
          </div>
        </section>
        <section class="band">
          <h2>План / факт</h2>
          <div class="kv">
            <span>Плановая прибыль</span><strong>{_rub(detail.estimated_profit)}</strong>
            <span>Фактическая прибыль</span><strong>{_rub_optional(detail.actual_profit)}</strong>
            <span>Отклонение</span><strong>{_rub_optional(detail.deviation)}</strong>
          </div>
          <p class="muted">
            Если фактическая прибыль отсутствует, финансовые отчёты маркетплейса
            ещё не сопоставлены с заказом.
          </p>
        </section>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Экономика позиций</h2>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th class="num">Кол-во</th><th class="num">Цена</th>
                <th class="num">Комиссия</th><th class="num">Логистика</th>
                <th class="num">Себестоимость</th><th class="num">Упаковка</th>
                <th class="num">Налог</th><th class="num">План</th><th class="num">Факт</th>
                <th>Достоверность</th>
              </tr>
            </thead>
            <tbody>{"".join(item_rows)}</tbody>
          </table>
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Исходные данные</h2>
        <pre class="mono">{raw_payload}</pre>
      </section>
    """


def _plan_fact_content(data: PlanFactPageData) -> str:
    summary = data.summary
    row_html = []
    for row in data.rows:
        deviation_tone = "bad" if row.deviation < 0 else "good"
        pending = (
            f'<span class="badge warn">{row.pending_actual} без факта</span>'
            if row.pending_actual
            else ""
        )
        row_html.append(
            "<tr>"
            f'<td>{escape(row.title)}<div class="muted">{escape(row.seller_article)}</div></td>'
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f"<td>{escape(row.sale_model.value if row.sale_model else 'н/д')}</td>"
            f'<td class="num">{row.orders}</td>'
            f'<td class="num">{_rub(row.estimated_profit)}</td>'
            f'<td class="num">{_rub(row.actual_profit)}</td>'
            f'<td class="num"><span class="badge {deviation_tone}">'
            f"{_rub(row.deviation)}</span></td>"
            f'<td class="num">{_percent_optional(row.deviation_percent)}</td>'
            f"<td>{escape(row.reason)} {pending}</td>"
            "</tr>"
        )
    body = (
        "".join(row_html)
        if row_html
        else '<tr><td colspan="9" class="muted">Данных для сравнения план/факт пока нет.</td></tr>'
    )
    deviation_tone = "bad" if summary.deviation < 0 else "good"
    return f"""
      {_section_subnav("plan_fact")}
      {_plan_fact_filters(data)}
      <section class="kpi-grid">
        {_simple_kpi("Плановая прибыль", _rub(summary.estimated_profit))}
        {_simple_kpi("Фактическая прибыль", _rub(summary.actual_profit))}
        {_simple_kpi("Отклонение", _rub(summary.deviation), deviation_tone)}
        {_simple_kpi("Без факта", str(summary.pending_actual), "warn")}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Отклонения по товарам</h2>
        <p class="muted">
          Факт появляется после сопоставления финансовых отчётов маркетплейса.
          Причина отклонения определяется по основному видимому фактору.
        </p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th>МП</th><th>Модель</th><th class="num">Заказов</th>
                <th class="num">План</th><th class="num">Факт</th>
                <th class="num">Отклонение</th><th class="num">%</th><th>Причина</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """


def _break_even_content(
    rows: list[BreakEvenRow],
    target_margin: str,
    price_delta: str,
) -> str:
    body = "".join(
        "<tr>"
        f'<td>{escape(row.title)}<div class="muted">{escape(row.seller_article)}</div></td>'
        f"<td>{_marketplace_label(row.marketplace)}</td>"
        f'<td class="num">{_rub(row.current_price)}</td>'
        f'<td class="num">{_rub(row.break_even_price)}</td>'
        f'<td class="num">{_rub(row.target_margin_price)}</td>'
        f'<td class="num">{row.commission_rate}%</td>'
        f'<td class="num">{_rub(row.logistics_cost)}</td>'
        f'<td class="num">{_rub(row.simulated_price)}</td>'
        f'<td class="num">{_rub(row.simulated_profit)}</td>'
        f'<td class="num">{row.simulated_margin_percent}%</td>'
        f"<td>{escape(row.recommendation)}</td>"
        "</tr>"
        for row in rows
    )
    if not body:
        body = (
            '<tr><td colspan="11" class="muted">'
            "Недостаточно заказов с экономикой для расчёта безубыточности.</td></tr>"
        )
    return f"""
      {_section_subnav("break_even")}
      <form class="filters" method="get" action="/web/break-even">
        <div>
          <label for="target_margin">Целевая маржа, %</label>
          <input id="target_margin" name="target_margin" type="number"
                 value="{escape(target_margin)}">
        </div>
        <div>
          <label for="price_delta">Симуляция цены, %</label>
          <input id="price_delta" name="price_delta" type="number" value="{escape(price_delta)}">
        </div>
        <button class="button primary" type="submit">Пересчитать</button>
      </form>
      <section class="band">
        <h2>Безубыточная цена и симулятор</h2>
        <p class="muted">
          Расчёт использует средние комиссию, логистику, налог и себестоимость из последних
          заказов. Прогнозные значения не считаются фактическим финансовым отчётом.
        </p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th>МП</th><th class="num">Текущая цена</th>
                <th class="num">Безубыток</th><th class="num">Цена для цели</th>
                <th class="num">Комиссия</th><th class="num">Логистика</th>
                <th class="num">Цена симуляции</th><th class="num">Прибыль</th>
                <th class="num">Маржа</th><th>Рекомендация</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """


def _products_content(rows: list[MasterProductAnalyticsRow]) -> str:
    row_html = []
    for row in rows:
        marketplace_badges = (
            f'<span class="badge wb">WB: {row.wb_products}</span> '
            f'<span class="badge ozon">Ozon: {row.ozon_products}</span>'
        )
        linked_products = "".join(
            '<div class="muted">'
            f"{_marketplace_label(item.marketplace)}: "
            f"{escape(item.seller_article)} / {escape(item.marketplace_article)}"
            f' · <a href="/web/costs/{item.product_id}">себестоимость</a>'
            "</div>"
            for item in row.marketplace_products
        )
        image = (
            f'<img src="{escape(row.image_url)}" alt="{escape(row.title)}" '
            'style="width:48px;height:48px;object-fit:cover;border-radius:6px;margin-right:10px">'
            if row.image_url
            else '<div class="product-thumb">нет фото</div>'
        )
        title_cell = (
            '<div style="display:flex;align-items:center;gap:10px">'
            f'{image}<div><strong><a href="/web/products/{row.master_product_id}">'
            f"{escape(row.title)}</a></strong>"
            f'<div class="muted">{escape(row.brand)} · {escape(row.category)}</div>'
            f"{linked_products}</div></div>"
        )
        profit_badge = "bad" if row.estimated_profit < 0 else "good"
        row_html.append(
            "<tr>"
            f"<td>{title_cell}</td>"
            f"<td>{escape(row.canonical_sku)}</td>"
            f"<td>{marketplace_badges}</td>"
            f'<td class="num">{row.orders}</td>'
            f'<td class="num">{row.sales}</td>'
            f'<td class="num">{_rub(row.revenue)}</td>'
            f'<td class="num"><span class="badge {profit_badge}">'
            f"{_rub(row.estimated_profit)}</span></td>"
            f'<td class="num">{row.stock_quantity}</td>'
            "</tr>"
        )
    body = (
        "".join(row_html)
        if row_html
        else (
            '<tr><td colspan="8" class="muted">'
            "Товары пока не импортированы. Подключите кабинет или запустите "
            "синхронизацию.</td></tr>"
        )
    )
    return f"""
      {_section_subnav("products")}
      <section class="band">
        <h2>Единые карточки товаров</h2>
        <p class="muted">
          Товары WB и Ozon сопоставляются по артикулу продавца. Это база для сравнения
          площадок, общей прибыли и карточки MasterProduct.
        </p>
        <p><a class="button" href="/web/product-matching">Сопоставление товаров</a></p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th>Единый SKU</th><th>Площадки</th>
                <th class="num">Заказов</th><th class="num">Выкупов</th>
                <th class="num">Выручка</th><th class="num">Плановая прибыль</th>
                <th class="num">Остаток</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """


def _master_product_detail_content(detail: MasterProductDetail) -> str:
    product_rows = "".join(
        "<tr>"
        f"<td>{_marketplace_label(item.marketplace)}</td>"
        f"<td>{escape(item.seller_article)}</td>"
        f"<td>{escape(item.marketplace_article)}</td>"
        f"<td>{escape(item.title)}</td>"
        f"<td>{escape(item.brand)}</td>"
        f'<td><a class="button" href="/web/costs/{item.product_id}">Себестоимость</a></td>'
        "</tr>"
        for item in detail.marketplace_products
    )
    comparison_rows = "".join(
        "<tr>"
        f"<td>{_marketplace_label(row.marketplace)}</td>"
        f'<td class="num">{row.orders}</td>'
        f'<td class="num">{row.sales}</td>'
        f'<td class="num">{_rub(row.revenue)}</td>'
        f'<td class="num">{_rub(row.estimated_profit)}</td>'
        f'<td class="num">{_rub(row.actual_profit)}</td>'
        f'<td class="num">{_percent_optional(row.margin_percent)}</td>'
        f'<td class="num">{row.stock_quantity}</td>'
        "</tr>"
        for row in detail.marketplace_comparison
    )
    recommendations = "".join(f"<li>{escape(item)}</li>" for item in detail.recommendations)
    image = (
        f'<img src="{escape(detail.image_url)}" alt="{escape(detail.title)}" '
        'style="width:96px;height:96px;object-fit:cover;border-radius:6px">'
        if detail.image_url
        else '<div class="product-thumb">нет фото</div>'
    )
    return f"""
      {_section_subnav("products")}
      <section class="band">
        <div style="display:flex;align-items:center;gap:14px">
          {image}
          <div>
            <h2>{escape(detail.title)}</h2>
            <p class="muted">{escape(detail.brand)} · {escape(detail.category)}</p>
            <p class="muted">Единый SKU: {escape(detail.canonical_sku)}</p>
          </div>
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Сравнение WB / Ozon</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>МП</th><th class="num">Заказов</th><th class="num">Выкупов</th>
            <th class="num">Выручка</th><th class="num">План</th><th class="num">Факт</th>
            <th class="num">Маржа</th><th class="num">Остаток</th></tr></thead>
            <tbody>{comparison_rows}</tbody>
          </table>
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Что важно</h2>
        <ul>{recommendations}</ul>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Связанные карточки</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>МП</th><th>Артикул продавца</th><th>Артикул МП</th>
          <th>Название</th><th>Бренд</th><th>Действие</th></tr></thead>
          <tbody>{product_rows}</tbody>
        </table></div>
      </section>
    """


def _product_matching_content(candidates: list[ProductMatchingCandidate]) -> str:
    rows = "".join(
        "<tr>"
        f'<td><input type="checkbox" name="product_ids" value="{item.product_id}"></td>'
        f"<td>{_marketplace_label(item.marketplace)}</td>"
        f"<td>{escape(item.seller_article)}</td>"
        f"<td>{escape(item.marketplace_article)}</td>"
        f"<td>{escape(item.title)}</td>"
        f"<td>{escape(item.current_group or 'нет группы')}</td>"
        f'<td><form method="post" action="/web/product-matching/unlink">'
        f'<input type="hidden" name="product_id" value="{item.product_id}">'
        '<button class="button" type="submit">Исключить</button></form></td>'
        "</tr>"
        for item in candidates
    )
    if not rows:
        rows = (
            '<tr><td colspan="7" class="muted">Товары для сопоставления пока не найдены.</td></tr>'
        )
    return f"""
      {_section_subnav("products")}
      <section class="band">
        <h2>Сопоставление товаров</h2>
        <p class="muted">
          Отметьте карточки WB/Ozon одного товара и создайте ручную группу. Ручная связь
          имеет приоритет над автоматическим сопоставлением по артикулу.
        </p>
        <form method="post" action="/web/product-matching/create">
          <div class="table-wrap"><table class="table">
            <thead><tr><th></th><th>МП</th><th>Артикул продавца</th><th>Артикул МП</th>
            <th>Название</th><th>Группа</th><th>Действие</th></tr></thead>
            <tbody>{rows}</tbody>
          </table></div>
          <button class="button primary" type="submit">Создать ручную MasterProduct-группу</button>
        </form>
      </section>
    """


def _stocks_forecast_content(rows: list[StockForecastRow]) -> str:
    body_rows = []
    for row in rows:
        days_until_stockout = (
            str(row.days_until_stockout) if row.days_until_stockout is not None else "н/д"
        )
        body_rows.append(
            "<tr>"
            f'<td>{escape(row.title)}<div class="muted">{escape(row.seller_article)}</div></td>'
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f"<td>{escape(row.warehouse)}</td>"
            f'<td class="num">{row.quantity}</td>'
            f'<td class="num">{row.average_daily_sales}</td>'
            f'<td class="num">{days_until_stockout}</td>'
            f'<td class="num">{_rub(row.lost_revenue_30d)}</td>'
            f"<td>{escape(row.status)}</td>"
            f"<td>{escape(row.recommendation)}</td>"
            "</tr>"
        )
    body = "".join(body_rows)
    if not body:
        body = (
            '<tr><td colspan="9" class="muted">'
            "Остатков пока нет. Дождитесь фоновой синхронизации складов.</td></tr>"
        )
    return f"""
      {_section_subnav("stocks")}
      <section class="band">
        <h2>Остатки, out-of-stock и потери выручки</h2>
        <p class="muted">
          Прогноз: текущий остаток делится на среднедневные выкупы за 30 дней.
          Упущенная выручка оценивается на горизонте 30 дней после даты возможного stockout.
        </p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th>МП</th><th>Склад</th><th class="num">Остаток</th>
                <th class="num">Продаж/день</th><th class="num">Дней запаса</th>
                <th class="num">Потери 30д</th><th>Статус</th><th>Рекомендация</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """


def _alerts_content(events: list[AlertEvent]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{escape(event.created_at.strftime('%d.%m.%Y %H:%M'))}</td>"
        f"<td>{escape(event.alert_type.value)}</td>"
        f"<td>{escape(event.title)}</td>"
        f"<td>{escape(event.message)}</td>"
        f"<td>{'отправлено' if event.sent_at else 'новое'}</td>"
        "</tr>"
        for event in events
    )
    if not body:
        body = '<tr><td colspan="5" class="muted">Активных алертов пока нет.</td></tr>'
    return f"""
      {_section_subnav("alerts")}
      <section class="band">
        <h2>Расширенные алерты</h2>
        <p class="muted">
          Здесь отображаются события по низкой марже, убыточным заказам, FBS-дедлайнам,
          остаткам, out-of-stock и качеству синхронизации.
        </p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>Дата</th><th>Тип</th><th>Заголовок</th><th>Сообщение</th><th>Статус</th></tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """


def _sales_content(data: SalesPageData, timezone: str, sku: str) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{localized_order_date(row.event_date, timezone)}</td>"
        f"<td>{_marketplace_label(row.marketplace)}</td>"
        f"<td>{escape(row.event_type)}</td>"
        f"<td>{escape(row.seller_article)}"
        f'<div class="muted">{escape(row.marketplace_article)}</div></td>'
        f'<td class="num">{row.quantity}</td>'
        f'<td class="num">{_rub(row.amount)}</td>'
        f'<td class="num">{_rub_optional(row.expected_payout)}</td>'
        f'<td class="num">{_rub_optional(row.estimated_profit)}</td>'
        f'<td class="num">{_rub_optional(row.actual_profit)}</td>'
        f"<td>{escape(row.order_external_id or 'н/д')}</td>"
        "</tr>"
        for row in data.rows
    )
    if not rows:
        rows = (
            '<tr><td colspan="10"><div class="empty-state">'
            "Продаж за выбранный период пока нет. Дождитесь синхронизации выкупов WB/Ozon."
            "</div></td></tr>"
        )
    return f"""
      {_page_header("Продажи", "Отслеживайте выкупы и завершённые продажи WB/Ozon.", "/web/orders", "Заказы")}
      {_sales_returns_filters("/web/sales", data.filters, sku)}
      <section class="kpi-grid">
        {_simple_kpi("Продаж", str(data.total_quantity))}
        {_simple_kpi("Выручка", _rub(data.total_amount))}
        {_simple_kpi("Плановая прибыль", _rub(data.total_profit), "good" if data.total_profit >= 0 else "bad")}
        {_simple_kpi("Средний чек", _rub(data.total_amount / Decimal(data.total_quantity) if data.total_quantity else ZERO))}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>События продаж</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Дата</th><th>МП</th><th>Тип</th><th>Товар</th>
          <th class="num">Кол-во</th><th class="num">Сумма</th><th class="num">Выплата</th>
          <th class="num">План</th><th class="num">Факт</th><th>Заказ</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
    """


def _returns_content(data: ReturnsPageData, timezone: str, sku: str) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{localized_order_date(row.event_date, timezone)}</td>"
        f"<td>{_marketplace_label(row.marketplace)}</td>"
        f"<td>{escape(row.order_external_id or 'н/д')}</td>"
        f'<td class="num">{row.quantity}</td>'
        f'<td class="num">{_rub(row.amount)}</td>'
        f"<td>{escape(row.reason)}</td>"
        "</tr>"
        for row in data.rows
    )
    if not rows:
        rows = (
            '<tr><td colspan="6"><div class="empty-state">'
            "Возвратов за выбранный период нет. Это хороший знак для контроля качества продаж."
            "</div></td></tr>"
        )
    return f"""
      {_page_header("Возвраты", "Контролируйте возвраты, суммы и причины по маркетплейсам.", "/web/sales", "Продажи")}
      {_sales_returns_filters("/web/returns", data.filters, sku)}
      <section class="kpi-grid">
        {_simple_kpi("Возвратов", str(data.total_quantity), "bad" if data.total_quantity else "neutral")}
        {_simple_kpi("Сумма возвратов", _rub(data.total_amount), "bad" if data.total_amount else "neutral")}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>События возвратов</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Дата</th><th>МП</th><th>Связанный заказ</th>
          <th class="num">Кол-во</th><th class="num">Сумма</th><th>Причина</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
    """


def _costs_content(data: CostsPageData) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{escape(row.product.title or 'Без названия')}"
        f'<div class="muted">{escape(row.product.seller_article or "н/д")}</div></td>'
        f"<td>{_marketplace_label(row.product.marketplace)}"
        f'<div class="muted">{escape(row.account_name)}</div></td>'
        f'<td class="num">{_rub(row.cost.cost_price) if row.cost else "не задана"}</td>'
        f'<td class="num">{_rub(row.cost.package_cost) if row.cost else "н/д"}</td>'
        f'<td class="num">{_rub(row.cost.additional_cost) if row.cost else "н/д"}</td>'
        f'<td class="num">{(row.cost.tax_rate * Decimal("100")).quantize(Decimal("0.01")) if row.cost else "н/д"}%</td>'
        f"<td>{row.cost.valid_from.strftime('%d.%m.%Y') if row.cost else 'н/д'}</td>"
        f"<td>{_cost_status_badge(row.cost is not None and row.cost.cost_price > 0)}</td>"
        f'<td><a class="button" href="/web/costs/{row.product.id}">Редактировать</a></td>'
        "</tr>"
        for row in data.rows
    )
    if not rows:
        rows = (
            '<tr><td colspan="10"><div class="empty-state">'
            "Товары ещё не синхронизированы. Подключите кабинет в Telegram-боте и дождитесь загрузки."
            "</div></td></tr>"
        )
    return f"""
      {_page_header("Себестоимость", "Контролируйте себестоимость, упаковку, доп. расходы и налог по товарам.", "/web/products", "Товары")}
      <section class="kpi-grid">
        {_simple_kpi("Себестоимость задана", str(data.configured_count), "good")}
        {_simple_kpi("Без себестоимости", str(data.missing_count), "warn" if data.missing_count else "neutral")}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Товары и текущая себестоимость</h2>
        <p class="muted">Новая запись создаётся исторически: предыдущий период закрывается датой начала новой себестоимости.</p>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Товар</th><th>Кабинет</th><th class="num">Себестоимость</th>
          <th class="num">Упаковка</th><th class="num">Доп. расходы</th><th class="num">Налог</th>
          <th>Обновлено</th><th>Статус</th><th>Действие</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
    """


def _cost_edit_content(detail: ProductCostDetail) -> str:
    latest = detail.history[0] if detail.history else None
    history = (
        "".join(
            "<tr>"
            f"<td>{row.valid_from.strftime('%d.%m.%Y')}</td>"
            f"<td>{row.valid_to.strftime('%d.%m.%Y') if row.valid_to else 'сейчас'}</td>"
            f'<td class="num">{_rub(row.cost_price)}</td>'
            f'<td class="num">{_rub(row.package_cost)}</td>'
            f'<td class="num">{_rub(row.additional_cost)}</td>'
            f'<td class="num">{(row.tax_rate * Decimal("100")).quantize(Decimal("0.01"))}%</td>'
            f"<td>{escape(row.comment or '')}</td>"
            "</tr>"
            for row in detail.history
        )
        or '<tr><td colspan="7" class="muted">Истории себестоимости пока нет.</td></tr>'
    )
    return f"""
      {_page_header("Редактирование себестоимости", escape(detail.product.title or "Без названия"), "/web/costs", "К списку")}
      <section class="detail-grid">
        <section class="band">
          <h2>Новая себестоимость</h2>
          <form method="post" action="/web/costs/{detail.product.id}">
            <label for="cost_price">Себестоимость</label>
            <input id="cost_price" name="cost_price" type="number" step="0.01" value="{latest.cost_price if latest else 0}">
            <label for="package_cost">Упаковка</label>
            <input id="package_cost" name="package_cost" type="number" step="0.01" value="{latest.package_cost if latest else 0}">
            <label for="additional_cost">Доп. расходы</label>
            <input id="additional_cost" name="additional_cost" type="number" step="0.01" value="{latest.additional_cost if latest else 0}">
            <label for="tax_rate">Налог, %</label>
            <input id="tax_rate" name="tax_rate" type="number" step="0.01" value="{(latest.tax_rate * Decimal("100")).quantize(Decimal("0.01")) if latest else 0}">
            <label for="valid_from">Дата начала действия</label>
            <input id="valid_from" name="valid_from" type="date" value="{datetime.now(tz=UTC).date().isoformat()}">
            <label for="comment">Комментарий</label>
            <input id="comment" name="comment" type="text" value="WEB-обновление">
            <p><button class="button primary" type="submit">Сохранить</button></p>
          </form>
        </section>
        <section class="band">
          <h2>Товар</h2>
          <div class="kv">
            <span>Маркетплейс</span><strong>{_marketplace_label(detail.product.marketplace)}</strong>
            <span>Кабинет</span><strong>{escape(detail.account_name)}</strong>
            <span>Артикул продавца</span><strong>{escape(detail.product.seller_article or "н/д")}</strong>
            <span>Артикул МП</span><strong>{escape(detail.product.marketplace_article or detail.product.external_product_id)}</strong>
            <span>Актуальная цена Ozon</span><strong>{_ozon_price_label(getattr(detail, "latest_ozon_price", None))}</strong>
          </div>
        </section>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>История себестоимости</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>С</th><th>По</th><th class="num">Себестоимость</th>
          <th class="num">Упаковка</th><th class="num">Доп. расходы</th>
          <th class="num">Налог</th><th>Комментарий</th></tr></thead>
          <tbody>{history}</tbody>
        </table></div>
      </section>
    """


def _accounts_content(data: AccountsPageData) -> str:
    rows = "".join(
        "<tr>"
        f'<td>{escape(row.account.name)}<div class="muted">#{row.account.id}'
        f"{_seller_name_hint(row.account)}</div></td>"
        f"<td>{_marketplace_label(row.account.marketplace)}</td>"
        f"<td>{_account_status_badge(row.account.status.value, row.account.is_active)}</td>"
        f"<td>{_dt(row.account.last_success_sync_at)}</td>"
        f'<td>{_dt(row.account.last_error_at)}<div class="muted">{escape(row.account.last_error_message or row.latest_job_error or "")}</div></td>'
        f'<td class="num">{row.products_count}</td>'
        f'<td class="num">{row.orders_30d}</td>'
        f"<td>{escape(row.latest_job_status or 'нет задач')}</td>"
        "</tr>"
        for row in data.rows
    )
    if not rows:
        rows = (
            '<tr><td colspan="8"><div class="empty-state">'
            "Кабинеты ещё не подключены. Подключение нового кабинета выполняется через Telegram-бота."
            "</div></td></tr>"
        )
    return f"""
      {_page_header("Кабинеты маркетплейсов", "Проверяйте подключённые кабинеты, статусы синхронизации и ошибки доступа.", "/web/profile", "Профиль")}
      <section class="kpi-grid">
        {_simple_kpi("Подключено кабинетов", f"{data.active_accounts} из {data.tier.max_marketplace_accounts}")}
        {_simple_kpi("Тариф", escape(data.tier.name))}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Wildberries и Ozon</h2>
        <p class="muted">Подключение нового кабинета сейчас выполняется через Telegram-бота: откройте настройки и выберите подключение WB или Ozon.</p>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Кабинет</th><th>МП</th><th>Статус</th><th>Успешная синхронизация</th>
          <th>Последняя ошибка</th><th class="num">Товаров</th><th class="num">Заказов 30д</th><th>Последняя задача</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
    """


def _seller_name_hint(account: MarketplaceAccount) -> str:
    if not account.seller_name and not account.seller_external_id:
        return ""
    label = account.seller_name or account.seller_external_id or ""
    return f" · продавец: {escape(label)}"


def _ozon_price_label(snapshot: object | None) -> str:
    if snapshot is None or not hasattr(snapshot, "price"):
        return "н/д"
    price = getattr(snapshot, "price", None)
    synced_at = getattr(snapshot, "synced_at", None)
    if price is None:
        return "н/д"
    date_label = f" · {_dt(synced_at)}" if synced_at else ""
    return f"{_rub(price)}{date_label}"


def _subscription_content(data: SubscriptionPageData, tiers: list[SubscriptionTier]) -> str:
    active = data.active_subscription
    status = subscription_status(active)
    expires = (
        active.expires_at.strftime("%d.%m.%Y") if active and active.expires_at else "бессрочно"
    )
    feature_rows = "".join(
        f"<li>{'✅' if enabled else '❌'} {escape(label)}</li>"
        for label, enabled in [
            ("Web-кабинет", data.tier.feature_web_cabinet),
            ("Расширенная аналитика", data.tier.feature_analytics),
            ("План/факт", data.tier.feature_plan_fact),
            ("Безубыточность", data.tier.feature_break_even),
            ("Прогноз остатков", data.tier.feature_stock_forecast),
            ("Алерты", data.tier.feature_alerts),
            ("API-доступ", data.tier.feature_api_access),
        ]
    )
    tier_cards = "".join(_web_tier_card(tier, data.tier.code) for tier in tiers)
    payment_rows = (
        "".join(
            "<tr>"
            f"<td>{payment.created_at.strftime('%d.%m.%Y')}</td>"
            f"<td>{_rub(payment.amount)}</td>"
            f"<td>{escape(payment.status.value)}</td>"
            f"<td>{escape(payment.provider)}</td>"
            "</tr>"
            for payment in data.payments
        )
        or '<tr><td colspan="4" class="muted">Платежей пока нет.</td></tr>'
    )
    return f"""
      {_page_header("Подписка и тариф", "Следите за лимитами, функциями и историей платежей.", "/web/accounts", "Кабинеты МП")}
      <section class="detail-grid">
        <section class="band">
          <h2>Текущая подписка</h2>
          <div class="kv">
            <span>Тариф</span><strong>{escape(data.tier.name)}</strong>
            <span>Статус</span><strong>{escape(status)}</strong>
            <span>Действует до</span><strong>{escape(expires)}</strong>
            <span>Кабинеты</span><strong>{data.used_accounts} / {data.tier.max_marketplace_accounts}</strong>
            <span>Заказы за месяц</span><strong>{data.used_orders_month} / {_limit(data.tier.max_orders_per_month)}</strong>
            <span>SKU</span><strong>{data.used_products} / {_limit(data.tier.max_products)}</strong>
          </div>
        </section>
        <section class="band">
          <h2>Доступные функции</h2>
          <ul>{feature_rows}</ul>
        </section>
      </section>
      <section class="dashboard-grid">
        {tier_cards}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>История платежей</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Дата</th><th>Сумма</th><th>Статус</th><th>Провайдер</th></tr></thead>
          <tbody>{payment_rows}</tbody>
        </table></div>
      </section>
    """


def _profile_content(user: User, subscription: SubscriptionPageData) -> str:
    checked = " checked" if user.notifications_enabled else ""
    return f"""
      {_page_header("Профиль", "Управляйте настройками пользователя, уведомлениями и подпиской.", "/web/subscription", "Подписка")}
      <section class="detail-grid">
        <section class="band">
          <h2>Данные Telegram</h2>
          <div class="kv">
            <span>Имя</span><strong>{escape(user.first_name or "н/д")}</strong>
            <span>Username</span><strong>{escape("@" + user.username if user.username else "н/д")}</strong>
            <span>Telegram ID</span><strong>{user.telegram_id}</strong>
            <span>Язык</span><strong>{escape(user.language)}</strong>
            <span>Статус</span><strong>{escape(user.status.value)}</strong>
            <span>Регистрация</span><strong>{_dt(user.created_at)}</strong>
          </div>
        </section>
        <section class="band">
          <h2>Подписка</h2>
          <div class="kv">
            <span>Тариф</span><strong>{escape(subscription.tier.name)}</strong>
            <span>Статус</span><strong>{escape(subscription_status(subscription.active_subscription))}</strong>
          </div>
          <p><a class="button primary" href="/web/subscription">Управление подпиской</a></p>
        </section>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Настройки профиля</h2>
        <form class="filters" method="post" action="/web/profile">
          <div>
            <label for="timezone">Часовой пояс</label>
            <input id="timezone" name="timezone" value="{escape(user.timezone)}">
          </div>
          <div>
            <label for="low_margin_threshold_percent">Порог низкой маржи, %</label>
            <input id="low_margin_threshold_percent" name="low_margin_threshold_percent" type="number" step="0.01" value="{user.low_margin_threshold_percent}">
          </div>
          <div>
            <label for="notifications_enabled">Уведомления</label>
            <label class="status-chip"><input id="notifications_enabled" name="notifications_enabled" type="checkbox"{checked}> включены</label>
          </div>
          <button class="button primary" type="submit">Сохранить</button>
        </form>
      </section>
    """


def _analytics_content(data: DashboardData, profit: ProfitPageData) -> str:
    top_rows = (
        "".join(
            "<tr>"
            f'<td>{escape(row.title)}<div class="muted">{escape(row.seller_article)}</div></td>'
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f'<td class="num">{_rub(row.revenue)}</td>'
            f'<td class="num">{_rub(row.estimated_profit)}</td>'
            f'<td class="num">{row.margin_percent.quantize(Decimal("0.1"))}%</td>'
            "</tr>"
            for row in profit.rows[:8]
        )
        or '<tr><td colspan="5" class="muted">Недостаточно данных для топа товаров.</td></tr>'
    )
    return f"""
      {_page_header("Аналитика", "Обзор динамики бизнеса, прибыльности и проблемных зон за 30 дней.", "/web/profit", "Прибыль")}
      <section class="kpi-grid">
        {"".join(_kpi(metric) for metric in data.metrics[:6])}
      </section>
      <section class="dashboard-grid">
        <section class="band wide">
          <h2>Динамика выручки</h2>
          {_line_chart(data.points, "revenue", "Выручка по дням", "#4557f6")}
        </section>
        <section class="band">
          <h2>Прибыльность по МП</h2>
          {_marketplace_table(data)}
        </section>
        <section class="band">
          <h2>Товары-лидеры</h2>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>Товар</th><th>МП</th><th class="num">Выручка</th><th class="num">Прибыль</th><th class="num">Маржа</th></tr></thead>
            <tbody>{top_rows}</tbody>
          </table></div>
        </section>
      </section>
    """


def _control_content(data: ControlPageData) -> str:
    accounts = (
        "".join(
            f"<li>{escape(account.name)}: {escape(account.last_error_message or 'ошибка синхронизации')}</li>"
            for account in data.error_accounts
        )
        or "<li>Критичных ошибок кабинетов сейчас нет.</li>"
    )
    alerts = (
        "".join(
            f"<li>{escape(alert.title)} — {escape(alert.message)}</li>"
            for alert in data.open_alerts
        )
        or "<li>Открытых алертов сейчас нет.</li>"
    )
    return f"""
      {_page_header("Контроль ошибок", "Что требует внимания прямо сейчас.", "/web/data-quality", "Качество данных")}
      <section class="kpi-grid">
        {_simple_kpi("Качество данных", str(data.report.score), "good" if data.report.score >= 80 else "warn")}
        {_simple_kpi("Без себестоимости", str(data.missing_cost_products), "warn" if data.missing_cost_products else "neutral")}
        {_simple_kpi("Предварительная экономика", str(data.preliminary_orders), "warn" if data.preliminary_orders else "neutral")}
        {_simple_kpi("Низкие остатки", str(data.low_stock_products), "bad" if data.low_stock_products else "neutral")}
      </section>
      <section class="detail-grid" style="margin-top:14px">
        <section class="band"><h2>Ошибки синхронизации</h2><ul>{accounts}</ul></section>
        <section class="band"><h2>Актуальные алерты</h2><ul>{alerts}</ul></section>
      </section>
    """


def _settings_content(user: User) -> str:
    threshold = user.low_margin_threshold_percent or Decimal("10")
    checked = "включены" if user.notifications_enabled else "выключены"
    return f"""
      {_page_header("Настройки", "Финансовый контроль, локализация, уведомления и быстрые переходы.", "/web/profile", "Профиль")}
      <section class="detail-grid">
        <section class="band">
          <h2>Финансовый контроль</h2>
          <form class="filters" method="post" action="/web/settings/low-margin">
            <div>
              <label for="threshold">Порог низкой маржи, %</label>
              <input id="threshold" name="threshold" type="number" min="0" max="100" step="0.01"
                     value="{threshold}">
            </div>
            <button class="button primary" type="submit">Сохранить</button>
          </form>
          <p class="muted">Порог используется в отчётах, алертах и контрольных web-экранах.</p>
        </section>
        <section class="band">
          <h2>Локализация</h2>
          <div class="kv">
            <span>Часовой пояс</span><strong>{escape(user.timezone)}</strong>
            <span>Язык</span><strong>{escape(user.language)}</strong>
          </div>
          <p><a class="button" href="/web/profile">Изменить в профиле</a></p>
        </section>
        <section class="band">
          <h2>Уведомления</h2>
          <p>Статус Telegram-уведомлений: <span class="badge">{checked}</span></p>
          <p class="muted">Тонкая настройка уведомлений по кабинетам доступна в Telegram-боте.</p>
        </section>
        <section class="band">
          <h2>Подписка и доступ</h2>
          <p class="muted">Проверьте текущий тариф, лимиты и доступные возможности.</p>
          <p><a class="button primary" href="/web/subscription">Открыть подписку</a></p>
        </section>
      </section>
    """


def _data_quality_content(report: DataQualityReport) -> str:
    tone = "good" if report.score >= 80 else "warn" if report.score >= 50 else "bad"
    metrics = "".join(
        "<tr>"
        f"<td>{escape(metric.title)}</td>"
        f'<td class="num">{metric.value}</td>'
        f"<td>{escape(metric.status)}</td>"
        f"<td>{escape(metric.description)}</td>"
        "</tr>"
        for metric in report.metrics
    )
    recommendations = "".join(f"<li>{escape(item)}</li>" for item in report.recommendations)
    return f"""
      {_section_subnav("data_quality")}
      <section class="kpi-grid">
        {_simple_kpi("Индекс качества данных", str(report.score), tone)}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Качество данных</h2>
        <div class="table-wrap">
          <table class="table">
        <thead>
          <tr>
            <th>Проверка</th><th class="num">Значение</th><th>Статус</th><th>Комментарий</th>
          </tr>
        </thead>
            <tbody>{metrics}</tbody>
          </table>
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Что сделать</h2>
        <ul>{recommendations}</ul>
      </section>
    """


def _profit_content(data: ProfitPageData) -> str:
    summary = data.summary
    row_html = []
    for row in data.rows:
        roi = f"{row.roi_percent}%" if row.roi_percent is not None else "н/д"
        missing = (
            f'<span class="badge warn">{row.missing_cost_items} без себестоимости</span>'
            if row.missing_cost_items
            else ""
        )
        preliminary = (
            f'<span class="badge warn">{row.preliminary_items} предв.</span>'
            if row.preliminary_items
            else ""
        )
        title_cell = (
            f"<td>{escape(row.title)}"
            f'<div class="muted">{escape(row.seller_article)}</div>{missing} {preliminary}</td>'
        )
        row_html.append(
            "<tr>"
            f"{title_cell}"
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f"<td>{escape(row.sale_model.value if row.sale_model else 'н/д')}</td>"
            f'<td class="num">{row.orders}</td>'
            f'<td class="num">{row.sales}</td>'
            f'<td class="num">{_rub(row.revenue)}</td>'
            f'<td class="num">{_rub(row.cost)}</td>'
            f'<td class="num">{_rub(row.marketplace_costs)}</td>'
            f'<td class="num">{_rub(row.estimated_profit)}</td>'
            f'<td class="num">{_rub(row.actual_profit)}</td>'
            f'<td class="num">{row.margin_percent.quantize(Decimal("0.1"))}%</td>'
            f'<td class="num">{roi}</td>'
            "</tr>"
        )
    body = (
        "".join(row_html)
        if row_html
        else (
            '<tr><td colspan="12" class="muted">'
            "Данных по прибыли за выбранный период пока нет.</td></tr>"
        )
    )
    estimated_tone = "good" if summary.estimated_profit >= 0 else "bad"
    deviation_tone = "bad" if summary.deviation < 0 else "good"
    roi_value = f"{summary.roi_percent}%" if summary.roi_percent is not None else "н/д"
    return f"""
      {_section_subnav("profit")}
      {_profit_filters(data.filters)}
      <section class="kpi-grid">
        {_simple_kpi("Плановая прибыль", _rub(summary.estimated_profit), estimated_tone)}
        {_simple_kpi("Фактическая прибыль", _rub(summary.actual_profit))}
        {_simple_kpi("Отклонение план/факт", _rub(summary.deviation), deviation_tone)}
        {_simple_kpi("Прибыль с заказа", _rub(summary.average_unit_profit))}
        {_simple_kpi("Средняя маржа", f"{summary.average_margin}%")}
        {_simple_kpi("ROI на себестоимость", roi_value)}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Прибыль по SKU</h2>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th>МП</th><th>Модель</th><th class="num">Заказов</th>
                <th class="num">Продаж</th><th class="num">Выручка</th>
                <th class="num">Себестоимость</th><th class="num">Расходы МП</th>
                <th class="num">Плановая прибыль</th><th class="num">Фактическая прибыль</th>
                <th class="num">Маржа</th><th class="num">ROI</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """


def _section_subnav(active: str) -> str:
    items = {
        "orders": ("Заказы", "/web/orders"),
        "profit": ("Прибыль", "/web/profit"),
        "plan_fact": ("План/факт", "/web/plan-fact"),
        "break_even": ("Безубыточность", "/web/break-even"),
        "products": ("Товары", "/web/products"),
        "product_matching": ("Сопоставление", "/web/product-matching"),
        "stocks": ("Остатки", "/web/stocks"),
        "alerts": ("Алерты", "/web/alerts"),
        "data_quality": ("Качество данных", "/web/data-quality"),
    }
    return (
        '<div class="subnav">'
        + "".join(
            f'<a class="{"active" if key == active else ""}" href="{href}">{label}</a>'
            for key, (label, href) in items.items()
        )
        + "</div>"
    )


def _dashboard_content(data: DashboardData) -> str:
    return f"""
      {_filters(data)}
      <section class="kpi-grid">
        {"".join(_kpi(metric) for metric in data.metrics)}
      </section>
      <section class="dashboard-grid">
        <section class="band wide">
          <h2>Пульс бизнеса</h2>
          <p class="muted">Заказы, выручка и плановая прибыль за выбранный период.</p>
          {_line_chart(data.points, "revenue", "Выручка по дням", "#0f6f8f")}
        </section>
        <section class="band">
          <h2>Плановая прибыль</h2>
          {_bar_chart(data.points, "estimated_profit", "Плановая прибыль по дням", "#147d4a")}
        </section>
        <section class="band">
          <h2>Заказы vs продажи</h2>
          {_grouped_bar_chart(data.points)}
        </section>
        <section class="band">
          <h2>Возвраты и отмены</h2>
          {_returns_chart(data.points)}
        </section>
        <section class="band">
          <h2>FBO / FBS / rFBS</h2>
          {_sale_model_chart(data.points)}
        </section>
        <section class="band">
          <h2>Wildberries / Ozon</h2>
          {_marketplace_table(data)}
        </section>
      </section>
    """


def _dashboard_welcome(
    user: User,
    subscription: SubscriptionPageData,
    accounts: AccountsPageData,
) -> str:
    active = subscription.active_subscription
    expires = (
        active.expires_at.strftime("%d.%m.%Y") if active and active.expires_at else "бессрочно"
    )
    return f"""
      <section class="page-header">
        <div>
          <h2>Добро пожаловать, {escape(user.first_name or user.username or "селлер")}!</h2>
          <p class="muted">
            Тариф: {escape(subscription.tier.name)} · действует до {escape(expires)} ·
            подключено кабинетов: {accounts.active_accounts} из {subscription.tier.max_marketplace_accounts}
          </p>
        </div>
        <div class="page-actions">
          <a class="button" href="/web/subscription">Подписка</a>
          <a class="button" href="/web/accounts">Кабинеты МП</a>
          <a class="button" href="/web/settings">Настройки</a>
        </div>
      </section>
    """


def _filters(data: DashboardData) -> str:
    filters = data.filters
    selected_marketplace = filters.marketplace.value if filters.marketplace else "all"
    selected_sale_model = filters.sale_model.value if filters.sale_model else "all"
    date_from = filters.local_date_from.isoformat()
    date_to = filters.local_date_to.isoformat()
    return f"""
      <form class="filters" method="get" action="/web/">
        {
        _select(
            "period",
            "Период",
            {
                "today": "Сегодня",
                "yesterday": "Вчера",
                "7d": "7 дней",
                "30d": "30 дней",
                "custom": "Произвольный",
            },
            filters.period,
        )
    }
        {
        _select(
            "marketplace",
            "Маркетплейс",
            {
                "all": "Все",
                Marketplace.WB.value: "Wildberries",
                Marketplace.OZON.value: "Ozon",
            },
            selected_marketplace,
        )
    }
        {
        _select(
            "sale_model",
            "Модель",
            {
                "all": "Все",
                "FBO": "FBO",
                "FBS": "FBS",
                "rFBS": "rFBS",
            },
            selected_sale_model,
        )
    }
        <div>
          <label for="date_from">Дата с</label>
          <input id="date_from" name="date_from" type="date" value="{date_from}">
        </div>
        <div>
          <label for="date_to">Дата по</label>
          <input id="date_to" name="date_to" type="date" value="{date_to}">
        </div>
        <button class="button primary" type="submit">Применить</button>
      </form>
    """


def _orders_filters(filters: OrderWebFilters) -> str:
    return _shared_order_filters(filters, "/web/orders", include_status=True)


def _profit_filters(filters: OrderWebFilters) -> str:
    return _shared_order_filters(filters, "/web/profit", include_status=False)


def _plan_fact_filters(data: PlanFactPageData) -> str:
    filters = data.filters
    selected_marketplace = filters.marketplace.value if filters.marketplace else "all"
    selected_sale_model = filters.sale_model.value if filters.sale_model else "all"
    date_from_value = filters.local_date_from.isoformat()
    date_to_value = filters.local_date_to.isoformat()
    return f"""
      <form class="filters" method="get" action="/web/plan-fact">
        {
        _select(
            "period",
            "Период",
            {
                "today": "Сегодня",
                "yesterday": "Вчера",
                "7d": "7 дней",
                "30d": "30 дней",
                "custom": "Произвольный",
            },
            filters.period,
        )
    }
        {
        _select(
            "marketplace",
            "Маркетплейс",
            {
                "all": "Все",
                Marketplace.WB.value: "Wildberries",
                Marketplace.OZON.value: "Ozon",
            },
            selected_marketplace,
        )
    }
        {
        _select(
            "sale_model",
            "Модель",
            {
                "all": "Все",
                "FBO": "FBO",
                "FBS": "FBS",
                "rFBS": "rFBS",
            },
            selected_sale_model,
        )
    }
        <div>
          <label for="sku">SKU / артикул</label>
          <input id="sku" name="sku" type="search" value="{escape(filters.sku)}">
        </div>
        <div>
          <label for="date_from">Дата с</label>
          <input id="date_from" name="date_from" type="date" value="{date_from_value}">
        </div>
        <div>
          <label for="date_to">Дата по</label>
          <input id="date_to" name="date_to" type="date" value="{date_to_value}">
        </div>
        {
        _select(
            "sort",
            "Сортировка",
            {
                "deviation": "Отклонение",
                "profit": "Плановая прибыль",
                "orders": "Заказы",
            },
            filters.sort,
        )
    }
        {
        _select(
            "direction",
            "Порядок",
            {
                "asc": "Сначала худшие",
                "desc": "Сначала лучшие",
            },
            filters.direction,
        )
    }
        <button class="button primary" type="submit">Применить</button>
      </form>
    """


def _shared_order_filters(
    filters: OrderWebFilters,
    action: str,
    *,
    include_status: bool,
) -> str:
    selected_marketplace = filters.marketplace.value if filters.marketplace else "all"
    selected_sale_model = filters.sale_model.value if filters.sale_model else "all"
    status_filter = (
        _select(
            "status",
            "Статус",
            {
                "all": "Все",
                "active": "Активные",
                "cancelled": "Отменённые",
                "action_required": "Требуют действия",
            },
            filters.status,
        )
        if include_status
        else ""
    )
    date_from_value = filters.local_date_from.isoformat()
    date_to_value = filters.local_date_to.isoformat()
    return f"""
      <form class="filters" method="get" action="{escape(action)}">
        {
        _select(
            "period",
            "Период",
            {
                "today": "Сегодня",
                "yesterday": "Вчера",
                "7d": "7 дней",
                "30d": "30 дней",
                "custom": "Произвольный",
            },
            filters.period,
        )
    }
        {
        _select(
            "marketplace",
            "Маркетплейс",
            {
                "all": "Все",
                Marketplace.WB.value: "Wildberries",
                Marketplace.OZON.value: "Ozon",
            },
            selected_marketplace,
        )
    }
        {
        _select(
            "sale_model",
            "Модель",
            {
                "all": "Все",
                "FBO": "FBO",
                "FBS": "FBS",
                "rFBS": "rFBS",
            },
            selected_sale_model,
        )
    }
        {
        _select(
            "economy",
            "Экономика",
            {
                "all": "Все",
                "profit": "Прибыльные",
                "loss": "Убыточные",
                "missing_cost": "Без себестоимости",
            },
            filters.economy,
        )
    }
        {status_filter}
        <div>
          <label for="sku">SKU / артикул</label>
          <input id="sku" name="sku" type="search" value="{escape(filters.sku)}">
        </div>
        <div>
          <label for="date_from">Дата с</label>
          <input id="date_from" name="date_from" type="date" value="{date_from_value}">
        </div>
        <div>
          <label for="date_to">Дата по</label>
          <input id="date_to" name="date_to" type="date" value="{date_to_value}">
        </div>
        {
        _select(
            "sort",
            "Сортировка",
            {
                "date": "Дата",
                "profit": "Прибыль",
                "revenue": "Выручка",
                "margin": "Маржа",
                "orders": "Заказы",
                "roi": "ROI",
            },
            filters.sort,
        )
    }
        {
        _select(
            "direction",
            "Порядок",
            {
                "desc": "По убыванию",
                "asc": "По возрастанию",
            },
            filters.direction,
        )
    }
        <button class="button primary" type="submit">Применить</button>
      </form>
    """


def _select(name: str, label: str, options: dict[str, str], selected: str) -> str:
    items = []
    for value, text in options.items():
        attr = " selected" if value == selected else ""
        items.append(f'<option value="{escape(value)}"{attr}>{escape(text)}</option>')
    return (
        f'<div><label for="{escape(name)}">{escape(label)}</label>'
        f'<select id="{escape(name)}" name="{escape(name)}">{"".join(items)}</select></div>'
    )


def _page_header(title: str, description: str, href: str, action: str) -> str:
    return (
        '<section class="page-header">'
        f'<div><h2>{escape(title)}</h2><p class="muted">{description}</p></div>'
        f'<div class="page-actions"><a class="button" href="{escape(href)}">{escape(action)}</a></div>'
        "</section>"
    )


def _sales_returns_filters(action: str, filters: DashboardFilters, sku: str) -> str:
    selected_marketplace = filters.marketplace.value if filters.marketplace else "all"
    return f"""
      <form class="filters filter-panel" method="get" action="{escape(action)}">
        {
        _select(
            "period",
            "Период",
            {
                "today": "Сегодня",
                "yesterday": "Вчера",
                "7d": "7 дней",
                "30d": "30 дней",
                "custom": "Произвольный",
            },
            filters.period,
        )
    }
        {
        _select(
            "marketplace",
            "Маркетплейс",
            {
                "all": "Все",
                Marketplace.WB.value: "Wildberries",
                Marketplace.OZON.value: "Ozon",
            },
            selected_marketplace,
        )
    }
        <div>
          <label for="sku">Товар / SKU</label>
          <input id="sku" name="sku" type="search" value="{escape(sku)}">
        </div>
        <div>
          <label for="date_from">Дата с</label>
          <input id="date_from" name="date_from" type="date" value="{
        filters.local_date_from.isoformat()
    }">
        </div>
        <div>
          <label for="date_to">Дата по</label>
          <input id="date_to" name="date_to" type="date" value="{
        filters.local_date_to.isoformat()
    }">
        </div>
        <button class="button primary" type="submit">Применить</button>
      </form>
    """


def _web_tier_card(tier: SubscriptionTier, current_code: str) -> str:
    current = tier.code == current_code
    badge = '<span class="badge good">Текущий тариф</span>' if current else ""
    price = "Бесплатно" if tier.price_monthly == 0 else f"{_rub(tier.price_monthly)} / месяц"
    return f"""
      <section class="band">
        <h2>{escape(tier.name)} {badge}</h2>
        <p class="muted">{escape(tier.description or "")}</p>
        <div class="kv">
          <span>Стоимость</span><strong>{price}</strong>
          <span>Кабинеты</span><strong>{tier.max_marketplace_accounts}</strong>
          <span>Заказы</span><strong>{_limit(tier.max_orders_per_month)}</strong>
          <span>SKU</span><strong>{_limit(tier.max_products)}</strong>
        </div>
        <p class="muted">Оформление и оплата подписки сейчас выполняются через Telegram-бота.</p>
      </section>
    """


def _account_status_badge(status: str, is_active: bool) -> str:
    if not is_active:
        return '<span class="badge">отключён</span>'
    tone = "good" if status == "ACTIVE" else "warn" if status == "DRAFT" else "bad"
    label = {"ACTIVE": "активен", "DRAFT": "черновик", "ERROR": "ошибка"}.get(status, status)
    return f'<span class="badge {tone}">{escape(label)}</span>'


def _cost_status_badge(ok: bool) -> str:
    return (
        '<span class="badge good">задана</span>'
        if ok
        else '<span class="badge warn">не задана</span>'
    )


def _limit(value: int | None) -> str:
    return "без ограничений" if value is None else str(value)


def _dt(value: datetime | None) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value else "н/д"


def _user_display_name(user: User) -> str:
    return user.first_name or user.username or str(user.telegram_id)


def _form_value(form: dict[str, list[str]], name: str, default: str) -> str:
    return (form.get(name) or [default])[0]


def _datetime_from_form(value: str) -> datetime:
    if not value:
        return datetime.now(tz=UTC)
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _kpi(metric: KpiMetric) -> str:
    change = ""
    if metric.change_percent is not None:
        css = "up" if metric.change_percent > 0 else "down" if metric.change_percent < 0 else ""
        sign = "+" if metric.change_percent > 0 else ""
        change = (
            f'<span class="change {css}">{sign}{metric.change_percent}% к прошлому периоду</span>'
        )
    elif metric.label != "Фактическая прибыль":
        change = '<span class="change">нет базы для сравнения</span>'
    value = _format_metric_value(metric.value, metric.suffix)
    return (
        f'<article class="kpi {escape(metric.tone)}">'
        f"<span>{escape(metric.label)}</span><strong>{value}</strong>{change}</article>"
    )


def _simple_kpi(label: str, value: str, tone: str = "neutral") -> str:
    return (
        f'<article class="kpi {tone}">'
        f"<span>{escape(label)}</span><strong>{value}</strong></article>"
    )


def _format_metric_value(value: Decimal | int, suffix: str) -> str:
    if isinstance(value, Decimal):
        if suffix == "%":
            return f"{value.quantize(Decimal('0.1'))}%"
        if suffix == "₽":
            return _rub(value)
    return f"{value}{suffix}"


def _line_chart(points: list[DailyPoint], attr: str, title: str, color: str) -> str:
    values = [_point_value(point, attr) for point in points]
    if not any(values):
        return _empty_chart()
    width = 720
    height = 220
    max_value = max(values) or Decimal("1")
    coords = []
    step = width / max(len(points) - 1, 1)
    for index, value in enumerate(values):
        x = Decimal(str(index * step))
        y = Decimal(height - 30) - (value / max_value * Decimal(height - 60))
        coords.append(f"{float(x):.1f},{float(y):.1f}")
    labels = _x_labels(points, width, height)
    return f"""
      <div class="chart" role="img" aria-label="{escape(title)}">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          <line x1="0" y1="{height - 30}" x2="{width}" y2="{height - 30}" stroke="#d9e0e8"/>
          <polyline fill="none" stroke="{color}" stroke-width="4" points="{" ".join(coords)}"/>
          {labels}
        </svg>
      </div>
    """


def _bar_chart(points: list[DailyPoint], attr: str, title: str, color: str) -> str:
    values = [_point_value(point, attr) for point in points]
    if not any(values):
        return _empty_chart()
    width = 720
    height = 220
    max_value = max(abs(value) for value in values) or Decimal("1")
    bar_width = max(width / max(len(points), 1) * 0.58, 4)
    bars = []
    for index, value in enumerate(values):
        x = index * (width / max(len(points), 1)) + bar_width * 0.35
        bar_height = abs(value) / max_value * Decimal(height - 60)
        y = Decimal(height - 30) - bar_height if value >= 0 else Decimal(height - 30)
        tone = color if value >= 0 else "#b42318"
        bars.append(
            f'<rect x="{x:.1f}" y="{float(y):.1f}" width="{bar_width:.1f}" '
            f'height="{float(bar_height):.1f}" rx="3" fill="{tone}"/>'
        )
    labels = _x_labels(points, width, height)
    return f"""
      <div class="chart" role="img" aria-label="{escape(title)}">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          <line x1="0" y1="{height - 30}" x2="{width}" y2="{height - 30}" stroke="#d9e0e8"/>
          {"".join(bars)}
          {labels}
        </svg>
      </div>
    """


def _grouped_bar_chart(points: list[DailyPoint]) -> str:
    if not any(point.orders or point.sales for point in points):
        return _empty_chart()
    width = 720
    height = 220
    max_value = max([point.orders for point in points] + [point.sales for point in points] + [1])
    group = width / max(len(points), 1)
    bars = []
    for index, point in enumerate(points):
        x = index * group + group * 0.25
        order_h = point.orders / max_value * (height - 60)
        sales_h = point.sales / max_value * (height - 60)
        bars.append(
            f'<rect x="{x:.1f}" y="{height - 30 - order_h:.1f}" width="{group * 0.18:.1f}" '
            f'height="{order_h:.1f}" rx="3" fill="#0f6f8f"/>'
            f'<rect x="{x + group * 0.22:.1f}" y="{height - 30 - sales_h:.1f}" '
            f'width="{group * 0.18:.1f}" height="{sales_h:.1f}" rx="3" fill="#147d4a"/>'
        )
    return f"""
      <div class="chart" role="img" aria-label="Заказы и продажи по дням">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          <line x1="0" y1="{height - 30}" x2="{width}" y2="{height - 30}" stroke="#d9e0e8"/>
          {"".join(bars)}
          {_x_labels(points, width, height)}
        </svg>
        <div class="legend"><span><i class="dot" style="background:#0f6f8f"></i>Заказы</span>
        <span><i class="dot" style="background:#147d4a"></i>Продажи</span></div>
      </div>
    """


def _returns_chart(points: list[DailyPoint]) -> str:
    if not any(point.returns or point.cancellations for point in points):
        return _empty_chart()
    width = 720
    height = 220
    max_value = max(
        [point.returns for point in points] + [point.cancellations for point in points] + [1]
    )
    group = width / max(len(points), 1)
    bars = []
    for index, point in enumerate(points):
        x = index * group + group * 0.25
        returns_h = point.returns / max_value * (height - 60)
        cancel_h = point.cancellations / max_value * (height - 60)
        bars.append(
            f'<rect x="{x:.1f}" y="{height - 30 - returns_h:.1f}" '
            f'width="{group * 0.18:.1f}" height="{returns_h:.1f}" rx="3" fill="#b42318"/>'
            f'<rect x="{x + group * 0.22:.1f}" y="{height - 30 - cancel_h:.1f}" '
            f'width="{group * 0.18:.1f}" height="{cancel_h:.1f}" rx="3" fill="#a65f00"/>'
        )
    return f"""
      <div class="chart" role="img" aria-label="Возвраты и отмены по дням">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          <line x1="0" y1="{height - 30}" x2="{width}" y2="{height - 30}" stroke="#d9e0e8"/>
          {"".join(bars)}
          {_x_labels(points, width, height)}
        </svg>
        <div class="legend"><span><i class="dot" style="background:#b42318"></i>Возвраты</span>
        <span><i class="dot" style="background:#a65f00"></i>Отмены</span></div>
      </div>
    """


def _sale_model_chart(points: list[DailyPoint]) -> str:
    totals = {
        "FBO": sum(point.fbo_orders for point in points),
        "FBS": sum(point.fbs_orders for point in points),
        "rFBS": sum(point.rfbs_orders for point in points),
    }
    if not any(totals.values()):
        return _empty_chart()
    max_value = max(totals.values())
    rows = []
    colors = {"FBO": "#7b3fc5", "FBS": "#0f6f8f", "rFBS": "#147d4a"}
    for label, value in totals.items():
        width = 100 if max_value == 0 else value / max_value * 100
        bar_style = f"height:12px;width:{width:.1f}%;background:{colors[label]};border-radius:4px"
        rows.append(
            f'<tr><td>{label}</td><td class="num">{value}</td><td>'
            f'<div style="{bar_style}"></div>'
            "</td></tr>"
        )
    return (
        '<table class="table"><thead><tr><th>Модель</th><th class="num">Заказы</th>'
        f"<th>Доля</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _marketplace_table(data: DashboardData) -> str:
    rows = []
    for item in data.marketplace_breakdown:
        label = "Wildberries" if item.marketplace == Marketplace.WB else "Ozon"
        rows.append(
            "<tr>"
            f"<td>{label}</td>"
            f'<td class="num">{item.orders}</td>'
            f'<td class="num">{item.sales}</td>'
            f'<td class="num">{_rub(item.revenue)}</td>'
            f'<td class="num">{_rub(item.estimated_profit)}</td>'
            "</tr>"
        )
    return (
        '<table class="table"><thead><tr><th>Площадка</th><th class="num">Заказы</th>'
        '<th class="num">Продажи</th><th class="num">Выручка</th>'
        f'<th class="num">Плановая прибыль</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


def _x_labels(points: list[DailyPoint], width: int, height: int) -> str:
    if not points:
        return ""
    step = width / max(len(points) - 1, 1)
    labels = []
    for index, point in enumerate(points):
        if len(points) > 10 and index not in {0, len(points) - 1} and index % 5 != 0:
            continue
        x = index * step
        labels.append(
            f'<text x="{x:.1f}" y="{height - 8}" fill="#667085" font-size="11" '
            f'text-anchor="middle">{escape(point.label)}</text>'
        )
    return "".join(labels)


def _point_value(point: DailyPoint, attr: str) -> Decimal:
    value = getattr(point, attr)
    if isinstance(value, Decimal):
        return value
    return Decimal(value)


def _empty_chart() -> str:
    return '<div class="chart-empty">Данных за выбранный период пока нет</div>'


def _rub(value: Decimal) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def _rub_optional(value: Decimal | None) -> str:
    if value is None:
        return "н/д"
    return _rub(value)


def _percent_optional(value: Decimal | None) -> str:
    if value is None:
        return "н/д"
    return f"{value.quantize(Decimal('0.1'))}%"


def _marketplace_label(value: Marketplace) -> str:
    return "Wildberries" if value == Marketplace.WB else "Ozon"


def _confidence_badge(value: str | None) -> str:
    labels = {
        "EXACT": ("good", "точный"),
        "ESTIMATED": ("warn", "оценочный"),
        "PRELIMINARY": ("warn", "предварительный"),
    }
    tone, label = labels.get(value or "PRELIMINARY", labels["PRELIMINARY"])
    return f'<span class="badge {tone}">{label}</span>'


def _parse_int_list(raw: str) -> list[int]:
    ids: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            ids.append(int(chunk))
    return ids


def _mask_token(token: str) -> str:
    if len(token) <= 12:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def _request_path(request: Request) -> str:
    url = getattr(request, "url", None)
    return str(getattr(url, "path", "unknown"))


async def _urlencoded_form(request: Request) -> dict[str, list[str]]:
    raw = (await request.body()).decode("utf-8")
    return parse_qs(raw, keep_blank_values=True)


def _query_param(request: Request, name: str, default: str) -> str:
    value = request.query_params.get(name)
    return value if value is not None else default


def _optional_query_param(request: Request, name: str) -> str | None:
    return request.query_params.get(name)


def _decimal_from_query(value: str, default: Decimal) -> Decimal:
    try:
        return Decimal(value)
    except Exception:
        return default
