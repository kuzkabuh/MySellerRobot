"""version: 1.0.0
description: Support ticket management service.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import SupportTicket, SupportTicketEvent, User

logger = logging.getLogger(__name__)

SUPPORT_STATUSES = {"new", "in_progress", "answered", "closed", "rejected"}
SUPPORT_PRIORITIES = {"low", "normal", "high", "urgent"}


@dataclass
class TicketData:
    id: int
    user_id: int
    telegram_id: int | None
    username: str | None
    full_name: str | None
    subject: str
    message: str
    status: str
    priority: str
    category: str | None
    admin_comment: str | None
    assigned_admin_id: int | None
    admin_response: str | None
    created_at: datetime
    updated_at: datetime
    responded_at: datetime | None
    closed_at: datetime | None
    resolved_at: datetime | None


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
        user = await self.session.get(User, user_id)
        full_name = None
        telegram_id = None
        username = None
        if user is not None:
            telegram_id = user.telegram_id
            username = user.username
            full_name = " ".join(part for part in (user.first_name, user.last_name) if part) or None
        ticket = SupportTicket(
            user_id=user_id,
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
            subject=subject[:255],
            message=message,
            category=category,
            priority=priority,
            status="new",
        )
        self.session.add(ticket)
        await self.session.flush()
        self._add_event(
            ticket.id,
            actor_type="user",
            actor_id=user_id,
            action="ticket_created",
            new_value=ticket.message,
        )
        await self.session.commit()
        await self.session.refresh(ticket)
        logger.info("support_ticket_created", extra={"ticket_id": ticket.id, "user_id": user_id})
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
            self._to_data(t)
            for t in rows
        ]

    async def get_ticket(self, ticket_id: int, user_id: int | None = None) -> TicketData | None:
        stmt = select(SupportTicket).where(SupportTicket.id == ticket_id)
        if user_id is not None:
            stmt = stmt.where(SupportTicket.user_id == user_id)
        result = await self.session.execute(stmt)
        t = result.scalar_one_or_none()
        if t is None:
            return None
        return self._to_data(t)

    async def get_ticket_model(self, ticket_id: int) -> SupportTicket | None:
        return await self.session.get(SupportTicket, ticket_id)

    async def list_tickets(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        search: str | None = None,
        limit: int = 200,
    ) -> list[SupportTicket]:
        stmt = select(SupportTicket).order_by(SupportTicket.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(SupportTicket.status == status)
        if priority:
            stmt = stmt.where(SupportTicket.priority == priority)
        if search:
            term = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    SupportTicket.message.ilike(term),
                    SupportTicket.subject.ilike(term),
                    SupportTicket.full_name.ilike(term),
                    SupportTicket.username.ilike(term),
                    cast(SupportTicket.telegram_id, String).ilike(term),
                )
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def respond_ticket(
        self, ticket_id: int, admin_id: int, response: str
    ) -> bool:
        ticket = await self.session.get(SupportTicket, ticket_id)
        if ticket is None:
            return False
        old_value = ticket.status
        ticket.admin_response = response
        ticket.responded_at = datetime.now(UTC)
        ticket.responded_by = admin_id
        ticket.status = "answered"
        self._add_event(
            ticket.id,
            actor_type="admin",
            actor_id=admin_id,
            action="admin_reply_sent",
            old_value=old_value,
            new_value="answered",
            comment=response,
        )
        await self.session.commit()
        logger.info(
            "support_ticket_answered",
            extra={"ticket_id": ticket_id, "admin_id": admin_id},
        )
        return True

    async def close_ticket(self, ticket_id: int, admin_id: int | None = None) -> bool:
        ticket = await self.session.get(SupportTicket, ticket_id)
        if ticket is None:
            return False
        old_value = ticket.status
        ticket.status = "closed"
        ticket.closed_at = datetime.now(UTC)
        ticket.resolved_at = ticket.closed_at
        self._add_event(
            ticket.id,
            actor_type="admin" if admin_id else "system",
            actor_id=admin_id,
            action="ticket_closed",
            old_value=old_value,
            new_value="closed",
        )
        await self.session.commit()
        return True

    async def update_admin_fields(
        self,
        ticket_id: int,
        *,
        admin_id: int,
        status: str | None = None,
        priority: str | None = None,
        admin_comment: str | None = None,
        assigned_admin_id: int | None = None,
    ) -> SupportTicket | None:
        ticket = await self.session.get(SupportTicket, ticket_id)
        if ticket is None:
            return None
        if status and status in SUPPORT_STATUSES and status != ticket.status:
            old_value = ticket.status
            ticket.status = status
            if status in {"closed", "rejected"}:
                ticket.resolved_at = datetime.now(UTC)
                ticket.closed_at = ticket.resolved_at
            self._add_event(
                ticket.id,
                actor_type="admin",
                actor_id=admin_id,
                action="status_changed",
                old_value=old_value,
                new_value=status,
            )
        if priority and priority in SUPPORT_PRIORITIES and priority != ticket.priority:
            old_value = ticket.priority
            ticket.priority = priority
            self._add_event(
                ticket.id,
                actor_type="admin",
                actor_id=admin_id,
                action="priority_changed",
                old_value=old_value,
                new_value=priority,
            )
        if admin_comment is not None and admin_comment != (ticket.admin_comment or ""):
            ticket.admin_comment = admin_comment
            self._add_event(
                ticket.id,
                actor_type="admin",
                actor_id=admin_id,
                action="admin_comment_updated",
                comment=admin_comment,
            )
        if assigned_admin_id is not None and assigned_admin_id != ticket.assigned_admin_id:
            old_value = str(ticket.assigned_admin_id or "")
            ticket.assigned_admin_id = assigned_admin_id
            self._add_event(
                ticket.id,
                actor_type="admin",
                actor_id=admin_id,
                action="ticket_assigned",
                old_value=old_value,
                new_value=str(assigned_admin_id),
            )
        await self.session.commit()
        logger.info(
            "support_ticket_admin_fields_updated",
            extra={"ticket_id": ticket_id, "admin_id": admin_id},
        )
        return ticket

    async def get_events(self, ticket_id: int) -> list[SupportTicketEvent]:
        result = await self.session.execute(
            select(SupportTicketEvent)
            .where(SupportTicketEvent.ticket_id == ticket_id)
            .order_by(SupportTicketEvent.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_open_tickets(self, limit: int = 100) -> list[TicketData]:
        stmt = (
            select(SupportTicket)
            .where(SupportTicket.status.in_(["new", "in_progress", "open", "responded"]))
            .order_by(SupportTicket.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            self._to_data(t)
            for t in rows
        ]

    def _add_event(
        self,
        ticket_id: int,
        *,
        actor_type: str,
        actor_id: int | None,
        action: str,
        old_value: str | None = None,
        new_value: str | None = None,
        comment: str | None = None,
    ) -> None:
        self.session.add(
            SupportTicketEvent(
                ticket_id=ticket_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                old_value=old_value,
                new_value=new_value,
                comment=comment,
            )
        )

    @staticmethod
    def _to_data(t: SupportTicket) -> TicketData:
        return TicketData(
            id=t.id,
            user_id=t.user_id,
            telegram_id=t.telegram_id,
            username=t.username,
            full_name=t.full_name,
            subject=t.subject,
            message=t.message,
            status=t.status,
            priority=t.priority,
            category=t.category,
            admin_comment=t.admin_comment,
            assigned_admin_id=t.assigned_admin_id,
            admin_response=t.admin_response,
            created_at=t.created_at,
            updated_at=t.updated_at,
            responded_at=t.responded_at,
            closed_at=t.closed_at,
            resolved_at=t.resolved_at,
        )


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
    "new": "Новое",
    "in_progress": "В работе",
    "answered": "Дан ответ",
    "closed": "Закрыт",
    "rejected": "Отклонено",
    "open": "Открыт",
    "responded": "Отвечен",
}
