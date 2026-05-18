"""version: 1.2.0
description: Idempotent upsert helpers for sales, buyouts, and returns events.
updated: 2026-05-17
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import ReturnsEvent, SalesEvent
from app.models.enums import Marketplace, SaleEventType
from app.schemas.sales import NormalizedSaleEvent


class SalesEventRepository:
    """Store sales events without duplicates."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_once(
        self,
        *,
        user_id: int,
        account_id: int,
        marketplace: Marketplace,
        external_event_id: str,
        order_external_id: str | None,
        event_date: datetime,
        quantity: int,
        amount: Decimal,
        raw_payload: dict[str, Any],
        event_type: SaleEventType = SaleEventType.SALE_COMPLETED,
        related_order_id: int | None = None,
        related_order_item_id: int | None = None,
        product_id: int | None = None,
        seller_article: str | None = None,
        marketplace_article: str | None = None,
        expected_payout: Decimal | None = None,
        estimated_profit: Decimal | None = None,
        actual_profit: Decimal | None = None,
    ) -> bool:
        exists = await self.session.execute(
            select(SalesEvent.id).where(
                SalesEvent.marketplace_account_id == account_id,
                SalesEvent.marketplace == marketplace,
                SalesEvent.external_event_id == external_event_id,
            )
        )
        if exists.scalar_one_or_none() is not None:
            return False
        self.session.add(
            SalesEvent(
                user_id=user_id,
                marketplace_account_id=account_id,
                marketplace=marketplace,
                related_order_id=related_order_id,
                related_order_item_id=related_order_item_id,
                external_event_id=external_event_id,
                order_external_id=order_external_id,
                event_type=event_type,
                event_date=event_date,
                product_id=product_id,
                seller_article=seller_article,
                marketplace_article=marketplace_article,
                quantity=quantity,
                amount=amount,
                expected_payout=expected_payout,
                estimated_profit=estimated_profit,
                actual_profit=actual_profit,
                raw_payload=raw_payload,
            )
        )
        await self.session.flush()
        return True

    async def upsert_normalized(
        self,
        *,
        user_id: int,
        account_id: int,
        event: NormalizedSaleEvent,
        related_order_id: int | None = None,
        related_order_item_id: int | None = None,
        product_id: int | None = None,
        estimated_profit: Decimal | None = None,
    ) -> tuple[SalesEvent, bool]:
        existing = await self.session.execute(
            select(SalesEvent).where(
                SalesEvent.marketplace_account_id == account_id,
                SalesEvent.marketplace == event.marketplace,
                SalesEvent.external_event_id == event.external_event_id,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = SalesEvent(
                user_id=user_id,
                marketplace_account_id=account_id,
                marketplace=event.marketplace,
                related_order_id=related_order_id,
                related_order_item_id=related_order_item_id,
                product_id=product_id,
                external_event_id=event.external_event_id,
                order_external_id=event.order_external_id,
                event_type=event.event_type,
                event_date=event.event_date,
                seller_article=event.seller_article,
                marketplace_article=event.marketplace_article,
                quantity=event.quantity,
                amount=event.amount,
                expected_payout=event.expected_payout,
                estimated_profit=estimated_profit,
                raw_payload=event.raw_payload,
            )
            self.session.add(row)
            await self.session.flush()
            return row, True
        row.related_order_id = related_order_id or row.related_order_id
        row.related_order_item_id = related_order_item_id or row.related_order_item_id
        row.product_id = product_id or row.product_id
        row.order_external_id = event.order_external_id or row.order_external_id
        row.event_type = event.event_type
        row.event_date = event.event_date
        row.seller_article = event.seller_article or row.seller_article
        row.marketplace_article = event.marketplace_article or row.marketplace_article
        row.quantity = event.quantity
        row.amount = event.amount
        row.expected_payout = event.expected_payout
        row.estimated_profit = (
            estimated_profit if estimated_profit is not None else row.estimated_profit
        )
        row.raw_payload = event.raw_payload
        await self.session.flush()
        return row, False

    async def pending_notifications(self, limit: int = 100) -> list[SalesEvent]:
        result = await self.session.execute(
            select(SalesEvent)
            .where(SalesEvent.notification_sent_at.is_(None))
            .order_by(SalesEvent.event_date.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_notified(self, row_id: int, notified_at: datetime | None = None) -> None:
        await self.session.execute(
            update(SalesEvent)
            .where(SalesEvent.id == row_id)
            .values(notification_sent_at=notified_at or datetime.now(tz=UTC))
        )


class ReturnsEventRepository:
    """Store returns events without duplicates."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        user_id: int,
        account_id: int,
        marketplace: Marketplace,
        external_event_id: str,
        order_external_id: str | None,
        event_date: datetime,
        quantity: int,
        amount: Decimal,
        reason: str | None,
        raw_payload: dict[str, Any],
    ) -> tuple[ReturnsEvent, bool]:
        existing = await self.session.execute(
            select(ReturnsEvent).where(
                ReturnsEvent.marketplace_account_id == account_id,
                ReturnsEvent.marketplace == marketplace,
                ReturnsEvent.external_event_id == external_event_id,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = ReturnsEvent(
                user_id=user_id,
                marketplace_account_id=account_id,
                marketplace=marketplace,
                external_event_id=external_event_id,
                order_external_id=order_external_id,
                event_date=event_date,
                quantity=quantity,
                amount=amount,
                reason=reason,
                raw_payload=raw_payload,
            )
            self.session.add(row)
            await self.session.flush()
            return row, True
        row.order_external_id = order_external_id or row.order_external_id
        row.event_date = event_date
        row.quantity = quantity
        row.amount = amount
        row.reason = reason or row.reason
        row.raw_payload = raw_payload
        await self.session.flush()
        return row, False

    async def add_once(
        self,
        *,
        user_id: int,
        account_id: int,
        marketplace: Marketplace,
        external_event_id: str,
        order_external_id: str | None,
        event_date: datetime,
        quantity: int,
        amount: Decimal,
        reason: str | None,
        raw_payload: dict[str, Any],
    ) -> bool:
        exists = await self.session.execute(
            select(ReturnsEvent.id).where(
                ReturnsEvent.marketplace_account_id == account_id,
                ReturnsEvent.marketplace == marketplace,
                ReturnsEvent.external_event_id == external_event_id,
            )
        )
        if exists.scalar_one_or_none() is not None:
            return False
        self.session.add(
            ReturnsEvent(
                user_id=user_id,
                marketplace_account_id=account_id,
                marketplace=marketplace,
                external_event_id=external_event_id,
                order_external_id=order_external_id,
                event_date=event_date,
                quantity=quantity,
                amount=amount,
                reason=reason,
                raw_payload=raw_payload,
            )
        )
        await self.session.flush()
        return True

    async def pending_notifications(self, limit: int = 100) -> list[ReturnsEvent]:
        result = await self.session.execute(
            select(ReturnsEvent)
            .where(ReturnsEvent.notification_sent_at.is_(None))
            .order_by(ReturnsEvent.event_date.asc(), ReturnsEvent.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_notified(self, row_id: int, notified_at: datetime | None = None) -> None:
        await self.session.execute(
            update(ReturnsEvent)
            .where(ReturnsEvent.id == row_id)
            .values(notification_sent_at=notified_at or datetime.now(tz=UTC))
        )
