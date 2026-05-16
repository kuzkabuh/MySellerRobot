"""version: 1.2.0
description: Product synchronization, tariff, cost update, and master product schemas.
updated: 2026-05-15
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
    marketplace_category_id: str | None = None
    marketplace_commission_rate: Decimal | None = None
    marketplace_commission_source: str | None = None
    is_active: bool = True


class CostUpdate(BaseModel):
    product_id: int
    cost_price: Decimal
    package_cost: Decimal = Decimal("0")
    additional_cost: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    valid_from: datetime
    comment: str | None = None


class MasterProductLinkRead(BaseModel):
    marketplace: Marketplace
    seller_article: str
    marketplace_article: str
    title: str
    brand: str


class MasterProductAnalyticsRead(BaseModel):
    master_product_id: int
    canonical_sku: str
    title: str
    brand: str
    category: str
    image_url: str | None = None
    wb_products: int
    ozon_products: int
    orders: int
    sales: int
    revenue: Decimal
    estimated_profit: Decimal
    stock_quantity: int
    marketplace_products: list[MasterProductLinkRead]
