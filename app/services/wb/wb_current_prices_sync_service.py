"""version: 2.0.0
description: Sync current WB product prices using /api/v2/list/goods/filter.
    Fetches prices for specific nmIDs and upserts into wb_product_prices table.
updated: 2026-05-24
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount, Product, WbProductPrice
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)

GOODS_FILTER_CHUNK_SIZE = 1000
RATE_LIMIT_DELAY = 0.6  # 600ms between requests (10 req / 6 sec)


@dataclass(slots=True)
class WbCurrentPricesSyncStats:
    """Statistics for a single WB current prices sync run."""

    accounts_processed: int = 0
    accounts_failed: int = 0
    products_scanned: int = 0
    prices_fetched: int = 0
    prices_upserted: int = 0
    errors: list[str] = field(default_factory=list)


class WbCurrentPricesSyncService:
    """Sync current WB product prices using /api/v2/list/goods/filter."""

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
                stats.products_scanned += account_stats.products_scanned
                stats.prices_fetched += account_stats.prices_fetched
                stats.prices_upserted += account_stats.prices_upserted
                stats.errors.extend(account_stats.errors)
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
                "products_scanned": stats.products_scanned,
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
        """Sync current prices for a single account using goods/filter API."""
        stats = WbCurrentPricesSyncStats()
        client = WildberriesClient(api_key=api_key)

        # Get all WB products for this account
        products_result = await self.session.execute(
            select(Product).where(
                Product.marketplace_account_id == account.id,
                Product.marketplace == Marketplace.WB,
                Product.is_active.is_(True),
            )
        )
        products = list(products_result.scalars().all())
        stats.products_scanned = len(products)

        if not products:
            logger.info(
                "wb_current_prices_sync_no_products",
                extra={"account_id": account.id},
            )
            return stats

        # Extract nmIDs from products
        nm_ids = []
        product_by_nm_id: dict[int, Product] = {}

        for product in products:
            nm_id = self._extract_nm_id(product)
            if nm_id is not None and nm_id not in product_by_nm_id:
                nm_ids.append(nm_id)
                product_by_nm_id[nm_id] = product

        if not nm_ids:
            logger.info(
                "wb_current_prices_sync_no_nm_ids",
                extra={"account_id": account.id},
            )
            return stats

        # Fetch prices in chunks
        for i in range(0, len(nm_ids), GOODS_FILTER_CHUNK_SIZE):
            chunk = nm_ids[i:i + GOODS_FILTER_CHUNK_SIZE]

            try:
                response = await client.get_goods_prices_by_nm_ids(chunk)
            except Exception as exc:
                logger.warning(
                    "wb_current_prices_filter_request_failed",
                    extra={
                        "account_id": account.id,
                        "chunk_start": i,
                        "chunk_size": len(chunk),
                        "error": str(exc),
                    },
                )
                stats.errors.append(f"Filter request failed at chunk {i}: {exc}")
                await asyncio.sleep(RATE_LIMIT_DELAY)
                continue

            error = response.get("error", False)
            error_text = response.get("errorText", "")

            if error:
                logger.warning(
                    "wb_current_prices_filter_api_error",
                    extra={
                        "account_id": account.id,
                        "error_text": error_text,
                        "chunk_start": i,
                    },
                )
                stats.errors.append(f"API error at chunk {i}: {error_text}")
                await asyncio.sleep(RATE_LIMIT_DELAY)
                continue

            list_goods = response.get("data", {}).get("listGoods", [])
            if not isinstance(list_goods, list):
                list_goods = []

            stats.prices_fetched += len(list_goods)

            if list_goods:
                await self._upsert_prices(account, list_goods)
                stats.prices_upserted += len(list_goods)

            # Rate limiting
            await asyncio.sleep(RATE_LIMIT_DELAY)

        return stats

    async def _upsert_prices(
        self,
        account: MarketplaceAccount,
        goods_list: list[dict[str, Any]],
    ) -> None:
        """Upsert prices from goods/filter response into wb_product_prices."""
        now_utc = datetime.now(tz=UTC)

        for item in goods_list:
            nm_id = item.get("nmID") or item.get("nmId")
            if nm_id is None:
                continue

            try:
                nm_id = int(nm_id)
            except (ValueError, TypeError):
                continue

            # Parse price fields from goods/filter response
            # Structure may vary, so we try multiple field names
            price = self._parse_price(item)
            discount = self._parse_discount(item)
            currency_code = item.get("currencyCode") or item.get("currencyIsoCode4217") or "RUB"
            club_discount = self._parse_club_discount(item)

            # Calculate discounted price if not provided
            discounted_price = self._parse_discounted_price(item)
            if discounted_price is None and price is not None and discount is not None and discount > 0:
                discounted_price = price * (Decimal("1") - Decimal(str(discount)) / Decimal("100"))
                discounted_price = discounted_price.quantize(Decimal("0.01"))
            elif discounted_price is None and price is not None:
                discounted_price = price

            club_discounted_price = None
            if club_discount is not None and club_discount > 0 and price is not None:
                club_discounted_price = price * (Decimal("1") - Decimal(str(club_discount)) / Decimal("100"))
                club_discounted_price = club_discounted_price.quantize(Decimal("0.01"))

            # Upsert
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
            existing_price.club_discount = club_discount
            existing_price.club_discounted_price = club_discounted_price
            existing_price.currency_code = currency_code
            existing_price.raw_payload = item
            existing_price.synced_at = now_utc

        await self.session.flush()

    @staticmethod
    def _extract_nm_id(product: Product) -> int | None:
        """Extract WB nmID from product."""
        if product.marketplace != Marketplace.WB:
            return None
        for field_value in (product.external_product_id, product.marketplace_article):
            if field_value is None:
                continue
            try:
                return int(str(field_value).strip())
            except (ValueError, TypeError):
                continue
        return None

    @staticmethod
    def _parse_price(item: dict[str, Any]) -> Decimal | None:
        """Parse price from goods/filter response item."""
        for key in ("price", "priceRub", "priceU", "basicPrice", "basicPriceRub"):
            val = item.get(key)
            if val is not None:
                try:
                    return Decimal(str(val))
                except (InvalidOperation, ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _parse_discount(item: dict[str, Any]) -> int | None:
        """Parse discount from goods/filter response item."""
        for key in ("discount", "discountPercent", "discountPercentRub"):
            val = item.get(key)
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _parse_discounted_price(item: dict[str, Any]) -> Decimal | None:
        """Parse discounted price from goods/filter response item."""
        for key in ("discountedPrice", "priceWithDiscount", "salePrice", "salePriceRub"):
            val = item.get(key)
            if val is not None:
                try:
                    return Decimal(str(val))
                except (InvalidOperation, ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _parse_club_discount(item: dict[str, Any]) -> int | None:
        """Parse WB Club discount from goods/filter response item."""
        for key in ("clubDiscount", "clubDiscountPercent", "wbClubDiscount"):
            val = item.get(key)
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    continue
        return None
