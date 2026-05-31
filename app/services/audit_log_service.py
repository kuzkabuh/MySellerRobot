"""Audit log creation and retrieval."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import AuditLog


class AuditLogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        action: str,
        *,
        user_id: int | None = None,
        actor_user_id: int | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        details: Mapping[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        row = AuditLog(
            user_id=user_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=dict(details) if details is not None else None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def recent(
        self,
        *,
        user_id: int | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditLog]:
        query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        if user_id is not None:
            query = query.where(AuditLog.user_id == user_id)
        if action:
            query = query.where(AuditLog.action == action)
        result = await self.session.execute(query)
        return list(result.scalars().all())
