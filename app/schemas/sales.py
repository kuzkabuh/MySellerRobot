"""version: 1.0.0
description: Normalized completed sale and buyout event DTOs.
updated: 2026-05-14
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.models.enums import Marketplace, SaleEventType


@dataclass(slots=True)
class NormalizedSaleEvent:
    marketplace: Marketplace
    external_event_id: str
    order_external_id: str | None
    event_type: SaleEventType
    event_date: datetime
    external_product_id: str | None
    seller_article: str | None
    marketplace_article: str | None
    title: str | None
    quantity: int
    amount: Decimal
    expected_payout: Decimal | None = None
    sale_model: str | None = None
    status: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
