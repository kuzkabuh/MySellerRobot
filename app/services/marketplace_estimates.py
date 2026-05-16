"""version: 1.2.0
description: Marketplace expense estimates with source tracking and economy confidence.
updated: 2026-05-15
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.models.domain import Order, OrderItem
from app.models.enums import EconomyConfidence, ExpenseSource, Marketplace, SaleModel

DEFAULT_WB_FBS_LOGISTICS = Decimal("92.00")
ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class ExpenseEstimate:
    commission: Decimal
    commission_rate: Decimal | None
    commission_is_known: bool
    commission_is_baseline: bool
    commission_source: ExpenseSource
    logistics: Decimal
    logistics_is_known: bool
    logistics_is_baseline: bool
    logistics_source: ExpenseSource
    confidence: EconomyConfidence


@dataclass(frozen=True, slots=True)
class PlannedEconomics:
    revenue: Decimal
    seller_payout: Decimal
    commission: Decimal
    commission_rate: Decimal | None
    commission_is_known: bool
    commission_is_baseline: bool
    commission_source: ExpenseSource
    logistics: Decimal
    logistics_is_known: bool
    logistics_is_baseline: bool
    logistics_source: ExpenseSource
    other_marketplace_costs: Decimal
    cost_price: Decimal
    package_cost: Decimal
    tax_amount: Decimal
    profit: Decimal
    margin_percent: Decimal
    confidence: EconomyConfidence


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
    commission_source = ExpenseSource.UNKNOWN
    if commission is None and product_commission_rate is not None:
        commission_rate = product_commission_rate
        commission = quantize_money(revenue * commission_rate)
        commission_is_known = True
        commission_is_baseline = True
        commission_source = ExpenseSource.WB_TARIFF_API
    elif commission is not None and revenue > ZERO:
        commission_rate = quantize_money(commission / revenue)
        commission_source = _known_commission_source(order)

    logistics = item.logistics_estimated
    logistics_is_known = logistics is not None and logistics != ZERO
    logistics_is_baseline = False
    logistics_source = (
        ExpenseSource.FINANCIAL_REPORT if logistics_is_known else ExpenseSource.UNKNOWN
    )
    if (
        (logistics is None or logistics == ZERO)
        and order.marketplace == Marketplace.WB
        and order.sale_model == SaleModel.FBS
    ):
        logistics = DEFAULT_WB_FBS_LOGISTICS
        logistics_is_known = False
        logistics_is_baseline = True
        logistics_source = ExpenseSource.FALLBACK_DEFAULT
    elif logistics_is_known and order.marketplace == Marketplace.OZON:
        logistics_source = ExpenseSource.OZON_FINANCIAL_DATA

    confidence = economy_confidence(
        commission_source=commission_source,
        logistics_source=logistics_source,
        commission_is_known=commission_is_known,
        logistics_is_known=logistics_is_known,
    )
    return ExpenseEstimate(
        commission=quantize_money(commission or ZERO),
        commission_rate=commission_rate,
        commission_is_known=commission_is_known,
        commission_is_baseline=commission_is_baseline,
        commission_source=commission_source,
        logistics=quantize_money(logistics or ZERO),
        logistics_is_known=logistics_is_known,
        logistics_is_baseline=logistics_is_baseline,
        logistics_source=logistics_source,
        confidence=confidence,
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

    # Цена покупателя (buyer price)
    buyer_price = quantize_money((item.discounted_price or ZERO) * Decimal(item.quantity or 1))
    other = quantize_money(item.other_marketplace_expenses_estimated or ZERO)

    # Выручка продавца (seller payout) = цена покупателя - расходы МП
    seller_payout = quantize_money(item.payout_amount_estimated or ZERO)
    if seller_payout == ZERO:
        # Если нет точного значения, рассчитываем
        seller_payout = quantize_money(
            buyer_price - expenses.commission - expenses.logistics - other
        )

    # Расходы продавца
    cost = quantize_money(item.cost_price_used or ZERO)
    package = quantize_money(item.package_cost_used or ZERO)

    # Налог от выручки продавца, а не от цены покупателя!
    tax_base = seller_payout
    tax = quantize_money(item.tax_amount_estimated or ZERO)
    if tax == ZERO and item.tax_rate:
        tax = quantize_money(tax_base * item.tax_rate)

    # Чистая прибыль
    profit = quantize_money(seller_payout - cost - package - tax)

    # Маржа от выручки продавца
    margin = (
        quantize_money(profit / seller_payout * Decimal("100"))
        if seller_payout > ZERO
        else ZERO
    )

    return PlannedEconomics(
        revenue=buyer_price,
        seller_payout=seller_payout,
        commission=expenses.commission,
        commission_rate=expenses.commission_rate,
        commission_is_known=expenses.commission_is_known,
        commission_is_baseline=expenses.commission_is_baseline,
        commission_source=expenses.commission_source,
        logistics=expenses.logistics,
        logistics_is_known=expenses.logistics_is_known,
        logistics_is_baseline=expenses.logistics_is_baseline,
        logistics_source=expenses.logistics_source,
        other_marketplace_costs=other,
        cost_price=cost,
        package_cost=package,
        tax_amount=tax,
        profit=profit,
        margin_percent=margin,
        confidence=expenses.confidence,
    )


def economy_confidence(
    *,
    commission_source: ExpenseSource,
    logistics_source: ExpenseSource,
    commission_is_known: bool,
    logistics_is_known: bool,
) -> EconomyConfidence:
    """Return the overall reliability level for planned order economics."""

    if not commission_is_known or commission_source == ExpenseSource.UNKNOWN:
        return EconomyConfidence.PRELIMINARY
    if logistics_source in {ExpenseSource.UNKNOWN, ExpenseSource.FALLBACK_DEFAULT}:
        return EconomyConfidence.PRELIMINARY
    estimated_sources = {ExpenseSource.WB_TARIFF_API}
    if commission_source in estimated_sources or logistics_source in estimated_sources:
        return EconomyConfidence.ESTIMATED
    if logistics_is_known:
        return EconomyConfidence.EXACT
    return EconomyConfidence.PRELIMINARY


def confidence_label(confidence: EconomyConfidence | str | None) -> str:
    value = EconomyConfidence(confidence or EconomyConfidence.PRELIMINARY)
    labels = {
        EconomyConfidence.EXACT: "✅ Расчёт точный",
        EconomyConfidence.ESTIMATED: "🟡 Расчёт оценочный",
        EconomyConfidence.PRELIMINARY: "⚪ Расчёт предварительный",
    }
    return labels[value]


def confidence_notes(economics: PlannedEconomics) -> list[str]:
    notes: list[str] = []
    if economics.commission_source == ExpenseSource.UNKNOWN:
        notes.append("Комиссия будет уточнена после финансового отчёта.")
    elif economics.commission_source == ExpenseSource.WB_TARIFF_API:
        notes.append("Комиссия рассчитана по официальному тарифу WB и может отличаться от факта.")
    if economics.logistics_source == ExpenseSource.FALLBACK_DEFAULT:
        notes.append("Логистика использована предварительно и может измениться.")
    elif economics.logistics_source == ExpenseSource.UNKNOWN:
        notes.append("Финальная логистика появится после получения фактических данных.")
    return notes


def _known_commission_source(order: Order) -> ExpenseSource:
    if order.marketplace == Marketplace.OZON:
        return ExpenseSource.OZON_FINANCIAL_DATA
    return ExpenseSource.FINANCIAL_REPORT
