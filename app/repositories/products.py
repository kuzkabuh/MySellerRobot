"""version: 1.0.0
description: Product and cost history persistence helpers.
updated: 2026-05-14
"""

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, Product, ProductCostHistory
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
