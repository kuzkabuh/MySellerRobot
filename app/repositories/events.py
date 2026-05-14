"""version: 1.0.0
description: Idempotent persistence helpers for sales and returns historical events.
updated: 2026-05-14
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import ReturnsEvent, SalesEvent
from app.models.enums import Marketplace


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
                external_event_id=external_event_id,
                order_external_id=order_external_id,
                event_date=event_date,
                quantity=quantity,
                amount=amount,
                raw_payload=raw_payload,
            )
        )
        await self.session.flush()
        return True


class ReturnsEventRepository:
    """Store returns events without duplicates."""

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
