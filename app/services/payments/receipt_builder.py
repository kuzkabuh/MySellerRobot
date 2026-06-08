"""version: 1.0.0
description: YooKassa receipt builder for subscription payments.
updated: 2026-06-08
"""

from decimal import Decimal
from typing import Any

_PERIOD_LABELS = {
    "monthly": "1 месяц",
    "3_months": "3 месяца",
    "6_months": "6 месяцев",
    "yearly": "1 год",
}


def build_subscription_receipt(
    *,
    tier_name: str,
    period: str,
    amount: Decimal,
    customer_email: str,
) -> dict[str, Any]:
    """Build YooKassa-compliant receipt for a subscription payment.

    Args:
        tier_name: Name of subscription tier
        period: Payment period (monthly, 3_months, 6_months, yearly)
        amount: Payment amount in RUB
        customer_email: Customer email for receipt

    Returns:
        Receipt dict for YooKassa API
    """
    period_label = _PERIOD_LABELS.get(period, period)
    item_description = f"Подписка MP Control — тариф {tier_name}, {period_label}"

    return {
        "customer": {"email": customer_email},
        "items": [
            {
                "description": item_description,
                "quantity": "1.00",
                "amount": {"value": str(amount), "currency": "RUB"},
                "vat_code": 1,
                "payment_subject": "service",
                "payment_mode": "full_payment",
            }
        ],
    }


def get_period_label(period: str) -> str:
    """Get human-readable period label.

    Args:
        period: Period code

    Returns:
        Localized period label
    """
    return _PERIOD_LABELS.get(period, period)
