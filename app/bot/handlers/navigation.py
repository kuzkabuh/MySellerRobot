"""version: 1.0.0
description: Global Telegram navigation commands that reset active FSM scenarios.
updated: 2026-05-17
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards.main import main_menu, user_menu
from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.repositories.users import UserRepository

router = Router(name="navigation")

WELCOME_TEXT = (
    "Привет! Я помогу контролировать продажи на Wildberries и Ozon.\n\n"
    "Я умею:\n"
    "— присылать новые заказы FBS, FBO и rFBS;\n"
    "— считать плановую прибыль по каждому заказу;\n"
    "— показывать ежедневную сводку;\n"
    "— следить за себестоимостью и проблемными товарами;\n"
    "— открывать web-кабинет для подробной аналитики.\n\n"
    "Начните с подключения магазина или откройте меню ниже."
)


@router.message(Command("start", "menu"))
async def start_or_menu_handler(message: Message, state: FSMContext) -> None:
    """Open the main menu from any FSM state."""

    await state.clear()
    if message.from_user is None:
        await message.answer("Не удалось определить Telegram-пользователя.")
        return
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        await repo.get_or_create(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        await session.commit()
    await message.answer(
        WELCOME_TEXT,
        reply_markup=main_menu(is_admin=_is_admin_telegram(message.from_user.id)),
    )


@router.message(Command("usermenu"))
async def user_menu_handler(message: Message, state: FSMContext) -> None:
    """Open the user menu."""

    await state.clear()
    if message.from_user is None:
        await message.answer("Не удалось определить Telegram-пользователя.")
        return
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        await repo.get_or_create(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        await session.commit()
    await message.answer(
        "👤 <b>Меню пользователя</b>\n\nВыберите раздел:",
        reply_markup=user_menu(),
        parse_mode="HTML",
    )


def _is_admin_telegram(telegram_id: int | None) -> bool:
    if telegram_id is None:
        return False
    return telegram_id in get_settings().admin_ids
