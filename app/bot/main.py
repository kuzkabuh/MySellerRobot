"""version: 1.0.0
description: Aiogram bot entrypoint.
updated: 2026-05-14
"""

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

from app.bot.handlers.accounts import router as accounts_router
from app.bot.handlers.common import router as common_router
from app.bot.handlers.costs import router as costs_router
from app.core.config import get_settings
from app.core.logging import configure_logging


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    bot = Bot(token=settings.bot_token.get_secret_value())
    storage = RedisStorage.from_url(settings.redis_url)
    dispatcher = Dispatcher(storage=storage)
    dispatcher.include_router(accounts_router)
    dispatcher.include_router(costs_router)
    dispatcher.include_router(common_router)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
