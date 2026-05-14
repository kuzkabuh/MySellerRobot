"""version: 1.0.0
description: Persistence helpers for one-time web login tokens and web sessions.
updated: 2026-05-14
"""

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import OneTimeLoginToken, User, UserWebSession


class WebAuthRepository:
    """Repository for web cabinet authentication state."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_login_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
    ) -> OneTimeLoginToken:
        row = OneTimeLoginToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_active_login_token(self, token_hash: str) -> OneTimeLoginToken | None:
        now = datetime.now(tz=UTC)
        result = await self.session.execute(
            select(OneTimeLoginToken)
            .where(OneTimeLoginToken.token_hash == token_hash)
            .where(OneTimeLoginToken.used_at.is_(None))
            .where(OneTimeLoginToken.expires_at > now)
        )
        return result.scalar_one_or_none()

    async def mark_login_token_used(
        self,
        token: OneTimeLoginToken,
        *,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        token.used_at = datetime.now(tz=UTC)
        token.ip_address = ip_address
        token.user_agent = user_agent[:512] if user_agent else None
        await self.session.flush()

    async def create_web_session(
        self,
        *,
        user_id: int,
        session_hash: str,
        expires_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> UserWebSession:
        row = UserWebSession(
            user_id=user_id,
            session_hash=session_hash,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent[:512] if user_agent else None,
            last_seen_at=datetime.now(tz=UTC),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_active_session_user(self, session_hash: str) -> User | None:
        now = datetime.now(tz=UTC)
        statement: Select[tuple[UserWebSession, User]] = (
            select(UserWebSession, User)
            .join(User, User.id == UserWebSession.user_id)
            .where(UserWebSession.session_hash == session_hash)
            .where(UserWebSession.revoked_at.is_(None))
            .where(UserWebSession.expires_at > now)
        )
        result = await self.session.execute(statement)
        row = result.first()
        if row is None:
            return None
        web_session, user = row
        web_session.last_seen_at = now
        await self.session.flush()
        return cast(User, user)

    async def revoke_session(self, session_hash: str) -> bool:
        result = await self.session.execute(
            select(UserWebSession).where(UserWebSession.session_hash == session_hash)
        )
        row = result.scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = datetime.now(tz=UTC)
        await self.session.flush()
        return True
