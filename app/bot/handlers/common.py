"""version: 1.1.0
description: Common Telegram command, menu, web-link, and admin handlers.
updated: 2026-05-14
"""

from datetime import UTC, date, datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from app.bot.keyboards.main import (
    admin_menu,
    control_menu,
    costs_menu,
    main_menu,
    notification_settings_menu,
    orders_menu,
    profit_menu,
    settings_menu,
    summary_menu,
    web_cabinet_link,
)
from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.models.domain import Order, OrderItem, ProfitSnapshot, StockSnapshot, User
from app.models.enums import CalculationType, SaleModel
from app.repositories.users import UserRepository
from app.services.admin_service import AdminService
from app.services.daily_report_service import DailyReportService
from app.services.fbs_control_service import FbsControlService
from app.services.message_formatter import rub
from app.services.web_auth_service import WebAuthService

router = Router(name="common")


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
    await message.answer(
        WELCOME_TEXT,
        reply_markup=main_menu(is_admin=_is_admin_telegram(message.from_user.id)),
    )


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "Команды: /summary, /orders, /profit, /stocks, /alerts, /settings.\n"
        "Основной интерфейс доступен через кнопки меню.",
        reply_markup=main_menu(
            is_admin=_is_admin_telegram(message.from_user.id if message.from_user else None)
        ),
    )


@router.message(Command("summary"))
async def summary_handler(message: Message) -> None:
    user_id = await _ensure_user(message)
    if user_id is None:
        return
    await message.answer(await _summary_text(user_id))


@router.message(Command("orders"))
async def orders_handler(message: Message) -> None:
    user_id = await _ensure_user(message)
    if user_id is None:
        return
    await message.answer(await _orders_text(user_id))


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
    user_id = await _ensure_user(message)
    if user_id is None:
        return
    await message.answer(await _control_text(user_id))


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
        await message.edit_text(
            "Главное меню",
            reply_markup=main_menu(is_admin=_is_admin_telegram(callback.from_user.id)),
        )
    elif data == "summary_menu":
        await message.edit_text("📊 Сводка", reply_markup=summary_menu())
    elif data.startswith("summary:") or data == "summary":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _summary_text(user_id))
    elif data == "orders_menu":
        await message.edit_text("🛒 Заказы", reply_markup=orders_menu())
    elif data.startswith("orders:") or data == "orders":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _orders_text(user_id, data))
    elif data == "profit_menu":
        await message.edit_text("💰 Прибыль", reply_markup=profit_menu())
    elif data.startswith("profit:") or data == "profit":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _profit_text(user_id))
    elif data == "products_costs_menu":
        await message.edit_text("📦 Товары и себестоимость", reply_markup=costs_menu())
    elif data == "stocks":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _stocks_text(user_id))
    elif data == "control_menu":
        await message.edit_text("⚠ Контроль и уведомления", reply_markup=control_menu())
    elif data.startswith("control:") or data == "control":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _control_text(user_id))
    elif data == "notifications":
        user = await _get_or_create_user(callback)
        if user:
            await message.edit_text(
                _notifications_text(user),
                reply_markup=notification_settings_menu(user.notifications_enabled),
            )
    elif data == "notifications:toggle":
        user = await _toggle_notifications(callback)
        if user:
            await message.edit_text(
                _notifications_text(user),
                reply_markup=notification_settings_menu(user.notifications_enabled),
            )
    elif data == "web_cabinet":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            text, url = await _web_login_payload(user_id)
            await message.answer(text, reply_markup=web_cabinet_link(url))
    elif data == "admin_menu" or data.startswith("admin:"):
        await _handle_admin_callback(callback, message, data)
    elif data in {"report_time", "timezone"}:
        await message.answer(
            "Эта настройка будет доступна в web-кабинете. "
            "Базовая логика уже учитывает часовой пояс пользователя."
        )
    elif data == "help":
        await help_handler(message)
    else:
        await message.answer("Я не нашёл такое действие. Откройте меню и выберите раздел заново.")
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
    user = await _get_or_create_user(callback)
    return user.id if user else None


async def _get_or_create_user(callback: CallbackQuery) -> User | None:
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        await session.commit()
        return user


async def _summary_text(user_id: int) -> str:
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


async def _orders_text(user_id: int, mode: str = "orders:last10") -> str:
    now = datetime.now(tz=UTC)
    query = (
        select(Order).where(Order.user_id == user_id).order_by(Order.order_date.desc()).limit(10)
    )
    if mode == "orders:today":
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.where(Order.order_date >= start_of_day)
    if mode == "orders:fbs":
        query = query.where(Order.requires_seller_action.is_(True))
    if mode == "orders:fbo":
        query = query.where(Order.sale_model == SaleModel.FBO)
    async with AsyncSessionFactory() as session:
        result = await session.execute(query)
        orders = list(result.scalars().all())
    if not orders:
        return "🛒 Заказов по выбранному фильтру пока нет."
    lines = ["🛒 Последние заказы", ""]
    for order in orders:
        action = "требует обработки" if order.requires_seller_action else "информационный"
        sale_model = order.sale_model.value if order.sale_model else "н/д"
        lines.append(
            f"— {order.order_date:%d.%m %H:%M} {order.marketplace.value} "
            f"{sale_model} #{order.order_external_id}: {action}"
        )
    return "\n".join(lines)


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
        return "📦 Остатков пока нет. Фоновая синхронизация обновит их автоматически."
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


def _notifications_text(user: User) -> str:
    status = "включены" if user.notifications_enabled else "отключены"
    return (
        "⚠ Настройки уведомлений\n\n"
        f"Сейчас уведомления: {status}.\n\n"
        "Эта настройка управляет оперативными сообщениями бота. "
        "Детальные настройки по FBO/FBS/rFBS будут доступны в web-кабинете."
    )


async def _toggle_notifications(callback: CallbackQuery) -> User | None:
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        user.notifications_enabled = not user.notifications_enabled
        await session.commit()
        return user


async def _web_login_payload(user_id: int) -> tuple[str, str]:
    async with AsyncSessionFactory() as session:
        link = await WebAuthService(session).create_login_link(user_id)
        await session.commit()
    return (
        "🌐 Web-кабинет\n\n"
        "В web-кабинете доступны:\n"
        "— расширенная аналитика;\n"
        "— управление товарами и себестоимостью;\n"
        "— отчёты по заказам и прибыли;\n"
        "— будущий дашборд и графики.\n\n"
        "Нажмите кнопку ниже, чтобы открыть кабинет.",
        link.url,
    )


async def _handle_admin_callback(callback: CallbackQuery, message: Message, data: str) -> None:
    if not _is_admin_telegram(callback.from_user.id):
        await message.answer("Админское меню доступно только администраторам.")
        return
    if data == "admin_menu":
        await message.edit_text("🛠 Администрирование", reply_markup=admin_menu())
        return
    async with AsyncSessionFactory() as session:
        service = AdminService(session)
        if data == "admin:users":
            text = await service.users_text()
        elif data == "admin:accounts":
            text = await service.accounts_text()
        elif data == "admin:sync":
            text = await service.sync_jobs_text()
        elif data == "admin:orders":
            text = await service.order_diagnostics_text()
        else:
            text = await service.system_text()
    await message.answer(text, reply_markup=admin_menu())


def _is_admin_telegram(telegram_id: int | None) -> bool:
    if telegram_id is None:
        return False
    return telegram_id in get_settings().admin_ids
