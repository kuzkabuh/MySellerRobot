"""version: 1.1.0
description: Master product matching, manual links, product cards, and WB/Ozon comparison service.
updated: 2026-05-15
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, desc, func, select
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
    product_id: int = 0


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


@dataclass(frozen=True)
class MarketplaceComparisonRow:
    marketplace: Marketplace
    orders: int
    sales: int
    revenue: Decimal
    estimated_profit: Decimal
    actual_profit: Decimal
    margin_percent: Decimal | None
    stock_quantity: int


@dataclass(frozen=True)
class MasterProductDetail:
    master_product_id: int
    canonical_sku: str
    title: str
    brand: str
    category: str
    image_url: str | None
    marketplace_products: tuple[MarketplaceProductInfo, ...]
    marketplace_comparison: tuple[MarketplaceComparisonRow, ...]
    recommendations: tuple[str, ...]


@dataclass(frozen=True)
class ProductMatchingCandidate:
    product_id: int
    marketplace: Marketplace
    seller_article: str
    marketplace_article: str
    title: str
    current_group: str | None
    match_method: str | None


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
        master_product_ids: dict[int, list[int]] = {}
        for master in masters:
            master_product_ids[master.id] = [
                link.product.id for link in master.links if link.product is not None
            ]
        all_product_ids = [
            product_id for product_ids in master_product_ids.values() for product_id in product_ids
        ]
        order_metrics = await self._order_metrics_by_product(all_product_ids)
        sales_counts = await self._sales_count_by_product(all_product_ids)
        stock_quantities = await self._latest_stock_quantity_by_product(all_product_ids)
        rows: list[MasterProductAnalyticsRow] = []
        for master in masters:
            products = [link.product for link in master.links if link.product is not None]
            product_ids = [product.id for product in products]
            orders = sum(
                order_metrics.get(product_id, (0, Decimal("0"), Decimal("0")))[0]
                for product_id in product_ids
            )
            revenue = sum(
                (
                    order_metrics.get(product_id, (0, Decimal("0"), Decimal("0")))[1]
                    for product_id in product_ids
                ),
                Decimal("0"),
            )
            estimated_profit = sum(
                (
                    order_metrics.get(product_id, (0, Decimal("0"), Decimal("0")))[2]
                    for product_id in product_ids
                ),
                Decimal("0"),
            )
            sales = sum(sales_counts.get(product_id, 0) for product_id in product_ids)
            stock_quantity = sum(stock_quantities.get(product_id, 0) for product_id in product_ids)
            marketplace_products = tuple(
                MarketplaceProductInfo(
                    product_id=product.id,
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

    async def detail(self, user_id: int, master_product_id: int) -> MasterProductDetail | None:
        result = await self.session.execute(
            select(MasterProduct)
            .options(selectinload(MasterProduct.links).selectinload(MasterProductLink.product))
            .where(MasterProduct.id == master_product_id)
            .where(MasterProduct.user_id == user_id)
            .where(MasterProduct.is_active.is_(True))
        )
        master = result.scalar_one_or_none()
        if master is None:
            return None
        products = [link.product for link in master.links if link.product is not None]
        product_infos = tuple(
            MarketplaceProductInfo(
                product_id=product.id,
                marketplace=product.marketplace,
                seller_article=product.seller_article or "н/д",
                marketplace_article=product.marketplace_article or product.external_product_id,
                title=product.title or master.title or "Без названия",
                brand=product.brand or master.brand or "н/д",
            )
            for product in products
        )
        comparison: list[MarketplaceComparisonRow] = []
        for marketplace in (Marketplace.WB, Marketplace.OZON):
            marketplace_ids = [
                product.id for product in products if product.marketplace == marketplace
            ]
            orders, revenue, estimated_profit = await self._order_metrics(marketplace_ids)
            sales = await self._sales_count(marketplace_ids)
            actual_profit = await self._actual_profit(marketplace_ids)
            stock_quantity = await self._latest_stock_quantity(marketplace_ids)
            margin = (
                (estimated_profit / revenue * Decimal("100")).quantize(Decimal("0.1"))
                if revenue
                else None
            )
            comparison.append(
                MarketplaceComparisonRow(
                    marketplace=marketplace,
                    orders=orders,
                    sales=sales,
                    revenue=revenue,
                    estimated_profit=estimated_profit,
                    actual_profit=actual_profit,
                    margin_percent=margin,
                    stock_quantity=stock_quantity,
                )
            )
        return MasterProductDetail(
            master_product_id=master.id,
            canonical_sku=master.canonical_sku,
            title=master.title or _first_present([product.title for product in products]),
            brand=master.brand or _first_present([product.brand for product in products]),
            category=master.category or _first_present([product.category for product in products]),
            image_url=master.image_url
            or _first_present_optional([product.image_url for product in products]),
            marketplace_products=product_infos,
            marketplace_comparison=tuple(comparison),
            recommendations=tuple(_recommendations(comparison, products)),
        )

    async def matching_candidates(self, user_id: int) -> list[ProductMatchingCandidate]:
        result = await self.session.execute(
            select(Product, MasterProduct, MasterProductLink)
            .outerjoin(MasterProductLink, MasterProductLink.product_id == Product.id)
            .outerjoin(MasterProduct, MasterProduct.id == MasterProductLink.master_product_id)
            .where(Product.user_id == user_id)
            .where(Product.is_active.is_(True))
            .order_by(Product.seller_article, Product.marketplace)
        )
        candidates: list[ProductMatchingCandidate] = []
        for product, master, link in result.all():
            candidates.append(
                ProductMatchingCandidate(
                    product_id=product.id,
                    marketplace=product.marketplace,
                    seller_article=product.seller_article or "н/д",
                    marketplace_article=product.marketplace_article or product.external_product_id,
                    title=product.title or "Без названия",
                    current_group=master.canonical_sku if master else None,
                    match_method=link.match_method if link else None,
                )
            )
        return candidates

    async def create_manual_group(
        self, user_id: int, product_ids: list[int]
    ) -> MasterProduct | None:
        if not product_ids:
            return None
        result = await self.session.execute(
            select(Product).where(Product.user_id == user_id).where(Product.id.in_(product_ids))
        )
        products = list(result.scalars().all())
        if not products:
            return None
        canonical_sku = (
            normalize_master_sku(products[0].seller_article) or f"MANUAL-{products[0].id}"
        )
        master = await self.master_products.get_or_create(
            user_id=user_id,
            canonical_sku=canonical_sku,
            title=products[0].title,
            brand=products[0].brand,
            category=products[0].category,
            image_url=products[0].image_url,
        )
        for product in products:
            await self.master_products.link_product(
                master_product_id=master.id,
                product=product,
                match_method="MANUAL",
            )
        await self.session.flush()
        return master

    async def unlink_product(self, user_id: int, product_id: int) -> None:
        await self.session.execute(
            delete(MasterProductLink)
            .where(MasterProductLink.product_id == product_id)
            .where(
                MasterProductLink.master_product_id.in_(
                    select(MasterProduct.id).where(MasterProduct.user_id == user_id)
                )
            )
        )
        await self.session.flush()

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

    async def _order_metrics_by_product(
        self,
        product_ids: list[int],
    ) -> dict[int, tuple[int, Decimal, Decimal]]:
        if not product_ids:
            return {}
        result = await self.session.execute(
            select(
                OrderItem.product_id,
                func.count(OrderItem.id),
                func.coalesce(func.sum(OrderItem.discounted_price * OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.profit_estimated), 0),
            )
            .where(OrderItem.product_id.in_(product_ids))
            .group_by(OrderItem.product_id)
        )
        return {
            int(product_id): (
                int(orders or 0),
                Decimal(str(revenue or 0)),
                Decimal(str(estimated_profit or 0)),
            )
            for product_id, orders, revenue, estimated_profit in result.all()
            if product_id is not None
        }

    async def _sales_count(self, product_ids: list[int]) -> int:
        if not product_ids:
            return 0
        result = await self.session.execute(
            select(func.coalesce(func.sum(SalesEvent.quantity), 0)).where(
                SalesEvent.product_id.in_(product_ids)
            )
        )
        return int(result.scalar_one() or 0)

    async def _sales_count_by_product(self, product_ids: list[int]) -> dict[int, int]:
        if not product_ids:
            return {}
        result = await self.session.execute(
            select(SalesEvent.product_id, func.coalesce(func.sum(SalesEvent.quantity), 0))
            .where(SalesEvent.product_id.in_(product_ids))
            .group_by(SalesEvent.product_id)
        )
        return {
            int(product_id): int(quantity or 0)
            for product_id, quantity in result.all()
            if product_id is not None
        }

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

    async def _latest_stock_quantity_by_product(self, product_ids: list[int]) -> dict[int, int]:
        if not product_ids:
            return {}
        result = await self.session.execute(
            select(StockSnapshot)
            .where(StockSnapshot.product_id.in_(product_ids))
            .order_by(StockSnapshot.product_id, desc(StockSnapshot.snapshot_at))
        )
        latest_by_product: dict[int, StockSnapshot] = {}
        for snapshot in result.scalars().all():
            if snapshot.product_id is not None and snapshot.product_id not in latest_by_product:
                latest_by_product[snapshot.product_id] = snapshot
        return {product_id: snapshot.quantity for product_id, snapshot in latest_by_product.items()}

    async def _actual_profit(self, product_ids: list[int]) -> Decimal:
        if not product_ids:
            return Decimal("0")
        from app.models.domain import ProfitSnapshot
        from app.models.enums import CalculationType

        result = await self.session.execute(
            select(func.coalesce(func.sum(ProfitSnapshot.profit), 0))
            .join(OrderItem, OrderItem.id == ProfitSnapshot.order_item_id)
            .where(OrderItem.product_id.in_(product_ids))
            .where(ProfitSnapshot.calculation_type == CalculationType.ACTUAL)
        )
        return Decimal(str(result.scalar_one() or 0))


def _first_present(values: list[str | None]) -> str:
    for value in values:
        if value:
            return value
    return "н/д"


def _first_present_optional(values: list[str | None]) -> str | None:
    for value in values:
        if value:
            return value
    return None


def _recommendations(
    comparison: list[MarketplaceComparisonRow],
    products: list[Product],
) -> list[str]:
    notes: list[str] = []
    wb = next((row for row in comparison if row.marketplace == Marketplace.WB), None)
    ozon = next((row for row in comparison if row.marketplace == Marketplace.OZON), None)
    if wb and ozon and wb.revenue and ozon.revenue:
        if (wb.margin_percent or Decimal("0")) > (ozon.margin_percent or Decimal("0")):
            notes.append("На Wildberries маржа выше, чем на Ozon.")
        elif (ozon.margin_percent or Decimal("0")) > (wb.margin_percent or Decimal("0")):
            notes.append("На Ozon маржа выше, чем на Wildberries.")
        if wb.orders > ozon.orders:
            notes.append("На WB объём заказов выше.")
        elif ozon.orders > wb.orders:
            notes.append("На Ozon объём заказов выше.")
    if any(row.stock_quantity <= 3 and row.orders > 0 for row in comparison):
        notes.append("Товар под риском out-of-stock: проверьте пополнение складов.")
    if any(product.marketplace_commission_rate is None for product in products):
        notes.append("Для части карточек не найден тариф комиссии маркетплейса.")
    if not notes:
        notes.append("Критичных отклонений по товару сейчас не найдено.")
    return notes
