"""Tests for automatic WB auto-promotion participation pricing."""

from decimal import Decimal

from app.services.pricing.wb_auto_promo_condition_resolver import (
    WbAutoPromoConditionResolver,
)
from app.services.pricing.wb_auto_promo_participation_service import (
    STATUS_ALREADY_ELIGIBLE,
    STATUS_BLOCKED_BY_MIN_PRICE,
    STATUS_BLOCKED_BY_MRC,
    STATUS_CAN_APPLY,
    STATUS_NO_AUTO_PROMO_PRICE,
    WbAutoPromoParticipationService,
)
from app.services.pricing.wb_price_apply_service import WbPriceApplyService


def test_mrc_1000_max_auto_950_current_1000_can_apply() -> None:
    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("4000"),
        current_discount=75,
        current_discounted_price=Decimal("1000"),
        max_auto_promo_price=Decimal("950"),
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.status == STATUS_CAN_APPLY
    assert rec.recommended_discounted_price == Decimal("950")
    assert rec.recommended_full_price == Decimal("3800")


def test_mrc_1000_max_auto_850_blocked_by_mrc() -> None:
    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("4000"),
        current_discount=75,
        current_discounted_price=Decimal("1000"),
        max_auto_promo_price=Decimal("850"),
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.mrc_lower_bound == Decimal("900.0")
    assert rec.status == STATUS_BLOCKED_BY_MRC


def test_current_940_max_auto_950_already_eligible() -> None:
    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("3760"),
        current_discount=75,
        current_discounted_price=Decimal("940"),
        max_auto_promo_price=Decimal("950"),
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.status == STATUS_ALREADY_ELIGIBLE


def test_payload_950_discount_75_full_price_3800() -> None:
    payload = WbPriceApplyService.build_payload(
        nm_id=123456789,
        recommended_price=Decimal("950"),
        discount=Decimal("75"),
        max_discounted_price=Decimal("950"),
    )

    assert payload.as_wb_item() == {"nmID": 123456789, "price": 3800, "discount": 75}
    assert payload.final_discounted_price <= Decimal("950")
    assert "minPrice" not in payload.as_wb_item()


def test_recommended_below_min_price_blocked() -> None:
    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("4000"),
        current_discount=75,
        current_discounted_price=Decimal("1000"),
        max_auto_promo_price=Decimal("950"),
        min_price=Decimal("980"),
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.status == STATUS_BLOCKED_BY_MIN_PRICE


def test_no_auto_promo_price_status() -> None:
    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("4000"),
        current_discount=75,
        current_discounted_price=Decimal("1000"),
        max_auto_promo_price=None,
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.status == STATUS_NO_AUTO_PROMO_PRICE


def test_parse_price_from_required_price() -> None:
    result = WbAutoPromoConditionResolver().resolve(
        {"products": [{"nmID": 1, "requiredPrice": 950}]}
    )

    assert result[0].max_auto_promo_price == Decimal("950.00")


def test_parse_price_from_max_price() -> None:
    result = WbAutoPromoConditionResolver().resolve({"items": [{"nmID": 1, "maxPrice": 950}]})

    assert result[0].max_auto_promo_price == Decimal("950.00")


def test_parse_price_from_nested_price_info() -> None:
    result = WbAutoPromoConditionResolver().resolve(
        {"goods": [{"nmID": 1, "priceInfo": {"requiredPrice": 950}}]}
    )

    assert result[0].max_auto_promo_price == Decimal("950.00")


def test_parse_discount_projection_from_condition_discount() -> None:
    result = WbAutoPromoConditionResolver().resolve(
        {"products": [{"nmID": 1, "fullPrice": 3800, "requiredDiscount": 76}]}
    )

    assert result[0].condition_type == "discount_projection"
    assert result[0].wb_condition_discount_percent == Decimal("76.00")
    assert result[0].candidate_discounted_price == Decimal("912.00")


def test_discount_projection_78_percent_blocked_by_mrc() -> None:
    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("3800"),
        current_discount=75,
        current_discounted_price=Decimal("950"),
        max_auto_promo_price=None,
        wb_condition_discount_percent=Decimal("78"),
        condition_type="discount_projection",
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.candidate_discounted_price == Decimal("836.00")
    assert rec.mrc_lower_bound == Decimal("900.0")
    assert rec.status == STATUS_BLOCKED_BY_MRC
    assert rec.condition_type == "discount_projection"


def test_discount_projection_76_percent_can_apply_with_default_discount() -> None:
    rec = WbAutoPromoParticipationService.calculate(
        wb_nm_id=123456789,
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("3800"),
        current_discount=75,
        current_discounted_price=Decimal("950"),
        max_auto_promo_price=None,
        wb_condition_discount_percent=Decimal("76"),
        condition_type="discount_projection",
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_CAN_APPLY
    assert rec.candidate_discounted_price == Decimal("912.00")
    assert rec.recommended_discounted_price == Decimal("912.00")
    assert rec.recommended_discount == 75
    assert rec.recommended_full_price == Decimal("3648")

    payload = WbPriceApplyService.build_payload(
        nm_id=123456789,
        recommended_price=rec.recommended_discounted_price,
        discount=Decimal(rec.recommended_discount),
        max_discounted_price=rec.candidate_discounted_price,
    )
    assert payload.as_wb_item() == {"nmID": 123456789, "price": 3648, "discount": 75}


def test_blocked_condition_exposes_safe_mrc_restore_payload() -> None:
    rec = WbAutoPromoParticipationService.calculate(
        wb_nm_id=123456789,
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("3800"),
        current_discount=75,
        current_discounted_price=Decimal("950"),
        max_auto_promo_price=None,
        wb_condition_discount_percent=Decimal("78"),
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_BLOCKED_BY_MRC
    assert rec.safe_discounted_price == Decimal("1000")
    assert rec.safe_full_price == Decimal("4000")
    assert rec.safe_discount == 75


def test_wb_report_plan_price_446_uses_default_discount_not_upload_discount() -> None:
    rec = WbAutoPromoParticipationService.calculate(
        wb_nm_id=303892412,
        mrc_price=Decimal("446"),
        current_full_price=Decimal("1820"),
        current_discount=75,
        current_discounted_price=Decimal("455"),
        max_auto_promo_price=Decimal("446"),
        wb_condition_discount_percent=Decimal("76"),
        condition_type="max_price",
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_CAN_APPLY
    assert rec.candidate_discounted_price == Decimal("446")
    assert rec.recommended_discounted_price == Decimal("446")
    assert rec.recommended_discount == 75
    assert rec.recommended_full_price == Decimal("1784")

    payload = WbPriceApplyService.build_payload(
        nm_id=303892412,
        recommended_price=rec.recommended_discounted_price,
        discount=Decimal(rec.recommended_discount),
        max_discounted_price=rec.candidate_discounted_price,
    )
    assert payload.as_wb_item() == {"nmID": 303892412, "price": 1784, "discount": 75}


def test_wb_report_plan_price_439_recalculates_full_price() -> None:
    rec = WbAutoPromoParticipationService.calculate(
        wb_nm_id=303892413,
        mrc_price=Decimal("439"),
        current_full_price=Decimal("1792"),
        current_discount=75,
        current_discounted_price=Decimal("448"),
        max_auto_promo_price=Decimal("439"),
        wb_condition_discount_percent=Decimal("76"),
        condition_type="max_price",
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_CAN_APPLY
    assert rec.candidate_discounted_price == Decimal("439")
    assert rec.recommended_discounted_price == Decimal("439")
    assert rec.recommended_full_price == Decimal("1756")
    assert rec.recommended_discount == 75


def test_wb_report_plan_price_451_already_eligible() -> None:
    rec = WbAutoPromoParticipationService.calculate(
        mrc_price=Decimal("451"),
        current_full_price=Decimal("1804"),
        current_discount=75,
        current_discounted_price=Decimal("451"),
        max_auto_promo_price=Decimal("451"),
        wb_condition_discount_percent=Decimal("75"),
        condition_type="max_price",
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_ALREADY_ELIGIBLE


def test_scenario_auto_promo_950_mrc_1000_can_apply() -> None:
    """Auto-promo requires price <= 950, MRC=1000 with 10% deviation.
    Lower bound: 1000 * 0.9 = 900. Required price 950 > 900, so CAN_APPLY.
    Recommended discounted price = 950, full price = 950 / 0.25 = 3800.
    """
    rec = WbAutoPromoParticipationService.calculate(
        wb_nm_id=123456789,
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("4000"),
        current_discount=75,
        current_discounted_price=Decimal("1000"),
        max_auto_promo_price=Decimal("950"),
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_CAN_APPLY
    assert rec.recommended_discounted_price == Decimal("950")
    assert rec.mrc_lower_bound == Decimal("900.00")
    assert rec.recommended_discounted_price >= rec.mrc_lower_bound
    assert rec.recommended_full_price == Decimal("3800")


def test_recommendation_price_not_exceeds_required_price() -> None:
    """Recommended discounted price must never exceed the required/max_auto_promo_price."""
    rec = WbAutoPromoParticipationService.calculate(
        wb_nm_id=1,
        mrc_price=Decimal("2000"),
        current_full_price=Decimal("8000"),
        current_discount=75,
        current_discounted_price=Decimal("2000"),
        max_auto_promo_price=Decimal("1900"),
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_CAN_APPLY
    assert rec.recommended_discounted_price is not None
    assert rec.recommended_discounted_price <= Decimal("1900")


def test_mrc_lower_bound_respected() -> None:
    """When candidate price is below MRC lower bound, status is BLOCKED_BY_MRC."""
    rec = WbAutoPromoParticipationService.calculate(
        wb_nm_id=1,
        mrc_price=Decimal("1000"),
        current_full_price=Decimal("4000"),
        current_discount=75,
        current_discounted_price=Decimal("1000"),
        max_auto_promo_price=Decimal("800"),
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.mrc_lower_bound == Decimal("900.00")
    assert rec.status == STATUS_BLOCKED_BY_MRC
    assert rec.recommended_discounted_price is None


def test_full_price_equals_discounted_divided_by_factor() -> None:
    """Full price = recommended_discounted_price / (1 - discount/100), rounded up."""
    rec = WbAutoPromoParticipationService.calculate(
        wb_nm_id=1,
        mrc_price=Decimal("500"),
        current_full_price=Decimal("2000"),
        current_discount=75,
        current_discounted_price=Decimal("500"),
        max_auto_promo_price=Decimal("480"),
        allowed_deviation_percent=Decimal("10"),
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_CAN_APPLY
    assert rec.recommended_discounted_price == Decimal("480")
    assert rec.recommended_full_price == Decimal("1920")
    assert rec.recommended_full_price == rec.recommended_discounted_price * Decimal("4")


def test_full_price_calculation_with_75_discount() -> None:
    """With 75% discount, full_price is calculated from discounted_price / 0.25."""

    cases = [
        (Decimal("100"), 400),
        (Decimal("500"), 2000),
        (Decimal("950"), 3800),
        (Decimal("1234.56"), 4938),
    ]
    for discounted, expected_full in cases:
        payload = WbPriceApplyService.build_payload(
            nm_id=1,
            recommended_price=discounted,
            discount=Decimal("75"),
            max_discounted_price=discounted,
        )
        assert payload.price == expected_full, (
            f"{discounted}: expected {expected_full}, got {payload.price}"
        )
        assert payload.discount == 75
