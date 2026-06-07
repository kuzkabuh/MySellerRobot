"""version: 1.0.0
description: Telegram Bot API webhook endpoint for receiving updates.
updated: 2026-06-02
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["telegram-webhook"])


@router.post("/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> Response:
    """Receive Telegram Bot API webhook updates."""
    settings = get_settings()

    expected_secret = settings.get_bot_webhook_secret()
    if expected_secret:
        if x_telegram_bot_api_secret_token != expected_secret:
            logger.warning(
                "telegram_webhook_invalid_secret",
                extra={"provided": bool(x_telegram_bot_api_secret_token)},
            )
            raise HTTPException(status_code=403, detail="Invalid secret token")
    else:
        if settings.webhook_insecure_dev_allowed:
            logger.warning(
                "telegram_webhook_insecure_dev_mode",
                extra={"path": request.url.path},
            )
        else:
            logger.error(
                "telegram_webhook_no_secret_configured",
                extra={"path": request.url.path},
            )
            raise HTTPException(status_code=403, detail="Webhook secret is not configured")

    try:
        update_data = await request.json()
    except Exception as exc:
        logger.error("telegram_webhook_invalid_json", extra={"error": str(exc)})
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    # Process update through dispatcher
    bot = None
    storage = None
    try:
        from app.bot.main import create_bot, create_dispatcher, create_storage

        bot = create_bot()
        storage = create_storage()
        dispatcher = create_dispatcher(storage)

        from aiogram.types import Update

        update = Update.model_validate(update_data, context={"bot": bot})
        await dispatcher.feed_update(bot, update)
    except Exception as exc:
        logger.exception(
            "telegram_webhook_processing_error",
            extra={"error": str(exc), "update_id": update_data.get("update_id")},
        )
        # Return 200 to prevent Telegram from retrying
        return JSONResponse({"ok": True, "error_logged": True})
    finally:
        if storage is not None:
            await storage.close()
        if bot is not None:
            await bot.session.close()

    return JSONResponse({"ok": True})
