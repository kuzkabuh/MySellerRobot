"""Tests for WbMrcPriceService - MRC price calculation."""

from decimal import Decimal

import pytest

from app.core.exceptions import ValidationError
from app.services.pricing.wb_mrc_price_service import WbMrcPriceService


@pytest.fixture()
def service() -> WbMrcPriceService:
    return WbMrcPriceService()


class TestWbMrcPriceServiceNoPromo:
    """Test cases when no promotion is active."""

    def test_no_promo_basic(self, service: WbMrcPriceService) -> None:
        """No promo: final price = MRC, price before discount = MRC * 4."""
        result = service.calculate(mrc_price=Decimal("699"))

        assert result.mrc_price == Decimal("699")
        assert result.promo_required_price is None
        assert result.final_discounted_price == Decimal("699")
        assert result.price_before_discount == Decimal("2796")
        assert result.is_promo_applied is False
        assert result.is_limited_by_mrc_rule is False
        assert result.is_limited_by_min_price is False

    def test_no_promo_round_number(self, service: WbMrcPriceService) -> None:
        """No promo with round MRC."""
        result = service.calculate(mrc_price=Decimal("500"))

        assert result.final_discounted_price == Decimal("500")
        assert result.price_before_discount == Decimal("2000")

    def test_no_promo_mrc_discount_is_zero(self, service: WbMrcPriceService) -> None:
        """No promo: MRC discount should be zero."""
        result = service.calculate(mrc_price=Decimal("699"))

        assert result.mrc_discount_rub == Decimal("0")
        assert result.mrc_discount_percent == Decimal("0")


class TestWbMrcPriceServicePromoWithinLimit:
    """Test cases when promo price is within the 10% limit."""

    def test_promo_within_limit(self, service: WbMrcPriceService) -> None:
        """Promo price 647 >= 629.10 (699 - 10%): use promo price."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("647"),
        )

        assert result.final_discounted_price == Decimal("647")
        assert result.price_before_discount == Decimal("2588")
        assert result.is_promo_applied is True
        assert result.is_limited_by_mrc_rule is False
        assert result.mrc_discount_rub == Decimal("52")

    def test_promo_exactly_at_limit(self, service: WbMrcPriceService) -> None:
        """Promo price exactly at limit (699 - 10% = 629.10, ceil = 630)."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("630"),
        )

        assert result.final_discounted_price == Decimal("630")
        assert result.price_before_discount == Decimal("2520")
        assert result.is_promo_applied is True
        assert result.is_limited_by_mrc_rule is False


class TestWbMrcPriceServicePromoBelowLimit:
    """Test cases when promo price is below the 10% limit."""

    def test_promo_below_limit(self, service: WbMrcPriceService) -> None:
        """Promo price 599 < 629.10: use ceil(699 * 0.9) = 630."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("599"),
        )

        assert result.final_discounted_price == Decimal("630")
        assert result.price_before_discount == Decimal("2520")
        assert result.is_promo_applied is True
        assert result.is_limited_by_mrc_rule is True

    def test_promo_way_below_limit(self, service: WbMrcPriceService) -> None:
        """Promo price 400 is way below limit."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("400"),
        )

        assert result.final_discounted_price == Decimal("630")
        assert result.is_limited_by_mrc_rule is True

    def test_rounding_up(self, service: WbMrcPriceService) -> None:
        """Ensure rounding up: 699 * 0.9 = 629.10 -> ceil = 630."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("599"),
        )

        assert result.final_discounted_price == Decimal("630")


class TestWbMrcPriceServiceMinPrice:
    """Test cases with minPrice constraint."""

    def test_min_price_above_calculated(self, service: WbMrcPriceService) -> None:
        """minPrice 650 > calculated 630: use minPrice."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("599"),
            min_price=Decimal("650"),
        )

        assert result.final_discounted_price == Decimal("650")
        assert result.price_before_discount == Decimal("2600")
        assert result.is_limited_by_min_price is True

    def test_min_price_below_calculated(self, service: WbMrcPriceService) -> None:
        """minPrice 600 < calculated 630: use calculated."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("599"),
            min_price=Decimal("600"),
        )

        assert result.final_discounted_price == Decimal("630")
        assert result.is_limited_by_min_price is False

    def test_min_price_no_promo(self, service: WbMrcPriceService) -> None:
        """minPrice above MRC: use minPrice."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=None,
            min_price=Decimal("750"),
        )

        assert result.final_discounted_price == Decimal("750")
        assert result.price_before_discount == Decimal("3000")
        assert result.is_limited_by_min_price is True


class TestWbMrcPriceServiceValidation:
    """Test input validation."""

    def test_zero_mrc_raises(self, service: WbMrcPriceService) -> None:
        """MRC = 0 should raise ValidationError."""
        with pytest.raises(ValidationError):
            service.calculate(mrc_price=Decimal("0"))

    def test_negative_mrc_raises(self, service: WbMrcPriceService) -> None:
        """Negative MRC should raise ValidationError."""
        with pytest.raises(ValidationError):
            service.calculate(mrc_price=Decimal("-100"))

    def test_none_mrc_raises(self, service: WbMrcPriceService) -> None:
        """None MRC should raise ValidationError."""
        with pytest.raises(ValidationError):
            service.calculate(mrc_price=None)  # type: ignore[arg-type]


class TestWbMrcPriceServiceCustomSettings:
    """Test with custom discount and multiplier settings."""

    def test_custom_max_discount(self) -> None:
        """Custom max discount of 5%."""
        service = WbMrcPriceService(max_discount_percent=5)

        result = service.calculate(
            mrc_price=Decimal("1000"),
            promo_required_price=Decimal("900"),
        )

        # min allowed = 1000 * 0.95 = 950
        assert result.final_discounted_price == Decimal("950")
        assert result.is_limited_by_mrc_rule is True

    def test_custom_multiplier(self) -> None:
        """Custom multiplier of 3."""
        service = WbMrcPriceService(price_before_discount_multiplier=3)

        result = service.calculate(mrc_price=Decimal("500"))

        assert result.price_before_discount == Decimal("1500")

    def test_custom_discount_and_multiplier(self) -> None:
        """Custom discount 20% and multiplier 5."""
        service = WbMrcPriceService(
            max_discount_percent=20,
            price_before_discount_multiplier=5,
        )

        result = service.calculate(
            mrc_price=Decimal("1000"),
            promo_required_price=Decimal("700"),
        )

        # min allowed = 1000 * 0.8 = 800
        assert result.final_discounted_price == Decimal("800")
        assert result.price_before_discount == Decimal("4000")


class TestWbMrcPriceServiceEdgeCases:
    """Edge case tests."""

    def test_promo_price_zero_ignored(self, service: WbMrcPriceService) -> None:
        """Promo price of 0 should be treated as no promo."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("0"),
        )

        assert result.final_discounted_price == Decimal("699")
        assert result.is_promo_applied is False

    def test_promo_price_negative_ignored(self, service: WbMrcPriceService) -> None:
        """Negative promo price should be treated as no promo."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("-50"),
        )

        assert result.final_discounted_price == Decimal("699")
        assert result.is_promo_applied is False

    def test_mrc_with_kopecks(self, service: WbMrcPriceService) -> None:
        """MRC with kopecks should work correctly."""
        result = service.calculate(mrc_price=Decimal("699.50"))

        assert result.final_discounted_price == Decimal("699.50")
        assert result.price_before_discount == Decimal("2798")

    def test_result_reason_no_promo(self, service: WbMrcPriceService) -> None:
        """Reason should be clear when no promo."""
        result = service.calculate(mrc_price=Decimal("699"))

        assert "Акции нет" in result.reason

    def test_result_reason_promo_applied(self, service: WbMrcPriceService) -> None:
        """Reason should be clear when promo applied."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("647"),
        )

        assert "допустимых пределах" in result.reason

    def test_result_reason_limited_by_mrc(self, service: WbMrcPriceService) -> None:
        """Reason should be clear when limited by MRC rule."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("599"),
        )

        assert "максимальное снижение" in result.reason

    def test_result_reason_limited_by_min_price(self, service: WbMrcPriceService) -> None:
        """Reason should be clear when limited by minPrice."""
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("599"),
            min_price=Decimal("650"),
        )

        assert "minPrice" in result.reason
