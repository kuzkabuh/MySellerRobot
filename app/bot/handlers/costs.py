"""version: 1.0.0
description: Telegram product synchronization and cost management handlers.
updated: 2026-05-14
"""

import logging
import tempfile
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.bot.keyboards.main import back_to_settings, costs_menu
from app.bot.states import CostStates
from app.core.db import AsyncSessionFactory
from app.repositories.products import ProductRepository
from app.repositories.users import UserRepository
from app.services.cost_management_service import (
    CostManagementError,
    CostManagementService,
    parse_manual_cost_line,
)
from app.services.excel_cost_import import CostTemplateProductRow, ExcelCostImportService
from app.services.web_sync_service import WebSyncService

router = Router(name="costs")
logger = logging.getLogger(__name__)
MAX_EXCEL_SIZE = 5 * 1024 * 1024


@router.callback_query(F.data == "costs")
async def costs_menu_handler(callback: CallbackQuery) -> None:
    message = callback.message
    if isinstance(message, Message):
        await message.edit_text("Себестоимость товаров", reply_markup=costs_menu())
    await callback.answer()


@router.callback_query(F.data == "products_sync")
async def products_sync_handler(callback: CallbackQuery) -> None:
    user_id = await _get_user_id(callback)
    if user_id is None:
        await callback.answer("Не удалось определить пользователя", show_alert=True)
        return
    message = callback.message
    if isinstance(message, Message):
        await message.answer("Ставлю синхронизацию товаров в очередь...")
    try:
        result = await WebSyncService().request_sync("products", user_id=user_id)
        if isinstance(message, Message):
            await message.answer(result.message, reply_markup=costs_menu())
    except Exception:
        logger.exception("product_sync_queue_failed", extra={"user_id": user_id})
        if isinstance(message, Message):
            await message.answer(
                "Не удалось поставить синхронизацию товаров в очередь. "
                "Проверьте Redis/worker и повторите позже.",
                reply_markup=costs_menu(),
            )
    await callback.answer()


@router.callback_query(F.data == "cost_template")
async def cost_template_handler(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message):
        await callback.answer("Сообщение недоступно", show_alert=True)
        return
    user_id = await _get_user_id(callback)
    if user_id is None:
        await callback.answer("Не удалось определить пользователя", show_alert=True)
        return
    path = Path(tempfile.gettempdir()) / "seller_profit_bot_cost_template.xlsx"
    async with AsyncSessionFactory() as session:
        rows = await ProductRepository(session).list_template_rows_for_user(user_id)
    products = [
        CostTemplateProductRow(
            marketplace=product.marketplace.value,
            account=account.name,
            seller_article=product.seller_article,
            marketplace_article=product.marketplace_article or product.external_product_id,
            title=product.title,
        )
        for product, account in rows
    ]
    excel = ExcelCostImportService()
    if products:
        excel.create_template_for_products(path, products)
        caption = (
            "Шаблон сформирован по синхронизированным товарам. "
            "Заполните себестоимость и отправьте файл обратно."
        )
    else:
        excel.create_template(path)
        caption = (
            "Синхронизированные товары не найдены, поэтому отправляю пример шаблона. "
            "Сначала нажмите «Синхронизировать товары», чтобы получить заполненный список."
        )
    await message.answer_document(
        FSInputFile(path),
        caption=caption,
        reply_markup=costs_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "cost_upload")
async def cost_upload_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CostStates.waiting_for_excel_file)
    message = callback.message
    if isinstance(message, Message):
        await message.answer(
            "Отправьте Excel-файл с себестоимостью. Максимальный размер: 5 МБ.\n"
            "Формат колонок должен совпадать с шаблоном.",
            reply_markup=back_to_settings(),
        )
    await callback.answer()


@router.message(CostStates.waiting_for_excel_file)
async def cost_excel_file_handler(message: Message, state: FSMContext) -> None:
    if message.document is None:
        await message.answer("Пожалуйста, отправьте Excel-файл документом.")
        return
    if message.document.file_size and message.document.file_size > MAX_EXCEL_SIZE:
        await message.answer("Файл слишком большой. Максимальный размер: 5 МБ.")
        return
    if not (message.document.file_name or "").lower().endswith((".xlsx", ".xlsm")):
        await message.answer("Поддерживаются только .xlsx и .xlsm файлы.")
        return
    user_id = await _get_user_id_from_message(message)
    if user_id is None:
        await message.answer("Не удалось определить Telegram-пользователя.")
        return
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / (message.document.file_name or "costs.xlsx")
        if message.bot is None:
            await message.answer("Не удалось получить файл от Telegram.")
            return
        await message.bot.download(message.document, destination=path)
        async with AsyncSessionFactory() as session:
            result = await CostManagementService(session).import_excel(user_id=user_id, path=path)
    await state.clear()
    await message.answer(
        _format_import_result(result.updated, result.errors),
        reply_markup=costs_menu(),
    )


@router.callback_query(F.data == "cost_manual")
async def cost_manual_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CostStates.waiting_for_manual_cost)
    message = callback.message
    if isinstance(message, Message):
        await message.answer(
            "Отправьте себестоимость строкой:\n\n"
            "Артикул; Себестоимость; Упаковка; Доп. расходы; Налог %; Дата начала\n\n"
            "Пример:\n"
            "SKU-001; 520; 25; 0; 6; 2026-05-14",
            reply_markup=back_to_settings(),
        )
    await callback.answer()


@router.message(CostStates.waiting_for_manual_cost)
async def cost_manual_line_handler(message: Message, state: FSMContext) -> None:
    user_id = await _get_user_id_from_message(message)
    if user_id is None:
        await message.answer("Не удалось определить Telegram-пользователя.")
        return
    try:
        article, cost_price, package_cost, additional_cost, tax_rate, valid_from = (
            parse_manual_cost_line(message.text or "")
        )
        async with AsyncSessionFactory() as session:
            await CostManagementService(session).update_by_article(
                user_id=user_id,
                article=article,
                cost_price=cost_price,
                package_cost=package_cost,
                additional_cost=additional_cost,
                tax_rate=tax_rate,
                valid_from=valid_from,
                comment="Ручной ввод через Telegram",
            )
        await state.clear()
        await message.answer("Себестоимость обновлена.", reply_markup=costs_menu())
    except CostManagementError as exc:
        await message.answer(_safe_text(str(exc)), reply_markup=costs_menu())


async def _get_user_id(callback: CallbackQuery) -> int | None:
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        await session.commit()
        return user.id


async def _get_user_id_from_message(message: Message) -> int | None:
    if message.from_user is None:
        return None
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        await session.commit()
        return user.id


def _format_import_result(updated: int, errors: list[str]) -> str:
    lines = [f"Импорт завершён. Обновлено позиций: {updated}."]
    if errors:
        lines.append("")
        lines.append("Ошибки:")
        lines.extend(f"— {_safe_text(error)}" for error in errors[:20])
        if len(errors) > 20:
            lines.append(f"И ещё ошибок: {len(errors) - 20}")
    return "\n".join(lines)


def _safe_text(value: object | None, fallback: str = "н/д") -> str:
    if value is None or value == "":
        return fallback
    return escape(str(value), quote=False)
