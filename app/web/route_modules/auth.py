# ruff: noqa: E501

import logging
from html import escape

from fastapi import APIRouter, Body, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories.web_auth import WebAuthRepository
from app.services.account.web_auth_service import WEB_SESSION_COOKIE, WebAuthService
from app.services.account.web_password_auth_service import WebPasswordAuthService
from app.utils.client_ip import get_client_ip
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
        if await _has_active_session(request, session):
            return RedirectResponse(url=WEB_DASHBOARD_PATH, status_code=303)
        return HTMLResponse(_password_login_page())
    masked_token = _mask_token(token)
    logger.info(
        "web_login_attempt",
        extra={"path": _request_path(request), "token": masked_token},
    )
    web_session = await WebAuthService(session).consume_login_token(
        token,
        ip_address=get_client_ip(request),
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


@router.post("/login")
async def password_login(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
    login_value: str = Form(..., alias="login"),
    password: str = Form(default=""),
) -> Response:
    web_session = await WebPasswordAuthService(session).authenticate(
        login=login_value,
        password=password,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    if web_session is None:
        await session.rollback()
        return HTMLResponse(
            _password_login_page(
                error=(
                    "Неверный логин или пароль. Если попыток было слишком много, "
                    "подождите 15 минут и попробуйте снова."
                ),
                login_value=login_value,
            ),
            status_code=400,
        )
    await session.commit()
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


@router.post("/logout")
async def logout_post(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    return await logout(request=request, session=session)


@router.get("/login-required", response_class=HTMLResponse)
async def login_required() -> str:
    return _password_login_page(
        error="Войдите по логину и паролю или получите новую ссылку в Telegram-боте."
    )


async def _has_active_session(request: Request, session: AsyncSession) -> bool:
    raw_session = getattr(request, "cookies", {}).get(WEB_SESSION_COOKIE)
    if not raw_session:
        return False
    user = await WebAuthRepository(session).get_active_session_user(
        WebAuthService.hash_secret(raw_session)
    )
    return user is not None


def _password_login_page(error: str = "", login_value: str = "") -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    safe_login = escape(login_value, quote=True)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Вход в web-кабинет — MP Control</title>
  <style>
    body{{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#f6f7f9;color:#111827}}
    .card{{width:min(440px,calc(100vw - 32px));padding:32px;background:#fff;border-radius:12px;box-shadow:0 18px 45px rgb(17 24 39 / .12)}}
    h1{{font-size:24px;margin:0 0 16px}} label{{display:block;margin:12px 0 6px;font-weight:700}}
    input{{width:100%;height:40px;border:1px solid #d1d5db;border-radius:8px;padding:0 10px;font:inherit;box-sizing:border-box}}
    button,.btn{{display:inline-flex;align-items:center;justify-content:center;height:40px;border-radius:8px;padding:0 14px;border:0;background:#2563eb;color:#fff;font-weight:700;text-decoration:none;cursor:pointer}}
    .hint{{color:#64748b;font-size:14px;line-height:1.5;margin-top:14px}} .error{{background:#fee2e2;color:#991b1b;border:1px solid #fecaca;border-radius:8px;padding:10px;margin-bottom:12px;font-weight:700}}
  </style>
</head>
<body>
  <main class="card">
    <h1>Вход в web-кабинет</h1>
    {error_html}
    <form method="post" action="/web/login">
      <label for="login">Логин, email или Telegram ID</label>
      <input id="login" name="login" value="{safe_login}" autocomplete="username" required>
      <label for="password">Пароль</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit" style="margin-top:16px;width:100%">Войти</button>
    </form>
    <p class="hint">Также можно войти через Telegram-бота: получите ссылку в меню «Web-кабинет».</p>
    <p><a class="btn" href="https://t.me/mpcontrolrobot">Открыть Telegram-бота</a></p>
  </main>
</body>
</html>"""


def _is_secure_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return (
        getattr(getattr(request, "url", None), "scheme", "http") == "https"
        or forwarded_proto.split(",", 1)[0].strip().lower() == "https"
        or get_settings().app_env == "production"
    )
