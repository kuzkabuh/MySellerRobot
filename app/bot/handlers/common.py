"""version: 1.0.0
description: Common Telegram command and callback handlers.
updated: 2026-05-14
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from app.bot.keyboards.main import main_menu, settings_menu
from app.core.db import AsyncSessionFactory
from app.models.domain import OrderItem, ProfitSnapshot, StockSnapshot
from app.models.enums import CalculationType
from app.repositories.users import UserRepository
from app.services.daily_report_service import DailyReportService
from app.services.fbs_control_service import FbsControlService
from app.services.message_formatter import rub
from app.services.web_auth_service import WebAuthService

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
    user_id = await _ensure_user(message)
    if user_id is None:
        return
    await message.answer(await _summary_text(user_id))


@router.message(Command("orders"))
async def orders_handler(message: Message) -> None:
    await message.answer("🛒 Заказы появятся здесь после первой синхронизации.")


@router.message(Command("profit"))
async def profit_handler(message: Message) -> None:
    user_id = await _ensure_user(message)
    if user_id is None:
        return
    await message.answer(await _profit_text(user_id))


@router.message(Command("stocks"))
async def stocks_handler(message: Message) -> None:
    user_id = await _ensure_user(message)
    if user_id is None:
        return
    await message.answer(await _stocks_text(user_id))


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
    elif data == "summary":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _summary_text(user_id))
    elif data == "profit":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _profit_text(user_id))
    elif data == "stocks":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _stocks_text(user_id))
    elif data == "control":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _control_text(user_id))
    elif data == "web_cabinet":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _web_login_text(user_id))
    elif data == "orders":
        await message.answer("🛒 Последние заказы будут расширены пагинацией в следующем проходе.")
    elif data.startswith("connect_"):
        await message.answer(
            "Подключение будет выполнено через безопасный пошаговый сценарий. "
            "API-ключи будут храниться в зашифрованном виде."
        )
    elif data == "accounts":
        await message.answer("Откройте раздел «Мои кабинеты» в настройках.")
    else:
        await message.answer("Раздел в разработке.")
    await callback.answer()


async def _ensure_user(message: Message) -> int | None:
    if message.from_user is None:
        await message.answer("Не удалось определить Telegram-пользователя.")
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


async def _get_or_create_user_id(callback: CallbackQuery) -> int | None:
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        await session.commit()
        return user.id


async def _summary_text(user_id: int) -> str:
    from datetime import date

    async with AsyncSessionFactory() as session:
        service = DailyReportService(session)
        payload = await service.build_payload(user_id, date.today())
        return service.format_today_summary(payload)


async def _profit_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(
                func.count(ProfitSnapshot.id),
                func.coalesce(func.sum(ProfitSnapshot.profit), 0),
                func.coalesce(func.avg(ProfitSnapshot.margin_percent), 0),
            )
            .join(OrderItem, OrderItem.id == ProfitSnapshot.order_item_id)
            .where(ProfitSnapshot.calculation_type == CalculationType.ESTIMATED)
            .where(OrderItem.order.has(user_id=user_id))
        )
        count, profit, margin = result.one()
    if not count:
        return "💰 Пока нет расчётов прибыли. Дождитесь новых заказов или синхронизации."
    return (
        "💰 Прибыль\n\n"
        f"Позиций с расчётом: {count}\n"
        f"Плановая прибыль: {rub(profit)}\n"
        f"Средняя маржа: {margin:.2f}%"
    )


async def _stocks_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(StockSnapshot)
            .where(StockSnapshot.user_id == user_id)
            .order_by(StockSnapshot.snapshot_at.desc())
            .limit(10)
        )
        snapshots = list(result.scalars().all())
    if not snapshots:
        return "📦 Остатков пока нет. Запустите синхронизацию остатков фоновыми задачами."
    lines = ["📦 Последние остатки", ""]
    for snapshot in snapshots:
        lines.append(
            f"{snapshot.marketplace.value}: {snapshot.quantity} шт., "
            f"склад {snapshot.warehouse or 'н/д'}"
        )
    return "\n".join(lines)


async def _control_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        risks = await FbsControlService(session).collect_deadline_risks(user_id=user_id)
        return FbsControlService(session).format_deadline_alert(risks)


async def _web_login_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        link = await WebAuthService(session).create_login_link(user_id)
        await session.commit()
    return (
        "🌐 Web-кабинет готов к входу.\n\n"
        "Ссылка одноразовая и действует ограниченное время:\n"
        f"{link.url}"
    )
