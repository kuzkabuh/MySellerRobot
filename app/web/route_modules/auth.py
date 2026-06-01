# ruff: noqa: E501

import logging

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.web_auth_service import WEB_SESSION_COOKIE, WebAuthService
from app.web.dependencies import (
    SESSION_DEPENDENCY,
    WEB_DASHBOARD_PATH,
    WEB_LOGIN_REQUIRED_PATH,
    WEB_SESSION_COOKIE_PATH,
)
from app.web.views import _mask_token, _request_path

logger = logging.getLogger(__name__)
frontend_logger = logging.getLogger("app.web.frontend")
router = APIRouter()
FRONTEND_ERROR_BODY = Body(default_factory=dict)


@router.get("/health")
async def web_health(session: AsyncSession = SESSION_DEPENDENCY) -> dict[str, str]:
    await session.execute(text("select 1"))
    return {"status": "ok"}


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
        secure=_is_secure_request(request),
    )
    return response


@router.post("/frontend-error")
async def frontend_error(
    request: Request,
    payload: dict[str, object] = FRONTEND_ERROR_BODY,
) -> dict[str, bool]:
    frontend_logger.error(
        "web_frontend_error",
        extra={
            "frontend_message": str(payload.get("message", ""))[:1000],
            "source": str(payload.get("source", ""))[:500],
            "frontend_lineno": payload.get("lineno"),
            "frontend_colno": payload.get("colno"),
            "stack": str(payload.get("stack", ""))[:4000],
            "path": str(payload.get("path") or request.url.path)[:500],
            "user_agent": str(payload.get("user_agent") or request.headers.get("user-agent", ""))[
                :500
            ],
        },
    )
    return {"ok": True}


@router.get("/web/login", include_in_schema=False)
async def login_compat(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> Response:
    """Serve login when a reverse proxy prepends /web upstream.

    Delegates to the main login handler with the token extracted from
    query params, avoiding redirect loops.
    """
    token = request.query_params.get("token")
    return await login(request=request, session=session, token=token)


@router.get("/logout")
async def logout(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    await WebAuthService(session).revoke_session(request.cookies.get(WEB_SESSION_COOKIE))
    await session.commit()
    response = RedirectResponse(url=WEB_LOGIN_REQUIRED_PATH, status_code=303)
    # Clear cookie from all paths that may have been used historically.
    for cookie_path in ("/", "/web", "/web/"):
        response.delete_cookie(WEB_SESSION_COOKIE, path=cookie_path)
    return response


@router.get("/login-required", response_class=HTMLResponse)
async def login_required() -> str:
    return (
        "<h1>Вход в web-кабинет</h1>"
        "<p>Откройте Telegram-бота и нажмите «🌐 Web-кабинет», чтобы получить новую ссылку.</p>"
    )


def _is_secure_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return (
        getattr(getattr(request, "url", None), "scheme", "http") == "https"
        or forwarded_proto.split(",", 1)[0].strip().lower() == "https"
        or get_settings().app_env == "production"
    )
