"""version: 1.1.0
description: Russian Telegram message formatting helpers.
updated: 2026-05-15
"""

from decimal import Decimal

from app.models.enums import Marketplace, SaleModel
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
        sale_model = order.sale_model or SaleModel.FBS
        is_action_required = order.requires_seller_action or sale_model in {
            SaleModel.FBS,
            SaleModel.RFBS,
            SaleModel.DBS,
            SaleModel.DBW,
        }
        title_icon = "🚨" if is_action_required else "🛒"
        deadline_label = "Собрать до" if is_action_required else "Дата обработки"
        result_line = (
            f"✅ Прибыль: +{rub(profit.profit)}"
            if profit.profit >= 0
            else f"🔴 Плановый убыток: {rub(profit.profit)}"
        )
        lines = [
            f"{title_icon} Новый заказ — {marketplace_title} / {sale_model.value}",
            "",
            f"📦 Товар: {item.title or 'Без названия'}",
            f"🏷 Артикул продавца: {item.seller_article or 'н/д'}",
            f"🔢 Артикул маркетплейса: {item.marketplace_article or 'н/д'}",
            f"🚚 Модель продаж: {sale_model.value}",
            f"🏭 Склад: {order.warehouse or 'н/д'}",
            f"🕒 {'Заказ получен' if is_action_required else 'Дата заказа'}: "
            f"{order.order_date:%d.%m.%Y %H:%M}",
        ]
        deadline = order.processing_deadline_at or order.deadline_at
        if deadline and is_action_required:
            lines.append(f"⏰ {deadline_label}: {deadline:%d.%m.%Y %H:%M}")
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
                    f"— Доп. расходы продавца: {rub(profit.additional_seller_cost)}",
                    f"— Налог: {rub(profit.tax_amount)}",
                ]
            )
        lines.extend(
            ["", "📊 Плановый результат:", result_line, f"📈 Маржа: {profit.margin_percent}%"]
        )
        if profit.missing_cost:
            lines.extend(["", "⚠ Себестоимость товара не указана. Прибыль рассчитана неполно."])
        for warning in profit.warnings:
            if "Комиссия маркетплейса" in warning:
                lines.extend(["", f"⚠ {warning}."])
        if profit.profit < 0:
            lines.append("Причина: расходы превышают расчётную выплату.")
        if is_action_required:
            lines.extend(["", "⚠ Требует обработки продавцом."])
        else:
            lines.extend(
                [
                    "",
                    "ℹ Заказ обрабатывается складом маркетплейса.",
                    "Действия от продавца не требуются.",
                ]
            )
            if order.source_event_type:
                lines.append("Источник данных может обновляться с задержкой маркетплейса.")
        return "\n".join(lines)
