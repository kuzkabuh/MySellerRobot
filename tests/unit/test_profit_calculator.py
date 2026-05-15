"""version: 1.2.0
description: Unit tests for profit calculation.
updated: 2026-05-15
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
    assert result.expected_payout == Decimal("1280.00")
    assert result.profit == Decimal("492.60")
    assert result.margin_percent == Decimal("33.06")
    assert not result.missing_cost


def test_profit_calculation_warns_without_cost() -> None:
    result = ProfitCalculator().calculate(ProfitInput(gross_revenue=Decimal("1000")))

    assert result.missing_cost
    assert result.warnings


def test_profit_subtracts_marketplace_commission_once_from_gross_revenue() -> None:
    result = ProfitCalculator().calculate(
        ProfitInput(
            gross_revenue=Decimal("1000"),
            expected_payout=Decimal("850"),
            marketplace_commission=Decimal("100"),
            logistics_cost=Decimal("50"),
            cost=CostInput(cost_price=Decimal("300"), tax_rate=Decimal("0")),
        )
    )

    assert result.profit == Decimal("550.00")


def test_zero_commission_is_explicit_and_does_not_warn() -> None:
    result = ProfitCalculator().calculate(
        ProfitInput(
            gross_revenue=Decimal("1000"),
            marketplace_commission=Decimal("0"),
            cost=CostInput(cost_price=Decimal("100"), tax_rate=Decimal("0")),
        )
    )

    assert result.profit == Decimal("900.00")
    assert not any("Комиссия маркетплейса" in warning for warning in result.warnings)


def test_missing_commission_does_not_crash_and_warns() -> None:
    result = ProfitCalculator().calculate(
        ProfitInput(
            gross_revenue=Decimal("1000"),
            cost=CostInput(cost_price=Decimal("100"), tax_rate=Decimal("0")),
        )
    )

    assert result.marketplace_commission == Decimal("0.00")
    assert result.profit == Decimal("900.00")
    assert any("Комиссия маркетплейса" in warning for warning in result.warnings)


def test_profit_uses_normalized_wb_price_for_margin() -> None:
    result = ProfitCalculator().calculate(
        ProfitInput(
            gross_revenue=Decimal("411"),
            expected_payout=Decimal("411"),
            marketplace_commission=Decimal("41"),
            logistics_cost=Decimal("0"),
            other_marketplace_costs=Decimal("0"),
            cost=CostInput(cost_price=Decimal("100"), tax_rate=Decimal("0")),
        )
    )

    assert result.gross_revenue == Decimal("411.00")
    assert result.profit == Decimal("270.00")
    assert result.margin_percent == Decimal("65.69")
