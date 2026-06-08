"""version: 1.0.0
description: Telegram bot admin handlers for commission tariff management.
updated: 2026-05-20
"""

import logging
from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.common import _is_admin_telegram
from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.core.security import TokenCipher
from app.models.domain import User
from app.models.enums import Marketplace
from app.repositories.accounts import MarketplaceAccountRepository
from app.services.commission_tariffs.admin_notifications import (
    format_ozon_import_notification,
    format_ozon_monitor_notification,
    format_wb_sync_notification,
    notify_admins,
)
from app.services.commission_tariffs.ozon_commission_source_monitor_service import (
    OzonCommissionSourceMonitorService,
)
from app.services.commission_tariffs.ozon_commission_xlsx_importer import OzonCommissionXlsxImporter
from app.services.commission_tariffs.wb_commission_sync_service import WbCommissionSyncService

router = Router(name="commission_admin")
logger = logging.getLogger(__name__)


class OzonImportStates(StatesGroup):
    waiting_file = State()
    waiting_date = State()


def _commission_admin_menu() -> str:
    return (
        "📊 <b>Комиссии маркетплейсов</b>\n\n"
        "Управление тарифами комиссий WB и Ozon.\n"
        "Выберите действие:"
    )


def _commission_admin_keyboard():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Обновить комиссии WB", callback_data="admin_commission:sync_wb"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Проверить обновления Ozon", callback_data="admin_commission:check_ozon"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📥 Загрузить таблицу Ozon", callback_data="admin_commission:import_ozon"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Текущие версии", callback_data="admin_commission:versions"
                )
            ],
            [InlineKeyboardButton(text="Назад", callback_data="admin_menu")],
        ]
    )


@router.callback_query(F.data == "admin:commissions")
async def commission_admin_menu_handler(callback: CallbackQuery) -> None:
    if not _is_admin_telegram(callback.from_user.id):
        await callback.answer("Доступно только администраторам.", show_alert=True)
        return
    message = callback.message
    if message:
        await message.edit_text(_commission_admin_menu(), reply_markup=_commission_admin_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_commission:sync_wb")
async def sync_wb_commissions_handler(callback: CallbackQuery) -> None:
    if not _is_admin_telegram(callback.from_user.id):
        await callback.answer("Доступно только администраторам.", show_alert=True)
        return
    message = callback.message
    if not message:
        await callback.answer()
        return

    await message.edit_text("⏳ Синхронизация комиссий WB...")

    try:
        async with AsyncSessionFactory() as session:
            repo = MarketplaceAccountRepository(session)
            accounts = await repo.list_active_accounts(marketplace=Marketplace.WB)
            if not accounts:
                await message.edit_text("Нет активных WB-кабинетов для синхронизации.")
                await callback.answer()
                return

            account = accounts[0]
            try:
                api_key = TokenCipher().decrypt(account.encrypted_api_key)
            except Exception:
                await message.edit_text("Не удалось расшифровать API-ключ WB.")
                await callback.answer()
                return

            service = WbCommissionSyncService(session)
            result = await service.sync(api_key)
            await session.commit()

        notification = format_wb_sync_notification(result)
        await message.edit_text(notification)

        from aiogram import Bot

        settings = get_settings()
        bot = Bot(settings.bot_token.get_secret_value())
        if result.get("changed") or not result.get("success"):
            await notify_admins(bot, notification)
        await bot.session.close()
    except Exception:
        logger.exception("commission_wb_manual_sync_failed")
        await message.edit_text(
            "⚠️ Не удалось синхронизировать комиссии WB. Ошибка зафиксирована в логах."
        )

    await callback.answer()


@router.callback_query(F.data == "admin_commission:check_ozon")
async def check_ozon_commissions_handler(callback: CallbackQuery) -> None:
    if not _is_admin_telegram(callback.from_user.id):
        await callback.answer("Доступно только администраторам.", show_alert=True)
        return
    message = callback.message
    if not message:
        await callback.answer()
        return

    await message.edit_text("⏳ Проверка страницы комиссий Ozon...")

    async with AsyncSessionFactory() as session:
        service = OzonCommissionSourceMonitorService(session)
        result = await service.check()

    notification = format_ozon_monitor_notification(result)
    if notification:
        await message.edit_text(notification)
    else:
        period = result.get("period_label", "н/д")
        await message.edit_text(
            f"✅ Проверка завершена. Изменений нет.\n\nТекущий период: {period}"
        )

    from aiogram import Bot

    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
    if notification:
        await notify_admins(bot, notification)
    await bot.session.close()

    await callback.answer()


@router.callback_query(F.data == "admin_commission:import_ozon")
async def start_ozon_import_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin_telegram(callback.from_user.id):
        await callback.answer("Доступно только администраторам.", show_alert=True)
        return
    message = callback.message
    if message:
        await message.edit_text(
            "📥 <b>Загрузка таблицы комиссий Ozon</b>\n\n"
            "Отправьте XLSX-файл с таблицей комиссий.\n"
            "Файл должен содержать лист 'Прайс РФ (БЗ)'."
        )
    await state.set_state(OzonImportStates.waiting_file)
    await callback.answer()


@router.message(OzonImportStates.waiting_file, F.document)
async def receive_ozon_file_handler(message: Message, state: FSMContext) -> None:
    if not _is_admin_telegram(message.from_user.id if message.from_user else None):
        return

    doc = message.document
    if not doc.file_name or not doc.file_name.lower().endswith((".xlsx", ".xls")):
        await message.answer("Пожалуйста, отправьте файл в формате .xlsx")
        return

    await state.update_data(file_id=doc.file_id, file_name=doc.file_name)
    await state.set_state(OzonImportStates.waiting_date)
    await message.answer(
        "Укажите дату начала действия тарифов в формате ДД.ММ.ГГГГ.\nНапример: 06.04.2026"
    )


@router.message(OzonImportStates.waiting_date)
async def receive_ozon_date_handler(message: Message, state: FSMContext) -> None:
    if not _is_admin_telegram(message.from_user.id if message.from_user else None):
        return

    text = (message.text or "").strip()
    try:
        parts = text.split(".")
        effective_from = date(int(parts[2]), int(parts[1]), int(parts[0]))
    except Exception:
        await message.answer("Неверный формат даты. Используйте ДД.ММ.ГГГГ, например 06.04.2026")
        return

    data = await state.get_data()
    file_id = data.get("file_id")
    file_name = data.get("file_name", "unknown.xlsx")

    await message.answer(f"⏳ Загрузка и импорт файла {file_name}...")

    from aiogram import Bot

    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())

    try:
        file_info = await bot.get_file(file_id)
        file_bytes = await bot.download_file(file_info.file_path)
        file_content = file_bytes.read() if hasattr(file_bytes, "read") else file_bytes
    except Exception as exc:
        await message.answer(f"Не удалось скачать файл: {exc}")
        await state.clear()
        await bot.session.close()
        return

    user = await _get_user_by_telegram(message.from_user.id if message.from_user else None)

    async with AsyncSessionFactory() as session:
        importer = OzonCommissionXlsxImporter(session)
        result = await importer.validate_and_import(
            file_bytes=file_content,
            file_name=file_name,
            effective_from=effective_from,
            uploaded_by_user_id=user.id if user else None,
        )

    notification = format_ozon_import_notification(result)
    await message.answer(notification)

    if result.get("success"):
        bot2 = Bot(settings.bot_token.get_secret_value())
        await notify_admins(bot2, notification)
        await bot2.session.close()

    await state.clear()
    await bot.session.close()


@router.callback_query(F.data == "admin_commission:versions")
async def show_versions_handler(callback: CallbackQuery) -> None:
    if not _is_admin_telegram(callback.from_user.id):
        await callback.answer("Доступно только администраторам.", show_alert=True)
        return
    message = callback.message
    if not message:
        await callback.answer()
        return

    from sqlalchemy import select

    from app.models.commission_tariffs import MarketplaceCommissionVersion

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MarketplaceCommissionVersion)
            .order_by(
                MarketplaceCommissionVersion.marketplace,
                MarketplaceCommissionVersion.effective_from.desc(),
            )
            .limit(20)
        )
        versions = list(result.scalars().all())

    if not versions:
        await message.edit_text("Нет сохранённых версий тарифов.")
        await callback.answer()
        return

    lines = ["📋 <b>Версии тарифов</b>", ""]
    for v in versions:
        status = "✅ активна" if v.is_active else "архив"
        lines.append(
            f"• {v.marketplace.value}: {v.version_label} "
            f"({v.effective_from.isoformat()}) — {status}"
        )

    await message.edit_text("\n".join(lines), reply_markup=_commission_admin_keyboard())
    await callback.answer()


async def _get_user_by_telegram(telegram_id: int | None) -> User | None:
    if telegram_id is None:
        return None
    async with AsyncSessionFactory() as session:
        from app.repositories.users import UserRepository

        repo = UserRepository(session)
        user = await repo.get_by_telegram_id(telegram_id)
        await session.commit()
        return user
