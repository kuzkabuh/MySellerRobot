"""version: 1.0.0
description: Product cost history lookup helpers.
updated: 2026-05-14
"""

from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import ProductCostHistory


class CostService:
    """Resolve cost history row active for a specific business timestamp."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_actual_cost(
        self,
        product_id: int,
        at: datetime,
    ) -> ProductCostHistory | None:
        query: Select[tuple[ProductCostHistory]] = (
            select(ProductCostHistory)
            .where(ProductCostHistory.product_id == product_id)
            .where(ProductCostHistory.valid_from <= at)
            .where((ProductCostHistory.valid_to.is_(None)) | (ProductCostHistory.valid_to > at))
            .order_by(ProductCostHistory.valid_from.desc())
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()


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
