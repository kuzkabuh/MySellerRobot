"""version: 1.3.0
description: Product synchronization, dimensions, tariff, cost update, and master product schemas.
updated: 2026-05-17
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
    chrt_id: str | None = None
    title: str | None = None
    brand: str | None = None
    image_url: str | None = None
    category: str | None = None
    marketplace_category_id: str | None = None
    length_cm: Decimal | None = None
    width_cm: Decimal | None = None
    height_cm: Decimal | None = None
    volume_liters: Decimal | None = None
    dimensions_source: str | None = None
    marketplace_commission_rate: Decimal | None = None
    marketplace_commission_source: str | None = None
    commission_fbw: Decimal | None = None
    commission_fbs: Decimal | None = None
    commission_dbs: Decimal | None = None
    commission_edbs: Decimal | None = None
    commission_pickup: Decimal | None = None
    commission_booking: Decimal | None = None
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
