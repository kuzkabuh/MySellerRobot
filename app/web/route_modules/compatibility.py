# ruff: noqa: E501

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.models.domain import User
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY
from app.web.views import _placeholder_page

logger = logging.getLogger(__name__)
router = APIRouter()


def _request_path(request: Request) -> str:
    return str(request.url.path)


@router.get("/{section}", response_class=HTMLResponse)
async def placeholder(
    section: str,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> str:
    return _placeholder_page(section, user)


@router.get("/web/{section:path}", include_in_schema=False)
async def double_web_compat(
    section: str,
    request: Request,
) -> Response:
    """Redirect legacy /web/web/... URLs to canonical /web/... paths.

    Previously this route manually invoked handler functions, which broke because
    FastAPI Query(...) defaults were never resolved outside the DI pipeline
    (TypeError: '<' not supported between instances of 'int' and 'Query').
    A clean redirect preserves query parameters and avoids the 500 entirely.
    """

    normalized = section.strip("/")
    logger.warning(
        "legacy_double_web_path_redirect",
        extra={"path": _request_path(request), "section": normalized or "dashboard"},
    )

    query_string = request.url.query
    suffix = f"?{query_string}" if query_string else ""

    if normalized == "" or normalized == "dashboard":
        return RedirectResponse(url=f"/web/{suffix}", status_code=301)
    if normalized.startswith("orders/"):
        return RedirectResponse(url=f"/web/orders/{normalized.split('/', 1)[1]}{suffix}", status_code=301)
    if normalized.startswith("products/"):
        return RedirectResponse(url=f"/web/products/{normalized.split('/', 1)[1]}{suffix}", status_code=301)
    if normalized.startswith("costs/"):
        return RedirectResponse(url=f"/web/costs/{normalized.split('/', 1)[1]}{suffix}", status_code=301)

    return RedirectResponse(url=f"/web/{normalized}{suffix}", status_code=301)

