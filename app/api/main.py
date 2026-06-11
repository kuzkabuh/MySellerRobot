"""version: 1.3.0
description: FastAPI application factory — slimmed down. Middleware, error handlers, and system endpoints extracted to submodules.
updated: 2026-06-10
"""

# ruff: noqa: E501

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.error_handlers import http_exception_handler
from app.api.middleware.access_log import (
    log_requests_middleware,
    redact_query,
    sanitize_headers,
    sanitize_url,
    should_log_access,
)
from app.api.routes.system import _read_app_version, router as system_router
from app.api.telegram_webhook import router as telegram_webhook_router
from app.api.webhooks import router as webhooks_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.web.route_modules.payment_public import router as payment_public_router
from app.web.route_modules.wb_logistics_admin import router as wb_logistics_router
from app.web.routes import router as web_router

# ── Compatibility re-exports for tests (preserve old import paths) ──
_redact_query = redact_query
_sanitize_url = sanitize_url
_sanitize_headers = sanitize_headers
_should_log_access = should_log_access


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    app = FastAPI(
        title="Seller Profit Bot API", version=_read_app_version(), debug=settings.app_debug
    )
    app.mount("/static", StaticFiles(directory="public/assets"), name="static")
    app.include_router(web_router)
    app.include_router(webhooks_router)
    app.include_router(telegram_webhook_router)
    app.include_router(payment_public_router)
    app.include_router(wb_logistics_router)
    app.include_router(system_router)

    @app.middleware("http")
    async def log_requests(request, call_next):
        return await log_requests_middleware(request, call_next)

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    return app


app = create_app()
