"""version: 1.0.0
description: Normalized marketplace order schemas.
updated: 2026-05-14
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import Marketplace, SaleModel


class NormalizedOrderItem(BaseModel):
    external_product_id: str | None = None
    seller_article: str | None = None
    marketplace_article: str | None = None
    title: str | None = None
    quantity: int = 1
    buyer_price: Decimal = Decimal("0")
    seller_price: Decimal = Decimal("0")
    discounted_price: Decimal = Decimal("0")
    payout_amount_estimated: Decimal | None = None
    commission_estimated: Decimal | None = None
    logistics_estimated: Decimal | None = None
    other_marketplace_expenses_estimated: Decimal | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class NormalizedOrder(BaseModel):
    marketplace: Marketplace
    order_external_id: str
    posting_number: str | None = None
    assembly_id: str | None = None
    srid: str | None = None
    order_date: datetime
    sale_model: SaleModel | None = None
    status: str
    warehouse: str | None = None
    deadline_at: datetime | None = None
    items: list[NormalizedOrderItem]
    raw_payload: dict[str, Any] = Field(default_factory=dict)
