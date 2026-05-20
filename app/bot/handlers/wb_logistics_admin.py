"""version: 1.0.0
description: Telegram bot admin handlers for WB logistics tariff management.
updated: 2026-05-20
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.core.db import AsyncSessionFactory
from app.integrations.wb import WildberriesClient
from app.services.wb_logistics.wb_logistics_tariff_sync_service import (
    WbLogisticsTariffSyncService,
)

router = Router(name="wb_logistics_admin")
logger = logging.getLogger(__name__)


@router.message(Command("wb_logistics_sync"))
async def cmd_sync_wb_logistics(message: Message) -> None:
    """Manually trigger WB logistics tariff sync (admin only)."""
    await message.answer("🔄 Синхронизация тарифов логистики WB...")

    async with AsyncSessionFactory() as session:
        try:
            from app.core.config import get_settings

            settings = get_settings()
            wb_client = WildberriesClient(api_key=settings.wb_api_key)
            sync_service = WbLogisticsTariffSyncService(session, wb_client)
            result = await sync_service.sync()
            await session.commit()

            status_emoji = {"new_version": "✅", "no_changes": "ℹ️", "error": "❌"}.get(
                result["status"], "❓"
            )
            await message.answer(
                f"{status_emoji} {result['message']}\n"
                f"Версия: {result.get('version_id', '—')}\n"
                f"Записей: {result.get('rows_count', 0)}"
            )
        except Exception:
            logger.exception("wb_logistics_sync_failed")
            await message.answer("❌ Ошибка синхронизации тарифов логистики WB")


@router.callback_query(F.data == "admin:wb_logistics_sync")
async def cb_sync_wb_logistics(callback: CallbackQuery) -> None:
    """Callback handler for WB logistics sync button."""
    await callback.answer("Синхронизация...")

    async with AsyncSessionFactory() as session:
        try:
            from app.core.config import get_settings

            settings = get_settings()
            wb_client = WildberriesClient(api_key=settings.wb_api_key)
            sync_service = WbLogisticsTariffSyncService(session, wb_client)
            result = await sync_service.sync()
            await session.commit()

            status_emoji = {"new_version": "✅", "no_changes": "ℹ️", "error": "❌"}.get(
                result["status"], "❓"
            )
            await callback.message.answer(
                f"{status_emoji} {result['message']}"
            )
        except Exception:
            logger.exception("wb_logistics_sync_failed")
            await callback.message.answer("❌ Ошибка синхронизации тарифов логистики WB")
