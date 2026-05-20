"""version: 1.3.0
description: Build rich tariff-aware Telegram order and buyout cards with marketplace-aware URLs.
updated: 2026-05-16
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from html import escape
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Order, OrderItem, Product, ReturnsEvent, SalesEvent, StockSnapshot
from app.models.enums import ExpenseSource, Marketplace, SaleModel
from app.repositories.products import ProductRepository
from app.services.marketplace_estimates import (
    PlannedEconomics,
    calculate_planned_economics,
    confidence_label,
    confidence_notes,
)
from app.services.message_formatter import rub
from app.utils.datetime import format_datetime_for_user, get_user_timezone, user_day_bounds_utc

ZERO = Decimal("0")


def _commission_source_label(source: ExpenseSource) -> str:
    labels = {
        ExpenseSource.WB_TARIFF_API: "тариф WB",
        ExpenseSource.OZON_TARIFF_DB: "тариф Ozon",
        ExpenseSource.OZON_FINANCIAL_DATA: "фин. данные Ozon",
        ExpenseSource.FINANCIAL_REPORT: "фин. отчёт",
        ExpenseSource.FALLBACK_DEFAULT: "предварительно",
        ExpenseSource.UNKNOWN: "не определена",
    }
    return labels.get(source, "не определена")


def _commission_confidence_label(confidence: str | None) -> str:
    """Return a user-friendly label for commission calculation confidence."""
    labels = {
        "exact": "",
        "estimated": " (оценка)",
        "not_available": "",
    }
    return labels.get(confidence or "", "")


@dataclass(frozen=True, slots=True)
class VisualNotification:
    text: str
    image_url: str | None = None
    product_url: str | None = None
    parse_mode: str | None = "HTML"


@dataclass(frozen=True, slots=True)
class OrderStats:
    marketplace_today_count: int = 0
    marketplace_today_revenue: Decimal = ZERO
    product_today_count: int = 0
    product_today_revenue: Decimal = ZERO
    product_yesterday_count: int = 0
    product_yesterday_revenue: Decimal = ZERO


class OrderCardService:
    """Prepare compact seller-style notification cards."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def new_order_card(
        self,
        *,
        order: Order,
        item: OrderItem,
        timezone_name: str,
    ) -> VisualNotification:
        product = await self._resolve_product(order, item)
        stats = await self._order_stats(order, item, timezone_name)
        stock = await self._latest_stock(order, item)
        product_url = self._product_url(order.marketplace, item.marketplace_article)
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
        text = self._format_wb_fbs_order(
            order=order,
            item=item,
            product=product,
            stats=stats,
            stock=stock,
            timezone_name=timezone_name,
            product_url=product_url,
        )
        image_url = product.image_url if product else None
        if order.marketplace != Marketplace.WB or order.sale_model != SaleModel.FBS:
            text = self._format_generic_order(order, item, product, timezone_name)
        profit_changed = economics.profit != item.profit_estimated
        margin_changed = economics.margin_percent != item.margin_percent_estimated
        if profit_changed or margin_changed:
            item.profit_estimated = economics.profit
            item.margin_percent_estimated = economics.margin_percent
            await self.session.flush()
        return VisualNotification(text=text, image_url=image_url, product_url=product_url)

    async def buyout_card(
        self,
        *,
        event: SalesEvent,
        timezone_name: str,
    ) -> VisualNotification:
        product = await self._resolve_product_for_event(event)
        product_url = self._product_url(event.marketplace, event.marketplace_article)
        image_url = product.image_url if product else None
        today_count, today_sum = await self._event_today_stats(event, timezone_name)
        product_today_count, product_today_sum = await self._event_product_stats(
            event, timezone_name, days_offset=0
        )
        product_yesterday_count, product_yesterday_sum = await self._event_product_stats(
            event, timezone_name, days_offset=1
        )
        buyouts_3m, orders_3m = await self._buyout_rate_3m(event)
        title = product.title if product and product.title else event.seller_article or "Товар"
        article = self._link_article(event.marketplace_article, product_url)
        days_from_order = await self._days_from_order(event, timezone_name)
        rate_line = (
            f"💎 Выкуп за 3 мес: {buyouts_3m * 100 // orders_3m}% ({buyouts_3m}/{orders_3m})"
            if orders_3m
            else "💎 Выкуп за 3 мес: пока нет базы"
        )
        days_line = (
            f"⏱ От даты заказа: {days_from_order} дн."
            if days_from_order is not None
            else "⏱ От даты заказа: н/д"
        )
        category = (
            escape(product.category) if product and product.category else "Категория не определена"
        )
        brand = escape(product.brand) if product and product.brand else "Бренд не определён"
        seller_article = escape(event.seller_article or "н/д")
        lines = [
            format_datetime_for_user(event.event_date, timezone_name),
            "",
            f"✅ #Выкуп: {rub(event.amount)}",
            days_line,
            f"📈 Сегодня: {today_count} на {rub(today_sum)}",
            "",
            f"🆔 Арт: {article}",
            f"📁 {category}",
            f"🏷 {brand} / {seller_article}",
            "",
            f"💵 Сегодня таких: {product_today_count} на {rub(product_today_sum)}",
            (
                f"💶 Вчера таких: {product_yesterday_count} на {rub(product_yesterday_sum)}"
                if product_yesterday_count
                else "💶 Вчера таких: 0"
            ),
            rate_line,
            "",
            f"📦 Товар: {escape(title)}",
            "ℹ Фактические расходы будут уточнены после финансовой отчётности маркетплейса.",
        ]
        return VisualNotification(
            text="\n".join(lines),
            image_url=image_url,
            product_url=product_url,
        )

    async def cancellation_card(
        self,
        *,
        order: Order,
        item: OrderItem | None,
        timezone_name: str,
    ) -> VisualNotification:
        product = await self._resolve_product(order, item) if item else None
        article = item.marketplace_article if item else None
        product_url = self._product_url(order.marketplace, article)
        title = item.title or item.seller_article if item else None
        lines = [
            format_datetime_for_user(order.order_date, timezone_name),
            "",
            f"❌ Отмена заказа — {order.marketplace.value}",
            f"📦 {escape(title or order.order_external_id or 'Заказ')}",
            f"🆔 Заказ: {escape(order.order_external_id)}",
            f"📌 Статус: {escape(order.normalized_status or order.status or 'cancelled')}",
        ]
        if item:
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
            lines.extend(
                [
                    f"💰 Сумма заказа: {rub(economics.revenue)}",
                    f"📊 Плановая прибыль была: {rub(economics.profit)}",
                ]
            )
        return VisualNotification(
            text="\n".join(lines),
            image_url=product.image_url if product else None,
            product_url=product_url,
        )

    async def return_card(
        self,
        *,
        event: ReturnsEvent,
        timezone_name: str,
    ) -> VisualNotification:
        lines = [
            format_datetime_for_user(event.event_date, timezone_name),
            "",
            f"↩️ Возврат — {event.marketplace.value}",
            f"🆔 Заказ: {escape(event.order_external_id or 'н/д')}",
            f"📦 Количество: {event.quantity}",
            f"💰 Сумма возврата: {rub(event.amount)}",
        ]
        if event.reason:
            lines.append(f"📌 Причина: {escape(event.reason)}")
        return VisualNotification(
            text="\n".join(lines),
            product_url=None,
        )

    async def _resolve_product(self, order: Order, item: OrderItem) -> Product | None:
        if item.product_id:
            return await self.session.get(Product, item.product_id)
        return await ProductRepository(self.session).find_for_order_item(
            account_id=order.marketplace_account_id,
            marketplace=order.marketplace,
            seller_article=item.seller_article,
            marketplace_article=item.marketplace_article,
            external_product_id=item.marketplace_article,
        )

    async def _resolve_product_for_event(self, event: SalesEvent) -> Product | None:
        if event.product_id:
            return await self.session.get(Product, event.product_id)
        return await ProductRepository(self.session).find_for_order_item(
            account_id=event.marketplace_account_id,
            marketplace=event.marketplace,
            seller_article=event.seller_article,
            marketplace_article=event.marketplace_article,
            external_product_id=event.marketplace_article,
        )

    async def _order_stats(self, order: Order, item: OrderItem, timezone_name: str) -> OrderStats:
        local_date = order.order_date.astimezone(get_user_timezone(timezone_name)).date()
        today_start, today_end = user_day_bounds_utc(local_date, timezone_name)
        yesterday_start, yesterday_end = user_day_bounds_utc(
            local_date - timedelta(days=1),
            timezone_name,
        )
        marketplace_row = await self.session.execute(
            select(
                func.count(func.distinct(Order.id)),
                func.coalesce(func.sum(OrderItem.discounted_price * OrderItem.quantity), 0),
            )
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(Order.user_id == order.user_id)
            .where(Order.marketplace == order.marketplace)
            .where(Order.order_date >= today_start)
            .where(Order.order_date <= today_end)
        )
        marketplace_count, marketplace_revenue = marketplace_row.one()
        today_count, today_revenue = await self._product_order_count(
            order, item, today_start, today_end
        )
        yesterday_count, yesterday_revenue = await self._product_order_count(
            order, item, yesterday_start, yesterday_end
        )
        return OrderStats(
            marketplace_today_count=int(marketplace_count or 0),
            marketplace_today_revenue=Decimal(str(marketplace_revenue or 0)),
            product_today_count=today_count,
            product_today_revenue=today_revenue,
            product_yesterday_count=yesterday_count,
            product_yesterday_revenue=yesterday_revenue,
        )

    async def _product_order_count(
        self,
        order: Order,
        item: OrderItem,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[int, Decimal]:
        query = (
            select(
                func.count(OrderItem.id),
                func.coalesce(func.sum(OrderItem.discounted_price * OrderItem.quantity), 0),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.user_id == order.user_id)
            .where(Order.order_date >= start_at)
            .where(Order.order_date <= end_at)
        )
        if item.product_id:
            query = query.where(OrderItem.product_id == item.product_id)
        elif item.marketplace_article:
            query = query.where(OrderItem.marketplace_article == item.marketplace_article)
        elif item.seller_article:
            query = query.where(OrderItem.seller_article == item.seller_article)
        result = await self.session.execute(query)
        count, revenue = result.one()
        return int(count or 0), Decimal(str(revenue or 0))

    async def _latest_stock(self, order: Order, item: OrderItem) -> StockSnapshot | None:
        query = (
            select(StockSnapshot)
            .where(StockSnapshot.user_id == order.user_id)
            .where(StockSnapshot.marketplace == order.marketplace)
            .order_by(StockSnapshot.snapshot_at.desc())
            .limit(1)
        )
        if item.product_id:
            query = query.where(StockSnapshot.product_id == item.product_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    def _format_wb_fbs_order(
        self,
        *,
        order: Order,
        item: OrderItem,
        product: Product | None,
        stats: OrderStats,
        stock: StockSnapshot | None,
        timezone_name: str,
        product_url: str | None,
    ) -> str:
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
        raw = order.raw_payload or {}
        base_price = self._raw_money(raw, "convertedPrice") or self._raw_money(raw, "price")
        discount_line = self._discount_line(base_price, economics.revenue)
        article = self._link_article(item.marketplace_article, product_url)
        commission_label = self._commission_label(economics)
        logistics_label = self._logistics_label(order, economics)
        stock_line = self._stock_line(stock)
        lines = [
            format_datetime_for_user(order.order_date, timezone_name),
            "",
            f"🛒 #Заказ: {rub(economics.revenue)}",
            f"💰 К выплате: {rub(economics.seller_payout)}",
            (
                f"📈 Сегодня: {stats.marketplace_today_count} "
                f"на {rub(stats.marketplace_today_revenue)}"
            ),
            "",
            f"🆔 Арт: {article}",
            f"📁 {self._product_category(product)}",
            f"🏷 {self._product_brand(product)} / {escape(item.seller_article or 'н/д')}",
        ]
        if discount_line:
            lines.append(discount_line)
        if order.assembly_id:
            lines.append(f"🫱🏻 Сборка: {escape(order.assembly_id)}")
        barcode = self._barcode(raw)
        if barcode:
            lines.append(f"🔢 Баркод: {escape(barcode)}")
        lines.extend(
            [
                "",
                (
                    f"💵 Сегодня таких: {stats.product_today_count} "
                    f"на {rub(stats.product_today_revenue)}"
                ),
                (
                    (
                        f"💶 Вчера таких: {stats.product_yesterday_count} "
                        f"на {rub(stats.product_yesterday_revenue)}"
                    )
                    if stats.product_yesterday_count
                    else "💶 Вчера таких: 0"
                ),
                "",
                commission_label,
                logistics_label,
            ]
        )
        if stock_line:
            lines.append(stock_line)
        lines.extend(
            [
                "",
                "📊 Плановый результат:",
                f"Выручка продавца: {rub(economics.seller_payout)}",
                f"Прибыль: {rub(economics.profit)}",
                f"Маржа: {economics.margin_percent}%",
                confidence_label(economics.confidence),
            ]
        )
        lines.extend(f"ℹ {note}" for note in confidence_notes(economics))
        return "\n".join(lines)

    def _format_generic_order(
        self,
        order: Order,
        item: OrderItem,
        product: Product | None,
        timezone_name: str,
    ) -> str:
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
        return "\n".join(
            [
                format_datetime_for_user(order.order_date, timezone_name),
                "",
                f"🛒 Новый заказ — {order.marketplace.value}",
                f"📦 {escape(item.title or item.seller_article or 'Товар')}",
                f"💰 Цена покупателя: {rub(economics.revenue)}",
                f"💵 К выплате: {rub(economics.seller_payout)}",
                f"📊 Плановая прибыль: {rub(economics.profit)}",
                confidence_label(economics.confidence),
            ]
        )

    @staticmethod
    def _product_url(marketplace: Marketplace, article: str | None) -> str | None:
        """Generate marketplace-specific product URL."""
        if not article:
            return None
        if marketplace == Marketplace.WB:
            return OrderCardService._wb_product_url(article)
        if marketplace == Marketplace.OZON:
            return OrderCardService._ozon_product_url(article)
        return None

    @staticmethod
    def _wb_product_url(article: str | None) -> str | None:
        if not article:
            return None
        digits = "".join(ch for ch in str(article) if ch.isdigit())
        if not digits:
            return None
        return f"https://www.wildberries.ru/catalog/{digits}/detail.aspx?targetUrl=XS"

    @staticmethod
    def _ozon_product_url(article: str | None) -> str | None:
        """Generate Ozon product URL from SKU."""
        if not article:
            return None
        digits = "".join(ch for ch in str(article) if ch.isdigit())
        if not digits:
            return None
        return f"https://www.ozon.ru/product/{digits}/"

    @staticmethod
    def _link_article(article: str | None, product_url: str | None) -> str:
        safe = escape(article or "н/д")
        return f'<a href="{escape(product_url)}">{safe}</a>' if product_url else safe

    @staticmethod
    def _product_category(product: Product | None) -> str:
        if product and product.category:
            return escape(product.category)
        return "Категория не определена"

    @staticmethod
    def _product_brand(product: Product | None) -> str:
        return escape(product.brand) if product and product.brand else "Бренд не определён"

    @staticmethod
    def _raw_money(raw: dict[str, Any], key: str) -> Decimal | None:
        value = raw.get(key)
        if value is None:
            return None
        return (Decimal(str(value)) / Decimal("100")).quantize(Decimal("0.01"))

    @staticmethod
    def _discount_line(base_price: Decimal | None, final_price: Decimal) -> str | None:
        if not base_price or base_price <= final_price:
            return None
        discount = base_price - final_price
        percent = (discount / base_price * Decimal("100")).quantize(Decimal("1"))
        return f"🛍️ WB скидка: {rub(discount)} ({percent}%)"

    @staticmethod
    def _barcode(raw: dict[str, Any]) -> str | None:
        skus = raw.get("skus")
        if isinstance(skus, list) and skus:
            return str(skus[0])
        value = raw.get("barcode") or raw.get("barcodeString")
        return str(value) if value else None

    @staticmethod
    def _commission_label(economics: PlannedEconomics) -> str:
        if not economics.commission_is_known:
            return "💼 Комиссия маркетплейса: не определена — тариф не найден"
        percent = ""
        if economics.commission_rate is not None:
            percent_value = (economics.commission_rate * Decimal("100")).quantize(Decimal("1"))
            percent = f" ({percent_value}%"
            if economics.commission_is_baseline:
                source_label = _commission_source_label(economics.commission_source)
                confidence_suffix = _commission_confidence_label(
                    economics.commission_source.value
                    if hasattr(economics.commission_source, "value")
                    else None
                )
                percent += f", {source_label}{confidence_suffix})"
            else:
                percent += ")"
        suffix = (
            _commission_source_label(economics.commission_source)
            if economics.commission_is_baseline
            else "Комиссия маркетплейса"
        )
        return f"💼 {suffix}: {rub(economics.commission)}{percent}"

    @staticmethod
    def _logistics_label(order: Order, economics: PlannedEconomics) -> str:
        from app.models.enums import EconomyConfidence, ExpenseSource

        if economics.logistics_is_baseline:
            prefix = order.sale_model.value if order.sale_model else "Логистика"
            return f"🌐 Логистика: {prefix}: {rub(economics.logistics)} (предварительно)"
        if economics.logistics == Decimal("0"):
            return "🌐 Логистика: будет уточнена после финансового отчёта"
        if (
            order.marketplace == Marketplace.WB
            and economics.logistics_source == ExpenseSource.WB_LOGISTICS_TARIFF_API
        ):
            if economics.confidence == EconomyConfidence.EXACT:
                return f"🌐 Логистика WB: {rub(economics.logistics)}"
            if economics.confidence == EconomyConfidence.ESTIMATED:
                return f"🌐 Логистика WB: около {rub(economics.logistics)} — оценка"
            return "🌐 Логистика WB: не определена — недостаточно данных для расчёта"
        prefix = order.sale_model.value if order.sale_model else "Логистика"
        return f"🌐 Логистика: {prefix}: {rub(economics.logistics)}"

    @staticmethod
    def _stock_line(stock: StockSnapshot | None) -> str | None:
        if stock is None:
            return None
        days = (
            f" хватит на {stock.days_until_stockout.quantize(Decimal('1'))} дн."
            if stock.days_until_stockout is not None
            else " нет данных для прогноза"
        )
        return f"📦 {stock.warehouse or 'Склад'}: {stock.quantity} шт.{days}"

    async def _event_today_stats(
        self,
        event: SalesEvent,
        timezone_name: str,
    ) -> tuple[int, Decimal]:
        local_date = event.event_date.astimezone(get_user_timezone(timezone_name)).date()
        start, end = user_day_bounds_utc(local_date, timezone_name)
        result = await self.session.execute(
            select(func.count(SalesEvent.id), func.coalesce(func.sum(SalesEvent.amount), 0))
            .where(SalesEvent.user_id == event.user_id)
            .where(SalesEvent.marketplace == event.marketplace)
            .where(SalesEvent.event_date >= start)
            .where(SalesEvent.event_date <= end)
        )
        count, amount = result.one()
        return int(count or 0), Decimal(str(amount or 0))

    async def _event_product_stats(
        self, event: SalesEvent, timezone_name: str, *, days_offset: int
    ) -> tuple[int, Decimal]:
        local_date = event.event_date.astimezone(get_user_timezone(timezone_name)).date()
        start, end = user_day_bounds_utc(local_date - timedelta(days=days_offset), timezone_name)
        query = (
            select(func.count(SalesEvent.id), func.coalesce(func.sum(SalesEvent.amount), 0))
            .where(SalesEvent.user_id == event.user_id)
            .where(SalesEvent.event_date >= start)
            .where(SalesEvent.event_date <= end)
        )
        if event.product_id:
            query = query.where(SalesEvent.product_id == event.product_id)
        elif event.marketplace_article:
            query = query.where(SalesEvent.marketplace_article == event.marketplace_article)
        result = await self.session.execute(query)
        count, amount = result.one()
        return int(count or 0), Decimal(str(amount or 0))

    async def _buyout_rate_3m(self, event: SalesEvent) -> tuple[int, int]:
        start = event.event_date - timedelta(days=90)
        buyout_query = select(func.count(SalesEvent.id)).where(
            SalesEvent.user_id == event.user_id,
            SalesEvent.event_date >= start,
        )
        order_query = (
            select(func.count(OrderItem.id))
            .join(Order)
            .where(
                Order.user_id == event.user_id,
                Order.order_date >= start,
            )
        )
        if event.marketplace_article:
            buyout_query = buyout_query.where(
                SalesEvent.marketplace_article == event.marketplace_article
            )
            order_query = order_query.where(
                OrderItem.marketplace_article == event.marketplace_article
            )
        buyouts = (await self.session.execute(buyout_query)).scalar_one() or 0
        orders = (await self.session.execute(order_query)).scalar_one() or 0
        return int(buyouts), int(orders)

    async def _days_from_order(self, event: SalesEvent, timezone_name: str) -> int | None:
        if not event.related_order_id:
            return None
        order = await self.session.get(Order, event.related_order_id)
        if order is None:
            return None
        timezone = get_user_timezone(timezone_name)
        event_date = event.event_date.astimezone(timezone).date()
        order_date = order.order_date.astimezone(timezone).date()
        return max((event_date - order_date).days, 0)
