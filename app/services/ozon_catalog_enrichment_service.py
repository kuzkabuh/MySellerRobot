"""version: 1.0.0
description: Ozon warehouse, price, and promo synchronization service.
updated: 2026-05-17
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.models.domain import (
    MarketplaceAccount,
    MarketplaceWarehouse,
    OzonPriceSnapshot,
    OzonPromo,
    OzonPromoProduct,
)
from app.models.enums import Marketplace
from app.repositories.products import ProductRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OzonEnrichmentStats:
    warehouses_fetched: int = 0
    warehouses_upserted: int = 0
    prices_fetched: int = 0
    prices_upserted: int = 0
    promos_fetched: int = 0
    promo_products_fetched: int = 0
    promo_products_upserted: int = 0
    failed: int = 0


class OzonCatalogEnrichmentService:
    """Synchronize Ozon read-only catalog enrichments."""

    def __init__(self, session: AsyncSession, cipher: TokenCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()
        self.products = ProductRepository(session)

    async def sync_account(self, account: MarketplaceAccount) -> OzonEnrichmentStats:
        if account.marketplace != Marketplace.OZON:
            return OzonEnrichmentStats()
        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client_id = self.cipher.decrypt(account.encrypted_client_id or "")
        client = OzonClient(client_id, api_key)
        stats = OzonEnrichmentStats()
        try:
            stats.warehouses_fetched, stats.warehouses_upserted = await self.sync_warehouses(
                account, client
            )
        except Exception:
            stats.failed += 1
            logger.exception("ozon_warehouses_sync_failed", extra={"account_id": account.id})
            await self.session.rollback()
        try:
            stats.prices_fetched, stats.prices_upserted = await self.sync_prices(account, client)
        except Exception:
            stats.failed += 1
            logger.exception("ozon_prices_sync_failed", extra={"account_id": account.id})
            await self.session.rollback()
        try:
            promo_stats = await self.sync_promos(account, client)
            stats.promos_fetched = promo_stats.promos_fetched
            stats.promo_products_fetched = promo_stats.promo_products_fetched
            stats.promo_products_upserted = promo_stats.promo_products_upserted
        except Exception:
            stats.failed += 1
            logger.exception("ozon_promos_sync_failed", extra={"account_id": account.id})
            await self.session.rollback()
        await self.session.commit()
        return stats

    async def sync_warehouses(
        self,
        account: MarketplaceAccount,
        client: OzonClient,
    ) -> tuple[int, int]:
        fetched = 0
        upserted = 0
        offset = 0
        while True:
            payload = await client.get_warehouses(limit=100, offset=offset)
            rows = _extract_rows(payload, keys=("warehouses", "result", "items"))
            if not rows:
                break
            fetched += len(rows)
            for row in rows:
                external_id = str(
                    row.get("warehouse_id") or row.get("warehouseId") or row.get("id") or ""
                )
                if not external_id:
                    continue
                existing = await self.session.execute(
                    select(MarketplaceWarehouse).where(
                        MarketplaceWarehouse.marketplace_account_id == account.id,
                        MarketplaceWarehouse.marketplace == Marketplace.OZON,
                        MarketplaceWarehouse.external_warehouse_id == external_id,
                    )
                )
                warehouse = existing.scalar_one_or_none()
                if warehouse is None:
                    warehouse = MarketplaceWarehouse(
                        user_id=account.user_id,
                        marketplace_account_id=account.id,
                        marketplace=Marketplace.OZON,
                        external_warehouse_id=external_id,
                        synced_at=datetime.now(tz=UTC),
                    )
                    self.session.add(warehouse)
                warehouse.name = str(row.get("name") or row.get("warehouse_name") or external_id)
                warehouse.warehouse_type = _optional_str(row.get("type") or row.get("status"))
                warehouse.is_active = not bool(row.get("is_archived") or row.get("is_disabled"))
                warehouse.synced_at = datetime.now(tz=UTC)
                warehouse.raw_payload = row
                upserted += 1
            if len(rows) < 100:
                break
            offset += 100
        logger.info(
            "ozon_warehouses_sync_completed",
            extra={"account_id": account.id, "fetched": fetched, "upserted": upserted},
        )
        return fetched, upserted

    async def sync_prices(
        self,
        account: MarketplaceAccount,
        client: OzonClient,
        *,
        synced_at: datetime | None = None,
    ) -> tuple[int, int]:
        fetched = 0
        upserted = 0
        cursor = ""
        synced_at = synced_at or datetime.now(tz=UTC)
        while True:
            payload = await client.get_product_info_prices(limit=1000, cursor=cursor)
            rows = _extract_rows(payload, keys=("items", "result"))
            if not rows:
                break
            fetched += len(rows)
            for row in rows:
                offer_id = str(row.get("offer_id") or "")
                if not offer_id:
                    continue
                product = await self.products.find_for_order_item(
                    account_id=account.id,
                    marketplace=Marketplace.OZON,
                    seller_article=offer_id,
                    marketplace_article=str(row.get("sku") or ""),
                    external_product_id=str(row.get("product_id") or ""),
                )
                snapshot = await self._get_or_create_price_snapshot(
                    account=account,
                    offer_id=offer_id,
                    synced_at=synced_at,
                )
                raw_price_data = row.get("price")
                price_data: dict[str, Any] = (
                    raw_price_data if isinstance(raw_price_data, dict) else row
                )
                snapshot.product_id = product.id if product else None
                snapshot.ozon_product_id = _optional_str(row.get("product_id"))
                snapshot.price = _money(price_data.get("price"))
                snapshot.old_price = _money(price_data.get("old_price"))
                snapshot.marketing_price = _money(
                    price_data.get("marketing_price")
                    or price_data.get("marketing_seller_price")
                    or price_data.get("discounted_price")
                )
                snapshot.min_price = _money(
                    price_data.get("min_price") or price_data.get("min_ozon_price")
                )
                snapshot.currency_code = _optional_str(price_data.get("currency_code"))
                snapshot.raw_payload = row
                upserted += 1
            cursor = _next_cursor(payload)
            if not cursor:
                break
        logger.info(
            "ozon_prices_sync_completed",
            extra={"account_id": account.id, "fetched": fetched, "upserted": upserted},
        )
        return fetched, upserted

    async def sync_promos(
        self,
        account: MarketplaceAccount,
        client: OzonClient,
    ) -> OzonEnrichmentStats:
        stats = OzonEnrichmentStats()
        offset = 0
        while True:
            payload = await client.get_actions(limit=100, offset=offset)
            actions = _extract_rows(payload, keys=("actions", "result", "items"))
            if not actions:
                break
            stats.promos_fetched += len(actions)
            for action in actions:
                promo = await self._upsert_promo(account, action)
                products_payload = await client.get_promos_products(
                    int(promo.external_promo_id),
                    limit=1000,
                )
                products = _extract_rows(products_payload, keys=("products", "result", "items"))
                stats.promo_products_fetched += len(products)
                for product_row in products:
                    await self._upsert_promo_product(account, promo, product_row)
                    stats.promo_products_upserted += 1
            if len(actions) < 100:
                break
            offset += 100
        logger.info(
            "ozon_promos_sync_completed",
            extra={
                "account_id": account.id,
                "promos": stats.promos_fetched,
                "products": stats.promo_products_upserted,
            },
        )
        return stats

    async def _get_or_create_price_snapshot(
        self,
        *,
        account: MarketplaceAccount,
        offer_id: str,
        synced_at: datetime,
    ) -> OzonPriceSnapshot:
        existing = await self.session.execute(
            select(OzonPriceSnapshot).where(
                OzonPriceSnapshot.marketplace_account_id == account.id,
                OzonPriceSnapshot.offer_id == offer_id,
                OzonPriceSnapshot.synced_at == synced_at,
            )
        )
        snapshot = existing.scalar_one_or_none()
        if snapshot is None:
            snapshot = OzonPriceSnapshot(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                offer_id=offer_id,
                synced_at=synced_at,
            )
            self.session.add(snapshot)
        return snapshot

    async def _upsert_promo(self, account: MarketplaceAccount, row: dict[str, Any]) -> OzonPromo:
        external_id = str(row.get("id") or row.get("action_id") or "")
        existing = await self.session.execute(
            select(OzonPromo).where(
                OzonPromo.marketplace_account_id == account.id,
                OzonPromo.external_promo_id == external_id,
            )
        )
        promo = existing.scalar_one_or_none()
        if promo is None:
            promo = OzonPromo(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                external_promo_id=external_id,
            )
            self.session.add(promo)
        promo.title = _optional_str(row.get("title") or row.get("name"))
        promo.status = _optional_str(row.get("status"))
        promo.date_from = _parse_dt(row.get("date_start") or row.get("date_from"))
        promo.date_to = _parse_dt(row.get("date_end") or row.get("date_to"))
        promo.raw_payload = row
        await self.session.flush()
        return promo

    async def _upsert_promo_product(
        self,
        account: MarketplaceAccount,
        promo: OzonPromo,
        row: dict[str, Any],
    ) -> None:
        offer_id = str(row.get("offer_id") or "")
        if not offer_id:
            return
        existing = await self.session.execute(
            select(OzonPromoProduct).where(
                OzonPromoProduct.promo_id == promo.id,
                OzonPromoProduct.offer_id == offer_id,
            )
        )
        promo_product = existing.scalar_one_or_none()
        if promo_product is None:
            promo_product = OzonPromoProduct(
                promo_id=promo.id,
                user_id=account.user_id,
                marketplace_account_id=account.id,
                offer_id=offer_id,
            )
            self.session.add(promo_product)
        product = await self.products.find_for_order_item(
            account_id=account.id,
            marketplace=Marketplace.OZON,
            seller_article=offer_id,
            marketplace_article=str(row.get("sku") or ""),
            external_product_id=str(row.get("product_id") or ""),
        )
        promo_product.product_id = product.id if product else None
        promo_product.ozon_product_id = _optional_str(row.get("product_id"))
        promo_product.status = _optional_str(row.get("status"))
        promo_product.action_price = _money(row.get("action_price"))
        promo_product.max_action_price = _money(row.get("max_action_price"))
        promo_product.raw_payload = row


def _extract_rows(payload: dict[str, Any], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_rows(value, keys=keys)
            if nested:
                return nested
    for value in payload.values():
        if isinstance(value, dict):
            nested = _extract_rows(value, keys=keys)
            if nested:
                return nested
    return []


def _next_cursor(payload: dict[str, Any]) -> str:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if not isinstance(result, dict):
        return ""
    return str(result.get("cursor") or result.get("last_id") or "")


def _money(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
