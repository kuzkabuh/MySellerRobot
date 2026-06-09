"""version: 1.0.0
description: Unit tests for product dimension and volume helpers.
updated: 2026-05-17
"""

from decimal import Decimal

from app.services.common.product_dimensions import calculate_volume_liters, decimal_or_none


def test_calculate_volume_liters_from_centimeters() -> None:
    assert calculate_volume_liters(20, 10, 5) == Decimal("1.000")


def test_calculate_volume_liters_for_fractional_wb_logistics_cases() -> None:
    assert calculate_volume_liters("10", "10", "2") == Decimal("0.200")
    assert calculate_volume_liters("10", "10", "4") == Decimal("0.400")
    assert calculate_volume_liters("10", "10", "6") == Decimal("0.600")
    assert calculate_volume_liters("10", "10", "8.5") == Decimal("0.850")
    assert calculate_volume_liters("10", "10", "15") == Decimal("1.500")


def test_calculate_volume_liters_returns_none_for_incomplete_dimensions() -> None:
    assert calculate_volume_liters(10, None, 5) is None
    assert calculate_volume_liters(10, 0, 5) is None
    assert calculate_volume_liters("bad", 10, 5) is None


def test_decimal_or_none_normalizes_comma_values() -> None:
    assert decimal_or_none("2,5") == Decimal("2.5")
