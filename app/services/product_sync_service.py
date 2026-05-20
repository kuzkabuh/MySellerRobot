"""version: 1.6.0
description: Product sync with WB per-model tariffs, Ozon details, logging, caching.
updated: 2026-05-20
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

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
from app.schemas.products import ProductUpsert
from app.services.master_product_service import MasterProductService

logger = logging.getLogger(__name__)

WB_COMMISSION_API_FIELDS: dict[str, str] = {
    "paidStorageKgvp": "commission_fbw",
    "kgvpMarketplace": "commission_fbs",
    "kgvpSupplier": "commission_dbs",
    "kgvpSupplierExpress": "commission_edbs",
    "kgvpPickup": "commission_pickup",
    "kgvpBooking": "commission_booking",
}


@dataclass(frozen=True, slots=True)
class WbTariffRow:
    subject_id: str
    subject_name: str
    parent_id: str
    parent_name: str
    commission_fbw: Decimal | None
    commission_fbs: Decimal | None
    commission_dbs: Decimal | None
    commission_edbs: Decimal | None
    commission_pickup: Decimal | None
    commission_booking: Decimal | None


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
        commission_tariffs = await self._load_wb_commission_tariffs(client)
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
                    self._apply_wb_commission_tariff(product, card, commission_tariffs)
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

    async def _load_wb_commission_tariffs(
        self,
        client: WildberriesClient,
    ) -> dict[str, WbTariffRow]:
        """Load official WB commission tariffs indexed by subject_id (lowercased)."""

        try:
            rows = await client.get_commission_tariffs(locale="ru")
        except Exception:
            logger.exception("wb_commission_tariffs_load_failed")
            return {}

        tariffs: dict[str, WbTariffRow] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue

            subject_id = str(row.get("subjectID") or "").strip().lower()
            subject_name = str(row.get("subjectName") or "").strip()
            parent_id = str(row.get("parentID") or "").strip()
            parent_name = str(row.get("parentName") or "").strip()

            if not subject_id:
                continue

            commission_values: dict[str, Decimal | None] = {}
            for api_field, schema_field in WB_COMMISSION_API_FIELDS.items():
                commission_values[schema_field] = _decimal_percent(row.get(api_field))

            tariff = WbTariffRow(
                subject_id=subject_id,
                subject_name=subject_name,
                parent_id=parent_id,
                parent_name=parent_name,
                commission_fbw=commission_values["commission_fbw"],
                commission_fbs=commission_values["commission_fbs"],
                commission_dbs=commission_values["commission_dbs"],
                commission_edbs=commission_values["commission_edbs"],
                commission_pickup=commission_values["commission_pickup"],
                commission_booking=commission_values["commission_booking"],
            )
            tariffs[subject_id] = tariff

        logger.info(
            "wb_commission_tariffs_loaded",
            extra={"tariff_count": len(tariffs)},
        )
        return tariffs

    @staticmethod
    def _apply_wb_commission_tariff(
        product: ProductUpsert,
        card: dict[str, object],
        tariffs: dict[str, WbTariffRow],
    ) -> None:
        subject_id = str(card.get("subjectID") or card.get("subjectId") or "").strip().lower()
        tariff = tariffs.get(subject_id)
        if tariff is None:
            return

        product.commission_fbw = tariff.commission_fbw
        product.commission_fbs = tariff.commission_fbs
        product.commission_dbs = tariff.commission_dbs
        product.commission_edbs = tariff.commission_edbs
        product.commission_pickup = tariff.commission_pickup
        product.commission_booking = tariff.commission_booking
        product.marketplace_commission_source = "WB tariffs /api/v1/tariffs/commission"

        if tariff.commission_fbs is not None:
            product.marketplace_commission_rate = tariff.commission_fbs
        elif tariff.commission_fbw is not None:
            product.marketplace_commission_rate = tariff.commission_fbw
        elif tariff.commission_dbs is not None:
            product.marketplace_commission_rate = tariff.commission_dbs

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
            details = await self._load_ozon_product_details(client, items)
            logger.info(
                "ozon_product_page_loaded",
                extra={
                    "account_id": account.id,
                    "items": len(items),
                    "details_loaded": len(details),
                    "last_id": last_id,
                },
            )

            for item in items:
                if not isinstance(item, dict):
                    continue

                try:
                    payload = {**item, **details.get(str(item.get("product_id") or ""), {})}
                    product = client.normalize_product(
                        payload=payload,
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

        logger.info("ozon_product_sync_completed", extra={"account_id": account.id, "count": count})
        return count

    async def _load_ozon_product_details(
        self,
        client: OzonClient,
        items: list[object],
    ) -> dict[str, dict[str, object]]:
        product_ids = [
            str(item.get("product_id"))
            for item in items
            if isinstance(item, dict) and item.get("product_id")
        ]
        if not product_ids:
            return {}
        try:
            payload = await client.get_product_info_list(product_ids=product_ids[:1000])
        except Exception:
            logger.exception("ozon_product_details_load_failed")
            return {}
        result = payload.get("result")
        raw_items = result.get("items") if isinstance(result, dict) else payload.get("items")
        if not isinstance(raw_items, list):
            return {}
        details: dict[str, dict[str, object]] = {}
        for row in raw_items:
            if isinstance(row, dict) and (row.get("id") or row.get("product_id")):
                key = str(row.get("id") or row.get("product_id"))
                details[key] = row
        return details

    async def _invalidate_product_cache(self, user_id: int) -> None:
        """Invalidate product-related cache entries."""
        pattern = cache_key("products", user_id, "*")
        await self.cache.clear_pattern(pattern)


def _decimal_percent(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return (Decimal(str(value).replace(",", ".")) / Decimal("100")).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError):
        return None
