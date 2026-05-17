"""version: 1.4.0
description: Product dimensions, tariffs, manual matching, and cost history persistence.
updated: 2026-05-17
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    MarketplaceAccount,
    MasterProduct,
    MasterProductLink,
    Product,
    ProductCostHistory,
)
from app.models.enums import Marketplace
from app.schemas.products import CostUpdate, ProductUpsert


class ProductRepository:
    """Repository for marketplace products."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, data: ProductUpsert) -> Product:
        existing = await self.get_by_external_id(
            data.marketplace_account_id,
            data.marketplace,
            data.external_product_id,
        )
        if existing is None:
            existing = Product(**data.model_dump())
            self.session.add(existing)
        else:
            for field, value in data.model_dump().items():
                if (
                    field
                    in {
                        "marketplace_commission_rate",
                        "marketplace_commission_source",
                        "length_cm",
                        "width_cm",
                        "height_cm",
                        "volume_liters",
                        "dimensions_source",
                    }
                    and value is None
                ):
                    continue
                setattr(existing, field, value)
        await self.session.flush()
        return existing

    async def get_by_external_id(
        self,
        account_id: int,
        marketplace: Marketplace,
        external_product_id: str,
    ) -> Product | None:
        result = await self.session.execute(
            select(Product).where(
                Product.marketplace_account_id == account_id,
                Product.marketplace == marketplace,
                Product.external_product_id == external_product_id,
            )
        )
        return result.scalar_one_or_none()

    async def find_for_user_by_article(
        self,
        user_id: int,
        article: str,
        account_name: str | None = None,
        marketplace: Marketplace | None = None,
    ) -> list[Product]:
        query = select(Product).where(
            Product.user_id == user_id,
            or_(
                Product.seller_article == article,
                Product.marketplace_article == article,
                Product.external_product_id == article,
            ),
        )
        if marketplace:
            query = query.where(Product.marketplace == marketplace)
        if account_name:
            from app.models.domain import MarketplaceAccount

            query = query.join(
                MarketplaceAccount,
                MarketplaceAccount.id == Product.marketplace_account_id,
            ).where(MarketplaceAccount.name == account_name)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def find_for_order_item(
        self,
        *,
        account_id: int,
        marketplace: Marketplace,
        seller_article: str | None,
        marketplace_article: str | None,
        external_product_id: str | None,
    ) -> Product | None:
        identifiers = [
            value for value in [seller_article, marketplace_article, external_product_id] if value
        ]
        if not identifiers:
            return None
        result = await self.session.execute(
            select(Product)
            .where(Product.marketplace_account_id == account_id)
            .where(Product.marketplace == marketplace)
            .where(
                or_(
                    Product.seller_article.in_(identifiers),
                    Product.marketplace_article.in_(identifiers),
                    Product.external_product_id.in_(identifiers),
                )
            )
            .order_by(Product.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_for_user(self, user_id: int) -> int:
        result = await self.session.execute(select(Product.id).where(Product.user_id == user_id))
        return len(result.scalars().all())

    async def list_template_rows_for_user(
        self,
        user_id: int,
    ) -> list[tuple[Product, MarketplaceAccount]]:
        result = await self.session.execute(
            select(Product, MarketplaceAccount)
            .join(MarketplaceAccount, MarketplaceAccount.id == Product.marketplace_account_id)
            .where(Product.user_id == user_id)
            .where(Product.is_active.is_(True))
            .order_by(Product.marketplace, MarketplaceAccount.name, Product.seller_article)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def list_active_for_user(self, user_id: int) -> list[Product]:
        result = await self.session.execute(
            select(Product)
            .where(Product.user_id == user_id)
            .where(Product.is_active.is_(True))
            .order_by(Product.seller_article, Product.marketplace)
        )
        return list(result.scalars().all())


class MasterProductRepository:
    """Repository for unified products across marketplaces."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(
        self,
        *,
        user_id: int,
        canonical_sku: str,
        title: str | None,
        brand: str | None,
        category: str | None,
        image_url: str | None,
    ) -> MasterProduct:
        existing = await self.session.execute(
            select(MasterProduct).where(
                MasterProduct.user_id == user_id,
                MasterProduct.canonical_sku == canonical_sku,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = MasterProduct(
                user_id=user_id,
                canonical_sku=canonical_sku,
                title=title,
                brand=brand,
                category=category,
                image_url=image_url,
            )
            self.session.add(row)
        else:
            row.title = row.title or title
            row.brand = row.brand or brand
            row.category = row.category or category
            row.image_url = row.image_url or image_url
            row.is_active = True
        await self.session.flush()
        return row

    async def link_product(
        self,
        *,
        master_product_id: int,
        product: Product,
        match_method: str,
        confidence: Decimal = Decimal("1.0000"),
    ) -> MasterProductLink:
        existing = await self.session.execute(
            select(MasterProductLink).where(MasterProductLink.product_id == product.id)
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = MasterProductLink(
                master_product_id=master_product_id,
                product_id=product.id,
                marketplace=product.marketplace,
                seller_article=product.seller_article,
                marketplace_article=product.marketplace_article,
                match_method=match_method,
                confidence=confidence,
            )
            self.session.add(row)
        else:
            if row.match_method == "MANUAL" and match_method != "MANUAL":
                return row
            row.master_product_id = master_product_id
            row.marketplace = product.marketplace
            row.seller_article = product.seller_article
            row.marketplace_article = product.marketplace_article
            row.match_method = match_method
            row.confidence = confidence
        await self.session.flush()
        return row

    async def linked_product_ids(self, user_id: int) -> set[int]:
        result = await self.session.execute(
            select(MasterProductLink.product_id)
            .join(MasterProduct, MasterProduct.id == MasterProductLink.master_product_id)
            .where(MasterProduct.user_id == user_id)
        )
        return set(result.scalars().all())


class ProductCostRepository:
    """Repository for product cost history."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_cost(self, data: CostUpdate) -> ProductCostHistory:
        await self.close_current_cost(data.product_id, data.valid_from)
        row = ProductCostHistory(
            product_id=data.product_id,
            cost_price=data.cost_price,
            package_cost=data.package_cost,
            additional_cost=data.additional_cost,
            tax_rate=data.tax_rate,
            valid_from=data.valid_from,
            valid_to=None,
            comment=data.comment,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def close_current_cost(self, product_id: int, valid_from: datetime) -> None:
        result = await self.session.execute(
            select(ProductCostHistory)
            .where(ProductCostHistory.product_id == product_id)
            .where(ProductCostHistory.valid_from < valid_from)
            .where(ProductCostHistory.valid_to.is_(None))
            .order_by(ProductCostHistory.valid_from.desc())
            .limit(1)
        )
        current = result.scalar_one_or_none()
        if current:
            current.valid_to = valid_from
        await self.session.flush()

    async def latest_for_product(self, product_id: int) -> ProductCostHistory | None:
        result = await self.session.execute(
            select(ProductCostHistory)
            .where(ProductCostHistory.product_id == product_id)
            .order_by(ProductCostHistory.valid_from.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
