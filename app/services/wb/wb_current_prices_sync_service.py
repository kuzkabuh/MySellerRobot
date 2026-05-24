"""version: 1.0.0
description: Sync current WB product prices from /api/v2/prices into wb_product_prices table.
updated: 2026-05-24
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount, WbProductPrice
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)

PRICES_SYNC_PAGE_LIMIT = 1000


@dataclass(slots=True)
class WbCurrentPricesSyncStats:
    """Statistics for a single WB current prices sync run."""

    accounts_processed: int = 0
    accounts_failed: int = 0
    prices_fetched: int = 0
    prices_upserted: int = 0
    errors: list[str] = field(default_factory=list)


class WbCurrentPricesSyncService:
    """Sync current WB product prices from /api/v2/prices into wb_product_prices."""

    def __init__(
        self,
        session: AsyncSession,
        cipher: TokenCipher | None = None,
    ) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()

    async def sync_all_accounts(self) -> WbCurrentPricesSyncStats:
        """Sync current prices for all active WB accounts."""
        stats = WbCurrentPricesSyncStats()

        accounts_result = await self.session.execute(
            select(MarketplaceAccount).where(
                MarketplaceAccount.marketplace == Marketplace.WB,
                MarketplaceAccount.is_active.is_(True),
            )
        )
        accounts = list(accounts_result.scalars().all())

        for account in accounts:
            try:
                api_key = self.cipher.decrypt(account.encrypted_api_key)
                account_stats = await self._sync_account(account, api_key)
                stats.accounts_processed += 1
                stats.prices_fetched += account_stats.prices_fetched
                stats.prices_upserted += account_stats.prices_upserted
            except Exception as exc:
                stats.accounts_failed += 1
                error_msg = f"account_id={account.id}: {exc}"
                stats.errors.append(error_msg)
                logger.exception(
                    "wb_current_prices_sync_account_failed",
                    extra={"account_id": account.id, "user_id": account.user_id},
                )

        logger.info(
            "wb_current_prices_sync_completed",
            extra={
                "accounts_processed": stats.accounts_processed,
                "accounts_failed": stats.accounts_failed,
                "prices_fetched": stats.prices_fetched,
                "prices_upserted": stats.prices_upserted,
            },
        )

        return stats

    async def sync_account(self, account: MarketplaceAccount) -> WbCurrentPricesSyncStats:
        """Sync current prices for a single WB account."""
        api_key = self.cipher.decrypt(account.encrypted_api_key)
        return await self._sync_account(account, api_key)

    async def _sync_account(
        self,
        account: MarketplaceAccount,
        api_key: str,
    ) -> WbCurrentPricesSyncStats:
        """Sync current prices for a single account using API key."""
        stats = WbCurrentPricesSyncStats()
        client = WildberriesClient(api_key=api_key)

        offset = 0
        total_fetched = 0

        while True:
            try:
                response = await client.get_current_prices(
                    limit=PRICES_SYNC_PAGE_LIMIT,
                    offset=offset,
                )
            except Exception as exc:
                logger.warning(
                    "wb_current_prices_api_request_failed",
                    extra={
                        "account_id": account.id,
                        "offset": offset,
                        "error": str(exc),
                    },
                )
                stats.errors.append(f"API request failed at offset={offset}: {exc}")
                break

            data = response.get("data", []) if isinstance(response, dict) else []
            if not isinstance(data, list):
                data = []

            if not data:
                break

            await self._upsert_prices(account, data)
            total_fetched += len(data)
            stats.prices_fetched += len(data)
            stats.prices_upserted += len(data)

            offset += PRICES_SYNC_PAGE_LIMIT

            if len(data) < PRICES_SYNC_PAGE_LIMIT:
                break

        return stats

    async def _upsert_prices(
        self,
        account: MarketplaceAccount,
        prices_data: list[dict[str, Any]],
    ) -> None:
        """Upsert current prices into wb_product_prices table."""
        now_utc = datetime.now(tz=UTC)

        for item in prices_data:
            nm_id = item.get("nmID") or item.get("nmId")
            if nm_id is None:
                continue

            try:
                nm_id = int(nm_id)
            except (ValueError, TypeError):
                continue

            price_raw = item.get("price") or item.get("priceRub")
            discount_raw = item.get("discount")
            discounted_price_raw = item.get("discountedPrice") or item.get("priceWithDiscount")
            currency_code = item.get("currencyCode") or item.get("currency") or "RUB"

            try:
                price = Decimal(str(price_raw)) if price_raw is not None else None
            except (InvalidOperation, ValueError, TypeError):
                price = None

            try:
                discount = int(discount_raw) if discount_raw is not None else 0
            except (ValueError, TypeError):
                discount = 0

            try:
                discounted_price = (
                    Decimal(str(discounted_price_raw))
                    if discounted_price_raw is not None
                    else None
                )
            except (InvalidOperation, ValueError, TypeError):
                discounted_price = None

            if price is not None and discounted_price is None and discount:
                discounted_price = price * (Decimal("1") - Decimal(str(discount)) / Decimal("100"))
                discounted_price = discounted_price.quantize(Decimal("0.01"))

            if discounted_price is not None and price is None:
                price = discounted_price

            if price is None or discounted_price is None:
                continue

            existing = await self.session.execute(
                select(WbProductPrice).where(
                    WbProductPrice.marketplace_account_id == account.id,
                    WbProductPrice.wb_nm_id == nm_id,
                )
            )
            existing_price = existing.scalar_one_or_none()

            if existing_price is None:
                existing_price = WbProductPrice(
                    user_id=account.user_id,
                    marketplace_account_id=account.id,
                    wb_nm_id=nm_id,
                )
                self.session.add(existing_price)

            existing_price.price = price
            existing_price.discount = discount
            existing_price.discounted_price = discounted_price
            existing_price.currency_code = currency_code
            existing_price.raw_payload = item
            existing_price.synced_at = now_utc

        await self.session.flush()
