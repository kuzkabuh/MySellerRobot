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
from app.services.unit_economics.cost_management_service import CostManagementError
from app.services.common.data_quality_service import DataQualityService
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
    is_admin_user,
)
from app.web.rendering import page as render_page
from app.web.views import *

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/orders", response_class=HTMLResponse)
async def orders_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="30d"),
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    economy: str = Query(default="all"),
    status: str = Query(default="all"),
    sku: str = Query(default=""),
    sort: str = Query(default="date"),
    direction: str = Query(default="desc"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    page_number: int = Query(default=1, ge=1, alias="page"),
    per_page: int = Query(default=50, ge=10, le=200),
) -> str:
    svc = WebOrdersProfitService(session)
    result = await svc.list_orders(
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
        page=page_number,
        per_page=per_page,
    )
    summary = await svc.orders_summary(
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
    )
    last_poll_info = await _get_last_poll_info(session, user.id)
    sync_stats = await _get_sync_order_counts(session, user.id)
    content = _orders_content(result, user.timezone, summary=summary, last_poll_info=last_poll_info, sync_stats=sync_stats)
    return render_page(
        "Заказы",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/orders",
    )


async def _get_last_poll_info(
    session: AsyncSession,
    user_id: int,
) -> dict[str, object]:
    """Get the most recent order poll timestamp across user's active accounts."""
    result = await session.execute(
        select(MarketplaceAccount.marketplace, MarketplaceAccount.last_order_poll_at)
        .where(MarketplaceAccount.user_id == user_id)
        .where(MarketplaceAccount.is_active.is_(True))
        .where(MarketplaceAccount.last_order_poll_at.is_not(None))
        .order_by(MarketplaceAccount.last_order_poll_at.desc())
    )
    rows = result.all()
    if not rows:
        return {"last_poll_at": None, "accounts": []}
    last_poll_at = rows[0][1]
    accounts_info = [{"marketplace": mp.value, "last_poll_at": ts} for mp, ts in rows]
    return {"last_poll_at": last_poll_at, "accounts": accounts_info}


async def _get_sync_order_counts(
    session: AsyncSession,
    user_id: int,
) -> dict[str, object]:
    from sqlalchemy import func as sa_func
    from app.models.orders import Order as OrderModel
    from app.models.marketplaces import MarketplaceAccount as MAAccount
    from app.models.enums import Marketplace as MarketplaceEnum

    result = {}
    for mp in MarketplaceEnum:
        accounts = await session.execute(
            select(MAAccount.id).where(
                MAAccount.user_id == user_id,
                MAAccount.is_active.is_(True),
                MAAccount.marketplace == mp,
            )
        )
        account_ids = [r[0] for r in accounts.all()]
        if not account_ids:
            result[mp.value] = {"count": 0, "last_poll": None}
            continue
        order_count = await session.execute(
            select(sa_func.count(OrderModel.id))
            .where(OrderModel.user_id == user_id)
            .where(OrderModel.marketplace == mp)
            .where(OrderModel.marketplace_account_id.in_(account_ids))
        )
        count = order_count.scalar() or 0
        last_poll = await session.execute(
            select(MAAccount.last_order_poll_at)
            .where(MAAccount.id.in_(account_ids))
            .where(MAAccount.last_order_poll_at.is_not(None))
            .order_by(MAAccount.last_order_poll_at.desc())
            .limit(1)
        )
        poll_ts = last_poll.scalar_one_or_none()
        result[mp.value] = {"count": int(count), "last_poll": poll_ts}
    return result


@router.get("/orders/{order_id}", response_class=HTMLResponse)
async def order_detail_page(
    order_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    try:
        detail = await WebOrdersProfitService(session).order_detail(
            user_id=user.id, order_id=order_id
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="Заказ не найден")
        is_admin = is_admin_user(user)
        content = _order_detail_content(detail, user.timezone, is_admin=is_admin)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to render order detail for order_id=%s", order_id)
        content = (
            '<section class="band"><div class="empty-state">'
            "<strong>Не удалось открыть детали заказа.</strong>"
            "<span>Попробуйте позже или обратитесь в поддержку.</span>"
            "</div></section>"
        )
    return render_page(
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
    status: str = Query(default="all"),
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
        status=status,
        sku=sku,
        sort=sort,
        direction=direction,
    )
    content = _profit_content(data)
    return render_page(
        "Прибыль",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/profit",
    )
