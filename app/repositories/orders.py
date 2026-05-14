"""version: 1.0.0
description: Order persistence and idempotency helpers.
updated: 2026-05-14
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Order, OrderItem
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
