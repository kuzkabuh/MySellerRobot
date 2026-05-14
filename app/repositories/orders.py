"""version: 1.0.0
description: Order persistence and idempotency helpers.
updated: 2026-05-14
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import FboDigestQueue, Order, OrderItem, ProfitSnapshot
from app.models.enums import CalculationType, FboNotificationMode, Marketplace
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
            fulfillment_type=normalized.fulfillment_type,
            urgency_type=normalized.urgency_type,
            source_event_type=normalized.source_event_type,
            status=normalized.status,
            raw_status=normalized.raw_status,
            normalized_status=normalized.normalized_status,
            warehouse=normalized.warehouse,
            warehouse_type=normalized.warehouse_type,
            delivery_schema=normalized.delivery_schema,
            deadline_at=normalized.deadline_at,
            processing_deadline_at=normalized.processing_deadline_at,
            requires_seller_action=normalized.requires_seller_action,
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

    async def upsert(
        self,
        user_id: int,
        account_id: int,
        normalized: NormalizedOrder,
    ) -> tuple[Order, bool]:
        existing = await self._get_existing(account_id, normalized)
        if existing is None:
            return await self.create(user_id, account_id, normalized), True
        self._apply_order(existing, normalized)
        await self.session.flush()
        if not existing.items:
            for item in normalized.items:
                self.session.add(
                    OrderItem(
                        order_id=existing.id,
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
                        other_marketplace_expenses_estimated=(
                            item.other_marketplace_expenses_estimated
                        ),
                    )
                )
        else:
            for persisted, incoming in zip(existing.items, normalized.items, strict=False):
                persisted.seller_article = incoming.seller_article or persisted.seller_article
                persisted.marketplace_article = (
                    incoming.marketplace_article or persisted.marketplace_article
                )
                persisted.title = incoming.title or persisted.title
                persisted.quantity = incoming.quantity
                persisted.buyer_price = incoming.buyer_price
                persisted.seller_price = incoming.seller_price
                persisted.discounted_price = incoming.discounted_price
                persisted.payout_amount_estimated = incoming.payout_amount_estimated
                persisted.commission_estimated = incoming.commission_estimated
                persisted.logistics_estimated = incoming.logistics_estimated
                persisted.other_marketplace_expenses_estimated = (
                    incoming.other_marketplace_expenses_estimated
                )
        await self.session.flush()
        return existing, False

    async def _get_existing(
        self,
        account_id: int,
        normalized: NormalizedOrder,
    ) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(
                Order.marketplace_account_id == account_id,
                Order.marketplace == normalized.marketplace,
                Order.order_external_id == normalized.order_external_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _apply_order(order: Order, normalized: NormalizedOrder) -> None:
        order.posting_number = normalized.posting_number or order.posting_number
        order.assembly_id = normalized.assembly_id or order.assembly_id
        order.srid = normalized.srid or order.srid
        order.order_date = normalized.order_date
        order.sale_model = normalized.sale_model
        order.fulfillment_type = normalized.fulfillment_type
        order.urgency_type = normalized.urgency_type
        order.source_event_type = normalized.source_event_type
        order.status = normalized.status
        order.raw_status = normalized.raw_status
        order.normalized_status = normalized.normalized_status
        order.warehouse = normalized.warehouse
        order.warehouse_type = normalized.warehouse_type
        order.delivery_schema = normalized.delivery_schema
        order.deadline_at = normalized.deadline_at
        order.processing_deadline_at = normalized.processing_deadline_at
        order.requires_seller_action = normalized.requires_seller_action
        order.raw_payload = normalized.raw_payload

    async def mark_notified(self, order_id: int, notified_at: datetime | None = None) -> None:
        timestamp = notified_at or datetime.now(tz=UTC)
        await self.session.execute(
            update(Order)
            .where(Order.id == order_id)
            .values(
                first_notified_at=func.coalesce(Order.first_notified_at, timestamp),
                last_notified_at=timestamp,
            )
        )

    async def order_totals(self, order_id: int) -> tuple[Decimal, Decimal]:
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(OrderItem.discounted_price * OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.profit_estimated), 0),
            ).where(OrderItem.order_id == order_id)
        )
        revenue, profit = result.one()
        return Decimal(str(revenue or 0)), Decimal(str(profit or 0))

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
            .where(Order.requires_seller_action.is_(True))
            .where(Order.processing_deadline_at.is_not(None))
            .where(Order.processing_deadline_at <= deadline_to)
            .where(Order.status.not_in(["delivered", "cancelled", "canceled", "completed"]))
            .order_by(Order.processing_deadline_at.asc())
        )
        if user_id is not None:
            query = query.where(Order.user_id == user_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())


class FboDigestQueueRepository:
    """Repository for idempotent FBO digest queue rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_once(
        self,
        *,
        user_id: int,
        order_id: int,
        marketplace: Marketplace,
        revenue: Decimal,
        estimated_profit: Decimal,
        mode: FboNotificationMode,
    ) -> bool:
        exists = await self.session.execute(
            select(FboDigestQueue.id).where(
                FboDigestQueue.user_id == user_id,
                FboDigestQueue.order_id == order_id,
            )
        )
        if exists.scalar_one_or_none() is not None:
            return False
        self.session.add(
            FboDigestQueue(
                user_id=user_id,
                order_id=order_id,
                marketplace=marketplace,
                revenue=revenue,
                estimated_profit=estimated_profit,
                queued_at=datetime.now(tz=UTC),
                sent_at=None,
                mode=mode,
            )
        )
        await self.session.flush()
        return True

    async def pending_digest_rows(self) -> list[FboDigestQueue]:
        result = await self.session.execute(
            select(FboDigestQueue)
            .where(FboDigestQueue.sent_at.is_(None))
            .where(FboDigestQueue.mode == FboNotificationMode.DIGEST_30_MIN)
            .order_by(FboDigestQueue.user_id, FboDigestQueue.queued_at)
        )
        return list(result.scalars().all())

    async def mark_sent(self, row_ids: list[int], sent_at: datetime | None = None) -> None:
        if not row_ids:
            return
        await self.session.execute(
            update(FboDigestQueue)
            .where(FboDigestQueue.id.in_(row_ids))
            .values(sent_at=sent_at or datetime.now(tz=UTC))
        )
