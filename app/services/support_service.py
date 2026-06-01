"""version: 1.0.0
description: Support ticket management service.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import SupportTicket

logger = logging.getLogger(__name__)


@dataclass
class TicketData:
    id: int
    user_id: int
    subject: str
    message: str
    status: str
    priority: str
    category: str | None
    admin_response: str | None
    created_at: datetime
    responded_at: datetime | None
    closed_at: datetime | None


class SupportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_ticket(
        self,
        user_id: int,
        subject: str,
        message: str,
        category: str | None = None,
        priority: str = "normal",
    ) -> SupportTicket:
        ticket = SupportTicket(
            user_id=user_id,
            subject=subject[:255],
            message=message,
            category=category,
            priority=priority,
            status="open",
        )
        self.session.add(ticket)
        await self.session.commit()
        await self.session.refresh(ticket)
        return ticket

    async def get_user_tickets(
        self, user_id: int, status: str | None = None, limit: int = 50
    ) -> list[TicketData]:
        stmt = (
            select(SupportTicket)
            .where(SupportTicket.user_id == user_id)
        )
        if status:
            stmt = stmt.where(SupportTicket.status == status)
        stmt = stmt.order_by(SupportTicket.created_at.desc()).limit(limit)

        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            TicketData(
                id=t.id,
                user_id=t.user_id,
                subject=t.subject,
                message=t.message,
                status=t.status,
                priority=t.priority,
                category=t.category,
                admin_response=t.admin_response,
                created_at=t.created_at,
                responded_at=t.responded_at,
                closed_at=t.closed_at,
            )
            for t in rows
        ]

    async def get_ticket(self, ticket_id: int, user_id: int) -> TicketData | None:
        stmt = select(SupportTicket).where(
            SupportTicket.id == ticket_id,
            SupportTicket.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        t = result.scalar_one_or_none()
        if t is None:
            return None
        return TicketData(
            id=t.id,
            user_id=t.user_id,
            subject=t.subject,
            message=t.message,
            status=t.status,
            priority=t.priority,
            category=t.category,
            admin_response=t.admin_response,
            created_at=t.created_at,
            responded_at=t.responded_at,
            closed_at=t.closed_at,
        )

    async def respond_ticket(
        self, ticket_id: int, admin_id: int, response: str
    ) -> bool:
        ticket = await self.session.get(SupportTicket, ticket_id)
        if ticket is None:
            return False
        ticket.admin_response = response
        ticket.responded_at = datetime.now(UTC)
        ticket.responded_by = admin_id
        ticket.status = "responded"
        await self.session.commit()
        return True

    async def close_ticket(self, ticket_id: int) -> bool:
        ticket = await self.session.get(SupportTicket, ticket_id)
        if ticket is None:
            return False
        ticket.status = "closed"
        ticket.closed_at = datetime.now(UTC)
        await self.session.commit()
        return True

    async def get_open_tickets(self, limit: int = 100) -> list[TicketData]:
        stmt = (
            select(SupportTicket)
            .where(SupportTicket.status.in_(["open", "responded"]))
            .order_by(SupportTicket.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            TicketData(
                id=t.id,
                user_id=t.user_id,
                subject=t.subject,
                message=t.message,
                status=t.status,
                priority=t.priority,
                category=t.category,
                admin_response=t.admin_response,
                created_at=t.created_at,
                responded_at=t.responded_at,
                closed_at=t.closed_at,
            )
            for t in rows
        ]


TICKET_CATEGORIES = [
    ("general", "Общий вопрос"),
    ("technical", "Техническая проблема"),
    ("billing", "Оплата и тарифы"),
    ("api_keys", "API-ключи и подключение"),
    ("data", "Проблема с данными"),
    ("feature", "Запрос функции"),
    ("bug", "Ошибка в работе"),
]

TICKET_PRIORITY = [
    ("low", "Низкий"),
    ("normal", "Обычный"),
    ("high", "Высокий"),
    ("urgent", "Срочный"),
]

TICKET_STATUS_LABELS = {
    "open": "Открыт",
    "responded": "Отвечен",
    "closed": "Закрыт",
}
