"""version: 1.0.0
description: HTTP access logging middleware and sanitization helpers.
updated: 2026-06-10
"""

import logging
import time
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import Request
from fastapi.responses import HTMLResponse, Response

from app.utils.client_ip import get_client_ip
from app.web.csrf import is_valid_web_origin, requires_web_csrf_check


def redact_query(query: str) -> str:
    """Mask sensitive query parameters."""
    sensitive_keys = {"token", "api_key", "secret", "password", "client_id"}
    pairs = parse_qsl(query, keep_blank_values=True)
    if not pairs:
        return query
    return urlencode(
        [
            (key, "***REDACTED***" if key.lower() in sensitive_keys else value)
            for key, value in pairs
        ]
    )


def sanitize_url(url: str) -> str:
    """Mask sensitive query parameters in a URL string (e.g. Referer header)."""
    if not url:
        return url
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        redacted_query = redact_query(parsed.query)
        return urlunparse(parsed._replace(query=redacted_query))
    except Exception:
        return url


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """Redact sensitive headers and mask tokens in URL-valued headers."""
    result = dict(headers)
    sensitive_headers = {
        "authorization",
        "cookie",
        "x-api-key",
        "x-admin-secret",
        "x-telegram-bot-api-secret-token",
    }
    url_headers = {"referer", "referrer"}
    for key in list(result.keys()):
        lower_key = key.lower()
        if lower_key in sensitive_headers:
            result[key] = "***REDACTED***"
        elif lower_key in url_headers:
            result[key] = sanitize_url(result[key])
    return result


def should_log_access(path: str, status_code: int, duration_ms: int) -> bool:
    """Skip /health logging unless slow or error."""
    if path == "/health":
        return status_code >= 400 or duration_ms > 1000
    return True


async def log_requests_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """HTTP request logging middleware with CSRF check and cookie anomaly detection."""
    logger = logging.getLogger("app.api.main")
    start_time = time.monotonic()
    from app.core.config import get_settings
    settings = get_settings()
    user_agent = request.headers.get("user-agent", "")
    referer = sanitize_url(request.headers.get("referer", ""))
    client_ip = get_client_ip(request)
    x_forwarded_for = request.headers.get("x-forwarded-for", "")

    if requires_web_csrf_check(request) and not is_valid_web_origin(request, settings):
        logger.warning(
            "web_csrf_origin_rejected",
            extra={"method": request.method, "path": request.url.path},
        )
        return HTMLResponse(
            "<h1>Запрос отклонён</h1>"
            "<p>Источник web-запроса не прошёл проверку происхождения.</p>",
            status_code=403,
        )

    headers = sanitize_headers(dict(request.headers))

    if request.url.path.startswith("/web"):
        cookie_header = request.headers.get("cookie", "")
        cookie_count = len([c for c in cookie_header.split(";") if c.strip()])
        session_cookie_count = sum(
            1 for c in cookie_header.split(";") if c.strip().startswith("seller_web_session=")
        )
        if session_cookie_count != 1 and session_cookie_count > 0:
            if session_cookie_count > 1:
                logger.warning(
                    "web_cookie_count_anomaly",
                    extra={
                        "path": request.url.path,
                        "seller_web_session_count": session_cookie_count,
                        "total_cookie_count": cookie_count,
                    },
                )
            else:
                logger.debug(
                    "web_cookie_count_anomaly",
                    extra={
                        "path": request.url.path,
                        "seller_web_session_count": session_cookie_count,
                        "total_cookie_count": cookie_count,
                    },
                )

    if request.url.path != "/health":
        logger.info(
            "incoming_request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "query": redact_query(str(request.url.query)),
                "client_ip": client_ip,
                "x_forwarded_for": x_forwarded_for,
                "headers": headers,
            },
        )
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.monotonic() - start_time) * 1000)
        logger.exception(
            "request_failed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "query": redact_query(str(request.url.query)),
                "duration_ms": duration_ms,
                "client_ip": client_ip,
            },
        )
        if request.url.path.startswith("/web"):
            return HTMLResponse(
                "<h1>Ошибка web-кабинета</h1>"
                "<p>Из-за технической неисправности страница не загружена. "
                "Пожалуйста, обновите страницу через несколько минут или обратитесь в бота.</p>",
                status_code=500,
            )
        return HTMLResponse(
            "<h1>Внутренняя ошибка сервера</h1>"
            "<p>Пожалуйста, повторите запрос позднее или обратитесь в поддержку.</p>",
            status_code=500,
        )

    duration_ms = round((time.monotonic() - start_time) * 1000)

    if request.url.path.startswith("/web"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    log_extra = {
        "path": request.url.path,
        "method": request.method,
        "status": response.status_code,
        "duration_ms": duration_ms,
        "client_ip": client_ip,
        "x_forwarded_for": x_forwarded_for,
        "user_agent": user_agent[:200],
        "referer": referer,
    }

    if not should_log_access(request.url.path, response.status_code, duration_ms):
        return response

    if duration_ms > 1000:
        logger.warning("slow_request", extra=log_extra)
    else:
        logger.info("response", extra=log_extra)

    return response
