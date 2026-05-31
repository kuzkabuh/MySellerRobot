"""Notification event admin service."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import NotificationEvent

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_PERMANENT_FAILED = "permanent_failed"


class NotificationEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int | None,
        telegram_id: int | None,
        notification_type: str,
        subject: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> NotificationEvent:
        event = NotificationEvent(
            user_id=user_id,
            telegram_id=telegram_id,
            notification_type=notification_type,
            status=STATUS_PENDING,
            subject=subject,
            payload=dict(payload) if payload is not None else None,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def mark_sent(self, event: NotificationEvent) -> NotificationEvent:
        event.status = STATUS_SENT
        event.sent_at = datetime.now(tz=UTC)
        event.error_message = None
        await self.session.flush()
        return event

    async def mark_failed(
        self,
        event: NotificationEvent,
        error: str,
        *,
        permanent: bool = False,
    ) -> NotificationEvent:
        event.attempts += 1
        event.error_message = error[:2000]
        event.status = STATUS_PERMANENT_FAILED if permanent else STATUS_FAILED
        if permanent:
            event.permanent_failed_at = datetime.now(tz=UTC)
        await self.session.flush()
        return event

    async def retry(self, event_id: int) -> NotificationEvent | None:
        event = await self.session.get(NotificationEvent, event_id)
        if event is None:
            return None
        event.status = STATUS_PENDING
        event.next_retry_at = None
        event.error_message = None
        await self.session.flush()
        return event

    async def recent(
        self,
        *,
        status: str | None = None,
        user_id: int | None = None,
        limit: int = 100,
    ) -> list[NotificationEvent]:
        query = select(NotificationEvent).order_by(NotificationEvent.created_at.desc()).limit(limit)
        if status:
            query = query.where(NotificationEvent.status == status)
        if user_id is not None:
            query = query.where(NotificationEvent.user_id == user_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())
