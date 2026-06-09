"""version: 2.0.0
description: Common Telegram menu, analytics, alerts, settings, and admin handlers.
updated: 2026-05-17
"""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from html import escape
from ipaddress import ip_address
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters.common import (
    format_percent,
    format_profit_overview,
    format_recent_orders,
    format_stock_rows,
    format_stockout_rows,
    format_sync_errors,
    format_user_dt,
)
from app.bot.keyboards.main import (
    TIMEZONE_OPTIONS,
    admin_deploy_menu,
    admin_menu,
    confirm_deploy_update,
    control_menu,
    costs_menu,
    low_margin_threshold_menu,
    main_menu,
    notification_settings_menu,
    orders_menu,
    profile_menu,
    profit_menu,
    sale_notification_settings_menu,
    settings_menu,
    summary_menu,
    sync_menu,
    timezone_menu,
    web_cabinet_link,
)
from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.models.domain import (
    MarketplaceAccount,
    Order,
    OrderItem,
    Product,
    ProfitSnapshot,
    User,
)
from app.models.enums import CalculationType, PaymentStatus, SaleModel
from app.models.subscriptions import Payment, UserSubscription
from app.repositories.accounts import MarketplaceAccountRepository
from app.repositories.orders import OrderRepository
from app.repositories.users import UserRepository
from app.services.admin.admin_service import AdminService
from app.services.alerts.daily_report_service import DailyReportService
from app.services.common.data_quality_service import DataQualityService
from app.services.admin.deployment_service import DeploymentService
from app.services.alerts.fbs_control_service import FbsControlService
from app.services.common.integration_error_classifier import classify_integration_error
from app.services.unit_economics.marketplace_estimates import (
    PlannedEconomics,
    calculate_planned_economics,
    confidence_label,
    confidence_notes,
)
from app.services.common.message_formatter import format_user_datetime, rub
from app.services.unit_economics.plan_fact_service import PlanFactService
from app.services.unit_economics.stock_forecast_service import StockForecastService
from app.services.subscriptions.subscription_service import SubscriptionService
from app.services.unit_economics.unit_economics_service import UnitEconomicsService
from app.services.account.web_auth_service import WebAuthService
from app.services.common.web_sync_service import WebSyncService

router = Router(name="common")
logger = logging.getLogger(__name__)
SUPPORTED_TIMEZONES = {value for _, value in TIMEZONE_OPTIONS}


def _html(value: object | None, fallback: str = "н/д") -> str:
    if value is None or value == "":
        return fallback
    return escape(str(value), quote=False)


async def _safe_edit_text(message: Message, text: str, **kwargs: Any) -> None:
    try:
        await message.edit_text(text, **kwargs)
    except Exception as e:
        error_msg = str(e).lower()
        if "there is no text" in error_msg or "message to edit" in error_msg:
            try:
                await message.answer(text, **kwargs)
            except Exception:
                logger.exception("safe_edit_text_fallback_failed")
        else:
            raise


class LowMarginStates(StatesGroup):
    waiting_value = State()


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


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        _help_text(),
        reply_markup=main_menu(
            is_admin=_is_admin_telegram(message.from_user.id if message.from_user else None)
        ),
    )


@router.message(Command("summary", "analytics"))
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


@router.message(Command("profile"))
async def profile_handler(message: Message) -> None:
    user_id = await _ensure_user(message)
    if user_id is None:
        return
    await message.answer(await _profile_text(user_id), reply_markup=profile_menu())


@router.message(Command("sync"))
async def sync_command_handler(message: Message) -> None:
    if await _ensure_user(message) is None:
        return
    await message.answer("🔄 Синхронизация", reply_markup=sync_menu())


@router.message(Command("alerts"))
async def alerts_handler(message: Message) -> None:
    user_id = await _ensure_user(message)
    if user_id is None:
        return
    await message.answer(await _control_text(user_id))


@router.message(Command("settings"))
async def settings_handler(message: Message) -> None:
    await message.answer("⚙ Настройки", reply_markup=settings_menu())


@router.message(Command("low_margin"))
async def low_margin_command_handler(message: Message) -> None:
    user_id = await _ensure_user(message)
    if user_id is None:
        return
    text = (message.text or "").replace("/low_margin", "", 1).strip()
    if not text:
        await message.answer("Укажите порог, например: /low_margin 15")
        return
    saved = await _save_low_margin_threshold(user_id, text)
    await message.answer(saved)


@router.message(LowMarginStates.waiting_value)
async def low_margin_manual_value_handler(message: Message, state: FSMContext) -> None:
    user_id = await _ensure_user(message)
    if user_id is None:
        await state.clear()
        return
    await message.answer(await _save_low_margin_threshold(user_id, message.text or ""))
    await state.clear()


@router.message(F.text == "🌐 Web-кабинет")
async def web_cabinet_text_handler(message: Message) -> None:
    user_id = await _ensure_user(message)
    if user_id is None:
        return
    await _send_web_cabinet_link(message, user_id)


@router.callback_query()
async def callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
    data = callback.data or ""
    message = callback.message
    if not isinstance(message, Message):
        await callback.answer("Сообщение недоступно")
        return

    # Subscription menu handlers - delegate to subscription router
    if data.startswith("subscription") or data.startswith("admin_tariff"):
        # These are handled by subscription router, skip here
        return

    if data == "settings":
        await _safe_edit_text(message, "⚙ Настройки", reply_markup=settings_menu())
    elif data == "back_main":
        await _safe_edit_text(
            message,
            "Главное меню",
            reply_markup=main_menu(is_admin=_is_admin_telegram(callback.from_user.id)),
        )
    elif data == "profile":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _profile_text(user_id), reply_markup=profile_menu())
    elif data == "sync_menu":
        await _safe_edit_text(message, "🔄 Синхронизация", reply_markup=sync_menu())
    elif data.startswith("sync:"):
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _request_sync_text(user_id, data.removeprefix("sync:")))
    elif data == "summary_menu":
        await _safe_edit_text(message, "📊 Сводка", reply_markup=summary_menu())
    elif data.startswith("summary:") or data == "summary":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _summary_text(user_id))
    elif data == "orders_menu":
        await _safe_edit_text(message, "🛒 Заказы", reply_markup=orders_menu())
    elif data.startswith("orders:") or data == "orders":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _orders_text(user_id, data))
    elif data == "profit_menu":
        await _safe_edit_text(message, "💰 Прибыль", reply_markup=profit_menu())
    elif data.startswith("profit:") or data == "profit":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            if data == "profit:plan_fact":
                await message.answer(await _plan_fact_text(user_id))
            elif data == "profit:break_even":
                await message.answer(await _break_even_text(user_id))
            else:
                await message.answer(await _profit_text(user_id))
    elif data == "products_costs_menu":
        await _safe_edit_text(message, "📦 Товары и себестоимость", reply_markup=costs_menu())
    elif data == "stocks":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _stocks_text(user_id))
    elif data == "control_menu":
        await _safe_edit_text(message, "⚠ Контроль и уведомления", reply_markup=control_menu())
    elif data.startswith("control:") or data == "control":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            if data == "control:stockout":
                await message.answer(await _stockout_text(user_id))
            elif data == "control:data_quality":
                await message.answer(await _data_quality_text(user_id))
            elif data == "control:low_margin":
                text, current_threshold = await _low_margin_text(user_id)
                await message.answer(
                    text,
                    reply_markup=low_margin_threshold_menu(current_threshold),
                )
            elif data == "control:sync_errors":
                await message.answer(await _sync_errors_text(user_id))
            else:
                await message.answer(await _control_text(user_id))
    elif data in {"notifications", "settings:notifications"}:
        user = await _get_or_create_user(callback)
        if user:
            await _safe_edit_text(
                message,
                _notifications_text(user),
                reply_markup=notification_settings_menu(user.notifications_enabled),
            )
    elif data == "notifications:toggle":
        user = await _toggle_notifications(callback)
        if user:
            await _safe_edit_text(
                message,
                _notifications_text(user),
                reply_markup=notification_settings_menu(user.notifications_enabled),
            )
    elif data == "sale_notifications":
        user = await _get_or_create_user(callback)
        if user:
            enabled = await _sale_notifications_enabled(user.id)
            await _safe_edit_text(
                message,
                _sale_notifications_text(enabled),
                reply_markup=sale_notification_settings_menu(enabled),
            )
    elif data == "sale_notifications:toggle":
        user = await _get_or_create_user(callback)
        if user:
            enabled = await _toggle_sale_notifications(user.id)
            await _safe_edit_text(
                message,
                _sale_notifications_text(enabled),
                reply_markup=sale_notification_settings_menu(enabled),
            )
    elif data == "web_cabinet":
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await _send_web_cabinet_link(message, user_id)
    elif data.startswith("low_margin:set:"):
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            threshold = data.removeprefix("low_margin:set:")
            await _safe_edit_text(
                message,
                await _save_low_margin_threshold(user_id, threshold),
                reply_markup=low_margin_threshold_menu(Decimal(threshold)),
            )
    elif data == "low_margin:manual":
        await state.set_state(LowMarginStates.waiting_value)
        await message.answer(
            "Введите новый порог низкой маржи в процентах, например 12.5.\n"
            "Допустимый диапазон: от 0 до 100."
        )
    elif data.startswith("order:"):
        user_id = await _get_or_create_user_id(callback)
        if user_id:
            await message.answer(await _order_action_text(user_id, data))
    elif data == "admin_menu" or data.startswith("admin:") or data.startswith("admin_deploy:"):
        await _handle_admin_callback(callback, message, data)
    elif data == "timezone":
        user = await _get_or_create_user(callback)
        if user:
            await _safe_edit_text(
                message, _timezone_text(user.timezone), reply_markup=timezone_menu(user.timezone)
            )
    elif data.startswith("timezone:set:"):
        user = await _set_user_timezone(callback, data.removeprefix("timezone:set:"))
        if user:
            await _safe_edit_text(
                message,
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
        await message.answer(
            _help_text(),
            reply_markup=main_menu(is_admin=_is_admin_telegram(callback.from_user.id)),
        )
    elif data.startswith("mrc:"):
        logger.warning(
            "unknown_mrc_callback",
            extra={"callback_data": data, "telegram_id": callback.from_user.id},
        )
        await message.answer(
            "Действие раздела МРЦ пока не обработано. Обновите меню и попробуйте ещё раз."
        )
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


def _help_text() -> str:
    return (
        "❓ <b>Помощь</b>\n\n"
        "Основные команды:\n"
        "• /menu — главное меню\n"
        "• /profile — профиль, тариф и кабинеты\n"
        "• /accounts — подключённые Wildberries и Ozon\n"
        "• /orders — последние заказы\n"
        "• /profit — прибыль и маржинальность\n"
        "• /stocks — остатки и риски out-of-stock\n"
        "• /analytics — краткая сводка\n"
        "• /alerts — контроль, ошибки и уведомления\n"
        "• /sync — запуск синхронизаций\n"
        "• /subscription — подписка и оплата\n\n"
        "Большие таблицы и подробная аналитика открываются в WEB-кабинете."
    )


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


async def _profile_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        user = await session.get(User, user_id)
        accounts = await MarketplaceAccountRepository(session).list_user_accounts(user_id)
        subscription_service = SubscriptionService(session)
        tier = await subscription_service.get_user_tier(user_id)
        active_subscription = await subscription_service.get_active_subscription(user_id)

        active_accounts = [account for account in accounts if account.is_active]
        wb_count = sum(1 for account in active_accounts if account.marketplace.value == "WB")
        ozon_count = sum(1 for account in active_accounts if account.marketplace.value == "OZON")
        notifications = "включены" if user and user.notifications_enabled else "отключены"
        timezone = user.timezone if user else "Europe/Moscow"
        expires_at = (
            format_user_dt(active_subscription.expires_at, timezone).split(",")[0]
            if active_subscription and active_subscription.expires_at
            else "без активного платного периода"
        )

    lines = [
        "👤 <b>Профиль</b>",
        "",
        f"Telegram ID: <code>{user.telegram_id if user else user_id}</code>",
        f"Тариф: <b>{_html(tier.name)}</b>",
        f"Срок действия: {expires_at}",
        f"Уведомления: {notifications}",
        "",
        "🏪 <b>Кабинеты</b>",
        f"Активных: {len(active_accounts)}",
        f"Wildberries: {wb_count}",
        f"Ozon: {ozon_count}",
    ]
    if active_accounts:
        lines.append("")
        lines.append("Последние подключённые:")
        for account in active_accounts[:5]:
            status = "активен" if account.is_active else "отключён"
            last_sync = format_user_dt(account.last_success_sync_at, user.timezone if user else "")
            lines.append(
                f"• {account.marketplace.value}: {_html(account.name)} — {status}, "
                f"синхронизация: {last_sync}"
            )
    else:
        lines.extend(
            [
                "",
                "Подключённых кабинетов пока нет. Начните с Wildberries или Ozon в настройках.",
            ]
        )
    return "\n".join(lines)


async def _request_sync_text(user_id: int, sync_type: str) -> str:
    try:
        result = await WebSyncService().request_sync(sync_type, user_id=user_id)
    except Exception:
        logger.exception(
            "telegram_sync_request_failed",
            extra={"user_id": user_id, "sync_type": sync_type},
        )
        return (
            "🔄 Синхронизация\n\n"
            "Не удалось поставить задачу в очередь. Проверьте Redis/worker и повторите позже."
        )
    marker = "✅" if result.queued else "ℹ️"
    return f"🔄 <b>Синхронизация</b>\n\n{marker} {result.message}"


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
    return format_profit_overview(
        int(count or 0),
        Decimal(str(profit or 0)),
        Decimal(str(margin or 0)),
    )


async def _plan_fact_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        user = await session.get(User, user_id)
        timezone_name = user.timezone if user else "Europe/Moscow"
        data = await PlanFactService(session).compare(
            user_id=user_id,
            timezone=timezone_name,
            period="30d",
            sort="deviation",
            direction="asc",
            limit=5,
        )
    if not data.rows:
        return (
            "📉 План/факт\n\n"
            "Пока нет данных для сравнения. Факт появится после загрузки финансовых отчётов."
        )
    lines = [
        "📉 План/факт за 30 дней",
        "",
        f"Плановая прибыль: {rub(data.summary.estimated_profit)}",
        f"Фактическая прибыль: {rub(data.summary.actual_profit)}",
        f"Отклонение: {rub(data.summary.deviation)}",
        f"Позиций без факта: {data.summary.pending_actual}",
        "",
        "Главные отклонения:",
    ]
    for row in data.rows[:5]:
        lines.append(
            f"• {_html(row.seller_article)}: {rub(row.deviation)} "
            f"({_html(row.reason)}, план {rub(row.estimated_profit)}, "
            f"факт {rub(row.actual_profit)})"
        )
    return "\n".join(lines)


async def _break_even_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        rows = await UnitEconomicsService(session).rows(user_id=user_id, limit=5)
    if not rows:
        return (
            "🧮 Безубыточная цена\n\n"
            "Пока недостаточно заказов с рассчитанной экономикой. "
            "После синхронизации заказов расчёт появится в web-кабинете."
        )
    lines = [
        "🧮 Безубыточная цена",
        "",
        "Первые товары по последним заказам:",
    ]
    for row in rows:
        lines.append(
            f"• {_html(row.seller_article)}: безубыток {rub(row.break_even_price)}, "
            f"цена для цели {rub(row.target_margin_price)}; {_html(row.recommendation)}"
        )
    lines.append("\nПодробный симулятор доступен в web-кабинете: /web/break-even")
    return "\n".join(lines)


async def _orders_text(user_id: int, mode: str = "orders:last10") -> str:
    base_query = select(Order).where(Order.user_id == user_id)
    async with AsyncSessionFactory() as session:
        user = await session.get(User, user_id)
        timezone_name = user.timezone if user else "Europe/Moscow"

        count_query = select(func.count(Order.id)).where(Order.user_id == user_id)
        if mode == "orders:today":
            start_of_day = _today_start_utc(timezone_name)
            base_query = base_query.where(Order.order_date >= start_of_day)
            count_query = count_query.where(Order.order_date >= start_of_day)
        if mode == "orders:fbs":
            base_query = base_query.where(Order.requires_seller_action.is_(True))
            count_query = count_query.where(Order.requires_seller_action.is_(True))
        if mode == "orders:fbo":
            base_query = base_query.where(Order.sale_model == SaleModel.FBO)
            count_query = count_query.where(Order.sale_model == SaleModel.FBO)

        count_result = await session.execute(count_query)
        total_count = int(count_result.scalar() or 0)

        query = base_query.order_by(Order.order_date.desc()).limit(10)
        result = await session.execute(query)
        orders = list(result.scalars().all())

    mode_hint = {
        "orders:today": (
            f"Показываю 10 последних заказов за сегодня (всего найдено: {total_count})."
        ),
        "orders:fbs": (
            f"Показываю 10 последних FBS / rFBS заказов, "
            f"которые требуют обработки (всего: {total_count})."
        ),
        "orders:fbo": f"Показываю 10 последних FBO заказов (всего: {total_count}).",
    }.get(mode, f"Показываю 10 последних заказов из {total_count} в базе.")

    if total_count > 10:
        mode_hint += " Полный список доступен в WEB-кабинете."

    return format_recent_orders(orders, timezone_name=timezone_name, mode_hint=mode_hint)


def _today_start_utc(timezone_name: str) -> datetime:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("Europe/Moscow")
    now_local = datetime.now(tz=timezone)
    return now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


async def _stocks_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        rows = await StockForecastService(session).forecast(user_id=user_id)
    return format_stock_rows(rows)


async def _stockout_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        rows = await StockForecastService(session).forecast(user_id=user_id)
    risky = [row for row in rows if row.status in {"out_of_stock", "critical", "warning"}]
    return format_stockout_rows(risky)


async def _data_quality_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        report = await DataQualityService(session).report(user_id=user_id)
    lines = ["🧪 <b>Качество данных</b>", "", f"<b>Индекс:</b> {report.score}/100", ""]
    for metric in report.metrics:
        lines.append(f"• {_html(metric.title)}: {_html(metric.value)} ({_html(metric.status)})")
    lines.append("\n<b>Что сделать:</b>")
    lines.extend(f"• {_html(item)}" for item in report.recommendations[:5])
    return "\n".join(lines)


async def _low_margin_text(user_id: int) -> tuple[str, Decimal]:
    async with AsyncSessionFactory() as session:
        user = await session.get(User, user_id)
        threshold = Decimal(str(user.low_margin_threshold_percent if user else Decimal("10")))
        result = await session.execute(
            select(OrderItem)
            .join(Order)
            .where(Order.user_id == user_id)
            .where(OrderItem.margin_percent_estimated.is_not(None))
            .where(OrderItem.margin_percent_estimated < threshold)
            .order_by(Order.order_date.desc())
            .limit(7)
        )
        rows = list(result.scalars().all())
    if not rows:
        return (
            "📉 <b>Низкая маржа</b>\n\n"
            f"<b>Текущий порог:</b> {format_percent(threshold)}.\n"
            "Заказов ниже этого уровня сейчас не найдено.\n\n"
            "Что делать: периодически проверяйте товары после изменения тарифов и себестоимости.",
            threshold,
        )
    lines = [
        "📉 <b>Заказы с низкой маржей</b>",
        "",
        f"<b>Текущий порог:</b> {format_percent(threshold)}.",
        "Почему важно: низкая маржа быстро съедается логистикой, скидками и возвратами.",
        "Что сделать: проверьте цену, себестоимость, комиссию и наличие акций.",
        "",
    ]
    for item in rows:
        lines.append(
            f"• {_html(item.seller_article or item.marketplace_article or 'товар')}: "
            f"маржа {format_percent(item.margin_percent_estimated or 0)} "
            f"прибыль {rub(item.profit_estimated or Decimal('0'))}"
        )
    return "\n".join(lines), threshold


async def _save_low_margin_threshold(user_id: int, raw_value: str) -> str:
    value_text = raw_value.strip().replace(",", ".").replace("%", "")
    try:
        threshold = Decimal(value_text).quantize(Decimal("0.01"))
    except Exception:
        return "Не удалось сохранить порог. Введите число от 0 до 100, например 15."
    if threshold < 0 or threshold > 100:
        return "Порог должен быть от 0 до 100%."
    async with AsyncSessionFactory() as session:
        user = await session.get(User, user_id)
        if user is None:
            return "Не удалось найти пользователя. Откройте /start и повторите настройку."
        user.low_margin_threshold_percent = threshold
        await session.commit()
    return (
        "✅ Порог низкой маржи сохранён.\n\n"
        f"Теперь отчёт и алерты будут считать низкой маржу ниже {threshold}%."
    )


async def _sync_errors_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MarketplaceAccount)
            .where(MarketplaceAccount.user_id == user_id)
            .where(MarketplaceAccount.last_error_at.is_not(None))
            .order_by(MarketplaceAccount.last_error_at.desc())
            .limit(7)
        )
        accounts = list(result.scalars().all())
    rows = [
        SimpleNamespace(
            marketplace=account.marketplace,
            name=account.name,
            last_error_message=account.last_error_message,
            advice=classify_integration_error(account.last_error_message),
        )
        for account in accounts
    ]
    return format_sync_errors(rows)


async def _control_text(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        risks = await FbsControlService(session).collect_deadline_risks(user_id=user_id)
        return FbsControlService(session).format_deadline_alert(risks)


def _notifications_text(user: User) -> str:
    status = "включены" if user.notifications_enabled else "отключены"
    return (
        "⚠️ <b>Настройки уведомлений</b>\n\n"
        f"<b>Сейчас уведомления:</b> {status}.\n\n"
        "Эта настройка управляет оперативными сообщениями бота. "
        "Детальные настройки по FBO/FBS/rFBS будут доступны в web-кабинете."
    )


def _sale_notifications_text(enabled: bool) -> str:
    status = "включены" if enabled else "отключены"
    return (
        "✅ <b>Уведомления о продажах и выкупах</b>\n\n"
        f"<b>Сейчас уведомления о выкупах:</b> {status}.\n\n"
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
            return await _format_order_details(session, order, timezone_name)
        if action == "profit":
            return await _format_order_profit(session, order)
        if action == "product":
            return _format_order_product(order)
    return "Не удалось открыть действие по заказу. Откройте меню и выберите раздел заново."


async def _format_order_details(
    session: AsyncSession,
    order: Order,
    timezone_name: str,
) -> str:
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
        product = await _item_product(session, item)
        economics = calculate_planned_economics(
            order,
            item,
            product_commission_rate=product.marketplace_commission_rate if product else None,
            commission_fbw=product.commission_fbw if product else None,
            commission_fbs=product.commission_fbs if product else None,
            commission_dbs=product.commission_dbs if product else None,
            commission_edbs=product.commission_edbs if product else None,
            commission_pickup=product.commission_pickup if product else None,
            commission_booking=product.commission_booking if product else None,
        )
        commission_label = _commission_detail_label(economics)
        logistics_label = _logistics_detail_label(economics)
        lines.extend(
            [
                "",
                f"📁 Товар: {_html(item.title, 'Без названия')}",
                f"🏷 Артикул продавца: {_html(item.seller_article)}",
                f"🆔 Артикул маркетплейса: {_html(item.marketplace_article)}",
                f"🔢 Количество: {item.quantity}",
                "",
                f"💰 Цена продажи: {rub(economics.revenue)}",
                f"💳 Сумма к расчёту: {rub(item.payout_amount_estimated)}",
                commission_label,
                logistics_label,
                f"📦 Себестоимость: {rub(economics.cost_price)}",
                f"💸 Налог: {rub(economics.tax_amount)}",
                "",
                "📊 Плановый результат:",
                f"Прибыль: {rub(economics.profit)}",
                f"Маржа: {economics.margin_percent}%",
                confidence_label(economics.confidence),
            ]
        )
        lines.extend(f"ℹ {note}" for note in confidence_notes(economics))
    return "\n".join(lines)


async def _format_order_profit(session: AsyncSession, order: Order) -> str:
    lines = ["💰 Расчёт прибыли", ""]
    for item in order.items:
        product = await _item_product(session, item)
        economics = calculate_planned_economics(
            order,
            item,
            product_commission_rate=product.marketplace_commission_rate if product else None,
            commission_fbw=product.commission_fbw if product else None,
            commission_fbs=product.commission_fbs if product else None,
            commission_dbs=product.commission_dbs if product else None,
            commission_edbs=product.commission_edbs if product else None,
            commission_pickup=product.commission_pickup if product else None,
            commission_booking=product.commission_booking if product else None,
        )
        marketplace_costs = (
            economics.commission + economics.logistics + economics.other_marketplace_costs
        )
        lines.extend(
            [
                f"{_html(item.title or item.seller_article or 'Товар')}",
                f"Выручка: {rub(economics.revenue)}",
                f"Расходы маркетплейса: {rub(marketplace_costs)}",
                f"Себестоимость: {rub(economics.cost_price)}",
                f"Налог: {rub(economics.tax_amount)}",
                f"Плановая прибыль: {rub(economics.profit)}",
                confidence_label(economics.confidence),
                "",
            ]
        )
        lines.extend(f"ℹ {note}" for note in confidence_notes(economics))
    return "\n".join(lines).strip()


async def _item_product(session: AsyncSession, item: OrderItem) -> Product | None:
    if not item.product_id:
        return None
    return await session.get(Product, item.product_id)


def _format_order_product(order: Order) -> str:
    lines = ["📦 О товаре", ""]
    for item in order.items:
        lines.extend(
            [
                f"Название: {_html(item.title, 'Без названия')}",
                f"Артикул продавца: {_html(item.seller_article)}",
                f"Артикул маркетплейса: {_html(item.marketplace_article)}",
                f"Количество в заказе: {item.quantity}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _commission_detail_label(economics: PlannedEconomics) -> str:
    if not economics.commission_is_known:
        return "🏷 Комиссия маркетплейса: не определена — тариф не найден"
    if economics.commission_rate is not None:
        percent = (economics.commission_rate * Decimal("100")).quantize(Decimal("1"))
        if economics.commission_is_baseline:
            source = _commission_source_detail_label(economics.commission_source)
            tariff = _commission_source_tariff_label(economics.commission_source)
            suffix = f", {tariff}" if tariff else ""
            return f"🏷 {source}: {rub(economics.commission)} ({percent}%{suffix})"
        return f"🏷 Комиссия маркетплейса: {rub(economics.commission)} ({percent}%)"
    return f"🏷 Комиссия маркетплейса: {rub(economics.commission)}"


def _commission_source_detail_label(source: Any) -> str:
    from app.models.enums import ExpenseSource

    labels = {
        ExpenseSource.WB_TARIFF_API: "Базовая комиссия WB",
        ExpenseSource.OZON_TARIFF_DB: "Базовая комиссия Ozon",
        ExpenseSource.OZON_FINANCIAL_DATA: "Комиссия из данных Ozon",
        ExpenseSource.FINANCIAL_REPORT: "Комиссия из отчёта",
        ExpenseSource.FALLBACK_DEFAULT: "Предварительная комиссия",
        ExpenseSource.UNKNOWN: "Комиссия маркетплейса",
    }
    return labels.get(source, "Комиссия маркетплейса")


def _commission_source_tariff_label(source: Any) -> str:
    from app.models.enums import ExpenseSource

    labels = {
        ExpenseSource.WB_TARIFF_API: "тариф WB",
        ExpenseSource.OZON_TARIFF_DB: "тариф Ozon",
        ExpenseSource.OZON_FINANCIAL_DATA: "фин. данные Ozon",
        ExpenseSource.FINANCIAL_REPORT: "фин. отчёт",
        ExpenseSource.FALLBACK_DEFAULT: "предварительно",
    }
    return labels.get(source, "")


def _logistics_detail_label(economics: PlannedEconomics) -> str:
    from app.models.enums import EconomyConfidence, ExpenseSource

    if economics.logistics_is_baseline:
        return f"🚚 Логистика: {rub(economics.logistics)} (предварительно)"
    if economics.logistics == Decimal("0"):
        return "🚚 Логистика: будет уточнена после финансового отчёта"
    if economics.logistics_source == ExpenseSource.WB_LOGISTICS_TARIFF_API:
        if economics.confidence == EconomyConfidence.EXACT:
            return f"🚚 Логистика WB: {rub(economics.logistics)}"
        if economics.confidence == EconomyConfidence.ESTIMATED:
            return f"🚚 Логистика WB: около {rub(economics.logistics)} — оценка"
        return "🚚 Логистика WB: не определена — недостаточно данных для расчёта"
    return f"🚚 Логистика: {rub(economics.logistics)}"


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
    """Check if URL is safe for public use.

    Telegram login buttons must use a host reachable from the user's device.
    """
    if not get_settings().is_safe_web_url(url):
        return False

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    hostname = parsed.hostname
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return False

    try:
        host_ip = ip_address(hostname)
    except ValueError:
        return True

    return not (host_ip.is_loopback or host_ip.is_private or host_ip.is_unspecified)


async def _handle_admin_callback(callback: CallbackQuery, message: Message, data: str) -> None:
    if not _is_admin_telegram(callback.from_user.id):
        await message.answer("Админское меню доступно только администраторам.")
        return
    if data == "admin_menu":
        await _safe_edit_text(message, "🛠 Администрирование", reply_markup=admin_menu())
        return
    if data == "admin:deploy":
        await _safe_edit_text(message, "🚀 Обновление и деплой", reply_markup=admin_deploy_menu())
        return
    if data.startswith("admin_deploy:"):
        await _handle_admin_deploy_callback(callback, message, data)
        return
    if data == "admin:commissions" or data.startswith("admin_commission:"):
        return
    async with AsyncSessionFactory() as session:
        service = AdminService(session)
        if data == "admin:users":
            text = await service.users_text()
        elif data == "admin:support":
            text = "🆘 Обращения пользователей доступны в web-админке: /web/admin/support"
        elif data == "admin:logs":
            text = "📄 Логи доступны в web-админке: /web/admin/logs"
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
        elif data == "admin:reconcile_subs":
            await message.answer(
                "Используйте команду /admin_reconcile_subs для запуска реконсиляции подписок.",
                reply_markup=admin_menu(),
            )
            await callback.answer()
            return
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
            f"📄 Последний лог обновления\n\n<pre>{service.read_update_log_tail()}</pre>",
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


# ============================================================
# ADMIN: SUBSCRIPTION RECONCILIATION
# ============================================================


class AdminReconcileStates(StatesGroup):
    waiting_for_confirm = State()


@router.message(Command("admin_reconcile_subs"))
async def admin_reconcile_subscriptions(message: Message) -> None:
    """Admin command to detect and fix inconsistent subscription states."""
    if message.from_user is None or not _is_admin_telegram(message.from_user.id):
        await message.answer("Доступно только администраторам.")
        return
    admin_telegram_id = message.from_user.id

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(User).where(
                User.id.in_(
                    select(UserSubscription.user_id)
                    .group_by(UserSubscription.user_id)
                    .having(func.count(UserSubscription.id) > 1)
                )
            )
        )
        users_with_multiple = list(result.scalars().all())

        from app.models.enums import SubscriptionStatus

        issues_found = []
        fixed = []

        for user in users_with_multiple:
            subs_result = await session.execute(
                select(UserSubscription)
                .where(
                    UserSubscription.user_id == user.id,
                    UserSubscription.status.in_(
                        [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]
                    ),
                )
                .order_by(UserSubscription.started_at.desc())
            )
            active_subs = list(subs_result.scalars().all())

            if len(active_subs) > 1:
                issues_found.append(
                    f"User {user.telegram_id} ({user.first_name or 'n/a'}): "
                    f"{len(active_subs)} active subscriptions"
                )
                for old_sub in active_subs[1:]:
                    old_sub.status = SubscriptionStatus.REPLACED
                    fixed.append(
                        f"  → Subscription {old_sub.id} (tier {old_sub.tier_id}) marked REPLACED"
                    )

        await session.commit()

        lines = ["🔧 <b>Реконсиляция подписок</b>", ""]
        if not users_with_multiple:
            lines.append("✅ Проблем не обнаружено.")
        else:
            lines.append(f"Пользователей с несколькими подписками: {len(users_with_multiple)}")
            lines.append("")
            if issues_found:
                lines.append("<b>Обнаруженные проблемы:</b>")
                for issue in issues_found:
                    lines.append(f"⚠ {issue}")
                lines.append("")
            if fixed:
                lines.append("<b>Исправлено:</b>")
                for fix in fixed:
                    lines.append(f"✅ {fix}")

        lines.extend(
            [
                "",
                f"Проверено: {len(users_with_multiple)}",
                f"Исправлено: {len(fixed)}",
            ]
        )

        await message.answer("\n".join(lines), reply_markup=admin_menu())

        logger.info(
            "admin_reconcile_subscriptions_completed",
            extra={
                "admin_telegram_id": admin_telegram_id,
                "users_checked": len(users_with_multiple),
                "subscriptions_fixed": len(fixed),
            },
        )


@router.message(Command("admin_fix_payment_urls"))
async def admin_fix_payment_urls(message: Message) -> None:
    """Admin command to fix payment confirmation URLs for pending payments."""
    if message.from_user is None or not _is_admin_telegram(message.from_user.id):
        await message.answer("Доступно только администраторам.")
        return
    admin_telegram_id = message.from_user.id

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Payment).where(
                Payment.status == PaymentStatus.PENDING,
                Payment.provider == "yookassa",
            )
        )
        pending_payments = list(result.scalars().all())

        fixed_count = 0
        settings = get_settings()
        web_url = settings.web_base_url.rstrip("/")
        if web_url.endswith("/web"):
            web_url = web_url[:-4]
        correct_base = f"{web_url}/payment/success"

        for payment in pending_payments:
            meta = payment.payment_metadata or {}
            old_url = meta.get("confirmation_url", "")
            if "/web/payment/success" in old_url or "web/payment/success" in old_url:
                new_url = old_url.replace("/web/payment/success", "/payment/success")
                meta["confirmation_url"] = new_url
                payment.payment_metadata = meta
                fixed_count += 1

        await session.commit()

        lines = [
            "🔧 <b>Исправление URL платежей</b>",
            "",
            f"Найдено pending платежей: {len(pending_payments)}",
            f"Исправлено URL: {fixed_count}",
            "",
            f"Правильный base URL: <code>{correct_base}</code>",
        ]

        await message.answer("\n".join(lines), reply_markup=admin_menu())

        logger.info(
            "admin_fix_payment_urls_completed",
            extra={
                "admin_telegram_id": admin_telegram_id,
                "pending_payments": len(pending_payments),
                "urls_fixed": fixed_count,
            },
        )


def _is_admin_telegram(telegram_id: int | None) -> bool:
    if telegram_id is None:
        return False
    return telegram_id in get_settings().admin_ids
