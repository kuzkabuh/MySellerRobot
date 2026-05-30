"""version: 1.0.0
description: Centralized bot lifecycle management to prevent session leaks.
updated: 2026-05-21
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_bot_instance: Bot | None = None


def create_bot() -> Bot:
    """Create a new Telegram bot instance from settings.

    WARNING: Each call creates a new aiohttp session.
    Prefer ``get_bot()`` or ``bot_session()`` for managed lifecycle.
    """
    settings = get_settings()
    return Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def get_bot() -> Bot:
    """Return a shared bot singleton for the running process.

    Safe for concurrent access. The singleton must be closed
    explicitly via ``close_bot_singleton()`` during shutdown.
    """
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = create_bot()
    return _bot_instance


async def close_bot_singleton() -> None:
    """Close the shared bot singleton if it exists."""
    global _bot_instance
    if _bot_instance is not None:
        try:
            await _bot_instance.session.close()
        except Exception:
            logger.exception("bot_singleton_close_failed")
        _bot_instance = None


@asynccontextmanager
async def bot_session() -> AsyncGenerator[Bot, None]:
    """Context manager that creates a bot and guarantees session close.

    Use this in workers, webhooks, and services that need a temporary bot:

        async with bot_session() as bot:
            await bot.send_message(chat_id, text)
    """
    bot = create_bot()
    try:
        yield bot
    finally:
        try:
            await bot.session.close()
        except Exception:
            logger.exception("bot_session_close_failed")
