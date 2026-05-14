"""version: 1.0.0
description: Basic web cabinet dashboard aggregation service.
updated: 2026-05-14
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Order, OrderItem, ProfitSnapshot, ReturnsEvent, SalesEvent
from app.models.enums import CalculationType


@dataclass(slots=True)
class DashboardKpi:
    revenue_today: Decimal
    orders_today: int
    sales_today: int
    estimated_profit_today: Decimal
    returns_today: int
    average_margin_today: Decimal
    loss_orders_today: int


class WebDashboardService:
    """Build compact dashboard data for the web cabinet home page."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def today_kpi(self, user_id: int) -> DashboardKpi:
        start = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        order_result = await self.session.execute(
            select(
                func.count(func.distinct(Order.id)),
                func.coalesce(func.sum(OrderItem.discounted_price * OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.profit_estimated), 0),
                func.coalesce(func.avg(OrderItem.margin_percent_estimated), 0),
                func.count(func.distinct(Order.id)).filter(OrderItem.profit_estimated < 0),
            )
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(Order.user_id == user_id)
            .where(Order.order_date >= start)
        )
        orders, revenue, profit, margin, loss_orders = order_result.one()
        sales_result = await self.session.execute(
            select(func.coalesce(func.sum(SalesEvent.quantity), 0))
            .where(SalesEvent.user_id == user_id)
            .where(SalesEvent.event_date >= start)
        )
        returns_result = await self.session.execute(
            select(func.coalesce(func.sum(ReturnsEvent.quantity), 0))
            .where(ReturnsEvent.user_id == user_id)
            .where(ReturnsEvent.event_date >= start)
        )
        return DashboardKpi(
            revenue_today=Decimal(str(revenue or 0)),
            orders_today=int(orders or 0),
            sales_today=int(sales_result.scalar_one() or 0),
            estimated_profit_today=Decimal(str(profit or 0)),
            returns_today=int(returns_result.scalar_one() or 0),
            average_margin_today=Decimal(str(margin or 0)),
            loss_orders_today=int(loss_orders or 0),
        )

    async def actual_profit_total(self, user_id: int) -> Decimal:
        result = await self.session.execute(
            select(func.coalesce(func.sum(ProfitSnapshot.profit), 0))
            .join(OrderItem, OrderItem.id == ProfitSnapshot.order_item_id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.user_id == user_id)
            .where(ProfitSnapshot.calculation_type == CalculationType.ACTUAL)
        )
        return Decimal(str(result.scalar_one() or 0))
