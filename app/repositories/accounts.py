"""version: 1.0.0
description: Marketplace account persistence helpers.
updated: 2026-05-14
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount
from app.models.enums import AccountStatus, Marketplace


class MarketplaceAccountRepository:
    """Repository for seller marketplace accounts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_user_accounts(self, user_id: int) -> list[MarketplaceAccount]:
        result = await self.session.execute(
            select(MarketplaceAccount)
            .where(MarketplaceAccount.user_id == user_id)
            .order_by(MarketplaceAccount.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_user_account(self, user_id: int, account_id: int) -> MarketplaceAccount | None:
        result = await self.session.execute(
            select(MarketplaceAccount).where(
                MarketplaceAccount.id == account_id,
                MarketplaceAccount.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: int,
        marketplace: Marketplace,
        name: str,
        encrypted_api_key: str,
        encrypted_client_id: str | None = None,
        status: AccountStatus = AccountStatus.ACTIVE,
    ) -> MarketplaceAccount:
        account = MarketplaceAccount(
            user_id=user_id,
            marketplace=marketplace,
            name=name,
            encrypted_api_key=encrypted_api_key,
            encrypted_client_id=encrypted_client_id,
            status=status,
            is_active=True,
            notification_settings={},
        )
        self.session.add(account)
        await self.session.flush()
        return account

    async def disable(self, account: MarketplaceAccount, error_message: str | None = None) -> None:
        account.is_active = False
        account.status = AccountStatus.DISABLED
        account.last_error_message = error_message
        await self.session.flush()
