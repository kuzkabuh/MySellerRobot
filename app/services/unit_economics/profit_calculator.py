"""version: 1.1.0
description: Centralized estimated and actual profit calculation service.
updated: 2026-05-15
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
        missing_commission = data.marketplace_commission is None
        marketplace_commission = data.marketplace_commission or Decimal("0")
        if missing_commission:
            warnings.append(
                "Комиссия маркетплейса не указана. Прибыль рассчитана без учёта комиссии"
            )

        # Расходы маркетплейса
        marketplace_expenses = (
            marketplace_commission
            + data.logistics_cost
            + data.acquiring_cost
            + data.storage_cost
            + data.return_cost
            + data.other_marketplace_costs
        )

        # Выручка продавца (после вычета расходов МП)
        seller_payout = data.expected_payout
        if seller_payout is None:
            seller_payout = data.gross_revenue - marketplace_expenses

        # Налог
        if data.fixed_tax_amount is not None:
            tax_amount = money(data.fixed_tax_amount)
        else:
            tax_base = data.tax_base if data.tax_base is not None else seller_payout
            tax_amount = money(tax_base * cost.tax_rate)

        # Расходы продавца
        seller_expenses = cost.cost_price + cost.package_cost + cost.additional_cost + tax_amount

        # Чистая прибыль
        profit = money(seller_payout - seller_expenses)

        # Маржа от выручки продавца
        margin = Decimal("0")
        if seller_payout > 0:
            margin = (profit / seller_payout * Decimal("100")).quantize(
                PERCENT_QUANT,
                rounding=ROUND_HALF_UP,
            )

        return ProfitResult(
            gross_revenue=money(data.gross_revenue),
            expected_payout=money(seller_payout),
            marketplace_commission=money(marketplace_commission),
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
