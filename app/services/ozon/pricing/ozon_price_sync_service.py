"""version: 1.0.0
description: Sync current Ozon product prices into ozon_current_prices table.
    Uses /v5/product/info/prices API with cursor-based pagination.
updated: 2026-06-13
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.models.domain import MarketplaceAccount, OzonCurrentPrice, Product
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)

PRICES_PAGE_LIMIT = 1000


@dataclass(slots=True)
class OzonPriceSyncStats:
    accounts_processed: int = 0
    accounts_failed: int = 0
    prices_fetched: int = 0
    prices_upserted: int = 0
    errors: list[str] = field(default_factory=list)


class OzonPriceSyncService:
    """Sync current Ozon prices using /v5/product/info/prices."""

    def __init__(self, session: AsyncSession, cipher: TokenCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()

    async def sync_all_accounts(self) -> OzonPriceSyncStats:
        stats = OzonPriceSyncStats()
        result = await self.session.execute(
            select(MarketplaceAccount).where(
                MarketplaceAccount.marketplace == Marketplace.OZON,
                MarketplaceAccount.is_active.is_(True),
            )
        )
        accounts = list(result.scalars().all())
        for account in accounts:
            try:
                acct_stats = await self._sync_account(account)
                stats.accounts_processed += 1
                stats.prices_fetched += acct_stats.prices_fetched
                stats.prices_upserted += acct_stats.prices_upserted
                stats.errors.extend(acct_stats.errors)
            except Exception as exc:
                stats.accounts_failed += 1
                stats.errors.append(f"account_id={account.id}: {exc}")
                logger.exception(
                    "ozon_price_sync_account_failed",
                    extra={"account_id": account.id},
                )
        logger.info(
            "ozon_price_sync_completed",
            extra={
                "accounts_processed": stats.accounts_processed,
                "accounts_failed": stats.accounts_failed,
                "prices_fetched": stats.prices_fetched,
                "prices_upserted": stats.prices_upserted,
            },
        )
        return stats

    async def sync_account(self, account: MarketplaceAccount) -> OzonPriceSyncStats:
        return await self._sync_account(account)

    async def _sync_account(self, account: MarketplaceAccount) -> OzonPriceSyncStats:
        stats = OzonPriceSyncStats()
        if not account.encrypted_client_id:
            logger.warning(
                "ozon_price_sync_no_client_id",
                extra={"account_id": account.id},
            )
            stats.errors.append(f"account_id={account.id}: missing client_id")
            return stats
        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client_id = self.cipher.decrypt(account.encrypted_client_id)
        client = OzonClient(client_id=client_id, api_key=api_key)

        # Build offer_id → product mapping for this account
        products_result = await self.session.execute(
            select(Product).where(
                Product.marketplace_account_id == account.id,
                Product.marketplace == Marketplace.OZON,
                Product.is_active.is_(True),
            )
        )
        products_by_offer: dict[str, Product] = {}
        for p in products_result.scalars().all():
            if p.seller_article:
                products_by_offer[p.seller_article] = p

        cursor = ""
        while True:
            try:
                response = await client.get_product_info_prices(
                    limit=PRICES_PAGE_LIMIT,
                    cursor=cursor,
                )
            except Exception as exc:
                stats.errors.append(f"API request failed: {exc}")
                logger.warning(
                    "ozon_price_sync_request_failed",
                    extra={"account_id": account.id, "error": str(exc)},
                )
                break

            items = response.get("items", []) or []
            stats.prices_fetched += len(items)

            if items:
                await self._upsert_prices(account, items, products_by_offer)
                stats.prices_upserted += len(items)

            cursor = response.get("cursor", "")
            if not items or not cursor:
                break

        return stats

    async def _upsert_prices(
        self,
        account: MarketplaceAccount,
        items: list[dict[str, Any]],
        products_by_offer: dict[str, Product],
    ) -> None:
        now_utc = datetime.now(tz=UTC)
        for item in items:
            offer_id = item.get("offer_id") or item.get("offerId")
            if not offer_id:
                continue
            ozon_product_id = str(item.get("product_id") or item.get("productId") or "")

            price_data = item.get("price") or {}
            if isinstance(price_data, dict):
                price = self._to_decimal(price_data.get("price"))
                old_price = self._to_decimal(price_data.get("old_price"))
                marketing_price = self._to_decimal(price_data.get("marketing_price"))
                min_price = self._to_decimal(price_data.get("min_price"))
                currency = price_data.get("currency_code", "RUB")
            else:
                price = self._to_decimal(item.get("price"))
                old_price = self._to_decimal(item.get("old_price"))
                marketing_price = self._to_decimal(item.get("marketing_price"))
                min_price = self._to_decimal(item.get("min_price"))
                currency = item.get("currency_code", "RUB")

            product = products_by_offer.get(offer_id)
            product_id = product.id if product else None
            if product is not None and min_price is not None:
                product.min_price = min_price

            existing_result = await self.session.execute(
                select(OzonCurrentPrice).where(
                    OzonCurrentPrice.marketplace_account_id == account.id,
                    OzonCurrentPrice.offer_id == offer_id,
                )
            )
            row = existing_result.scalar_one_or_none()
            if row is None:
                row = OzonCurrentPrice(
                    user_id=account.user_id,
                    marketplace_account_id=account.id,
                    offer_id=offer_id,
                )
                self.session.add(row)

            row.product_id = product_id
            row.ozon_product_id = ozon_product_id or None
            row.price = price
            row.old_price = old_price
            row.marketing_price = marketing_price
            row.min_price = min_price
            row.currency_code = currency or "RUB"
            row.raw_payload = item
            row.synced_at = now_utc

        await self.session.flush()

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None
