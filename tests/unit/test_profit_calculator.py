"""version: 1.0.0
description: Unit tests for profit calculation.
updated: 2026-05-14
"""

from decimal import Decimal

from app.schemas.profit import CostInput, ProfitInput
from app.services.profit_calculator import ProfitCalculator


def test_profit_calculation_with_costs() -> None:
    result = ProfitCalculator().calculate(
        ProfitInput(
            gross_revenue=Decimal("1490"),
            expected_payout=Decimal("1280"),
            marketplace_commission=Decimal("256"),
            logistics_cost=Decimal("89"),
            other_marketplace_costs=Decimal("18"),
            cost=CostInput(
                cost_price=Decimal("520"),
                package_cost=Decimal("25"),
                additional_cost=Decimal("0"),
                tax_rate=Decimal("0.06"),
            ),
        )
    )

    assert result.tax_amount == Decimal("89.40")
    assert result.profit == Decimal("282.60")
    assert result.margin_percent == Decimal("18.97")
    assert not result.missing_cost


def test_profit_calculation_warns_without_cost() -> None:
    result = ProfitCalculator().calculate(ProfitInput(gross_revenue=Decimal("1000")))

    assert result.missing_cost
    assert result.warnings
