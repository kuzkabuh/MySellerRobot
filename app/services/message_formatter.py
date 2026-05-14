"""version: 1.0.0
description: Russian Telegram message formatting helpers.
updated: 2026-05-14
"""

from decimal import Decimal

from app.models.enums import Marketplace
from app.schemas.orders import NormalizedOrder, NormalizedOrderItem
from app.schemas.profit import ProfitResult


def rub(value: Decimal | None) -> str:
    if value is None:
        return "н/д"
    rounded = value.quantize(Decimal("1"))
    return f"{rounded:,.0f}".replace(",", " ") + " ₽"


class MessageFormatter:
    """Format bot-facing Russian messages."""

    def new_order_card(
        self,
        order: NormalizedOrder,
        item: NormalizedOrderItem,
        profit: ProfitResult,
        detailed: bool = False,
    ) -> str:
        marketplace_title = "Wildberries" if order.marketplace == Marketplace.WB else "Ozon"
        result_line = (
            f"✅ Прибыль: +{rub(profit.profit)}"
            if profit.profit >= 0
            else f"🔴 Плановый убыток: {rub(profit.profit)}"
        )
        lines = [
            f"🛒 Новый заказ — {marketplace_title} / {order.sale_model or 'FBS'}",
            "",
            f"📦 Товар: {item.title or 'Без названия'}",
            f"🏷 Артикул продавца: {item.seller_article or 'н/д'}",
            f"🔢 Артикул маркетплейса: {item.marketplace_article or 'н/д'}",
            f"🚚 Модель продаж: {order.sale_model or 'н/д'}",
            f"🏭 Склад / пункт обработки: {order.warehouse or 'н/д'}",
            f"🕒 Заказ получен: {order.order_date:%d.%m.%Y %H:%M}",
        ]
        if order.deadline_at:
            lines.append(f"⏰ Обработать до: {order.deadline_at:%d.%m.%Y %H:%M}")
        lines.extend(
            [
                "",
                f"💰 Цена продажи: {rub(item.discounted_price or item.seller_price)}",
                f"💳 Сумма к расчёту: {rub(item.payout_amount_estimated)}",
            ]
        )
        if detailed:
            lines.extend(
                [
                    "",
                    "📉 Плановые расходы:",
                    f"— Комиссия МП: {rub(profit.marketplace_commission)}",
                    f"— Логистика: {rub(profit.logistics_cost)}",
                    f"— Прочие расходы МП: {rub(profit.other_marketplace_costs)}",
                    f"— Себестоимость: {rub(profit.cost_price)}",
                    f"— Упаковка: {rub(profit.package_cost)}",
                    f"— Налог: {rub(profit.tax_amount)}",
                ]
            )
        lines.extend(
            ["", "📊 Плановый результат:", result_line, f"📈 Маржа: {profit.margin_percent}%"]
        )
        if profit.missing_cost:
            lines.extend(["", "⚠ Себестоимость товара не указана. Прибыль рассчитана неполно."])
        if profit.profit < 0:
            lines.append("Причина: расходы превышают расчётную выплату.")
        return "\n".join(lines)
