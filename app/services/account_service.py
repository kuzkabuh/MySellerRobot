"""version: 1.0.0
description: Marketplace account connection, verification, and token storage service.
updated: 2026-05-14
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.integrations.base import MarketplaceApiError
from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount
from app.models.enums import AccountStatus, Marketplace
from app.repositories.accounts import MarketplaceAccountRepository


class AccountConnectionError(RuntimeError):
    """Raised when marketplace credentials cannot be verified or saved."""


@dataclass(slots=True)
class CreateAccountCommand:
    user_id: int
    marketplace: Marketplace
    name: str
    api_key: str
    client_id: str | None = None


class MarketplaceAccountService:
    """Application service for safe marketplace account management."""

    def __init__(
        self,
        session: AsyncSession,
        cipher: TokenCipher | None = None,
    ) -> None:
        self.session = session
        self.repo = MarketplaceAccountRepository(session)
        self._cipher = cipher

    @property
    def cipher(self) -> TokenCipher:
        if self._cipher is None:
            self._cipher = TokenCipher()
        return self._cipher

    async def connect(self, command: CreateAccountCommand) -> MarketplaceAccount:
        await self._verify_credentials(command)
        try:
            account = await self.repo.create(
                user_id=command.user_id,
                marketplace=command.marketplace,
                name=command.name,
                encrypted_api_key=self.cipher.encrypt(command.api_key),
                encrypted_client_id=(
                    self.cipher.encrypt(command.client_id) if command.client_id else None
                ),
                status=AccountStatus.ACTIVE,
            )
            account.last_success_sync_at = datetime.now(tz=UTC)
            await self.session.commit()
            return account
        except IntegrityError as exc:
            await self.session.rollback()
            raise AccountConnectionError(
                "Кабинет с таким названием уже подключён. Выберите другое название."
            ) from exc

    async def _verify_credentials(self, command: CreateAccountCommand) -> None:
        try:
            if command.marketplace == Marketplace.WB:
                await WildberriesClient(command.api_key).check_connection()
            else:
                if not command.client_id:
                    raise AccountConnectionError("Для Ozon нужен Client ID.")
                await OzonClient(command.client_id, command.api_key).check_connection()
        except MarketplaceApiError as exc:
            if exc.status_code in {401, 403}:
                raise AccountConnectionError(
                    "Маркетплейс отклонил ключ. Проверьте права доступа и значение ключа."
                ) from exc
            raise AccountConnectionError(
                "Не удалось проверить ключ маркетплейса. Попробуйте позже."
            ) from exc

    async def list_accounts(self, user_id: int) -> list[MarketplaceAccount]:
        return await self.repo.list_user_accounts(user_id)

    async def delete_account(self, user_id: int, account_id: int) -> bool:
        account = await self.repo.get_user_account(user_id, account_id)
        if account is None:
            return False
        await self.repo.disable(account)
        await self.session.commit()
        return True
