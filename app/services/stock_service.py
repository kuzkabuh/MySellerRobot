"""version: 1.1.0
description: Stock synchronization, stockout forecast, and low-stock alert service.
updated: 2026-05-15
"""

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
        data = await client.get_wb_warehouses_stocks()
        rows = self._extract_rows(data)
        count = 0
        for row in rows:
            product = await self.products.find_for_order_item(
                account_id=account.id,
                marketplace=Marketplace.WB,
                seller_article=str(row.get("vendorCode") or row.get("supplierArticle") or ""),
                marketplace_article=str(row.get("nmID") or row.get("nmId") or ""),
                external_product_id=str(row.get("nmID") or row.get("nmId") or ""),
            )
            quantity = int(row.get("quantity") or row.get("qty") or row.get("stock") or 0)
            await self._add_snapshot(account, product, quantity, row)
            count += 1
        return count

    async def _sync_ozon(self, account: MarketplaceAccount) -> int:
        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client_id = self.cipher.decrypt(account.encrypted_client_id or "")
        client = OzonClient(client_id, api_key)
        data = await client.get_product_info_stocks()
        rows = self._extract_rows(data)
        count = 0
        for row in rows:
            product = await self.products.find_for_order_item(
                account_id=account.id,
                marketplace=Marketplace.OZON,
                seller_article=str(row.get("offer_id") or ""),
                marketplace_article=str(row.get("sku") or ""),
                external_product_id=str(row.get("product_id") or row.get("sku") or ""),
            )
            raw_stocks = row.get("stocks")
            stocks = raw_stocks if isinstance(raw_stocks, dict) else {}
            quantity = int(
                row.get("present")
                or row.get("free_to_sell_amount")
                or stocks.get("present")
                or stocks.get("fbs")
                or 0
            )
            await self._add_snapshot(account, product, quantity, row)
            count += 1
        return count

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

    async def _alert_exists(self, idempotency_key: str) -> bool:
        result = await self.session.execute(
            select(AlertEvent.id).where(AlertEvent.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none() is not None
