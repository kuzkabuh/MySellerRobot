"""version: 1.0.0
description: User persistence helpers.
updated: 2026-05-14
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User


class UserRepository:
    """Repository for Telegram users."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
    ) -> User:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            user.username = username
            user.first_name = first_name
            return user
        user = User(telegram_id=telegram_id, username=username, first_name=first_name)
        self.session.add(user)
        await self.session.flush()
        return user
