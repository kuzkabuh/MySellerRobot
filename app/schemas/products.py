"""version: 1.0.0
description: Product synchronization and cost update schemas.
updated: 2026-05-14
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import Marketplace


class ProductUpsert(BaseModel):
    user_id: int
    marketplace_account_id: int
    marketplace: Marketplace
    external_product_id: str
    seller_article: str | None = None
    marketplace_article: str | None = None
    title: str | None = None
    brand: str | None = None
    image_url: str | None = None
    category: str | None = None
    is_active: bool = True


class CostUpdate(BaseModel):
    product_id: int
    cost_price: Decimal
    package_cost: Decimal = Decimal("0")
    additional_cost: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    valid_from: datetime
    comment: str | None = None
