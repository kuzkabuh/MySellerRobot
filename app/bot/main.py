"""version: 1.2.0
description: Aiogram bot entrypoint with centralized HTML parse mode and router wiring.
updated: 2026-06-02
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand

from app.bot.handlers.accounts import router as accounts_router
from app.bot.handlers.admin_panel import router as admin_panel_router
from app.bot.handlers.commissions import router as commissions_router
from app.bot.handlers.common import router as common_router
from app.bot.handlers.costs import router as costs_router
from app.bot.handlers.mrc_pricing import router as mrc_router
from app.bot.handlers.navigation import router as navigation_router
from app.bot.handlers.subscription import router as subscription_router
from app.bot.handlers.user_menu import router as user_menu_router
from app.bot.handlers.wb_logistics_admin import router as wb_logistics_router
from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)

BOT_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand(command="start", description="Открыть главное меню"),
    BotCommand(command="menu", description="Вернуться в главное меню"),
    BotCommand(command="profile", description="Профиль, тариф и подключённые кабинеты"),
    BotCommand(command="orders", description="Последние заказы"),
    BotCommand(command="profit", description="Прибыль и маржинальность"),
    BotCommand(command="stocks", description="Остатки и риски out-of-stock"),
    BotCommand(command="analytics", description="Краткая сводка и аналитика"),
    BotCommand(command="alerts", description="Контроль, ошибки и уведомления"),
    BotCommand(command="accounts", description="Подключённые кабинеты WB и Ozon"),
    BotCommand(command="sync", description="Запустить синхронизацию"),
    BotCommand(command="subscription", description="Подписка и тарифы"),
    BotCommand(command="usermenu", description="Меню пользователя"),
    BotCommand(command="admin", description="Админ-панель"),
    BotCommand(command="tariffs", description="Админ: управление тарифами"),
    BotCommand(command="promocodes", description="Админ: управление промокодами"),
    BotCommand(command="settings", description="Настройки бота"),
    BotCommand(command="low_margin", description="Настроить порог низкой маржи"),
    BotCommand(command="help", description="Помощь по боту"),
)


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
        mrc_router,
        subscription_router,
        admin_panel_router,
        commissions_router,
        wb_logistics_router,
        user_menu_router,
        common_router,
    ):
        _include_router(dispatcher, router)
    return dispatcher


def _include_router(dispatcher: Dispatcher, router: Router) -> None:
    """Attach module-level routers while keeping dispatcher factory reusable in tests."""
    if router.parent_router is not None:
        router._parent_router = None
    dispatcher.include_router(router)


async def set_webhook() -> None:
    """Set Telegram webhook URL from settings."""
    settings = get_settings()
    webhook_url = settings.get_bot_webhook_url()
    bot = create_bot()
    settings.ensure_bot_webhook_secret_allowed()
    secret = settings.get_bot_webhook_secret()

    logger.info("setting_telegram_webhook", extra={"url": webhook_url, "has_secret": bool(secret)})

    try:
        await bot.set_webhook(
            url=webhook_url,
            secret_token=secret,
            drop_pending_updates=False,
        )
    finally:
        await bot.session.close()
    logger.info("telegram_webhook_set_success")


async def delete_webhook() -> None:
    """Delete Telegram webhook and switch to polling mode."""
    bot = create_bot()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    finally:
        await bot.session.close()
    logger.info("telegram_webhook_deleted")


async def get_webhook_info() -> dict[str, object]:
    """Get current Telegram webhook info."""
    bot = create_bot()
    try:
        info = await bot.get_webhook_info()
    finally:
        await bot.session.close()
    return {
        "url": info.url,
        "has_custom_certificate": info.has_custom_certificate,
        "pending_update_count": info.pending_update_count,
        "last_error_date": info.last_error_date,
        "last_error_message": info.last_error_message,
    }


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    bot = create_bot()
    await bot.set_my_commands(list(BOT_COMMANDS))
    dispatcher = create_dispatcher(create_storage())

    if settings.bot_webhook_enabled:
        webhook_url = settings.get_bot_webhook_url()
        settings.ensure_bot_webhook_secret_allowed()
        secret = settings.get_bot_webhook_secret()
        logger.info(
            "bot_webhook_mode",
            extra={"url": webhook_url, "has_secret": bool(secret)},
        )
        await bot.set_webhook(
            url=webhook_url,
            secret_token=secret,
            drop_pending_updates=False,
        )
        logger.info("bot_waiting_for_webhook_updates")
        # In webhook mode, bot doesn't poll - webhook endpoint handles updates
        # Keep process alive for health checks
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("bot_webhook_mode_stopping")
    else:
        logger.info("bot_polling_mode")
        await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
