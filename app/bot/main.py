"""version: 1.0.0
description: Aiogram bot entrypoint.
updated: 2026-05-14
"""

import asyncio

from aiogram import Bot, Dispatcher

from app.bot.handlers.common import router as common_router
from app.core.config import get_settings
from app.core.logging import configure_logging


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    bot = Bot(token=settings.bot_token.get_secret_value())
    dispatcher = Dispatcher()
    dispatcher.include_router(common_router)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
