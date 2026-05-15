"""version: 1.1.0
description: Profit calculation schemas.
updated: 2026-05-15
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CostInput(BaseModel):
    cost_price: Decimal = Decimal("0")
    package_cost: Decimal = Decimal("0")
    additional_cost: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    valid_from: datetime | None = None


class ProfitInput(BaseModel):
    gross_revenue: Decimal = Decimal("0")
    expected_payout: Decimal | None = None
    marketplace_commission: Decimal | None = None
    logistics_cost: Decimal = Decimal("0")
    acquiring_cost: Decimal = Decimal("0")
    storage_cost: Decimal = Decimal("0")
    return_cost: Decimal = Decimal("0")
    other_marketplace_costs: Decimal = Decimal("0")
    cost: CostInput | None = None
    tax_base: Decimal | None = None
    calculation_source: str = "estimated"


class ProfitResult(BaseModel):
    gross_revenue: Decimal
    expected_payout: Decimal | None = None
    marketplace_commission: Decimal
    logistics_cost: Decimal
    acquiring_cost: Decimal
    storage_cost: Decimal
    return_cost: Decimal
    other_marketplace_costs: Decimal
    cost_price: Decimal
    package_cost: Decimal
    additional_seller_cost: Decimal
    tax_amount: Decimal
    profit: Decimal
    margin_percent: Decimal
    missing_cost: bool = False
    warnings: list[str] = Field(default_factory=list)
