"""version: 1.1.0
description: Master product matching, manual links, product cards, and WB/Ozon comparison service.
updated: 2026-05-15
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, delete, desc, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import (
    MasterProduct,
    MasterProductLink,
    OrderItem,
    Product,
    ProductCostHistory,
    SalesEvent,
    StockSnapshot,
)
from app.models.enums import Marketplace
from app.models.ozon_reports import OzonPriceSnapshot
from app.models.products import WbProductPrice
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
    status: str = ""
    status_level: str = "neutral"
    updated_at: datetime | None = None
    total_cost: Decimal | None = None


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
class PriceHistoryPoint:
    date: str
    marketplace: Marketplace
    price: Decimal | None
    discounted_price: Decimal | None


@dataclass(frozen=True)
class CostHistoryPoint:
    valid_from: str
    valid_to: str | None
    cost_price: Decimal
    package_cost: Decimal
    additional_cost: Decimal
    tax_rate: Decimal | None = None
    comment: str | None = None


@dataclass(frozen=True)
class StockHistoryPoint:
    date: str
    warehouse: str | None
    quantity: int
    avg_daily_sales: Decimal | None


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
    price_history: tuple[PriceHistoryPoint, ...] = ()
    cost_history: tuple[CostHistoryPoint, ...] = ()
    stock_history: tuple[StockHistoryPoint, ...] = ()
    status: str = ""
    status_level: str = "neutral"
    updated_at: datetime | None = None
    has_wb: bool = False
    has_ozon: bool = False


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
        latest_updates = await self._latest_product_update_batch(all_product_ids)
        total_costs = await self._total_costs_batch(all_product_ids)
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
            has_wb = any(p.marketplace == Marketplace.WB for p in products)
            has_ozon = any(p.marketplace == Marketplace.OZON for p in products)
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
            updated_at = max(
                (latest_updates.get(pid) for pid in product_ids if latest_updates.get(pid)),
                default=None,
            )
            total_cost = sum(
                (total_costs.get(pid, Decimal("0")) for pid in product_ids),
                Decimal("0"),
            )
            has_cost = total_cost > 0
            status, status_level = compute_product_status(
                has_cost=has_cost,
                profit=estimated_profit,
                stock=stock_quantity,
                has_wb=has_wb,
                has_ozon=has_ozon,
                updated_at=updated_at,
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
                    wb_products=int(has_wb),
                    ozon_products=int(has_ozon),
                    orders=orders,
                    sales=sales,
                    revenue=revenue,
                    estimated_profit=estimated_profit,
                    stock_quantity=stock_quantity,
                    marketplace_products=marketplace_products,
                    status=status,
                    status_level=status_level,
                    updated_at=updated_at,
                    total_cost=total_cost,
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
        product_ids_flat = [product.id for product in products]
        price_history = await self._price_history(product_ids_flat)
        cost_history = await self._cost_history(product_ids_flat)
        stock_history = await self._stock_history(product_ids_flat)
        has_wb = any(p.marketplace == Marketplace.WB for p in products)
        has_ozon = any(p.marketplace == Marketplace.OZON for p in products)
        has_cost = any(c.cost_price > 0 for c in cost_history)
        total_revenue = sum((c.revenue for c in comparison), Decimal("0"))
        total_profit = sum((c.estimated_profit for c in comparison), Decimal("0"))
        total_stock = sum((c.stock_quantity for c in comparison))
        total_orders = sum((c.orders for c in comparison))
        updated_at = max(
            (p.updated_at for p in products if p.updated_at),
            default=None,
        )
        status, status_level = compute_product_status(
            has_cost=has_cost,
            profit=total_profit,
            stock=total_stock,
            has_wb=has_wb,
            has_ozon=has_ozon,
            updated_at=updated_at,
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
            price_history=price_history,
            cost_history=cost_history,
            stock_history=stock_history,
            status=status,
            status_level=status_level,
            updated_at=updated_at,
            has_wb=has_wb,
            has_ozon=has_ozon,
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

    async def _price_history(
        self,
        product_ids: list[int],
    ) -> tuple[PriceHistoryPoint, ...]:
        if not product_ids:
            return ()
        points: list[PriceHistoryPoint] = []

        # WB prices — query via product external IDs + account IDs
        wb_ids = set()
        ozon_ids = set()
        for pid in product_ids:
            prod = await self.session.get(Product, pid)
            if prod is None:
                continue
            if prod.marketplace == Marketplace.WB and prod.external_product_id:
                try:
                    wb_ids.add(int(prod.external_product_id))
                except (ValueError, TypeError):
                    pass
            elif prod.marketplace == Marketplace.OZON:
                ozon_ids.add(pid)

        if wb_ids:
            wb_result = await self.session.execute(
                select(WbProductPrice)
                .where(WbProductPrice.wb_nm_id.in_(wb_ids))
                .where(WbProductPrice.price.isnot(None))
                .order_by(WbProductPrice.synced_at.desc())
                .limit(200)
            )
            for row in wb_result.scalars().all():
                points.append(PriceHistoryPoint(
                    date=row.synced_at.strftime("%d.%m %H:%M"),
                    marketplace=Marketplace.WB,
                    price=row.price,
                    discounted_price=row.discounted_price or row.price,
                ))

        if ozon_ids:
            ozon_result = await self.session.execute(
                select(OzonPriceSnapshot)
                .where(OzonPriceSnapshot.product_id.in_(ozon_ids))
                .where(OzonPriceSnapshot.price.isnot(None))
                .order_by(OzonPriceSnapshot.synced_at.desc())
                .limit(200)
            )
            for row in ozon_result.scalars().all():
                points.append(PriceHistoryPoint(
                    date=row.synced_at.strftime("%d.%m %H:%M"),
                    marketplace=Marketplace.OZON,
                    price=row.price,
                    discounted_price=row.marketing_price or row.price,
                ))

        points.sort(key=lambda p: p.date, reverse=True)
        return tuple(points[:50])

    async def _cost_history(
        self,
        product_ids: list[int],
    ) -> tuple[CostHistoryPoint, ...]:
        if not product_ids:
            return ()
        result = await self.session.execute(
            select(ProductCostHistory)
            .distinct(ProductCostHistory.valid_from, ProductCostHistory.cost_price, ProductCostHistory.package_cost, ProductCostHistory.additional_cost)
            .where(ProductCostHistory.product_id.in_(product_ids))
            .order_by(ProductCostHistory.valid_from.desc())
            .limit(100)
        )
        seen: set[tuple] = set()
        points: list[CostHistoryPoint] = []
        for c in result.scalars().all():
            key = (c.valid_from, c.cost_price, c.package_cost, c.additional_cost)
            if key not in seen:
                seen.add(key)
                points.append(CostHistoryPoint(
                    valid_from=c.valid_from.strftime("%d.%m.%Y") if c.valid_from else "н/д",
                    valid_to=c.valid_to.strftime("%d.%m.%Y") if c.valid_to else "текущая",
                    cost_price=c.cost_price,
                    package_cost=c.package_cost,
                    additional_cost=c.additional_cost,
                    tax_rate=c.tax_rate,
                    comment=c.comment,
                ))
        return tuple(points)

    async def _stock_history(
        self,
        product_ids: list[int],
    ) -> tuple[StockHistoryPoint, ...]:
        if not product_ids:
            return ()
        result = await self.session.execute(
            select(StockSnapshot)
            .where(StockSnapshot.product_id.in_(product_ids))
            .order_by(StockSnapshot.snapshot_at.desc())
            .limit(100)
        )
        seen: set[tuple[int, str | None, str]] = set()
        points: list[StockHistoryPoint] = []
        for s in result.scalars().all():
            key = (s.product_id or 0, s.warehouse, s.snapshot_at.strftime("%d.%m %H:%M"))
            if key not in seen:
                seen.add(key)
                points.append(StockHistoryPoint(
                    date=s.snapshot_at.strftime("%d.%m %H:%M"),
                    warehouse=s.warehouse,
                    quantity=s.quantity,
                    avg_daily_sales=s.average_daily_sales_7d,
                ))
        return tuple(points[:50])

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

    async def _latest_product_update(self, product_ids: list[int]) -> datetime | None:
        if not product_ids:
            return None
        result = await self.session.execute(
            select(func.max(Product.updated_at)).where(Product.id.in_(product_ids))
        )
        return result.scalar_one_or_none()

    async def _latest_product_update_batch(self, product_ids: list[int]) -> dict[int, datetime]:
        if not product_ids:
            return {}
        result = await self.session.execute(
            select(Product.id, Product.updated_at).where(Product.id.in_(product_ids))
        )
        return {int(row[0]): row[1] for row in result.all() if row[0] is not None and row[1] is not None}

    async def _total_costs_batch(self, product_ids: list[int]) -> dict[int, Decimal]:
        if not product_ids:
            return {}
        from datetime import UTC
        now = datetime.now(tz=UTC)
        result = await self.session.execute(
            select(
                ProductCostHistory.product_id,
                func.coalesce(
                    func.sum(ProductCostHistory.cost_price + ProductCostHistory.package_cost + ProductCostHistory.additional_cost), 0
                ),
            )
            .where(ProductCostHistory.product_id.in_(product_ids))
            .where(ProductCostHistory.valid_from <= now)
            .where(
                (ProductCostHistory.valid_to.is_(None))
                | (ProductCostHistory.valid_to >= now)
            )
            .group_by(ProductCostHistory.product_id)
        )
        return {int(row[0]): Decimal(str(row[1])) for row in result.all() if row[0] is not None}

    async def _total_cost_for_products(self, product_ids: list[int]) -> Decimal | None:
        if not product_ids:
            return None
        from datetime import UTC
        now = datetime.now(tz=UTC)
        result = await self.session.execute(
            select(
                func.coalesce(
                    func.sum(ProductCostHistory.cost_price + ProductCostHistory.package_cost + ProductCostHistory.additional_cost), 0
                )
            )
            .where(ProductCostHistory.product_id.in_(product_ids))
            .where(ProductCostHistory.valid_from <= now)
            .where(
                (ProductCostHistory.valid_to.is_(None))
                | (ProductCostHistory.valid_to >= now)
            )
        )
        total = result.scalar_one_or_none()
        return Decimal(str(total)) if total else None


def compute_product_status(
    has_cost: bool,
    profit: Decimal,
    stock: int,
    has_wb: bool,
    has_ozon: bool,
    updated_at: datetime | None = None,
) -> tuple[str, str]:
    """Return (status_label, status_level) for a master product."""
    now = datetime.now(tz=UTC)

    if updated_at and (now - updated_at) > timedelta(hours=72):
        return "Требует проверки", "warn"
    if not has_cost:
        return "Нет себестоимости", "warn"
    if profit < 0:
        return "В минусе", "bad"
    if stock <= 0:
        return "Нет остатков", "warn"
    if has_wb and has_ozon:
        return "В норме", "good"
    if has_wb or has_ozon:
        return "Не сопоставлен", "warn"
    return "В норме", "good"


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
