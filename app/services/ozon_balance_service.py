"""Ozon balance synchronization service using POST /v1/finance/balance."""

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, MarketplaceApiError, RateLimitError
from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.models.domain import AccountBalanceSnapshot, MarketplaceAccount
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)

OZON_BALANCE_PERIOD_DAYS = 29


class OzonBalanceService:
    """Sync Ozon cabinet balance via the official /v1/finance/balance endpoint."""

    def __init__(self, session: AsyncSession, cipher: TokenCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()

    async def sync_balance(self, account: MarketplaceAccount) -> AccountBalanceSnapshot:
        """Fetch and persist Ozon balance for the last 29 days.

        The primary value is total.closing_balance.value.
        """
        now = datetime.now(tz=UTC)
        date_to = now.date()
        date_from = date_to - timedelta(days=OZON_BALANCE_PERIOD_DAYS)

        logger.info(
            "ozon_balance_sync_started",
            extra={
                "account_id": account.id,
                "user_id": account.user_id,
                "period_from": date_from.isoformat(),
                "period_to": date_to.isoformat(),
            },
        )

        if not account.encrypted_client_id:
            raise ValueError("Ozon Client ID is not configured")

        client = OzonClient(
            self.cipher.decrypt(account.encrypted_client_id),
            self.cipher.decrypt(account.encrypted_api_key),
        )

        try:
            payload = await client.get_finance_balance(date_from, date_to)
            snapshot = self._parse_balance_response(account, payload, date_from, date_to, now)
            logger.info(
                "ozon_balance_sync_finished",
                extra={
                    "account_id": account.id,
                    "user_id": account.user_id,
                    "closing_balance": str(snapshot.current),
                    "currency_code": snapshot.currency,
                },
            )
        except (AuthenticationError, RateLimitError, MarketplaceApiError) as exc:
            status = "NO_ACCESS" if isinstance(exc, AuthenticationError) else "API_ERROR"
            if isinstance(exc, RateLimitError):
                status = "RATE_LIMITED"
            snapshot = AccountBalanceSnapshot(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                marketplace=Marketplace.OZON,
                currency="RUB",
                current=None,
                for_withdraw=None,
                opening_balance=None,
                accrued=None,
                payments_total=None,
                period_from=date_from,
                period_to=date_to,
                status=status,
                error_message=str(exc)[:1000],
                fetched_at=now,
                raw_payload={},
            )
            logger.warning(
                "ozon_balance_sync_failed",
                extra={
                    "account_id": account.id,
                    "user_id": account.user_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:300],
                },
            )
        except Exception as exc:
            snapshot = AccountBalanceSnapshot(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                marketplace=Marketplace.OZON,
                currency="RUB",
                current=None,
                for_withdraw=None,
                opening_balance=None,
                accrued=None,
                payments_total=None,
                period_from=date_from,
                period_to=date_to,
                status="ERROR",
                error_message=str(exc)[:1000],
                fetched_at=now,
                raw_payload={},
            )
            logger.exception(
                "ozon_balance_sync_failed",
                extra={
                    "account_id": account.id,
                    "user_id": account.user_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:300],
                },
            )

        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    @staticmethod
    def _parse_balance_response(
        account: MarketplaceAccount,
        payload: dict[str, Any],
        date_from: date,
        date_to: date,
        fetched_at: datetime,
    ) -> AccountBalanceSnapshot:
        if not isinstance(payload, dict):
            return _error_snapshot(
                account, date_from, date_to, fetched_at, "ozon_balance_invalid_response"
            )

        result = payload.get("result")

        if result is None:
            return _error_snapshot(
                account, date_from, date_to, fetched_at, "ozon_balance_invalid_response"
            )

        if not isinstance(result, dict):
            return _error_snapshot(
                account,
                date_from,
                date_to,
                fetched_at,
                f"ozon_balance_invalid_response: expected dict, got {type(result).__name__}",
            )

        closing = result.get("closing_balance")
        if not isinstance(closing, dict):
            return _error_snapshot(
                account, date_from, date_to, fetched_at, "ozon_balance_invalid_response"
            )

        closing_value = _decimal_or_none(closing.get("value"))
        currency = str(closing.get("currency_code") or "RUB")

        opening_balance = _decimal_or_none(_safe_nested_value(result, "opening_balance", "value"))
        accrued = _decimal_or_none(_safe_nested_value(result, "accrued", "value"))

        payments = result.get("payments")
        payments_total = _sum_payments(payments)

        return AccountBalanceSnapshot(
            user_id=account.user_id,
            marketplace_account_id=account.id,
            marketplace=Marketplace.OZON,
            currency=currency,
            current=closing_value,
            for_withdraw=None,
            opening_balance=opening_balance,
            accrued=accrued,
            payments_total=payments_total,
            period_from=date_from,
            period_to=date_to,
            status="OK",
            fetched_at=fetched_at,
            raw_payload=payload,
        )


def _safe_nested_value(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _sum_payments(payments: Any) -> Decimal | None:
    if not isinstance(payments, list):
        return None
    total = Decimal("0")
    has_any = False
    for payment in payments:
        if not isinstance(payment, dict):
            continue
        amount = _safe_nested_value(payment, "amount", "value")
        if amount is not None:
            dec = _decimal_or_none(amount)
            if dec is not None:
                total += dec
                has_any = True
    return total if has_any else None


def _error_snapshot(
    account: MarketplaceAccount,
    date_from: date,
    date_to: date,
    fetched_at: datetime,
    message: str,
) -> AccountBalanceSnapshot:
    return AccountBalanceSnapshot(
        user_id=account.user_id,
        marketplace_account_id=account.id,
        marketplace=Marketplace.OZON,
        currency="RUB",
        current=None,
        for_withdraw=None,
        opening_balance=None,
        accrued=None,
        payments_total=None,
        period_from=date_from,
        period_to=date_to,
        status="PARSE_ERROR",
        error_message=message,
        fetched_at=fetched_at,
        raw_payload={},
    )
