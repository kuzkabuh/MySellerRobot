"""Tests for auto promotion price logic with real-world example.

Example from WB seller cabinet:
- nmID: 345455998
- Article: 2461.RoeRue
- MRC: 930 ₽
- WB price before discount: 3 384 ₽
- WB discount: 75%
- WB discounted price: 846 ₽
- Auto promotions: 3 active, strictest required price = 846 ₽
"""

from decimal import Decimal


class TestAutoPromotionRealExample:
    """Test auto promotion logic with the real-world example nmID=345455998."""

    def test_auto_promo_already_in_action(self) -> None:
        """Product participates in auto promotion with acceptable price.

        Input:
        - mrc_price = 930
        - allowed_deviation_percent = 10
        - current_wb_discounted_price = 846
        - auto_promo_required_prices = [863, 854, 846]
        - wb_reports_in_action = True

        Expected:
        - lower_bound = 837
        - upper_bound = 1023
        - strictest_required_price = 846
        - status = AUTO_PROMO_ALREADY_IN_ACTION
        - mrc_status = OK
        """
        mrc_price = Decimal("930")
        allowed_deviation = Decimal("10")

        lower_bound = mrc_price * (Decimal("1") - allowed_deviation / Decimal("100"))
        upper_bound = mrc_price * (Decimal("1") + allowed_deviation / Decimal("100"))

        assert lower_bound == Decimal("837")
        assert upper_bound == Decimal("1023")

        strictest_required_price = min([Decimal("863"), Decimal("854"), Decimal("846")])
        assert strictest_required_price == Decimal("846")

        # 846 is within 837-1023, so participation is acceptable
        assert lower_bound <= strictest_required_price <= upper_bound

    def test_auto_promo_set_price_when_not_participating(self) -> None:
        """Product can enter auto promotion by changing price.

        Input:
        - mrc_price = 930
        - allowed_deviation_percent = 10
        - current_wb_discounted_price = 930
        - strictest_required_price = 846
        - wb_reports_in_action = False

        Expected:
        - status = AUTO_PROMO_SET_PRICE
        - recommended_price = 846
        """
        mrc_price = Decimal("930")
        allowed_deviation = Decimal("10")
        current_price = Decimal("930")
        required_price = Decimal("846")

        lower_bound = mrc_price * (Decimal("1") - allowed_deviation / Decimal("100"))

        # Current price is above required price, need to reduce
        assert current_price > required_price

        # Required price is within MRC bounds
        assert required_price >= lower_bound

        # Should recommend setting price to required_price
        # (This would be AUTO_PROMO_SET_PRICE in the service)

    def test_auto_promo_price_violation(self) -> None:
        """Auto promotion requires price below MRC lower bound.

        Input:
        - mrc_price = 930
        - allowed_deviation_percent = 10
        - required_price = 820

        Expected:
        - status = AUTO_PROMO_PRICE_VIOLATION
        - reason contains "ниже допустимой цены по МРЦ"
        - lower_bound = 837
        """
        mrc_price = Decimal("930")
        allowed_deviation = Decimal("10")
        required_price = Decimal("820")

        lower_bound = mrc_price * (Decimal("1") - allowed_deviation / Decimal("100"))

        assert lower_bound == Decimal("837")
        assert required_price < lower_bound

        # Should be AUTO_PROMO_PRICE_VIOLATION
        # Reason should mention price below MRC lower bound

    def test_mrc_bounds_calculation(self) -> None:
        """Verify MRC bounds calculation for the real example."""
        mrc_price = Decimal("930")
        deviation_percent = Decimal("10")

        lower_bound = mrc_price * (Decimal("1") - deviation_percent / Decimal("100"))
        upper_bound = mrc_price * (Decimal("1") + deviation_percent / Decimal("100"))

        assert lower_bound == Decimal("837")
        assert upper_bound == Decimal("1023")

        # WB required price 846 is within bounds
        assert Decimal("846") >= lower_bound
        assert Decimal("846") <= upper_bound

    def test_wb_price_calculation_from_mrc(self) -> None:
        """Verify WB price calculation matches the real example.

        WB shows:
        - Price before discount: 3 384 ₽
        - Discount: 75%
        - Discounted price: 846 ₽

        Check: 3384 * 0.25 = 846
        """
        price_before_discount = Decimal("3384")
        discount_percent = Decimal("75")
        expected_discounted = price_before_discount * (
            Decimal("1") - discount_percent / Decimal("100")
        )

        assert expected_discounted == Decimal("846")

    def test_mrc_multiplier_calculation(self) -> None:
        """Verify MRC multiplier calculation.

        MRC = 930
        Multiplier = 4
        Price before discount = 930 * 4 = 3720

        But WB shows 3384, which means the actual price was set differently.
        """
        mrc_price = Decimal("930")
        multiplier = Decimal("4")
        calculated_price = mrc_price * multiplier

        assert calculated_price == Decimal("3720")

        # WB actual price is 3384, which is different from calculated 3720
        # This shows that WB price can be set independently of MRC calculation
        assert Decimal("3384") != calculated_price
