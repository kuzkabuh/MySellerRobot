"""version: 1.0.0
description: Common Telegram command and callback handlers.
updated: 2026-05-14
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.main import main_menu, settings_menu
from app.core.db import AsyncSessionFactory
from app.repositories.users import UserRepository

router = Router(name="common")


WELCOME_TEXT = (
    "Привет! Я KUZ’KA.SELLER BOT.\n\n"
    "Я буду показывать новые заказы WB и Ozon не просто как событие, "
    "а сразу с плановой прибылью или убытком.\n\n"
    "Начните с подключения кабинета маркетплейса и загрузки себестоимости товаров."
)


@router.message(Command("start"))
async def start_handler(message: Message) -> None:
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
    await message.answer(WELCOME_TEXT, reply_markup=main_menu())


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "Команды: /summary, /orders, /profit, /stocks, /alerts, /settings.\n"
        "Основной интерфейс доступен через кнопки меню.",
        reply_markup=main_menu(),
    )


@router.message(Command("summary"))
async def summary_handler(message: Message) -> None:
    await message.answer("📊 Сводка за сегодня пока формируется. Подключите кабинет в настройках.")


@router.message(Command("orders"))
async def orders_handler(message: Message) -> None:
    await message.answer("🛒 Заказы появятся здесь после первой синхронизации.")


@router.message(Command("profit"))
async def profit_handler(message: Message) -> None:
    await message.answer("💰 Отчёт по прибыли будет доступен после загрузки себестоимости.")


@router.message(Command("stocks"))
async def stocks_handler(message: Message) -> None:
    await message.answer("📦 Остатки будут доступны после синхронизации товаров.")


@router.message(Command("alerts"))
async def alerts_handler(message: Message) -> None:
    await message.answer("⚠ Активных предупреждений пока нет.")


@router.message(Command("settings"))
async def settings_handler(message: Message) -> None:
    await message.answer("⚙ Настройки", reply_markup=settings_menu())


@router.callback_query()
async def callback_handler(callback: CallbackQuery) -> None:
    data = callback.data or ""
    message = callback.message
    if not isinstance(message, Message):
        await callback.answer("Сообщение недоступно")
        return
    if data == "settings":
        await message.edit_text("⚙ Настройки", reply_markup=settings_menu())
    elif data == "back_main":
        await message.edit_text("Главное меню", reply_markup=main_menu())
    elif data in {"summary", "orders", "profit", "stocks", "control"}:
        await message.answer("Раздел уже заложен в MVP и будет наполняться данными синхронизации.")
    elif data.startswith("connect_"):
        await message.answer(
            "Подключение будет выполнено через безопасный пошаговый сценарий. "
            "API-ключи будут храниться в зашифрованном виде."
        )
    else:
        await message.answer("Раздел в разработке.")
    await callback.answer()
