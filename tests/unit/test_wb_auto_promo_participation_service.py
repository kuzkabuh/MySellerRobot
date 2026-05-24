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
