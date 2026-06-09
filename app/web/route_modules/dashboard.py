# ruff: noqa: E501

import logging
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User
from app.services.account.web_cabinet_service import WebCabinetService
from app.services.common.web_dashboard_service import WebDashboardService
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.rendering import page
from app.web.views import _dashboard_content, _dashboard_welcome, _user_display_name

logger = logging.getLogger(__name__)
router = APIRouter()


def _qp(request: Request, name: str, default: str = "") -> str:
    return request.query_params.get(name, default)


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
    start = time.monotonic()
    try:
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
        subscription = await WebCabinetService(session).subscription_page(user.id, user.timezone)
        accounts = await WebCabinetService(session).accounts_page(user.id, user.timezone)
        content = _dashboard_welcome(user, subscription, accounts, data) + _dashboard_content(data)
        logger.info(
            "web_dashboard_rendered",
            extra={
                "user_id": user.id,
                "telegram_id": user.telegram_id,
                "subscription_tier": getattr(subscription.tier, "code", None),
                "template": "dashboard",
                "duration_ms": round((time.monotonic() - start) * 1000),
                "accounts_count": accounts.active_accounts,
                "orders_widgets_count": len(data.metrics),
            },
        )
        return page("Главная", _user_display_name(user), content)
    except Exception:
        logger.exception(
            "dashboard_failed",
            extra={
                "user_id": user.id,
                "telegram_id": user.telegram_id,
                "template": "dashboard",
                "duration_ms": round((time.monotonic() - start) * 1000),
            },
        )
        return page(
            "Ошибка — Главная",
            _user_display_name(user),
            '<div class="band"><h2>Не удалось загрузить главную страницу</h2>'
            "<p>Ошибка уже записана в лог. Попробуйте обновить страницу позже.</p>"
            '<p><a href="/web/" class="button primary">Обновить</a></p></div>',
        )


@router.get("/web", response_class=HTMLResponse, include_in_schema=False)
@router.get("/web/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_compat(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    """Serve cabinet dashboard when a reverse proxy prepends /web upstream.

    Renders content directly to avoid redirect loops caused by the proxy
    re-adding the /web prefix on every response.
    """
    logger.warning(
        "legacy_double_web_dashboard_served",
        extra={"path": str(request.url.path)},
    )
    return await dashboard(
        user=user,
        session=session,
        period=_qp(request, "period", "today"),
        marketplace=_qp(request, "marketplace", "all"),
        sale_model=_qp(request, "sale_model", "all"),
        date_from=_qp(request, "date_from") or None,
        date_to=_qp(request, "date_to") or None,
    )
