"""version: 1.0.0
description: Normalized marketplace order schemas.
updated: 2026-05-14
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import Marketplace, SaleModel, SourceEventType, UrgencyType


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
    seller_payout_estimated: Decimal | None = None
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
    fulfillment_type: str | None = None
    urgency_type: UrgencyType | None = None
    source_event_type: SourceEventType | None = None
    status: str
    raw_status: str | None = None
    normalized_status: str | None = None
    warehouse: str | None = None
    warehouse_type: str | None = None
    delivery_schema: str | None = None
    deadline_at: datetime | None = None
    processing_deadline_at: datetime | None = None
    requires_seller_action: bool = False
    items: list[NormalizedOrderItem]
    raw_payload: dict[str, Any] = Field(default_factory=dict)
