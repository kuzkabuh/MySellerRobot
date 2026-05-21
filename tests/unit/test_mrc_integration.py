"""Tests for MRC pricing bot handlers, web routes, and integration."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.states import MrcStates
from app.models.enums import FeatureCode
from app.services.feature_access_service import _PRO_FEATURES
from app.services.pricing.wb_mrc_price_service import WbMrcPriceService


class TestFeatureCodeMrcPricing:
    """Test MRC_PRICING feature code integration."""

    def test_feature_code_exists(self) -> None:
        """MRC_PRICING feature code should exist."""
        assert FeatureCode.MRC_PRICING == "MRC_PRICING"

    def test_mrc_in_pro_features(self) -> None:
        """MRC_PRICING should be in PRO features."""
        assert FeatureCode.MRC_PRICING in _PRO_FEATURES

    def test_mrc_required_plan_is_pro(self) -> None:
        """MRC_PRICING should require Pro plan."""
        from app.services.feature_access_service import FeatureAccessService

        assert FeatureAccessService._required_plan_for_feature(FeatureCode.MRC_PRICING) == "Pro"


class TestMrcStates:
    """Test MRC FSM states."""

    def test_waiting_for_article_state_exists(self) -> None:
        """waiting_for_article state should exist."""
        assert hasattr(MrcStates, "waiting_for_article")

    def test_waiting_for_mrc_price_state_exists(self) -> None:
        """waiting_for_mrc_price state should exist."""
        assert hasattr(MrcStates, "waiting_for_mrc_price")


class TestMrcPriceServiceIntegration:
    """Test MRC price service integration with realistic data."""

    def test_mrc_from_db_used_in_calculation(self) -> None:
        """MRC from DB should be used in calculation."""
        service = WbMrcPriceService()
        mrc_price = Decimal("699")

        result = service.calculate(mrc_price=mrc_price)
        assert result.mrc_price == mrc_price
        assert result.final_discounted_price == mrc_price

    def test_plan_price_from_promo_used_in_calculation(self) -> None:
        """planPrice from active promo should be used in calculation."""
        service = WbMrcPriceService()

        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("647"),
        )

        assert result.final_discounted_price == Decimal("647")
        assert result.is_promo_applied is True

    def test_no_promo_returns_to_mrc(self) -> None:
        """If no promo, price should return to MRC."""
        service = WbMrcPriceService()

        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=None,
        )

        assert result.final_discounted_price == Decimal("699")
        assert result.is_promo_applied is False

    def test_no_mrc_does_not_break_old_logic(self) -> None:
        """If MRC is not set, old logic should not break."""
        service = WbMrcPriceService()

        # MRC not set - ValidationError is expected
        with pytest.raises(Exception):
            service.calculate(mrc_price=None)  # type: ignore[arg-type]


class TestMrcPriceServiceEdgeCases:
    """Test edge cases for MRC price service."""

    def test_mrc_with_kopecks(self) -> None:
        """MRC with kopecks should work."""
        service = WbMrcPriceService()

        result = service.calculate(mrc_price=Decimal("699.50"))
        assert result.mrc_price == Decimal("699.50")
        assert result.price_before_discount == Decimal("2798")

    def test_promo_price_zero_treated_as_no_promo(self) -> None:
        """Promo price of 0 should be treated as no promo."""
        service = WbMrcPriceService()

        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("0"),
        )

        assert result.final_discounted_price == Decimal("699")
        assert result.is_promo_applied is False

    def test_promo_price_negative_treated_as_no_promo(self) -> None:
        """Negative promo price should be treated as no promo."""
        service = WbMrcPriceService()

        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("-100"),
        )

        assert result.final_discounted_price == Decimal("699")
        assert result.is_promo_applied is False

    def test_min_price_above_mrc(self) -> None:
        """minPrice above MRC should use minPrice."""
        service = WbMrcPriceService()

        result = service.calculate(
            mrc_price=Decimal("500"),
            min_price=Decimal("600"),
        )

        assert result.final_discounted_price == Decimal("600")
        assert result.is_limited_by_min_price is True

    def test_min_price_below_calculated(self) -> None:
        """minPrice below calculated should use calculated."""
        service = WbMrcPriceService()

        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("647"),
            min_price=Decimal("600"),
        )

        assert result.final_discounted_price == Decimal("647")
        assert result.is_limited_by_min_price is False


class TestMrcValidation:
    """Test MRC input validation."""

    def test_zero_mrc_raises(self) -> None:
        """MRC = 0 should raise ValidationError."""
        from app.core.exceptions import ValidationError

        service = WbMrcPriceService()
        with pytest.raises(ValidationError):
            service.calculate(mrc_price=Decimal("0"))

    def test_negative_mrc_raises(self) -> None:
        """Negative MRC should raise ValidationError."""
        from app.core.exceptions import ValidationError

        service = WbMrcPriceService()
        with pytest.raises(ValidationError):
            service.calculate(mrc_price=Decimal("-100"))

    def test_none_mrc_raises(self) -> None:
        """None MRC should raise ValidationError."""
        from app.core.exceptions import ValidationError

        service = WbMrcPriceService()
        with pytest.raises(ValidationError):
            service.calculate(mrc_price=None)  # type: ignore[arg-type]


class TestMrcResultReasons:
    """Test human-readable reasons in MRC results."""

    def test_reason_no_promo(self) -> None:
        """Reason should mention no promo."""
        service = WbMrcPriceService()
        result = service.calculate(mrc_price=Decimal("699"))

        assert "Акции нет" in result.reason

    def test_reason_promo_applied(self) -> None:
        """Reason should mention promo applied."""
        service = WbMrcPriceService()
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("647"),
        )

        assert "допустимых пределах" in result.reason

    def test_reason_limited_by_mrc(self) -> None:
        """Reason should mention MRC limit."""
        service = WbMrcPriceService()
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("599"),
        )

        assert "максимальное снижение" in result.reason

    def test_reason_limited_by_min_price(self) -> None:
        """Reason should mention minPrice."""
        service = WbMrcPriceService()
        result = service.calculate(
            mrc_price=Decimal("699"),
            promo_required_price=Decimal("599"),
            min_price=Decimal("650"),
        )

        assert "minPrice" in result.reason


class TestSubscriptionTierMrcFeature:
    """Test subscription tier feature flag for MRC."""

    def test_subscription_tier_has_feature_mrc_pricing(self) -> None:
        """SubscriptionTier should have feature_mrc_pricing attribute."""
        from app.models.subscriptions import SubscriptionTier

        assert hasattr(SubscriptionTier, "feature_mrc_pricing")

    def test_feature_mrc_pricing_default_false(self) -> None:
        """feature_mrc_pricing should default to False."""
        from app.models.subscriptions import SubscriptionTier

        # Check the mapped_column default
        col = SubscriptionTier.__table__.c.feature_mrc_pricing
        assert col.default.arg is False  # type: ignore[union-attr]
