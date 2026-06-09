"""version: 1.0.0
description: Telegram bot admin handlers for WB logistics tariff management.
updated: 2026-05-20
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionFactory
from app.core.security import TokenCipher
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount
from app.models.enums import Marketplace
from app.services.wb.logistics.wb_logistics_tariff_sync_service import (
    WbLogisticsTariffSyncService,
)

router = Router(name="wb_logistics_admin")
logger = logging.getLogger(__name__)


def _is_admin_telegram(telegram_id: int | None) -> bool:
    from app.core.config import get_settings

    return telegram_id in get_settings().admin_ids


async def _get_active_wb_api_key(session: AsyncSession) -> str | None:
    result = await session.execute(
        select(MarketplaceAccount)
        .where(
            MarketplaceAccount.marketplace == Marketplace.WB,
            MarketplaceAccount.is_active.is_(True),
            MarketplaceAccount.encrypted_api_key.isnot(None),
        )
        .order_by(MarketplaceAccount.id.asc())
        .limit(1)
    )
    account = result.scalar_one_or_none()
    if account is None:
        return None
    return TokenCipher().decrypt(account.encrypted_api_key)


@router.message(Command("wb_logistics_sync"))
async def cmd_sync_wb_logistics(message: Message) -> None:
    """Manually trigger WB logistics tariff sync (admin only)."""
    if not _is_admin_telegram(message.from_user.id if message.from_user else None):
        await message.answer("Доступно только администраторам.")
        return

    await message.answer("🔄 Синхронизация тарифов логистики WB...")

    async with AsyncSessionFactory() as session:
        try:
            api_key = await _get_active_wb_api_key(session)
            if api_key is None:
                await message.answer("❌ Нет активного кабинета Wildberries с API-ключом.")
                return

            wb_client = WildberriesClient(api_key=api_key)
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
    if not _is_admin_telegram(callback.from_user.id):
        await callback.answer("Доступно только администраторам.", show_alert=True)
        return

    await callback.answer("Синхронизация...")

    async with AsyncSessionFactory() as session:
        try:
            api_key = await _get_active_wb_api_key(session)
            if api_key is None:
                if callback.message:
                    await callback.message.answer(
                        "❌ Нет активного кабинета Wildberries с API-ключом."
                    )
                return

            wb_client = WildberriesClient(api_key=api_key)
            sync_service = WbLogisticsTariffSyncService(session, wb_client)
            result = await sync_service.sync()
            await session.commit()

            status_emoji = {"new_version": "✅", "no_changes": "ℹ️", "error": "❌"}.get(
                result["status"], "❓"
            )
            if callback.message:
                await callback.message.answer(f"{status_emoji} {result['message']}")
        except Exception:
            logger.exception("wb_logistics_sync_failed")
            if callback.message:
                await callback.message.answer("❌ Ошибка синхронизации тарифов логистики WB")
