"""version: 1.1.0
description: Product cost history lookup with caching.
updated: 2026-05-15
"""

from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheManager, cache_key
from app.models.domain import ProductCostHistory


class CostService:
    """Resolve cost history row active for a specific business timestamp."""

    def __init__(self, session: AsyncSession, cache: CacheManager | None = None) -> None:
        self.session = session
        self.cache = cache or CacheManager()

    async def get_actual_cost(
        self,
        product_id: int,
        at: datetime,
    ) -> ProductCostHistory | None:
        """Get actual cost for product at specific datetime with caching."""
        cache_key_str = cache_key("cost", product_id, at.isoformat())

        # Try to get from cache
        cached = await self.cache.get(cache_key_str)
        if cached is not None:
            # Reconstruct object from cached data
            return ProductCostHistory(**cached)

        # Query database
        query: Select[tuple[ProductCostHistory]] = (
            select(ProductCostHistory)
            .where(ProductCostHistory.product_id == product_id)
            .where(ProductCostHistory.valid_from <= at)
            .where((ProductCostHistory.valid_to.is_(None)) | (ProductCostHistory.valid_to > at))
            .order_by(ProductCostHistory.valid_from.desc())
            .limit(1)
        )
        result = await self.session.execute(query)
        cost = result.scalar_one_or_none()

        # Cache result for 1 hour
        if cost is not None:
            cost_dict = {
                "id": cost.id,
                "product_id": cost.product_id,
                "cost_price": float(cost.cost_price),
                "package_cost": float(cost.package_cost),
                "additional_cost": float(cost.additional_cost),
                "tax_rate": float(cost.tax_rate),
                "valid_from": cost.valid_from.isoformat(),
                "valid_to": cost.valid_to.isoformat() if cost.valid_to else None,
                "comment": cost.comment,
            }
            await self.cache.set(cache_key_str, cost_dict, ttl=3600)

        return cost


def choose_actual_cost(
    costs: list[ProductCostHistory],
    at: datetime,
) -> ProductCostHistory | None:
    """Choose active cost row from an in-memory history list."""

    active = [
        cost
        for cost in costs
        if cost.valid_from <= at and (cost.valid_to is None or cost.valid_to > at)
    ]
    return max(active, key=lambda cost: cost.valid_from, default=None)
