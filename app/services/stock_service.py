"""version: 1.2.0
description: Stock synchronization, marketplace stock parsing, stockout forecast, and alerts.
updated: 2026-05-17
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import AlertEvent, MarketplaceAccount, Product, StockSnapshot
from app.models.enums import AlertType, Marketplace
from app.repositories.products import ProductRepository
from app.services.stock_forecast_service import StockForecastService

logger = logging.getLogger(__name__)


class StockService:
    """Synchronize stock snapshots and create basic low-stock alerts."""

    def __init__(self, session: AsyncSession, cipher: TokenCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()
        self.products = ProductRepository(session)

    async def sync_account_stocks(self, account: MarketplaceAccount) -> int:
        if account.marketplace == Marketplace.WB:
            count = await self._sync_wb(account)
        else:
            count = await self._sync_ozon(account)
        await self.session.commit()
        return count

    async def _sync_wb(self, account: MarketplaceAccount) -> int:
        client = WildberriesClient(self.cipher.decrypt(account.encrypted_api_key))
        count = await self._sync_wb_seller_stocks(account, client)
        count += await self._sync_wb_analytics_stocks(account, client)
        return count

    async def _sync_wb_seller_stocks(
        self,
        account: MarketplaceAccount,
        client: WildberriesClient,
    ) -> int:
        products = await self._list_products_for_account(account)
        chrt_products: dict[int, Product] = {}
        for catalog_product in products:
            chrt_id = _int_or_none(catalog_product.chrt_id)
            if chrt_id is not None:
                chrt_products[chrt_id] = catalog_product
        if not chrt_products:
            logger.info(
                "wb_fbs_stock_sync_skipped_no_chrt_ids",
                extra={"account_id": account.id, "user_id": account.user_id},
            )
            return 0
        try:
            warehouses = await client.get_seller_warehouses()
        except Exception:
            logger.exception(
                "wb_fbs_stock_warehouses_load_failed",
                extra={"account_id": account.id, "user_id": account.user_id},
            )
            return 0

        logger.info(
            "wb_fbs_stock_sync_started",
            extra={
                "account_id": account.id,
                "warehouses": len(warehouses),
                "chrt_ids": len(chrt_products),
            },
        )
        count = 0
        for warehouse in warehouses:
            warehouse_id = (
                warehouse.get("ID") or warehouse.get("id") or warehouse.get("warehouseId")
            )
            if not warehouse_id:
                continue
            warehouse_name = str(warehouse.get("name") or warehouse_id)
            for chunk in _chunks(list(chrt_products), 1000):
                try:
                    rows = await client.get_seller_warehouse_stocks(
                        warehouse_id=warehouse_id,
                        chrt_ids=chunk,
                    )
                except Exception:
                    logger.exception(
                        "wb_fbs_stock_load_failed",
                        extra={
                            "account_id": account.id,
                            "warehouse_id": warehouse_id,
                            "chrt_ids": len(chunk),
                        },
                    )
                    continue
                for row in rows:
                    chrt_id = _int_or_none(row.get("chrtId") or row.get("chrtID"))
                    product = chrt_products.get(chrt_id) if chrt_id is not None else None
                    quantity = self._quantity_from_stock_row(row)
                    raw = {
                        **row,
                        "warehouseName": f"FBS: {warehouse_name}",
                        "stock_source": "WB_SELLER_STOCKS",
                    }
                    await self._add_snapshot(account, product, quantity, raw)
                    count += 1
        logger.info(
            "wb_fbs_stock_sync_completed",
            extra={"account_id": account.id, "snapshots": count},
        )
        return count

    async def _sync_wb_analytics_stocks(
        self,
        account: MarketplaceAccount,
        client: WildberriesClient,
    ) -> int:
        limit = 1000
        offset = 0
        count = 0
        while True:
            try:
                data = await client.get_wb_warehouses_stocks(limit=limit, offset=offset)
            except Exception:
                logger.exception(
                    "wb_fbo_stock_analytics_load_failed",
                    extra={"account_id": account.id, "user_id": account.user_id, "offset": offset},
                )
                return count
            rows = self._extract_rows(data)
            if not rows:
                break
            for row in rows:
                product = await self.products.find_for_order_item(
                    account_id=account.id,
                    marketplace=Marketplace.WB,
                    seller_article=str(row.get("vendorCode") or row.get("supplierArticle") or ""),
                    marketplace_article=str(row.get("nmID") or row.get("nmId") or ""),
                    external_product_id=str(row.get("nmID") or row.get("nmId") or ""),
                )
                quantity = self._quantity_from_stock_row(row)
                await self._add_snapshot(
                    account,
                    product,
                    quantity,
                    {
                        **row,
                        "warehouseName": row.get("warehouseName") or "FBO: склады WB",
                        "stock_source": "WB_ANALYTICS_STOCKS",
                    },
                )
                count += 1
            if len(rows) < limit:
                break
            offset += limit
        logger.info(
            "wb_fbo_stock_analytics_sync_completed",
            extra={"account_id": account.id, "snapshots": count},
        )
        return count

    async def _sync_ozon(self, account: MarketplaceAccount) -> int:
        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client_id = self.cipher.decrypt(account.encrypted_client_id or "")
        client = OzonClient(client_id, api_key)
        count = await self._sync_ozon_total_stocks(account, client)
        count += await self._sync_ozon_warehouse_stocks(account, client)
        return count

    async def _sync_ozon_total_stocks(
        self,
        account: MarketplaceAccount,
        client: OzonClient,
    ) -> int:
        count = 0
        cursor = ""
        while True:
            data = await client.get_product_info_stocks_page(cursor=cursor, limit=1000)
            rows = self._extract_rows(data)
            for row in rows:
                product = await self.products.find_for_order_item(
                    account_id=account.id,
                    marketplace=Marketplace.OZON,
                    seller_article=str(row.get("offer_id") or ""),
                    marketplace_article=str(row.get("sku") or ""),
                    external_product_id=str(row.get("product_id") or row.get("sku") or ""),
                )
                quantity = self._quantity_from_stock_row(row)
                await self._add_snapshot(
                    account,
                    product,
                    quantity,
                    {**row, "warehouseName": row.get("warehouseName") or "Ozon: общий остаток"},
                )
                count += 1
            cursor = self._next_cursor(data)
            if not cursor:
                break
        logger.info(
            "ozon_total_stock_sync_completed",
            extra={"account_id": account.id, "snapshots": count},
        )
        return count

    async def _sync_ozon_warehouse_stocks(
        self,
        account: MarketplaceAccount,
        client: OzonClient,
    ) -> int:
        count = 0
        offset = 0
        while True:
            try:
                data = await client.get_product_info_warehouse_stocks(limit=1000, offset=offset)
            except Exception:
                logger.exception(
                    "ozon_warehouse_stock_load_failed",
                    extra={"account_id": account.id, "offset": offset},
                )
                return count
            rows = self._extract_rows(data)
            if not rows:
                break
            for row in rows:
                product = await self.products.find_for_order_item(
                    account_id=account.id,
                    marketplace=Marketplace.OZON,
                    seller_article=str(row.get("offer_id") or ""),
                    marketplace_article=str(row.get("sku") or ""),
                    external_product_id=str(row.get("product_id") or row.get("sku") or ""),
                )
                quantity = self._quantity_from_stock_row(row)
                warehouse = (
                    row.get("warehouse_name")
                    or row.get("warehouseName")
                    or row.get("warehouse_id")
                    or row.get("warehouseId")
                    or "склад Ozon"
                )
                await self._add_snapshot(
                    account,
                    product,
                    quantity,
                    {
                        **row,
                        "warehouseName": f"Ozon FBS: {warehouse}",
                        "stock_source": "OZON_WAREHOUSE_STOCKS",
                    },
                )
                count += 1
            if len(rows) < 1000:
                break
            offset += 1000
        logger.info(
            "ozon_warehouse_stock_sync_completed",
            extra={"account_id": account.id, "snapshots": count},
        )
        return count

    @staticmethod
    def _next_cursor(data: dict[str, Any]) -> str:
        result = data.get("result")
        if isinstance(result, dict):
            value = result.get("cursor") or result.get("last_id")
            return str(value or "")
        value = data.get("cursor") or data.get("last_id")
        return str(value or "")

    async def create_low_stock_alerts(self, threshold: int = 5) -> int:
        result = await self.session.execute(
            select(StockSnapshot).order_by(
                StockSnapshot.product_id, StockSnapshot.snapshot_at.desc()
            )
        )
        latest_by_product: dict[int | None, StockSnapshot] = {}
        for snapshot in result.scalars().all():
            if snapshot.product_id not in latest_by_product:
                latest_by_product[snapshot.product_id] = snapshot
        created = 0
        for snapshot in latest_by_product.values():
            if snapshot.quantity > threshold:
                continue
            key = f"low_stock:{snapshot.product_id}:{snapshot.quantity}"
            if await self._alert_exists(key):
                continue
            self.session.add(
                AlertEvent(
                    user_id=snapshot.user_id,
                    rule_id=None,
                    alert_type=AlertType.LOW_STOCK,
                    idempotency_key=key,
                    title="Низкий остаток",
                    message=f"📦 Остаток товара ниже порога: {snapshot.quantity} шт.",
                    payload={"product_id": snapshot.product_id, "quantity": snapshot.quantity},
                )
            )
            created += 1
        await self.session.commit()
        return created

    async def create_stockout_forecast_alerts(self, threshold_days: int = 7) -> int:
        user_result = await self.session.execute(select(StockSnapshot.user_id).distinct())
        created = 0
        for user_id in user_result.scalars().all():
            rows = await StockForecastService(self.session).forecast(user_id=int(user_id))
            for row in rows:
                if row.product_id is None or row.days_until_stockout is None:
                    continue
                if row.days_until_stockout > threshold_days:
                    continue
                key = f"stockout:{row.product_id}:{row.warehouse}:{row.days_until_stockout}"
                if await self._alert_exists(key):
                    continue
                self.session.add(
                    AlertEvent(
                        user_id=int(user_id),
                        rule_id=None,
                        alert_type=AlertType.STOCKOUT_FORECAST,
                        idempotency_key=key,
                        title="Риск out-of-stock",
                        message=(
                            f"📦 {row.title}: запас закончится примерно через "
                            f"{row.days_until_stockout} дн. Возможная упущенная выручка "
                            f"за 30 дней: {row.lost_revenue_30d:.0f} ₽."
                        ),
                        payload={
                            "product_id": row.product_id,
                            "warehouse": row.warehouse,
                            "days_until_stockout": str(row.days_until_stockout),
                            "lost_revenue_30d": str(row.lost_revenue_30d),
                        },
                    )
                )
                created += 1
        await self.session.commit()
        return created

    async def _add_snapshot(
        self,
        account: MarketplaceAccount,
        product: Product | None,
        quantity: int,
        raw: dict[str, Any],
    ) -> None:
        self.session.add(
            StockSnapshot(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                product_id=product.id if product else None,
                marketplace=account.marketplace,
                warehouse=str(raw.get("warehouseName") or raw.get("warehouse") or ""),
                quantity=quantity,
                average_daily_sales_7d=None,
                days_until_stockout=None,
                snapshot_at=datetime.now(tz=UTC),
                raw_payload=raw,
            )
        )

    @staticmethod
    def _extract_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("stocks", "items", "data", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        result = data.get("result")
        if isinstance(result, dict):
            return StockService._extract_rows(result)
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        return []

    async def _list_products_for_account(self, account: MarketplaceAccount) -> list[Product]:
        result = await self.session.execute(
            select(Product)
            .where(Product.marketplace_account_id == account.id)
            .where(Product.marketplace == account.marketplace)
            .where(Product.is_active.is_(True))
        )
        return list(result.scalars().all())

    @staticmethod
    def _quantity_from_stock_row(row: dict[str, Any]) -> int:
        for key in (
            "amount",
            "quantity",
            "qty",
            "stock",
            "present",
            "free_to_sell",
            "free_to_sell_amount",
            "available_stock_count",
        ):
            value = _int_or_none(row.get(key))
            if value is not None:
                return value
        raw_stocks = row.get("stocks")
        if isinstance(raw_stocks, dict):
            for key in ("present", "fbs", "fbo", "free_to_sell", "available_stock_count"):
                value = _int_or_none(raw_stocks.get(key))
                if value is not None:
                    return value
        if isinstance(raw_stocks, list):
            total = 0
            found = False
            for item in raw_stocks:
                if not isinstance(item, dict):
                    continue
                value = _int_or_none(
                    item.get("present")
                    or item.get("free_to_sell")
                    or item.get("available_stock_count")
                    or item.get("amount")
                )
                if value is not None:
                    total += value
                    found = True
            if found:
                return total
        return 0

    async def _alert_exists(self, idempotency_key: str) -> bool:
        result = await self.session.execute(
            select(AlertEvent.id).where(AlertEvent.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none() is not None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _chunks(values: list[int], size: int) -> list[list[int]]:
    return [values[index : index + size] for index in range(0, len(values), size)]
