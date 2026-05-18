# ruff: noqa: E501, F401, F403, F405

import logging
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
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

