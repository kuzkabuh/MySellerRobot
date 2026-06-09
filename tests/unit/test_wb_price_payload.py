"""Tests for WB price payload calculation and quarantine guard."""

from decimal import Decimal

from app.services.wb.pricing.wb_price_update_service import (
    calculate_wb_price_payload_for_target,
    is_quarantine_risk,
)


# Test 1: Basic price payload calculation
def test_price_payload_basic():
    """target_discounted_price=846, discount=75
    price_before_discount = ceil(846 / 0.25) = 3384
    final_price = 3384 * 0.25 = 846
    """
    payload = calculate_wb_price_payload_for_target(
        target_discounted_price=Decimal("846"),
        discount_percent=Decimal("75"),
        nm_id=345455998,
    )

    assert payload.price == 3384
    assert payload.discount == 75
    assert payload.final_discounted_price == Decimal("846.00")
    assert payload.nm_id == 345455998


# Test 2: Rounding adjustment - final_price > target
def test_price_payload_rounding_adjustment():
    """target=100, discount=75
    price = ceil(100 / 0.25) = 400
    final = 400 * 0.25 = 100 (exact, no adjustment needed)
    """
    payload = calculate_wb_price_payload_for_target(
        target_discounted_price=Decimal("100"),
        discount_percent=Decimal("75"),
    )

    assert payload.price == 400
    assert payload.final_discounted_price == Decimal("100.00")


# Test 3: Quarantine guard - 3x lower
def test_quarantine_risk_3x_lower():
    """old=3000, target=900 -> target <= old/3 -> quarantine risk"""
    assert (
        is_quarantine_risk(
            old_discounted_price=Decimal("3000"),
            target_discounted_price=Decimal("900"),
        )
        is True
    )


# Test 4: Quarantine guard - just above threshold
def test_quarantine_risk_above_threshold():
    """old=3000, target=1001 -> target > old/3 -> no quarantine risk"""
    assert (
        is_quarantine_risk(
            old_discounted_price=Decimal("3000"),
            target_discounted_price=Decimal("1001"),
        )
        is False
    )


# Test 5: Quarantine guard - no old price
def test_quarantine_risk_no_old_price():
    """No old price -> no quarantine risk"""
    assert (
        is_quarantine_risk(
            old_discounted_price=None,
            target_discounted_price=Decimal("846"),
        )
        is False
    )


# Test 6: Quarantine guard - zero old price
def test_quarantine_risk_zero_old_price():
    """Zero old price -> no quarantine risk"""
    assert (
        is_quarantine_risk(
            old_discounted_price=Decimal("0"),
            target_discounted_price=Decimal("846"),
        )
        is False
    )


# Test 7: Quarantine guard - exact 3x
def test_quarantine_risk_exact_3x():
    """old=3000, target=1000 -> target == old/3 -> quarantine risk"""
    assert (
        is_quarantine_risk(
            old_discounted_price=Decimal("3000"),
            target_discounted_price=Decimal("1000"),
        )
        is True
    )


# Test 8: Price payload with different discount
def test_price_payload_different_discount():
    """target=500, discount=50
    price = ceil(500 / 0.5) = 1000
    final = 1000 * 0.5 = 500
    """
    payload = calculate_wb_price_payload_for_target(
        target_discounted_price=Decimal("500"),
        discount_percent=Decimal("50"),
    )

    assert payload.price == 1000
    assert payload.discount == 50
    assert payload.final_discounted_price == Decimal("500.00")


# Test 9: Price payload with rounding down needed
def test_price_payload_rounding_down():
    """target=847, discount=75
    price = ceil(847 / 0.25) = 3388
    final = 3388 * 0.25 = 847 (exact)
    """
    payload = calculate_wb_price_payload_for_target(
        target_discounted_price=Decimal("847"),
        discount_percent=Decimal("75"),
    )

    assert payload.price == 3388
    assert payload.final_discounted_price == Decimal("847.00")


# Test 10: Price payload with odd target
def test_price_payload_odd_target():
    """target=845, discount=75
    price = ceil(845 / 0.25) = 3380
    final = 3380 * 0.25 = 845
    """
    payload = calculate_wb_price_payload_for_target(
        target_discounted_price=Decimal("845"),
        discount_percent=Decimal("75"),
    )

    assert payload.price == 3380
    assert payload.final_discounted_price == Decimal("845.00")
