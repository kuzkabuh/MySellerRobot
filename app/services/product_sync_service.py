"""version: 1.2.0
description: Enhanced product synchronization service with caching and error handling.
updated: 2026-05-15
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheManager, cache_key
from app.core.exceptions import IntegrationError
from app.core.logging import LogContext, log_exception
from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount
from app.models.enums import Marketplace
from app.repositories.products import ProductRepository
from app.services.master_product_service import MasterProductService

logger = logging.getLogger(__name__)


class ProductSyncService:
    """Synchronize product cards from marketplace APIs into local catalog."""

    def __init__(
        self,
        session: AsyncSession,
        cipher: TokenCipher | None = None,
        cache: CacheManager | None = None,
    ) -> None:
        self.session = session
        self.repo = ProductRepository(session)
        self.master_products = MasterProductService(session)
        self.cipher = cipher or TokenCipher()
        self.cache = cache or CacheManager()

    async def sync_account_products(self, account: MarketplaceAccount) -> int:
        """Sync products for marketplace account with error handling."""
        with LogContext(
            account_id=account.id,
            marketplace=account.marketplace.value,
            user_id=account.user_id,
        ):
            try:
                logger.info("product_sync_started")

                if account.marketplace == Marketplace.WB:
                    count = await self._sync_wb(account)
                else:
                    count = await self._sync_ozon(account)

                account.last_success_sync_at = datetime.now(tz=UTC)
                account.last_error_at = None
                account.last_error_message = None
                await self.session.commit()

                await self._invalidate_product_cache(account.user_id)

                logger.info(
                    "product_sync_completed",
                    extra={"products_synced": count},
                )
                return count

            except Exception as exc:
                account.last_error_at = datetime.now(tz=UTC)
                account.last_error_message = str(exc)[:500]
                await self.session.commit()

                log_exception(logger, exc, "product_sync_failed")
                raise IntegrationError(
                    f"Failed to sync products for {account.marketplace.value}",
                    details={"account_id": account.id, "error": str(exc)},
                ) from exc

    async def _sync_wb(self, account: MarketplaceAccount) -> int:
        """Sync Wildberries products."""
        client = WildberriesClient(self.cipher.decrypt(account.encrypted_api_key))
        cursor: dict[str, object] = {"limit": 100}
        count = 0

        while True:
            data = await client.get_cards_list(cursor)
            cards = data.get("cards", [])
            if not isinstance(cards, list) or not cards:
                break

            for card in cards:
                if not isinstance(card, dict):
                    continue

                try:
                    product = client.normalize_card_product(
                        payload=card,
                        user_id=account.user_id,
                        account_id=account.id,
                    )
                    if product.external_product_id:
                        saved_product = await self.repo.upsert(product)
                        await self.master_products.ensure_product_linked(saved_product)
                        count += 1
                except Exception as exc:
                    logger.warning(
                        "product_normalization_failed",
                        extra={
                            "card_id": card.get("nmID"),
                            "error": str(exc),
                        },
                    )
                    continue

            response_cursor = data.get("cursor")
            if not isinstance(response_cursor, dict):
                break
            total = int(response_cursor.get("total", 0) or 0)
            if total < 100:
                break
            cursor = {
                "limit": 100,
                "updatedAt": response_cursor.get("updatedAt"),
                "nmID": response_cursor.get("nmID"),
            }

        return count

    async def _sync_ozon(self, account: MarketplaceAccount) -> int:
        """Sync Ozon products."""
        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client_id = self.cipher.decrypt(account.encrypted_client_id or "")
        client = OzonClient(client_id, api_key)
        last_id = ""
        count = 0

        while True:
            data = await client.get_product_list(last_id=last_id, limit=100)
            result = data.get("result", {})
            if not isinstance(result, dict):
                break
            items = result.get("items", [])
            if not isinstance(items, list) or not items:
                break

            for item in items:
                if not isinstance(item, dict):
                    continue

                try:
                    product = client.normalize_product(
                        payload=item,
                        user_id=account.user_id,
                        account_id=account.id,
                    )
                    if product.external_product_id:
                        saved_product = await self.repo.upsert(product)
                        await self.master_products.ensure_product_linked(saved_product)
                        count += 1
                except Exception as exc:
                    logger.warning(
                        "product_normalization_failed",
                        extra={
                            "product_id": item.get("product_id"),
                            "error": str(exc),
                        },
                    )
                    continue

            last_id = str(result.get("last_id") or "")
            if not last_id:
                break

        return count

    async def _invalidate_product_cache(self, user_id: int) -> None:
        """Invalidate product-related cache entries."""
        pattern = cache_key("products", user_id, "*")
        await self.cache.clear_pattern(pattern)
