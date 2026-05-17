"""version: 1.0.0
description: Product dimension helpers for marketplace logistics and stock diagnostics.
updated: 2026-05-17
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


def decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return result if result > 0 else None


def calculate_volume_liters(
    length_cm: Any,
    width_cm: Any,
    height_cm: Any,
) -> Decimal | None:
    """Return volume in liters from centimeter dimensions, or None for incomplete data."""

    length = decimal_or_none(length_cm)
    width = decimal_or_none(width_cm)
    height = decimal_or_none(height_cm)
    if length is None or width is None or height is None:
        return None
    return (length * width * height / Decimal("1000")).quantize(
        Decimal("0.001"),
        rounding=ROUND_HALF_UP,
    )
