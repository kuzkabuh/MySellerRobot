"""version: 1.0.0
description: HTTP error handlers for web cabinet HTML error pages.
updated: 2026-06-10
"""

from html import escape

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler as fastapi_http_exception_handler
from fastapi.responses import HTMLResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """Custom HTML error pages for /web routes, fallback to FastAPI default for others."""
    if request.url.path.startswith("/web"):
        if exc.status_code == 401:
            return HTMLResponse(
                "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
                "<title>Вход в MP Control</title>"
                "<style>body{font-family:system-ui,sans-serif;display:grid;"
                "place-items:center;min-height:80vh;margin:0;background:#f6f7f9;color:#111827}"
                ".card{max-width:440px;padding:36px;background:#fff;border-radius:16px;"
                "box-shadow:0 18px 45px rgb(17 24 39 / .12);text-align:center}"
                "h1{font-size:26px;margin:0 0 12px}a{display:inline-block;margin-top:16px;"
                "padding:10px 18px;background:#2563eb;color:#fff;border-radius:8px;"
                "text-decoration:none;font-weight:700}"
                "</style></head><body>"
                "<div class='card'><h1>Нет доступа в web-кабинет</h1>"
                "<p>Ваша сессия истекла или отсутствует.</p>"
                "<p>Откройте бота <b>@mpcontrolrobot</b> и нажмите "
                "<b>🌐 Web-кабинет</b>, чтобы получить новую ссылку.</p>"
                '<a href="https://t.me/mpcontrolrobot">Открыть бота</a>'
                "</div></body></html>",
                status_code=401,
            )
        if exc.status_code == 404:
            return HTMLResponse(
                "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
                "<title>404 в MP Control</title>"
                "<style>body{font-family:system-ui,sans-serif;display:grid;"
                "place-items:center;min-height:80vh;margin:0;background:#f6f7f9;color:#111827}"
                ".card{max-width:440px;padding:36px;background:#fff;border-radius:16px;"
                "box-shadow:0 18px 45px rgb(17 24 39 / .12);text-align:center}"
                "h1{font-size:26px;margin:0 0 12px}a{color:#2563eb;text-decoration:none;font-weight:600}"
                "</style></head><body>"
                "<div class='card'><h1>404 — Страница не найдена</h1>"
                f"<p>Запрошен путь <code>{escape(str(request.url.path))}</code> не существует.</p>"
                '<p><a href="/web/">Вернуться на главную</a></p>'
                "</div></body></html>",
                status_code=404,
            )
    return await fastapi_http_exception_handler(request, exc)
