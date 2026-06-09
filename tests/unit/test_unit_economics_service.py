"""version: 1.0.0
description: Unit tests for break-even price and price simulation calculations.
updated: 2026-05-15
"""

from decimal import Decimal

from app.models.enums import Marketplace
from app.services.unit_economics.unit_economics_service import UnitEconomicsService


def test_break_even_price_uses_commission_logistics_cost_and_tax() -> None:
    row = UnitEconomicsService(session=None).calculate_row(  # type: ignore[arg-type]
        product_id=1,
        title="Товар",
        seller_article="SKU-1",
        marketplace=Marketplace.WB,
        current_price=Decimal("1000"),
        cost_price=Decimal("400"),
        commission_amount=Decimal("200"),
        logistics_cost=Decimal("100"),
        tax_amount=Decimal("60"),
        target_margin_percent=Decimal("20"),
        price_delta_percent=Decimal("10"),
    )

    assert row.commission_rate == Decimal("20.0")
    assert row.tax_rate == Decimal("6.0")
    assert row.break_even_price == Decimal("675.68")
    assert row.target_margin_price == Decimal("925.93")
    assert row.simulated_price == Decimal("1100.00")
    assert row.simulated_profit == Decimal("314.00")
    assert row.simulated_margin_percent == Decimal("28.5")
