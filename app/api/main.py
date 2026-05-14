"""version: 1.0.0
description: FastAPI application factory and service endpoints.
updated: 2026-05-14
"""

import asyncio
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.logging import configure_logging
from app.web.routes import router as web_router

SESSION_DEPENDENCY = Depends(get_session)
SETTINGS_DEPENDENCY = Depends(get_settings)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    app = FastAPI(title="Seller Profit Bot API", version="1.4.4", debug=settings.app_debug)
    app.include_router(web_router)

    @app.get("/health")
    async def health(session: AsyncSession = SESSION_DEPENDENCY) -> dict[str, str]:
        await session.execute(text("select 1"))
        return {"status": "ok"}

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
