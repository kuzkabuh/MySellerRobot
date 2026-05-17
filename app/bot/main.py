"""version: 1.1.0
description: Aiogram bot entrypoint with centralized HTML parse mode and router wiring.
updated: 2026-05-16
"""

import asyncio

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from app.bot.handlers.accounts import router as accounts_router
from app.bot.handlers.common import router as common_router
from app.bot.handlers.costs import router as costs_router
from app.bot.handlers.navigation import router as navigation_router
from app.bot.handlers.subscription import router as subscription_router
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_bot() -> Bot:
    """Create Telegram bot instance from settings."""

    settings = get_settings()
    return Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_storage() -> RedisStorage:
    """Create FSM storage for aiogram."""

    settings = get_settings()
    return RedisStorage.from_url(settings.redis_url)


def create_dispatcher(storage: RedisStorage | None = None) -> Dispatcher:
    """Create dispatcher and register all bot routers without starting polling."""

    dispatcher = Dispatcher(storage=storage)
    for router in (
        navigation_router,
        accounts_router,
        costs_router,
        subscription_router,
        common_router,
    ):
        _include_router(dispatcher, router)
    return dispatcher


def _include_router(dispatcher: Dispatcher, router: Router) -> None:
    """Attach module-level routers while keeping dispatcher factory reusable in tests."""
    if router.parent_router is not None:
        router._parent_router = None
    dispatcher.include_router(router)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    bot = create_bot()
    dispatcher = create_dispatcher(create_storage())
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
