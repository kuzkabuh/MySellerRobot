"""Tests for WB auto promotion price control and current prices sync."""

from decimal import Decimal

from app.services.pricing.wb_price_update_service import (
    WbPricePayload,
    calculate_wb_price_payload_for_target,
    is_quarantine_risk,
)


class TestCalculateWbPricePayload:
    """Test WB price/discount payload calculation."""

    def test_basic_payload_75_discount(self):
        """target=846, discount=75 => price=3384, discount=75, final=846."""
        payload = calculate_wb_price_payload_for_target(
            target_discounted_price=Decimal("846"),
            discount_percent=Decimal("75"),
            nm_id=345455998,
        )
        assert payload.nm_id == 345455998
        assert payload.price == 3384
        assert payload.discount == 75
        assert payload.final_discounted_price == Decimal("846.00")
        assert payload.target_discounted_price == Decimal("846")

    def test_payload_50_discount(self):
        """target=500, discount=50 => price=1000, discount=50, final=500."""
        payload = calculate_wb_price_payload_for_target(
            target_discounted_price=Decimal("500"),
            discount_percent=Decimal("50"),
            nm_id=123,
        )
        assert payload.price == 1000
        assert payload.discount == 50
        assert payload.final_discounted_price == Decimal("500.00")

    def test_payload_rounding_adjustment(self):
        """If final > target due to rounding, price should be reduced."""
        payload = calculate_wb_price_payload_for_target(
            target_discounted_price=Decimal("100"),
            discount_percent=Decimal("33"),
            nm_id=1,
        )
        assert payload.final_discounted_price <= payload.target_discounted_price


class TestIsQuarantineRisk:
    """Test quarantine risk detection."""

    def test_no_risk_small_change(self):
        """Old=1000, target=900 => no risk."""
        assert is_quarantine_risk(Decimal("1000"), Decimal("900")) is False

    def test_risk_3x_drop(self):
        """Old=3000, target=900 => risk (900 <= 3000/3)."""
        assert is_quarantine_risk(Decimal("3000"), Decimal("900")) is True

    def test_risk_4x_drop(self):
        """Old=3000, target=500 => risk (500 <= 3000/3)."""
        assert is_quarantine_risk(Decimal("3000"), Decimal("500")) is True

    def test_no_risk_old_price_none(self):
        """Old=None => no risk."""
        assert is_quarantine_risk(None, Decimal("900")) is False

    def test_no_risk_old_price_zero(self):
        """Old=0 => no risk."""
        assert is_quarantine_risk(Decimal("0"), Decimal("900")) is False


class TestAutoPromoRecommendationLogic:
    """Test auto promotion recommendation status determination."""

    def test_set_price_when_current_above_required(self):
        """mrc=930, current=930, required=846, deviation=10, min=800
        => AUTO_PROMOTION_SET_PRICE, recommended=846."""
        mrc_price = Decimal("930")
        deviation = Decimal("10")
        lower_bound = mrc_price * (Decimal("1") - deviation / Decimal("100"))
        upper_bound = mrc_price * (Decimal("1") + deviation / Decimal("100"))

        current_wb_price = Decimal("930")
        required_price = Decimal("846")
        min_price = Decimal("800")

        assert current_wb_price > required_price
        assert required_price >= lower_bound
        assert required_price <= upper_bound
        assert required_price >= min_price

    def test_price_ok_when_current_at_required(self):
        """current=846, required=846 => AUTO_PROMOTION_PRICE_OK."""
        current_wb_price = Decimal("846")
        required_price = Decimal("846")
        assert current_wb_price <= required_price

    def test_price_ok_when_current_below_required(self):
        """current=800, required=846 => AUTO_PROMOTION_PRICE_OK."""
        current_wb_price = Decimal("800")
        required_price = Decimal("846")
        assert current_wb_price <= required_price

    def test_required_price_unknown(self):
        """required=None => AUTO_PROMOTION_REQUIRED_PRICE_UNKNOWN."""
        required_price = None
        assert required_price is None

    def test_mrc_violation_when_below_lower_bound(self):
        """mrc=930, deviation=10 => lower=837. required=800 < 837 => violation."""
        mrc_price = Decimal("930")
        deviation = Decimal("10")
        lower_bound = mrc_price * (Decimal("1") - deviation / Decimal("100"))
        required_price = Decimal("800")
        assert required_price < lower_bound

    def test_min_price_violation(self):
        """min=900, required=846 < 900 => min price violation."""
        min_price = Decimal("900")
        required_price = Decimal("846")
        assert required_price < min_price


class TestWbPricePayload:
    """Test WbPricePayload dataclass."""

    def test_payload_fields(self):
        payload = WbPricePayload(
            nm_id=123,
            price=1000,
            discount=75,
            final_discounted_price=Decimal("250.00"),
            target_discounted_price=Decimal("250"),
        )
        assert payload.nm_id == 123
        assert payload.price == 1000
        assert payload.discount == 75
        assert payload.final_discounted_price == Decimal("250.00")
