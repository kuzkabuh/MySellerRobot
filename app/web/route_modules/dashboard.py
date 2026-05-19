# ruff: noqa: E501

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User
from app.services.web_cabinet_service import WebCabinetService
from app.services.web_dashboard_service import WebDashboardService
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.rendering import page
from app.web.views import _dashboard_content, _dashboard_welcome, _user_display_name

logger = logging.getLogger(__name__)
router = APIRouter()


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
    subscription = await WebCabinetService(session).subscription_page(user.id, user.timezone)
    accounts = await WebCabinetService(session).accounts_page(user.id, user.timezone)
    content = _dashboard_welcome(user, subscription, accounts, data) + _dashboard_content(data)
    return page("Главная", _user_display_name(user), content)


@router.get("/web", include_in_schema=False)
@router.get("/web/", include_in_schema=False)
async def dashboard_compat(request: Request) -> Response:
    """Redirect legacy /web/web paths to canonical /web/."""
    query_string = request.url.query
    suffix = f"?{query_string}" if query_string else ""
    return RedirectResponse(url=f"/web/{suffix}", status_code=301)
