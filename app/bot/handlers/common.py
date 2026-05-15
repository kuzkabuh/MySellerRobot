"""version: 1.4.0
description: Common Telegram command, menu, web-link, and admin deploy handlers.
updated: 2026-05-15
"""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from app.bot.keyboards.main import (
    TIMEZONE_OPTIONS,
    admin_deploy_menu,
    admin_menu,
    confirm_deploy_update,
    control_menu,
    costs_menu,
    main_menu,
    notification_settings_menu,
    orders_menu,
    profit_menu,
    sale_notification_settings_menu,
    settings_menu,
    summary_menu,
    timezone_menu,
    web_cabinet_link,
)
from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.models.domain import (
    MarketplaceAccount,
    Order,
    OrderItem,
    ProfitSnapshot,
    StockSnapshot,
    User,
)
from app.models.enums import CalculationType, SaleModel
from app.repositories.orders import OrderRepository
from app.repositories.users import UserRepository
from app.services.admin_service import AdminService
from app.services.daily_report_service import DailyReportService
from app.services.deployment_service import DeploymentService
from app.services.fbs_control_service import FbsControlService
from app.services.message_formatter import format_user_datetime, rub
from app.services.web_auth_service import WebAuthService

router = Router(name="common")
logger = logging.getLogger(__name__)
SUPPORTED_TIMEZONES = {value for _, value in TIMEZONE_OPTIONS}


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


@router.message(F.text == "🌐 Web-кабинет")
async def web_cabinet_text_handler(message: Message) -> None:
    user_id = await _ensure_user(message)
    if user_id is None:
        return
    await _send_web_cabinet_link(message, user_id)


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
    elif data in {"notifications", "settings:notifications"}:
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
    elif data == "sale_notifications":
        user = await _get_or_create_user(callback)
        if user:
            enabled = await _sale_notifications_enabled(user.id)
            await message.edit_text(
                _sale_notifications_text(enabled),
                reply_markup=sale_notification_settings_menu(enabled),
            )
    elif data == "sale_notifications:toggle":
        user = await _get_or_create_user(callback)
        if user:
            enabled = await _toggle_sale_notifications(user.id)
            await message.edit_text(
                _sale_notifications_text(enabled),
                reply_markup=sale_notification_settings_menu(enabled),
            )
    elif data == "web_cabinet":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await _send_web_cabinet_link(message, user_id)
    elif data.startswith("order:"):
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _order_action_text(user_id, data))
    elif data == "admin_menu" or data.startswith("admin:") or data.startswith("admin_deploy:"):
        await _handle_admin_callback(callback, message, data)
    elif data == "timezone":
        user = await _get_or_create_user(callback)
        if user:
            await message.edit_text(
                _timezone_text(user.timezone), reply_markup=timezone_menu(user.timezone)
            )
    elif data.startswith("timezone:set:"):
        user = await _set_user_timezone(callback, data.removeprefix("timezone:set:"))
        if user:
            await message.edit_text(
                "✅ Часовой пояс сохранён.\n\n" + _timezone_text(user.timezone),
                reply_markup=timezone_menu(user.timezone),
            )
    elif data == "report_time":
        await message.answer(
            "⏰ Время ежедневных отчётов\n\n"
            "По умолчанию ежедневная сводка отправляется утром. "
            "Точное время будет использовать ваш часовой пояс из настроек."
        )
    elif data == "hide":
        try:
            await message.delete()
        except Exception:
            logger.debug("failed_to_hide_notification", extra={"callback_data": data})
    elif data == "help":
        await help_handler(message)
    else:
        logger.warning(
            "unknown_callback",
            extra={"callback_data": data, "telegram_id": callback.from_user.id},
        )
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
    query = (
        select(Order).where(Order.user_id == user_id).order_by(Order.order_date.desc()).limit(10)
    )
    async with AsyncSessionFactory() as session:
        user = await session.get(User, user_id)
        timezone_name = user.timezone if user else "Europe/Moscow"
        if mode == "orders:today":
            start_of_day = _today_start_utc(timezone_name)
            query = query.where(Order.order_date >= start_of_day)
        if mode == "orders:fbs":
            query = query.where(Order.requires_seller_action.is_(True))
        if mode == "orders:fbo":
            query = query.where(Order.sale_model == SaleModel.FBO)
        result = await session.execute(query)
        orders = list(result.scalars().all())
    if not orders:
        return "🛒 Заказов по выбранному фильтру пока нет."
    lines = ["🛒 Последние заказы", ""]
    for order in orders:
        action = "требует обработки" if order.requires_seller_action else "информационный"
        sale_model = order.sale_model.value if order.sale_model else "н/д"
        lines.append(
            f"— {format_user_datetime(order.order_date, timezone_name)} {order.marketplace.value} "
            f"{sale_model} #{order.order_external_id}: {action}"
        )
    return "\n".join(lines)


def _today_start_utc(timezone_name: str) -> datetime:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("Europe/Moscow")
    now_local = datetime.now(tz=timezone)
    return now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


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


def _sale_notifications_text(enabled: bool) -> str:
    status = "включены" if enabled else "отключены"
    return (
        "✅ Уведомления о продажах и выкупах\n\n"
        f"Сейчас уведомления о выкупах: {status}.\n\n"
        "Бот будет присылать отдельное сообщение, когда маркетплейс зафиксирует "
        "выкуп Wildberries или завершённую продажу Ozon."
    )


async def _sale_notifications_enabled(user_id: int) -> bool:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MarketplaceAccount).where(MarketplaceAccount.user_id == user_id)
        )
        accounts = list(result.scalars().all())
        if not accounts:
            return True
        return all(
            (account.notification_settings or {}).get("SALE_COMPLETED", True)
            for account in accounts
        )


async def _toggle_sale_notifications(user_id: int) -> bool:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MarketplaceAccount).where(MarketplaceAccount.user_id == user_id)
        )
        accounts = list(result.scalars().all())
        current_enabled = all(
            (account.notification_settings or {}).get("SALE_COMPLETED", True)
            for account in accounts
        )
        new_value = not current_enabled
        for account in accounts:
            settings = dict(account.notification_settings or {})
            settings["SALE_COMPLETED"] = new_value
            account.notification_settings = settings
        await session.commit()
        return new_value


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


async def _set_user_timezone(callback: CallbackQuery, timezone_name: str) -> User | None:
    if timezone_name not in SUPPORTED_TIMEZONES:
        await callback.answer("Неизвестный часовой пояс", show_alert=True)
        return None
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        user.timezone = timezone_name
        await session.commit()
        return user


def _timezone_text(timezone_name: str) -> str:
    title = next(
        (label for label, value in TIMEZONE_OPTIONS if value == timezone_name),
        timezone_name,
    )
    return (
        "🕒 Часовой пояс\n\n"
        f"Текущий часовой пояс: {title}\n\n"
        "Выберите свой часовой пояс. Он будет использоваться для времени заказов, "
        "уведомлений и аналитики."
    )


async def _order_action_text(user_id: int, callback_data: str) -> str:
    parts = callback_data.split(":")
    if len(parts) != 3 or not parts[1].isdigit():
        return "Не удалось открыть заказ: кнопка устарела или повреждена."
    order_id = int(parts[1])
    action = parts[2]
    async with AsyncSessionFactory() as session:
        user = await session.get(User, user_id)
        order = await OrderRepository(session).get_with_items(order_id)
        if order is None or order.user_id != user_id:
            return "Заказ не найден. Возможно, он был удалён или относится к другому кабинету."
        timezone_name = user.timezone if user else "Europe/Moscow"
        if action == "details":
            return _format_order_details(order, timezone_name)
        if action == "profit":
            return _format_order_profit(order)
        if action == "product":
            return _format_order_product(order)
    return "Не удалось открыть действие по заказу. Откройте меню и выберите раздел заново."


def _format_order_details(order: Order, timezone_name: str) -> str:
    lines = [
        "📦 Детали заказа",
        "",
        f"Маркетплейс: {order.marketplace.value}",
        f"Модель продаж: {order.sale_model.value if order.sale_model else 'н/д'}",
        f"Статус: {order.normalized_status or order.status}",
        f"Заказ: {order.order_external_id}",
        f"Склад: {order.warehouse or 'не определено'}",
        f"Дата и время заказа: {format_user_datetime(order.order_date, timezone_name)}",
    ]
    deadline = order.processing_deadline_at or order.deadline_at
    if deadline:
        lines.append(f"Дедлайн обработки: {format_user_datetime(deadline, timezone_name)}")
    for item in order.items:
        margin = (
            item.margin_percent_estimated if item.margin_percent_estimated is not None else "н/д"
        )
        lines.extend(
            [
                "",
                f"Товар: {item.title or 'Без названия'}",
                f"Артикул продавца: {item.seller_article or 'н/д'}",
                f"Артикул маркетплейса: {item.marketplace_article or 'н/д'}",
                f"Количество: {item.quantity}",
                "",
                f"💰 Цена продажи: {rub(item.discounted_price)}",
                f"💳 Сумма к расчёту: {rub(item.payout_amount_estimated)}",
                f"🏷 Комиссия маркетплейса: {rub(item.commission_estimated)}",
                f"🚚 Логистика: {rub(item.logistics_estimated)}",
                f"📦 Себестоимость: {rub(item.cost_price_used)}",
                f"💸 Налог: {rub(item.tax_amount_estimated)}",
                "",
                "📊 Плановый результат:",
                f"Прибыль: {rub(item.profit_estimated)}",
                f"Маржа: {margin}%",
            ]
        )
    return "\n".join(lines)


def _format_order_profit(order: Order) -> str:
    lines = ["💰 Расчёт прибыли", ""]
    for item in order.items:
        marketplace_costs = (
            (item.commission_estimated or Decimal("0"))
            + (item.logistics_estimated or Decimal("0"))
            + (item.other_marketplace_expenses_estimated or Decimal("0"))
        )
        lines.extend(
            [
                f"{item.title or item.seller_article or 'Товар'}",
                f"Выручка: {rub(item.discounted_price * item.quantity)}",
                f"Расходы маркетплейса: {rub(marketplace_costs)}",
                f"Себестоимость: {rub(item.cost_price_used)}",
                f"Налог: {rub(item.tax_amount_estimated)}",
                f"Плановая прибыль: {rub(item.profit_estimated)}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _format_order_product(order: Order) -> str:
    lines = ["📦 О товаре", ""]
    for item in order.items:
        lines.extend(
            [
                f"Название: {item.title or 'Без названия'}",
                f"Артикул продавца: {item.seller_article or 'н/д'}",
                f"Артикул маркетплейса: {item.marketplace_article or 'н/д'}",
                f"Количество в заказе: {item.quantity}",
                "",
            ]
        )
    return "\n".join(lines).strip()


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


async def _send_web_cabinet_link(message: Message, user_id: int) -> None:
    try:
        text, url = await _web_login_payload(user_id)
        if not _is_public_web_url(url):
            await message.answer(
                "🌐 Web-кабинет\n\n"
                "Ссылка входа создана, но публичный адрес web-кабинета настроен некорректно.\n"
                "Администратору нужно указать внешний HTTPS-адрес в WEB_BASE_URL "
                "или WEB_APP_BASE_URL."
            )
            return
        await message.answer(text, reply_markup=web_cabinet_link(url))
    except Exception:
        logger.exception("web_cabinet_link_failed", extra={"user_id": user_id})
        await message.answer(
            "🌐 Web-кабинет\n\n"
            "Не удалось сформировать ссылку входа. Попробуйте ещё раз чуть позже "
            "или напишите администратору."
        )


def _is_public_web_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        return False
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        return False
    return parsed.hostname not in {"127.0.0.1", "localhost"}


async def _handle_admin_callback(callback: CallbackQuery, message: Message, data: str) -> None:
    if not _is_admin_telegram(callback.from_user.id):
        await message.answer("Админское меню доступно только администраторам.")
        return
    if data == "admin_menu":
        await message.edit_text("🛠 Администрирование", reply_markup=admin_menu())
        return
    if data == "admin:deploy":
        await message.edit_text("🚀 Обновление и деплой", reply_markup=admin_deploy_menu())
        return
    if data.startswith("admin_deploy:"):
        await _handle_admin_deploy_callback(callback, message, data)
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
        elif data == "admin:wb":
            text = await service.wildberries_diagnostics_text()
        elif data == "admin:events":
            text = await service.event_diagnostics_text()
        else:
            text = await service.system_text()
    await message.answer(text, reply_markup=admin_menu())


async def _handle_admin_deploy_callback(
    callback: CallbackQuery,
    message: Message,
    data: str,
) -> None:
    service = DeploymentService()
    if data == "admin_deploy:version":
        version = await service.current_version()
        text = (
            "📌 Текущая версия MP Control\n\n"
            f"Версия: {version.version}\n"
            f"Ветка: {version.branch}\n"
            f"Commit: {version.commit}\n"
            f"Последний commit: {version.last_commit_message}\n"
            f"Обновлено: {version.updated_at}\n"
            f"Источник: {version.source}"
        )
        await message.answer(text, reply_markup=admin_deploy_menu())
        return
    if data == "admin_deploy:check":
        result = await service.check_updates()
        if result.has_updates:
            text = (
                "⬆ Доступно обновление\n\n"
                f"Ветка: {result.branch}\n"
                f"Текущий commit: {result.current_commit[:7]}\n"
                f"Новый commit: {result.remote_commit[:7]}\n\n"
                "Нажмите «Запустить обновление», чтобы обновить сервер."
            )
        else:
            text = (
                "✅ Установлена последняя версия.\n\n"
                f"Ветка: {result.branch}\n"
                f"Commit: {result.current_commit[:7]}"
            )
        await message.answer(text, reply_markup=admin_deploy_menu())
        return
    if data == "admin_deploy:update":
        await message.answer(
            "⬆ Запустить обновление production-сервера?\n\n"
            "Во время обновления сервисы могут быть кратковременно перезапущены.",
            reply_markup=confirm_deploy_update(),
        )
        return
    if data == "admin_deploy:update_confirm":
        text = await service.start_update(callback.from_user.id)
        await message.answer(text, reply_markup=admin_deploy_menu())
        return
    if data == "admin_deploy:status":
        await message.answer(
            service.format_status(service.read_last_status()),
            reply_markup=admin_deploy_menu(),
        )
        return
    if data == "admin_deploy:log":
        await message.answer(
            "📄 Последний лог обновления\n\n" f"<pre>{service.read_update_log_tail()}</pre>",
            reply_markup=admin_deploy_menu(),
        )
        return
    if data == "admin_deploy:backups":
        backups = service.list_backups()
        if not backups:
            text = "💾 Последние backup\n\nРезервных копий пока нет."
        else:
            lines = ["💾 Последние backup", ""]
            for backup in backups:
                size_mb = backup.size_bytes / 1024 / 1024
                lines.append(
                    f"— {backup.created_at}: {size_mb:.1f} МБ, "
                    f"commit {backup.git_commit[:7]}, версия {backup.app_version}"
                )
            text = "\n".join(lines)
        await message.answer(text, reply_markup=admin_deploy_menu())
        return
    if data == "admin_deploy:cancel":
        await message.answer("Обновление отменено.", reply_markup=admin_deploy_menu())


def _is_admin_telegram(telegram_id: int | None) -> bool:
    if telegram_id is None:
        return False
    return telegram_id in get_settings().admin_ids
