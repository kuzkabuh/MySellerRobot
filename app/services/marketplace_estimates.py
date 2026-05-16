"""version: 1.1.0
description: Marketplace expense estimates for planned order economics with tariff-aware labels.
updated: 2026-05-15
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.models.domain import Order, OrderItem
from app.models.enums import Marketplace, SaleModel

DEFAULT_WB_FBS_LOGISTICS = Decimal("92.00")
ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class ExpenseEstimate:
    commission: Decimal
    commission_rate: Decimal | None
    commission_is_known: bool
    commission_is_baseline: bool
    logistics: Decimal
    logistics_is_known: bool
    logistics_is_baseline: bool


@dataclass(frozen=True, slots=True)
class PlannedEconomics:
    revenue: Decimal
    commission: Decimal
    commission_rate: Decimal | None
    commission_is_known: bool
    commission_is_baseline: bool
    logistics: Decimal
    logistics_is_known: bool
    logistics_is_baseline: bool
    other_marketplace_costs: Decimal
    cost_price: Decimal
    package_cost: Decimal
    tax_amount: Decimal
    profit: Decimal
    margin_percent: Decimal


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def estimate_marketplace_expenses(
    order: Order,
    item: OrderItem,
    *,
    product_commission_rate: Decimal | None = None,
) -> ExpenseEstimate:
    """Return known or baseline marketplace expenses for planned calculations."""

    revenue = quantize_money((item.discounted_price or ZERO) * Decimal(item.quantity or 1))
    commission = item.commission_estimated
    commission_rate: Decimal | None = None
    commission_is_known = commission is not None
    commission_is_baseline = False
    if commission is None and product_commission_rate is not None:
        commission_rate = product_commission_rate
        commission = quantize_money(revenue * commission_rate)
        commission_is_known = True
        commission_is_baseline = True
    elif commission is not None and revenue > ZERO:
        commission_rate = quantize_money(commission / revenue)

    logistics = item.logistics_estimated
    logistics_is_known = logistics is not None and logistics != ZERO
    logistics_is_baseline = False
    if (
        (logistics is None or logistics == ZERO)
        and order.marketplace == Marketplace.WB
        and order.sale_model == SaleModel.FBS
    ):
        logistics = DEFAULT_WB_FBS_LOGISTICS
        logistics_is_known = True
        logistics_is_baseline = True

    return ExpenseEstimate(
        commission=quantize_money(commission or ZERO),
        commission_rate=commission_rate,
        commission_is_known=commission_is_known,
        commission_is_baseline=commission_is_baseline,
        logistics=quantize_money(logistics or ZERO),
        logistics_is_known=logistics_is_known,
        logistics_is_baseline=logistics_is_baseline,
    )


def calculate_planned_economics(
    order: Order,
    item: OrderItem,
    *,
    product_commission_rate: Decimal | None = None,
) -> PlannedEconomics:
    """Calculate display-safe planned profit with baseline estimates when needed."""

    expenses = estimate_marketplace_expenses(
        order, item, product_commission_rate=product_commission_rate
    )
    revenue = quantize_money((item.discounted_price or ZERO) * Decimal(item.quantity or 1))
    other = quantize_money(item.other_marketplace_expenses_estimated or ZERO)
    cost = quantize_money(item.cost_price_used or ZERO)
    package = quantize_money(item.package_cost_used or ZERO)
    tax = quantize_money(item.tax_amount_estimated or ZERO)
    profit = quantize_money(
        revenue - expenses.commission - expenses.logistics - other - cost - package - tax
    )
    margin = quantize_money(profit / revenue * Decimal("100")) if revenue > ZERO else ZERO
    return PlannedEconomics(
        revenue=revenue,
        commission=expenses.commission,
        commission_rate=expenses.commission_rate,
        commission_is_known=expenses.commission_is_known,
        commission_is_baseline=expenses.commission_is_baseline,
        logistics=expenses.logistics,
        logistics_is_known=expenses.logistics_is_known,
        logistics_is_baseline=expenses.logistics_is_baseline,
        other_marketplace_costs=other,
        cost_price=cost,
        package_cost=package,
        tax_amount=tax,
        profit=profit,
        margin_percent=margin,
    )
