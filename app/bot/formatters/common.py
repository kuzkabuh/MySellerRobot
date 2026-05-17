"""version: 1.0.0
description: Shared Telegram text formatters for seller-facing lists and empty states.
updated: 2026-05-17
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from html import escape
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.enums import Marketplace, SaleModel
from app.services.marketplace_presentation import (
    marketplace_marker,
)
from app.services.marketplace_presentation import (
    marketplace_title as presentation_marketplace_title,
)
from app.services.marketplace_presentation import (
    order_status_label as presentation_order_status_label,
)
from app.services.marketplace_presentation import (
    sale_model_title as presentation_sale_model_title,
)
from app.services.message_formatter import rub


def html(value: object | None, fallback: str = "н/д") -> str:
    """Escape external values for Telegram HTML messages."""
    if value is None or value == "":
        return fallback
    return escape(str(value), quote=False)


def format_empty_state(
    *,
    icon: str,
    title: str,
    body: str,
    action: str | None = None,
) -> str:
    """Build a consistent Telegram empty state."""
    lines = [f"{icon} <b>{html(title)}</b>", "", html(body)]
    if action:
        lines.extend(["", f"<b>Что сделать:</b> {html(action)}"])
    return "\n".join(lines)


def format_user_dt(value: datetime | None, timezone_name: str = "Europe/Moscow") -> str:
    """Format a date for user-facing Telegram messages."""
    if value is None:
        return "н/д"
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("Europe/Moscow")
    return value.astimezone(timezone).strftime("%d.%m.%Y, %H:%M")


def format_percent(value: Decimal | int | float | None) -> str:
    """Format percentage with Russian decimal separator."""
    if value is None:
        return "н/д"
    decimal = Decimal(str(value)).quantize(Decimal("0.1"))
    return f"{decimal}".replace(".", ",") + "%"


def marketplace_title(value: Marketplace | str | None) -> str:
    return presentation_marketplace_title(value)


def sale_model_title(value: SaleModel | str | None) -> str:
    return presentation_sale_model_title(value)


def compact_external_id(value: object | None, *, max_length: int = 22) -> str:
    """Shorten long marketplace identifiers for list previews."""
    text = str(value or "н/д")
    if len(text) <= max_length:
        return text
    left = max(6, (max_length - 1) // 2)
    right = max(4, max_length - left - 1)
    return f"{text[:left]}…{text[-right:]}"


def order_status_label(requires_action: bool, status: str | None = None) -> tuple[str, str]:
    if requires_action:
        return "⚠️", presentation_order_status_label(status, True)
    return "ℹ️", presentation_order_status_label(status, False)


def format_recent_orders(
    orders: Sequence[Any],
    *,
    timezone_name: str = "Europe/Moscow",
    title: str = "Последние заказы",
    mode_hint: str = "Показываю последние заказы по всем кабинетам.",
) -> str:
    """Format recent orders as compact Telegram cards instead of technical log lines."""
    if not orders:
        return format_empty_state(
            icon="🛒",
            title="Заказов пока нет",
            body="Мы ещё не нашли заказов по выбранному фильтру.",
            action="Проверьте подключение кабинета или выберите другой период.",
        )

    lines = [f"🛒 <b>{html(title)}</b>", "", html(mode_hint), ""]
    for index, order in enumerate(orders[:10], start=1):
        icon, status = order_status_label(
            bool(getattr(order, "requires_seller_action", False)),
            getattr(order, "normalized_status", None) or getattr(order, "status", None),
        )
        marketplace = marketplace_marker(getattr(order, "marketplace", None))
        sale_model = sale_model_title(getattr(order, "sale_model", None))
        external_id = compact_external_id(getattr(order, "order_external_id", None))
        lines.extend(
            [
                f"{index}. {icon} <b>{marketplace} · {html(sale_model)}</b>",
                f"   • Дата: {format_user_dt(getattr(order, 'order_date', None), timezone_name)}",
                f"   • Заказ: <code>{html(external_id)}</code>",
                f"   • Статус: {status}",
                "",
            ]
        )
    lines.append(
        "<b>Подсказка:</b> подробности по заказам доступны в разделе «Заказы» и в WEB-кабинете."
    )
    return "\n".join(lines).strip()


def format_profit_overview(count: int, profit: Decimal, margin: Decimal) -> str:
    if not count:
        return format_empty_state(
            icon="💰",
            title="Прибыль пока не рассчитана",
            body="Боту нужны заказы и себестоимость товаров, чтобы оценить прибыльность.",
            action="Дождитесь синхронизации или добавьте себестоимость товаров.",
        )
    return "\n".join(
        [
            "💰 <b>Прибыль</b>",
            "",
            "<b>Итог по рассчитанным позициям:</b>",
            f"• Позиций с расчётом: {count}",
            f"• Плановая прибыль: {rub(profit)}",
            f"• Средняя маржа: {format_percent(margin)}",
        ]
    )


def format_stock_rows(rows: Sequence[object]) -> str:
    if not rows:
        return format_empty_state(
            icon="📦",
            title="Остатки пока не загружены",
            body="Данные появятся после успешной синхронизации кабинета маркетплейса.",
        )
    lines = ["📦 <b>Остатки и прогноз</b>", "", "Показываю товары, которые важно проверить.", ""]
    for row in rows[:10]:
        days = getattr(row, "days_until_stockout", None)
        days_text = f"{days} дн." if days is not None else "н/д"
        lines.extend(
            [
                f"⚠️ <b>{html(getattr(row, 'seller_article', None), 'Товар')}</b>",
                f"• Остаток: {getattr(row, 'quantity', 0)} шт.",
                f"• Склад: {html(getattr(row, 'warehouse', None))}",
                f"• Прогноз: хватит примерно на {days_text}",
                f"• Потери за 30 дней: {rub(getattr(row, 'lost_revenue_30d', None))}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def format_stockout_rows(rows: Sequence[object]) -> str:
    if not rows:
        return format_empty_state(
            icon="📦",
            title="Критичных остатков нет",
            body="Сейчас бот не видит товаров с высоким риском out-of-stock.",
        )
    lines = ["📦 <b>Риски out-of-stock</b>", "", "Эти товары стоит проверить в первую очередь.", ""]
    for row in rows[:7]:
        days = getattr(row, "days_until_stockout", None)
        days_text = f"{days} дн." if days is not None else "н/д"
        lines.extend(
            [
                f"⚠️ <b>{html(getattr(row, 'seller_article', None), 'Товар')}</b>",
                f"• Прогноз: {days_text}",
                f"• Рекомендация: {html(getattr(row, 'recommendation', None))}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def format_sync_errors(accounts: Sequence[object]) -> str:
    if not accounts:
        return format_empty_state(
            icon="✅",
            title="Ошибок синхронизации нет",
            body="Активных ошибок по подключённым кабинетам сейчас не найдено.",
        )
    lines = ["⚠️ <b>Ошибки синхронизации</b>", "", "Проверьте кабинеты с последними ошибками.", ""]
    for account in accounts:
        advice = getattr(account, "advice", None)
        lines.extend(
            [
                f"❌ <b>{marketplace_title(getattr(account, 'marketplace', None))} · "
                f"{html(getattr(account, 'name', None), 'Кабинет')}</b>",
                f"• Ошибка: {html(getattr(account, 'last_error_message', None), 'без описания')}",
            ]
        )
        if advice is not None:
            lines.extend(
                [
                    f"• Тип: {html(getattr(advice, 'title', None))}",
                    f"• Что сделать: {html(getattr(advice, 'recommendation', None))}",
                ]
            )
        lines.append("")
    return "\n".join(lines).strip()


def format_fbs_deadline_alert(orders: Sequence[Any]) -> str:
    if not orders:
        return format_empty_state(
            icon="✅",
            title="FBS-заказов с риском нет",
            body="Сейчас нет заказов, которые требуют срочной обработки.",
        )
    lines = ["⚠️ <b>Риск просрочки FBS / rFBS</b>", "", "Эти заказы требуют внимания.", ""]
    for order in orders[:10]:
        deadline = getattr(order, "processing_deadline_at", None) or getattr(
            order, "deadline_at", None
        )
        external_id = compact_external_id(getattr(order, "order_external_id", None))
        lines.extend(
            [
                f"⚠️ <b>{marketplace_title(getattr(order, 'marketplace', None))} · "
                f"{html(sale_model_title(getattr(order, 'sale_model', None)))}</b>",
                f"• Заказ: <code>{html(external_id)}</code>",
                f"• Обработать до: {format_user_dt(deadline)}",
                "",
            ]
        )
    if len(orders) > 10:
        lines.append(f"И ещё заказов: {len(orders) - 10}")
    return "\n".join(lines).strip()
