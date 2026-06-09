"""WB financial detail API operation classification.

Classifies rows from WB /api/finance/v1/sales-reports/detailed
into operation types, scopes, and determines if they represent
a real buyer order or a financial adjustment.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


# Operation types returned by classify_operation()
SALE = "sale"
RETURN = "return"
LOGISTICS = "logistics"
STORAGE = "storage"
PENALTY = "penalty"
DEDUCTION = "deduction"
PAID_ACCEPTANCE = "paid_acceptance"
COMPENSATION = "compensation"
ADJUSTMENT = "adjustment"
ACQUIRING = "acquiring"
COMMISSION = "commission"
OTHER = "other"


# Scope returned by classify_scope()
SCOPE_ORDER = "order"
SCOPE_PRODUCT = "product"
SCOPE_PERIOD = "period"
SCOPE_ACCOUNT = "account"
SCOPE_UNKNOWN = "unknown"


def classify_financial_operation(
    seller_oper_name: str | None,
    doc_type_name: str | None = None,
    bonus_type_name: str | None = None,
) -> tuple[str, str]:
    """Classify a WB financial detail row into (operation_type, category).

    Args:
        seller_oper_name: sellerOperName from the API row
        doc_type_name: docTypeName from the API row
        bonus_type_name: bonusTypeName from the API row

    Returns:
        (operation_type, category) where:
        - operation_type is one of SALE, RETURN, LOGISTICS, etc.
        - category is a human-readable grouping like "revenue", "expense", "correction"
    """
    text = _best_name(seller_oper_name, doc_type_name, bonus_type_name)

    if not text:
        return OTHER, "other"

    if any(kw in text for kw in ("возврат", "return")):
        return RETURN, "return"

    if any(kw in text for kw in ("логист", "достав", "delivery", "logistic")):
        return LOGISTICS, "logistics"

    if any(kw in text for kw in ("хранен", "storage", "хран")):
        return STORAGE, "storage"

    if any(kw in text for kw in ("приемк", "приёмк", "acceptance", "приём")):
        return PAID_ACCEPTANCE, "paid_acceptance"

    if any(kw in text for kw in ("штраф", "penalty", "fine")):
        return PENALTY, "penalty"

    if any(kw in text for kw in ("удержан", "deduction", "удержание")):
        return DEDUCTION, "deduction"

    if any(kw in text for kw in ("компенсац", "возмещ", "compensation")):
        return COMPENSATION, "compensation"

    if any(kw in text for kw in ("доплат", "additional")):
        return COMPENSATION, "compensation"

    if any(kw in text for kw in ("коррект", "adjustment", "correction")):
        return ADJUSTMENT, "adjustment"

    if any(kw in text for kw in ("эквайринг", "acquiring", "payment processing")):
        return ACQUIRING, "acquiring"

    if any(kw in text for kw in ("комисс", "commission", "reward", "вознаграж")):
        return COMMISSION, "commission"

    if any(kw in text for kw in ("продаж", "реализац", "sale")):
        return SALE, "revenue"

    return OTHER, "other"


def is_sale_operation(operation_type: str) -> bool:
    """Check if operation type represents a real buyer sale that should create an order.

    Only 'sale' operations should create Orders. Everything else is a financial
    adjustment (commission, logistics, compensation, storage, etc.)
    """
    return operation_type == SALE


def is_order_creating_operation(operation_type: str) -> bool:
    """Check if this operation type should result in an Order record.

    Returns True only for actual sales. Returns, logistics, compensations,
    penalties, etc. are financial adjustments and should NOT create orders.
    """
    return operation_type == SALE


def has_real_order_id(row: dict[str, Any]) -> bool:
    """Check if the financial row has a real order identifier.

    orderId = 0 means 'no order'. Only orderId > 0 is a valid order reference.
    """
    order_id = row.get("orderId")
    if order_id is not None:
        try:
            return int(order_id) > 0
        except (TypeError, ValueError):
            return False
    return False


def classify_srid(srid: str | None) -> bool:
    """Check if srid looks like a real order identifier (not a short code).

    Real WB srids are typically longer UUID-like strings.
    Short numeric srids might be ambiguous.
    """
    if not srid:
        return False
    text = str(srid).strip()
    if len(text) < 8:
        return False
    if text.isdigit() and len(text) < 10:
        return False
    return True


def _best_name(
    seller_oper_name: str | None,
    doc_type_name: str | None,
    bonus_type_name: str | None,
) -> str:
    """Pick the best text for classification from available fields."""
    text = (seller_oper_name or "").strip().lower()
    if text:
        return text
    text = (doc_type_name or "").strip().lower()
    if text:
        return text
    return (bonus_type_name or "").strip().lower()
