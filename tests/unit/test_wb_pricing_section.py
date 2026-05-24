"""Tests for the production WB pricing and auto-promotion services."""

from decimal import Decimal


def test_import_wb_promotions_sync_service_does_not_fail() -> None:
    from app.services.wb.wb_promotions_sync_service import WbPromotionsSyncService

    assert WbPromotionsSyncService is not None


def test_auto_promo_condition_required_price_from_direct_fields() -> None:
    from app.services.pricing.wb_auto_promo_condition_resolver import (
        WbAutoPromoConditionResolver,
    )

    resolver = WbAutoPromoConditionResolver()
    detail = {"nomenclatures": [{"nmID": 1, "requiredPrice": 950}]}

    result = resolver.resolve(detail)

    assert result[0].wb_nm_id == 1
    assert result[0].required_price == Decimal("950.00")
    assert result[0].confidence == "high"


def test_auto_promo_condition_required_price_from_max_price() -> None:
    from app.services.pricing.wb_auto_promo_condition_resolver import (
        WbAutoPromoConditionResolver,
    )

    detail = {"products": [{"id": 2, "maxPrice": "930"}]}

    result = WbAutoPromoConditionResolver().resolve(detail)

    assert result[0].required_price == Decimal("930.00")


def test_auto_promo_condition_required_price_from_nested_price_info() -> None:
    from app.services.pricing.wb_auto_promo_condition_resolver import (
        WbAutoPromoConditionResolver,
    )

    detail = {"data": {"items": [{"nmId": 3, "priceInfo": {"requiredPrice": 910}}]}}

    result = WbAutoPromoConditionResolver().resolve(detail)

    assert result[0].required_price == Decimal("910.00")


def test_auto_promo_condition_required_price_from_discount_and_full_price() -> None:
    from app.services.pricing.wb_auto_promo_condition_resolver import (
        WbAutoPromoConditionResolver,
    )

    detail = {"conditions": {"products": [{"nmID": 4, "fullPrice": 1000, "requiredDiscount": 15}]}}

    result = WbAutoPromoConditionResolver().resolve(detail)

    assert result[0].required_price == Decimal("850.00")
    assert result[0].confidence == "medium"


def test_auto_promo_condition_finds_any_nested_product_list() -> None:
    from app.services.pricing.wb_auto_promo_condition_resolver import (
        WbAutoPromoConditionResolver,
    )

    detail = {"outer": {"deep": [{"goods": [{"nmID": 5, "actionPrice": 777}]}]}}

    result = WbAutoPromoConditionResolver().resolve(detail)

    assert result[0].wb_nm_id == 5
    assert result[0].required_price == Decimal("777.00")


def test_recommendation_mrc_1000_required_950_is_can_apply() -> None:
    from app.services.pricing.wb_price_recommendation_service import (
        STATUS_CAN_APPLY,
        WbPriceRecommendationService,
    )

    rec = WbPriceRecommendationService.calculate(
        mrc_price=Decimal("1000"),
        current_wb_price=Decimal("1000"),
        required_price=Decimal("950"),
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.lower_bound == Decimal("900.0")
    assert rec.upper_bound == Decimal("1100.0")
    assert rec.recommended_price == Decimal("950")
    assert rec.full_wb_price == 3800
    assert rec.discount == 75
    assert rec.status == STATUS_CAN_APPLY


def test_recommendation_required_850_is_blocked_by_mrc() -> None:
    from app.services.pricing.wb_price_recommendation_service import (
        STATUS_BLOCKED_BY_MRC,
        WbPriceRecommendationService,
    )

    rec = WbPriceRecommendationService.calculate(
        mrc_price=Decimal("1000"),
        current_wb_price=Decimal("1000"),
        required_price=Decimal("850"),
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.status == STATUS_BLOCKED_BY_MRC


def test_recommendation_current_940_required_950_is_already_ok() -> None:
    from app.services.pricing.wb_price_recommendation_service import (
        STATUS_ALREADY_OK,
        WbPriceRecommendationService,
    )

    rec = WbPriceRecommendationService.calculate(
        mrc_price=Decimal("1000"),
        current_wb_price=Decimal("940"),
        required_price=Decimal("950"),
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.status == STATUS_ALREADY_OK


def test_price_apply_payload_950_discount_75() -> None:
    from app.services.pricing.wb_price_apply_service import WbPriceApplyService

    payload = WbPriceApplyService.build_payload(
        nm_id=123,
        recommended_price=Decimal("950"),
        discount=Decimal("75"),
    )

    assert payload.as_wb_item() == {"nmID": 123, "price": 3800, "discount": 75}
    assert "minPrice" not in payload.as_wb_item()


def test_price_apply_blocks_below_min_price() -> None:
    import pytest

    from app.services.pricing.wb_price_apply_service import WbPriceApplyService

    with pytest.raises(ValueError):
        WbPriceApplyService.build_payload(
            nm_id=123,
            recommended_price=Decimal("900"),
            discount=Decimal("75"),
            min_price=Decimal("950"),
        )


def test_no_required_price_creates_no_required_price_status() -> None:
    from app.services.pricing.wb_price_recommendation_service import (
        STATUS_NO_REQUIRED_PRICE,
        WbPriceRecommendationService,
    )

    rec = WbPriceRecommendationService.calculate(
        mrc_price=Decimal("1000"),
        current_wb_price=Decimal("1000"),
        required_price=None,
        allowed_deviation_percent=Decimal("10"),
    )

    assert rec.status == STATUS_NO_REQUIRED_PRICE
    assert rec.recommended_price is None
    assert "raw_payload" in rec.reason
