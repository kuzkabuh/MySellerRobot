"""Seller profile and balance refresh service."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, MarketplaceApiError, RateLimitError
from app.core.security import TokenCipher
from app.integrations.wb import WildberriesClient
from app.models.domain import AccountBalanceSnapshot, MarketplaceAccount
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SellerCabinetSnapshot:
    account: MarketplaceAccount
    balance: AccountBalanceSnapshot | None = None
    balance_error: str | None = None


class AccountProfileService:
    """Refresh and read seller profile data without excessive finance calls."""

    balance_ttl = timedelta(minutes=30)

    def __init__(self, session: AsyncSession, cipher: TokenCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()

    async def refresh_wb_account(
        self,
        account: MarketplaceAccount,
        *,
        force_balance: bool = False,
    ) -> SellerCabinetSnapshot:
        if account.marketplace != Marketplace.WB:
            return SellerCabinetSnapshot(account=account)
        client = WildberriesClient(self.cipher.decrypt(account.encrypted_api_key))
        try:
            info = await client.get_seller_info()
            _apply_wb_seller_info(account, info)
        except Exception:
            logger.exception("wb_seller_info_refresh_failed", extra={"account_id": account.id})

        balance = await self.latest_balance(account.id)
        balance_is_stale = (
            balance is None
            or balance.fetched_at < datetime.now(tz=UTC) - self.balance_ttl
        )
        if force_balance or balance_is_stale:
            balance = await self._refresh_wb_balance(account, client)
        await self.session.flush()
        return SellerCabinetSnapshot(account=account, balance=balance)

    async def latest_balance(self, account_id: int) -> AccountBalanceSnapshot | None:
        result = await self.session.execute(
            select(AccountBalanceSnapshot)
            .where(AccountBalanceSnapshot.marketplace_account_id == account_id)
            .order_by(AccountBalanceSnapshot.fetched_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _refresh_wb_balance(
        self,
        account: MarketplaceAccount,
        client: WildberriesClient,
    ) -> AccountBalanceSnapshot:
        now = datetime.now(tz=UTC)
        try:
            payload = await client.get_account_balance()
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            snapshot = AccountBalanceSnapshot(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                marketplace=Marketplace.WB,
                currency=str(data.get("currency") or "RUB"),
                current=_decimal_or_none(data.get("current")),
                for_withdraw=_decimal_or_none(data.get("for_withdraw") or data.get("forWithdraw")),
                status="OK",
                fetched_at=now,
                raw_payload=payload,
            )
        except (AuthenticationError, RateLimitError, MarketplaceApiError) as exc:
            status = "NO_ACCESS" if isinstance(exc, AuthenticationError) else "API_ERROR"
            if isinstance(exc, RateLimitError):
                status = "RATE_LIMITED"
            snapshot = AccountBalanceSnapshot(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                marketplace=Marketplace.WB,
                currency="RUB",
                current=None,
                for_withdraw=None,
                status=status,
                error_message=str(exc)[:1000],
                fetched_at=now,
                raw_payload={},
            )
            logger.warning(
                "wb_balance_refresh_failed",
                extra={"account_id": account.id, "status": status},
            )
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot


def _apply_wb_seller_info(account: MarketplaceAccount, payload: dict[str, Any]) -> None:
    external_id = str(payload.get("sid") or payload.get("supplierID") or "")
    seller_name = str(payload.get("tradeMark") or payload.get("name") or "")
    account.seller_external_id = external_id or account.seller_external_id
    account.seller_name = seller_name or account.seller_name
    account.seller_legal_name = str(payload.get("name") or "") or account.seller_legal_name
    account.seller_info_payload = payload


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
