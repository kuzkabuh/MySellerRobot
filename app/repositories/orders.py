"""version: 1.0.0
description: Order persistence and idempotency helpers.
updated: 2026-05-14
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import Order, OrderItem, ProfitSnapshot
from app.models.enums import CalculationType, Marketplace
from app.schemas.orders import NormalizedOrder


class OrderRepository:
    """Repository for normalized marketplace orders."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists(self, account_id: int, normalized: NormalizedOrder) -> bool:
        result = await self.session.execute(
            select(Order.id).where(
                Order.marketplace_account_id == account_id,
                Order.marketplace == normalized.marketplace,
                Order.order_external_id == normalized.order_external_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def create(
        self,
        user_id: int,
        account_id: int,
        normalized: NormalizedOrder,
    ) -> Order:
        order = Order(
            user_id=user_id,
            marketplace_account_id=account_id,
            marketplace=normalized.marketplace,
            order_external_id=normalized.order_external_id,
            posting_number=normalized.posting_number,
            assembly_id=normalized.assembly_id,
            srid=normalized.srid,
            order_date=normalized.order_date,
            event_received_at=datetime.now(tz=UTC),
            sale_model=normalized.sale_model,
            status=normalized.status,
            warehouse=normalized.warehouse,
            deadline_at=normalized.deadline_at,
            raw_payload=normalized.raw_payload,
        )
        self.session.add(order)
        await self.session.flush()
        for item in normalized.items:
            self.session.add(
                OrderItem(
                    order_id=order.id,
                    seller_article=item.seller_article,
                    marketplace_article=item.marketplace_article,
                    title=item.title,
                    quantity=item.quantity,
                    buyer_price=item.buyer_price,
                    seller_price=item.seller_price,
                    discounted_price=item.discounted_price,
                    payout_amount_estimated=item.payout_amount_estimated,
                    commission_estimated=item.commission_estimated,
                    logistics_estimated=item.logistics_estimated,
                    other_marketplace_expenses_estimated=item.other_marketplace_expenses_estimated,
                )
            )
        await self.session.flush()
        return order

    async def get_with_items(self, order_id: int) -> Order | None:
        result = await self.session.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def daily_marketplace_summary(
        self,
        user_id: int,
        report_date: date,
    ) -> dict[str, dict[str, Decimal | int]]:
        start = datetime.combine(report_date, datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(report_date, datetime.max.time(), tzinfo=UTC)
        query: Select[tuple[Marketplace, int, Decimal, Decimal]] = (
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
            .where(Order.order_date <= end)
            .group_by(Order.marketplace)
        )
        rows = await self.session.execute(query)
        summary: dict[str, dict[str, Decimal | int]] = {}
        for marketplace, orders_count, revenue, profit in rows:
            summary[marketplace.value] = {
                "orders": orders_count,
                "sales": 0,
                "returns": 0,
                "cancellations": 0,
                "revenue": Decimal(str(revenue or 0)),
                "estimated_profit": Decimal(str(profit or 0)),
            }
        return summary

    async def fbs_deadline_risks(
        self,
        *,
        user_id: int | None = None,
        minutes_before_deadline: int = 120,
    ) -> list[Order]:
        now = datetime.now(tz=UTC)
        deadline_to = now + timedelta(minutes=minutes_before_deadline)
        query = (
            select(Order)
            .where(Order.deadline_at.is_not(None))
            .where(Order.deadline_at <= deadline_to)
            .where(Order.status.not_in(["delivered", "cancelled", "canceled", "completed"]))
            .order_by(Order.deadline_at.asc())
        )
        if user_id is not None:
            query = query.where(Order.user_id == user_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())
