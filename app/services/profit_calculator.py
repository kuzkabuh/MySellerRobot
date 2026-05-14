"""version: 1.0.0
description: Estimated and actual profit calculation service.
updated: 2026-05-14
"""

from decimal import ROUND_HALF_UP, Decimal

from app.schemas.profit import CostInput, ProfitInput, ProfitResult

MONEY_QUANT = Decimal("0.01")
PERCENT_QUANT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


class ProfitCalculator:
    """Calculate marketplace order economics from separated expense types."""

    def calculate(self, data: ProfitInput) -> ProfitResult:
        cost = data.cost or CostInput()
        missing_cost = data.cost is None or cost.cost_price == 0
        warnings: list[str] = []
        if missing_cost:
            warnings.append("Себестоимость не задана. Прибыль рассчитана без учёта себестоимости")

        tax_base = data.tax_base if data.tax_base is not None else data.gross_revenue
        tax_amount = money(tax_base * cost.tax_rate)
        payout_or_revenue = (
            data.expected_payout if data.expected_payout is not None else data.gross_revenue
        )
        marketplace_expenses = (
            data.marketplace_commission
            + data.logistics_cost
            + data.acquiring_cost
            + data.storage_cost
            + data.return_cost
            + data.other_marketplace_costs
        )
        seller_expenses = cost.cost_price + cost.package_cost + cost.additional_cost + tax_amount
        profit = money(payout_or_revenue - marketplace_expenses - seller_expenses)
        margin = Decimal("0")
        if data.gross_revenue:
            margin = (profit / data.gross_revenue * Decimal("100")).quantize(
                PERCENT_QUANT,
                rounding=ROUND_HALF_UP,
            )

        return ProfitResult(
            gross_revenue=money(data.gross_revenue),
            marketplace_commission=money(data.marketplace_commission),
            logistics_cost=money(data.logistics_cost),
            acquiring_cost=money(data.acquiring_cost),
            storage_cost=money(data.storage_cost),
            return_cost=money(data.return_cost),
            other_marketplace_costs=money(data.other_marketplace_costs),
            cost_price=money(cost.cost_price),
            package_cost=money(cost.package_cost),
            additional_seller_cost=money(cost.additional_cost),
            tax_amount=tax_amount,
            profit=profit,
            margin_percent=margin,
            missing_cost=missing_cost,
            warnings=warnings,
        )
