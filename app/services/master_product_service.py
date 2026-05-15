"""version: 1.0.0
description: Master product matching and WB/Ozon comparison service.
updated: 2026-05-15
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import (
    MasterProduct,
    MasterProductLink,
    OrderItem,
    Product,
    SalesEvent,
    StockSnapshot,
)
from app.models.enums import Marketplace
from app.repositories.products import MasterProductRepository, ProductRepository


@dataclass(frozen=True)
class MarketplaceProductInfo:
    """Product identifiers for one marketplace inside a master product."""

    marketplace: Marketplace
    seller_article: str
    marketplace_article: str
    title: str
    brand: str


@dataclass(frozen=True)
class MasterProductAnalyticsRow:
    """Aggregated product row for cross-marketplace comparison."""

    master_product_id: int
    canonical_sku: str
    title: str
    brand: str
    category: str
    image_url: str | None
    wb_products: int
    ozon_products: int
    orders: int
    sales: int
    revenue: Decimal
    estimated_profit: Decimal
    stock_quantity: int
    marketplace_products: tuple[MarketplaceProductInfo, ...]


def normalize_master_sku(value: str | None) -> str | None:
    """Return a stable SKU key for automatic WB/Ozon product matching."""

    if not value:
        return None
    normalized = "".join(str(value).strip().upper().split())
    return normalized or None


class MasterProductService:
    """Link marketplace products into internal master products and aggregate metrics."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.products = ProductRepository(session)
        self.master_products = MasterProductRepository(session)

    async def ensure_product_linked(self, product: Product) -> MasterProduct | None:
        canonical_sku = normalize_master_sku(product.seller_article) or normalize_master_sku(
            product.external_product_id
        )
        if canonical_sku is None:
            return None
        master_product = await self.master_products.get_or_create(
            user_id=product.user_id,
            canonical_sku=canonical_sku,
            title=product.title,
            brand=product.brand,
            category=product.category,
            image_url=product.image_url,
        )
        await self.master_products.link_product(
            master_product_id=master_product.id,
            product=product,
            match_method="AUTO_SELLER_ARTICLE" if product.seller_article else "AUTO_EXTERNAL_ID",
        )
        return master_product

    async def ensure_user_products_linked(self, user_id: int) -> int:
        products = await self.products.list_active_for_user(user_id)
        linked = 0
        for product in products:
            if await self.ensure_product_linked(product):
                linked += 1
        await self.session.flush()
        return linked

    async def list_analytics(self, user_id: int) -> list[MasterProductAnalyticsRow]:
        await self.ensure_user_products_linked(user_id)
        result = await self.session.execute(
            select(MasterProduct)
            .options(selectinload(MasterProduct.links).selectinload(MasterProductLink.product))
            .where(MasterProduct.user_id == user_id)
            .where(MasterProduct.is_active.is_(True))
            .order_by(MasterProduct.canonical_sku)
        )
        masters = list(result.scalars().unique().all())
        rows: list[MasterProductAnalyticsRow] = []
        for master in masters:
            products = [link.product for link in master.links if link.product is not None]
            product_ids = [product.id for product in products]
            orders, revenue, estimated_profit = await self._order_metrics(product_ids)
            sales = await self._sales_count(product_ids)
            stock_quantity = await self._latest_stock_quantity(product_ids)
            marketplace_products = tuple(
                MarketplaceProductInfo(
                    marketplace=product.marketplace,
                    seller_article=product.seller_article or "н/д",
                    marketplace_article=product.marketplace_article or product.external_product_id,
                    title=product.title or master.title or "Без названия",
                    brand=product.brand or master.brand or "н/д",
                )
                for product in products
            )
            rows.append(
                MasterProductAnalyticsRow(
                    master_product_id=master.id,
                    canonical_sku=master.canonical_sku,
                    title=master.title or _first_present([product.title for product in products]),
                    brand=master.brand or _first_present([product.brand for product in products]),
                    category=master.category
                    or _first_present([product.category for product in products]),
                    image_url=master.image_url
                    or _first_present([product.image_url for product in products]),
                    wb_products=sum(
                        1 for product in products if product.marketplace == Marketplace.WB
                    ),
                    ozon_products=sum(
                        1 for product in products if product.marketplace == Marketplace.OZON
                    ),
                    orders=orders,
                    sales=sales,
                    revenue=revenue,
                    estimated_profit=estimated_profit,
                    stock_quantity=stock_quantity,
                    marketplace_products=marketplace_products,
                )
            )
        return rows

    async def _order_metrics(self, product_ids: list[int]) -> tuple[int, Decimal, Decimal]:
        if not product_ids:
            return 0, Decimal("0"), Decimal("0")
        result = await self.session.execute(
            select(
                func.count(OrderItem.id),
                func.coalesce(func.sum(OrderItem.discounted_price * OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.profit_estimated), 0),
            ).where(OrderItem.product_id.in_(product_ids))
        )
        orders, revenue, estimated_profit = result.one()
        return int(orders or 0), Decimal(str(revenue or 0)), Decimal(str(estimated_profit or 0))

    async def _sales_count(self, product_ids: list[int]) -> int:
        if not product_ids:
            return 0
        result = await self.session.execute(
            select(func.coalesce(func.sum(SalesEvent.quantity), 0)).where(
                SalesEvent.product_id.in_(product_ids)
            )
        )
        return int(result.scalar_one() or 0)

    async def _latest_stock_quantity(self, product_ids: list[int]) -> int:
        if not product_ids:
            return 0
        result = await self.session.execute(
            select(StockSnapshot)
            .where(StockSnapshot.product_id.in_(product_ids))
            .order_by(StockSnapshot.product_id, desc(StockSnapshot.snapshot_at))
        )
        latest_by_product: dict[int, StockSnapshot] = {}
        for snapshot in result.scalars().all():
            if snapshot.product_id is not None and snapshot.product_id not in latest_by_product:
                latest_by_product[snapshot.product_id] = snapshot
        return sum(snapshot.quantity for snapshot in latest_by_product.values())


def _first_present(values: list[str | None]) -> str:
    for value in values:
        if value:
            return value
    return "н/д"
