"""version: 1.2.0
description: FastAPI application factory, service endpoints, and web error handling.
updated: 2026-05-17
"""
# ruff: noqa: E501

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler as fastapi_http_exception_handler
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.webhooks import router as webhooks_router
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.logging import configure_logging
from app.web.routes import router as web_router

SESSION_DEPENDENCY = Depends(get_session)
SETTINGS_DEPENDENCY = Depends(get_settings)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    app = FastAPI(title="Seller Profit Bot API", version="1.7.0", debug=settings.app_debug)
    app.include_router(web_router)
    app.include_router(webhooks_router)

    @app.middleware("http")
    async def log_requests(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        import logging

        logger = logging.getLogger("app.api.main")

        # Sanitize sensitive headers
        headers = dict(request.headers)
        sensitive_headers = {"authorization", "cookie", "x-api-key", "x-admin-secret"}
        for header in sensitive_headers:
            if header in headers:
                headers[header] = "***REDACTED***"

        logger.info(
            "incoming_request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "headers": headers,
            },
        )
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "query": str(request.url.query),
                },
            )
            if request.url.path.startswith("/web"):
                return HTMLResponse(
                    "<h1>Ошибка web-кабинета</h1>"
                    "<p>Мы уже записали технические детали в лог. "
                    "Попробуйте открыть кабинет ещё раз или получите новую ссылку в боте.</p>",
                    status_code=500,
                )
            return HTMLResponse(
                "<h1>Внутренняя ошибка сервера</h1>"
                "<p>Технические детали записаны в лог приложения.</p>",
                status_code=500,
            )
        logger.info(
            "response",
            extra={"path": request.url.path, "status": response.status_code},
        )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith("/web") and exc.status_code in {401, 404}:
            if exc.status_code == 401:
                return HTMLResponse(
                    "<h1>Вход в web-кабинет</h1>"
                    "<p>Сессия отсутствует или истекла. Получите новую ссылку в Telegram-боте.</p>",
                    status_code=401,
                )
            return HTMLResponse(
                "<h1>Раздел не найден</h1>"
                "<p>Проверьте ссылку или откройте кабинет из Telegram.</p>",
                status_code=404,
            )
        return await fastapi_http_exception_handler(request, exc)

    @app.get("/health")
    async def health(session: AsyncSession = SESSION_DEPENDENCY) -> dict[str, str]:
        await session.execute(text("select 1"))
        return {"status": "ok"}

    @app.get("/logo.png")
    async def logo() -> FileResponse:
        path = Path("logo.png")
        return FileResponse(path)

    @app.get("/", response_class=HTMLResponse)
    async def landing() -> str:
        return _landing_page()

    @app.get("/admin/errors")
    async def errors(
        x_admin_secret: str = Header(default=""),
        current_settings: Settings = SETTINGS_DEPENDENCY,
    ) -> dict[str, str]:
        expected = current_settings.app_secret_key.get_secret_value()
        if x_admin_secret != expected:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        log = await asyncio.to_thread(_read_errors_log)
        return {"log": log}

    return app


def _read_errors_log() -> str:
    path = Path("logs/errors.log")
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")[-20_000:]


def _landing_page() -> str:
    return """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MP Control — аналитика Wildberries и Ozon</title>
  <style>
    body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;color:#0f172a;background:#f8fafc}
    .wrap{max-width:1120px;margin:0 auto;padding:28px 18px}
    .hero{min-height:78vh;display:grid;grid-template-columns:1.1fr .9fr;gap:40px;align-items:center}
    .logo{width:96px;height:96px;object-fit:contain;margin-bottom:22px}
    h1{font-size:52px;line-height:1.02;margin:0 0 18px;letter-spacing:0}
    p{font-size:18px;line-height:1.65;color:#475569}
    .cta{display:inline-flex;align-items:center;gap:10px;background:#4557f6;color:#fff;text-decoration:none;padding:14px 18px;border-radius:8px;font-weight:700}
    .panel{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:24px;box-shadow:0 10px 30px rgb(15 23 42 / .08)}
    .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:20px}
    .item{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:18px}
    h2{margin:0 0 10px;font-size:24px} h3{margin:0 0 8px;font-size:17px}
    ol{padding-left:22px;color:#475569;line-height:1.8}
    @media(max-width:820px){.hero{grid-template-columns:1fr;min-height:auto;padding-top:32px}h1{font-size:38px}.grid{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <div>
        <img class="logo" src="/logo.png" alt="MP Control">
        <h1>MP Control</h1>
        <p>Сервис для селлеров Wildberries и Ozon: заказы, Telegram-уведомления, продажи и выкупы, остатки, ошибки синхронизации, экономика, план и факт в одном кабинете.</p>
        <a class="cta" href="https://t.me/mpcontrolrobot">Открыть Telegram-бота</a>
      </div>
      <div class="panel">
        <h2>Как начать</h2>
        <ol>
          <li>Откройте Telegram-бота @mpcontrolrobot.</li>
          <li>Подключите кабинеты Wildberries и Ozon.</li>
          <li>Получайте аналитику, уведомления и контроль ошибок в WEB-кабинете.</li>
        </ol>
      </div>
    </section>
    <section class="grid">
      <div class="item"><h3>Что умеет</h3><p>Следит за заказами, продажами, выкупами, остатками и финансовыми отчётами.</p></div>
      <div class="item"><h3>Для кого</h3><p>Для селлеров, которым нужен понятный ежедневный контроль WB и Ozon без ручных таблиц.</p></div>
      <div class="item"><h3>WEB-кабинет</h3><p>Дашборд, товары, остатки, план/факт, продавцы, балансы и диагностика ошибок.</p></div>
    </section>
  </main>
</body>
</html>"""
