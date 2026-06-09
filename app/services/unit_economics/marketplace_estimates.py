"""version: 1.3.0
description: Per-model WB commission selection with source tracking and economy confidence.
updated: 2026-05-20
"""

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.models.domain import Order, OrderItem
from app.models.enums import EconomyConfidence, ExpenseSource, Marketplace, SaleModel

logger = logging.getLogger(__name__)

DEFAULT_WB_FBS_LOGISTICS = Decimal("92.00")
ZERO = Decimal("0.00")

SALE_MODEL_TO_COMMISSION_FIELD: dict[SaleModel, str] = {
    SaleModel.FBO: "commission_fbw",
    SaleModel.FBS: "commission_fbs",
    SaleModel.RFBS: "commission_fbs",
    SaleModel.DBS: "commission_dbs",
    SaleModel.DBW: "commission_dbs",
}


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
    commission_fbw: Decimal | None = None,
    commission_fbs: Decimal | None = None,
    commission_dbs: Decimal | None = None,
    commission_edbs: Decimal | None = None,
    commission_pickup: Decimal | None = None,
    commission_booking: Decimal | None = None,
) -> ExpenseEstimate:
    """Return known or baseline marketplace expenses for planned calculations.

    For WB orders, selects the commission rate matching the order's sale_model
    from the per-model commission fields. Falls back to the legacy
    product_commission_rate only when per-model fields are not available.
    """

    revenue = quantize_money((item.discounted_price or ZERO) * Decimal(item.quantity or 1))
    commission = item.commission_estimated
    commission_rate: Decimal | None = None
    commission_is_known = commission is not None
    commission_is_baseline = False
    commission_source = ExpenseSource.UNKNOWN

    if commission is None and order.marketplace == Marketplace.WB:
        resolved_rate, resolved_field = _resolve_wb_commission(
            order=order,
            commission_fbw=commission_fbw,
            commission_fbs=commission_fbs,
            commission_dbs=commission_dbs,
            commission_edbs=commission_edbs,
            commission_pickup=commission_pickup,
            commission_booking=commission_booking,
            fallback_rate=product_commission_rate,
        )
        if resolved_rate is not None:
            commission_rate = resolved_rate
            commission = quantize_money(revenue * commission_rate)
            commission_is_known = True
            commission_is_baseline = True
            commission_source = ExpenseSource.WB_TARIFF_API
            logger.debug(
                "wb_commission_resolved",
                extra={
                    "order_id": order.id,
                    "external_order_id": order.order_external_id,
                    "nm_id": item.marketplace_article,
                    "sales_model": order.sale_model.value if order.sale_model else None,
                    "api_field": resolved_field,
                    "commission_percent": (commission_rate * Decimal("100")).quantize(
                        Decimal("0.01")
                    ),
                },
            )
    elif commission is None and product_commission_rate is not None:
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
    commission_fbw: Decimal | None = None,
    commission_fbs: Decimal | None = None,
    commission_dbs: Decimal | None = None,
    commission_edbs: Decimal | None = None,
    commission_pickup: Decimal | None = None,
    commission_booking: Decimal | None = None,
) -> PlannedEconomics:
    """Calculate display-safe planned profit with baseline estimates when needed."""

    expenses = estimate_marketplace_expenses(
        order,
        item,
        product_commission_rate=product_commission_rate,
        commission_fbw=commission_fbw,
        commission_fbs=commission_fbs,
        commission_dbs=commission_dbs,
        commission_edbs=commission_edbs,
        commission_pickup=commission_pickup,
        commission_booking=commission_booking,
    )

    # Цена покупателя (buyer price)
    buyer_price = quantize_money((item.discounted_price or ZERO) * Decimal(item.quantity or 1))
    other = quantize_money(item.other_marketplace_expenses_estimated or ZERO)

    # Выручка продавца (seller payout) = цена покупателя - расходы МП
    seller_payout = quantize_money(item.payout_amount_estimated or ZERO)
    if seller_payout == ZERO or seller_payout == buyer_price:
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

    # Маржа от цены продажи, чтобы карточки заказов совпадали с unit economics UI.
    margin = quantize_money(profit / buyer_price * Decimal("100")) if buyer_price > ZERO else ZERO

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


def _resolve_wb_commission(
    *,
    order: Order,
    commission_fbw: Decimal | None,
    commission_fbs: Decimal | None,
    commission_dbs: Decimal | None,
    commission_edbs: Decimal | None,
    commission_pickup: Decimal | None,
    commission_booking: Decimal | None,
    fallback_rate: Decimal | None,
) -> tuple[Decimal | None, str | None]:
    """Select the WB commission rate matching the order's sale_model.

    Returns (rate, api_field_name) or (None, None) if no rate found.
    Never silently falls back to a different model's commission.
    """
    sale_model = order.sale_model
    if sale_model is None:
        return (fallback_rate, None)

    field_name = SALE_MODEL_TO_COMMISSION_FIELD.get(sale_model)
    if field_name is None:
        return (fallback_rate, None)

    commission_map = {
        "commission_fbw": commission_fbw,
        "commission_fbs": commission_fbs,
        "commission_dbs": commission_dbs,
        "commission_edbs": commission_edbs,
        "commission_pickup": commission_pickup,
        "commission_booking": commission_booking,
    }

    rate = commission_map.get(field_name)
    if rate is not None:
        return (rate, field_name)

    if sale_model in (SaleModel.FBS, SaleModel.RFBS) and commission_fbw is not None:
        logger.warning(
            "wb_commission_fbs_not_found_falling_back_to_fbw",
            extra={
                "order_id": order.id,
                "sale_model": sale_model.value,
            },
        )
        return (commission_fbw, "commission_fbw")

    if sale_model == SaleModel.FBO and commission_fbs is not None:
        logger.warning(
            "wb_commission_fbw_not_found_falling_back_to_fbs",
            extra={
                "order_id": order.id,
                "sale_model": sale_model.value,
            },
        )
        return (commission_fbs, "commission_fbs")

    if fallback_rate is not None:
        logger.warning(
            "wb_commission_not_found_for_model_using_legacy_fallback",
            extra={
                "order_id": order.id,
                "sale_model": sale_model.value,
                "field_name": field_name,
            },
        )
        return (fallback_rate, None)

    logger.warning(
        "wb_commission_not_found_any_source",
        extra={
            "order_id": order.id,
            "sale_model": sale_model.value,
            "field_name": field_name,
        },
    )
    return (None, None)


def _known_commission_source(order: Order) -> ExpenseSource:
    if order.marketplace == Marketplace.OZON:
        return ExpenseSource.OZON_FINANCIAL_DATA
    return ExpenseSource.FINANCIAL_REPORT
