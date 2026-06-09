"""version: 1.2.0
description: Daily and period summary report service with polished Telegram formatting.
updated: 2026-05-17
"""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    MarketplaceAccount,
    Order,
    OrderItem,
    ProfitSnapshot,
    ReturnsEvent,
    SalesEvent,
    User,
)
from app.models.enums import CalculationType, Marketplace
from app.services.common.message_formatter import rub


class DailyReportService:
    """Build compact Russian daily reports."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    async def build_payload(
        self,
        user_id: int,
        report_date: date,
    ) -> dict[str, dict[str, Decimal | int]]:
        if self.session is None:
            raise RuntimeError("Для построения отчёта нужна DB-сессия")
        user = await self.session.get(User, user_id)
        timezone_name = user.timezone if user else "Europe/Moscow"
        start, end = self._day_bounds_utc(report_date, timezone_name)
        marketplaces = await self._connected_marketplaces(user_id)
        if not marketplaces:
            marketplaces = [Marketplace.WB, Marketplace.OZON]
        payload = self._empty_payload(marketplaces)
        await self._fill_orders(user_id, start, end, payload)
        await self._fill_sales(user_id, start, end, payload)
        await self._fill_returns(user_id, start, end, payload)
        return {marketplace.value: payload[marketplace] for marketplace in marketplaces}

    def format_report(self, report_date: date, payload: dict[str, dict[str, Decimal | int]]) -> str:
        lines = [f"📊 <b>Сводка за {report_date:%d.%m.%Y}</b>", ""]
        total_revenue = Decimal("0")
        total_sales_revenue = Decimal("0")
        total_profit = Decimal("0")
        total_orders = 0
        total_sales = 0
        total_returns = 0
        total_cancellations = 0
        marketplace_blocks: list[str] = []
        for marketplace, data in payload.items():
            revenue = Decimal(str(data.get("revenue", 0)))
            sales_revenue = Decimal(str(data.get("sales_revenue", 0)))
            profit = Decimal(str(data.get("estimated_profit", 0)))
            sales_profit = Decimal(str(data.get("sales_estimated_profit", 0)))
            orders = int(data.get("orders", 0))
            sales = int(data.get("sales", 0))
            returns = int(data.get("returns", 0))
            cancellations = int(data.get("cancellations", 0))
            total_revenue += revenue
            total_sales_revenue += sales_revenue
            total_profit += profit
            total_orders += orders
            total_sales += sales
            total_returns += returns
            total_cancellations += cancellations
            sales_label = "Выкупов" if marketplace == Marketplace.WB.value else "Завершённых продаж"
            title = self._marketplace_title(marketplace)
            marketplace_blocks.extend(
                [
                    f"<b>{title}</b>",
                    f"• Заказов: {orders} на {rub(revenue)}",
                    f"• {sales_label}: {sales} на {rub(sales_revenue)}",
                    f"• Возвратов: {returns}",
                    f"• Отмен: {cancellations}",
                    f"• Плановая прибыль по заказам: {rub(profit)}",
                    f"• Плановая прибыль по выкупам: {rub(sales_profit)}",
                    "",
                ]
            )
        lines.extend(
            [
                "<b>Продажи и заказы:</b>",
                f"• Заказов: {total_orders}",
                f"• Выкупов / завершённых продаж: {total_sales}",
                f"• Возвратов: {total_returns}",
                f"• Отмен: {total_cancellations}",
                "",
                "<b>Финансы:</b>",
                f"• Выручка по заказам: {rub(total_revenue)}",
                f"• Выкуплено / завершено продаж: {rub(total_sales_revenue)}",
                f"• Плановая прибыль: {rub(total_profit)}",
                "",
                "<b>По маркетплейсам:</b>",
                *marketplace_blocks,
            ]
        )
        return "\n".join(lines).strip()

    def format_today_summary(self, payload: dict[str, dict[str, Decimal | int]]) -> str:
        if not payload:
            return (
                "📊 <b>Сводка за сегодня</b>\n\n"
                "Заказов пока нет. Данные появятся после синхронизации кабинетов."
            )
        return self.format_report(date.today(), payload).replace("Сводка за", "Сегодня")

    async def _connected_marketplaces(self, user_id: int) -> list[Marketplace]:
        if self.session is None:
            return []
        result = await self.session.execute(
            select(MarketplaceAccount.marketplace)
            .where(MarketplaceAccount.user_id == user_id)
            .where(MarketplaceAccount.is_active.is_(True))
            .group_by(MarketplaceAccount.marketplace)
        )
        existing = set(result.scalars().all())
        return [
            marketplace
            for marketplace in [Marketplace.WB, Marketplace.OZON]
            if marketplace in existing
        ]

    @staticmethod
    def _empty_payload(
        marketplaces: list[Marketplace],
    ) -> dict[Marketplace, dict[str, Decimal | int]]:
        return {
            marketplace: {
                "orders": 0,
                "sales": 0,
                "sales_revenue": Decimal("0"),
                "sales_estimated_profit": Decimal("0"),
                "returns": 0,
                "cancellations": 0,
                "revenue": Decimal("0"),
                "estimated_profit": Decimal("0"),
            }
            for marketplace in marketplaces
        }

    async def _fill_orders(
        self,
        user_id: int,
        start: datetime,
        end: datetime,
        payload: dict[Marketplace, dict[str, Decimal | int]],
    ) -> None:
        if self.session is None:
            return
        result = await self.session.execute(
            select(
                Order.marketplace,
                func.count(func.distinct(Order.id)),
                func.coalesce(func.sum(OrderItem.discounted_price * OrderItem.quantity), 0),
                func.coalesce(func.sum(ProfitSnapshot.profit), 0),
            )
            .join(OrderItem, OrderItem.order_id == Order.id)
            .outerjoin(
                ProfitSnapshot,
                (ProfitSnapshot.order_item_id == OrderItem.id)
                & (ProfitSnapshot.calculation_type == CalculationType.ESTIMATED),
            )
            .where(Order.user_id == user_id)
            .where(Order.order_date >= start)
            .where(Order.order_date < end)
            .group_by(Order.marketplace)
        )
        for marketplace, orders_count, revenue, profit in result.all():
            if marketplace not in payload:
                payload[marketplace] = self._empty_payload([marketplace])[marketplace]
            payload[marketplace]["orders"] = int(orders_count or 0)
            payload[marketplace]["revenue"] = Decimal(str(revenue or 0))
            payload[marketplace]["estimated_profit"] = Decimal(str(profit or 0))

    async def _fill_sales(
        self,
        user_id: int,
        start: datetime,
        end: datetime,
        payload: dict[Marketplace, dict[str, Decimal | int]],
    ) -> None:
        if self.session is None:
            return
        result = await self.session.execute(
            select(
                SalesEvent.marketplace,
                func.coalesce(func.sum(SalesEvent.quantity), 0),
                func.coalesce(func.sum(SalesEvent.amount), 0),
                func.coalesce(func.sum(SalesEvent.estimated_profit), 0),
            )
            .where(SalesEvent.user_id == user_id)
            .where(SalesEvent.event_date >= start)
            .where(SalesEvent.event_date < end)
            .group_by(SalesEvent.marketplace)
        )
        for marketplace, quantity, amount, estimated_profit in result.all():
            if marketplace not in payload:
                payload[marketplace] = self._empty_payload([marketplace])[marketplace]
            payload[marketplace]["sales"] = int(quantity or 0)
            payload[marketplace]["sales_revenue"] = Decimal(str(amount or 0))
            payload[marketplace]["sales_estimated_profit"] = Decimal(str(estimated_profit or 0))

    async def _fill_returns(
        self,
        user_id: int,
        start: datetime,
        end: datetime,
        payload: dict[Marketplace, dict[str, Decimal | int]],
    ) -> None:
        if self.session is None:
            return
        result = await self.session.execute(
            select(ReturnsEvent.marketplace, func.coalesce(func.sum(ReturnsEvent.quantity), 0))
            .where(ReturnsEvent.user_id == user_id)
            .where(ReturnsEvent.event_date >= start)
            .where(ReturnsEvent.event_date < end)
            .group_by(ReturnsEvent.marketplace)
        )
        for marketplace, quantity in result.all():
            if marketplace not in payload:
                payload[marketplace] = self._empty_payload([marketplace])[marketplace]
            payload[marketplace]["returns"] = int(quantity or 0)

    @staticmethod
    def _day_bounds_utc(report_date: date, timezone_name: str) -> tuple[datetime, datetime]:
        try:
            timezone = ZoneInfo(timezone_name)
        except Exception:
            timezone = ZoneInfo("Europe/Moscow")
        start_local = datetime.combine(report_date, time.min, tzinfo=timezone)
        end_local = datetime.combine(report_date, time.max, tzinfo=timezone)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    @staticmethod
    def _marketplace_title(marketplace: str) -> str:
        if marketplace == Marketplace.WB.value:
            return "🟣 Wildberries"
        if marketplace == Marketplace.OZON.value:
            return "🔵 Ozon"
        return marketplace
