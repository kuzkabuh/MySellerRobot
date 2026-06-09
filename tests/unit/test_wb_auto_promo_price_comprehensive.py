"""Tests for WB auto promotion price control - real-world scenarios and edge cases.

Covers:
1. Regular nomenclatures parse
2. Auto condition recommendation (real example from task spec)
3. Auto already OK
4. MRC violation
5. minPrice violation (before MRC bounds check)
6. Price update safety
7. Auto mode disabled/enabled
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.wb.pricing.wb_auto_promo_price_service import (
    STATUS_AUTO_MIN_PRICE_VIOLATION,
    STATUS_AUTO_PRICE_OK,
    STATUS_AUTO_PRICE_VIOLATION,
    STATUS_AUTO_REQUIRED_PRICE_UNKNOWN,
    STATUS_AUTO_SET_PRICE,
    STATUS_AUTO_WAITING_WB_SYNC,
    WbAutoPromoPriceService,
)


def _make_product(
    product_id: int = 1,
    user_id: int = 1,
    account_id: int = 1,
    mrc_price: Decimal | None = Decimal("930"),
    marketplace_article: str = "345455998",
    external_product_id: str = "345455998",
    title: str = "Test Product",
    seller_article: str = "ART-001",
) -> MagicMock:
    product = MagicMock()
    product.id = product_id
    product.user_id = user_id
    product.marketplace_account_id = account_id
    product.mrc_price = mrc_price
    product.marketplace_article = marketplace_article
    product.external_product_id = external_product_id
    product.title = title
    product.seller_article = seller_article
    return product


def _make_settings_result(
    deviation: Decimal = Decimal("10"),
) -> MagicMock:
    settings = MagicMock()
    settings.allowed_action_price_deviation_percent = deviation
    return settings


# Test 1: Real example from task spec
# mrc=930, required_price=846, current_wb_price=930, deviation=10, min_price=800
# lower_bound=837, upper_bound=1023
# expected: AUTO_PROMOTION_SET_PRICE, recommended_price=846
@pytest.mark.asyncio
async def test_real_example_set_price():
    """Control product: nmID=345455998, MRC=930, required=846, current=930.
    lower_bound=837, upper_bound=1023.
    => AUTO_PROMOTION_SET_PRICE, recommended=846
    """
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=Decimal("930"),
            required_price=Decimal("846"),
            min_price=Decimal("800"),
        )

    assert rec.status == STATUS_AUTO_SET_PRICE
    assert rec.recommended_price == Decimal("846")
    assert rec.mrc_lower_bound == Decimal("837.00")
    assert rec.mrc_upper_bound == Decimal("1023.00")
    assert rec.mrc_price == Decimal("930")


# Test 2: Auto already OK
# mrc=930, required_price=846, current_wb_price=846
# expected: AUTO_PROMOTION_PRICE_OK, recommended_price=None
@pytest.mark.asyncio
async def test_auto_already_ok():
    """Current price already matches required price.
    => AUTO_PROMOTION_PRICE_OK
    """
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=Decimal("846"),
            required_price=Decimal("846"),
        )

    assert rec.status == STATUS_AUTO_PRICE_OK
    assert rec.recommended_price is None


# Test 3: MRC violation
# mrc=930, required_price=820, deviation=10, lower_bound=837
# expected: AUTO_PROMOTION_PRICE_VIOLATION
@pytest.mark.asyncio
async def test_mrc_violation():
    """Required price 820 is below lower bound 837.
    => AUTO_PROMOTION_PRICE_VIOLATION
    """
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=Decimal("930"),
            required_price=Decimal("820"),
            min_price=Decimal("800"),
        )

    assert rec.status == STATUS_AUTO_PRICE_VIOLATION
    assert rec.recommended_price is None
    assert rec.mrc_lower_bound == Decimal("837.00")


# Test 4: minPrice violation (before MRC bounds check)
# required_price=846, min_price=870
# expected: AUTO_PROMOTION_MIN_PRICE_VIOLATION
@pytest.mark.asyncio
async def test_min_price_violation_before_mrc():
    """Required price 846 is below minPrice 870.
    minPrice check should come BEFORE MRC bounds check.
    => AUTO_PROMOTION_MIN_PRICE_VIOLATION
    """
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=Decimal("930"),
            required_price=Decimal("846"),
            min_price=Decimal("870"),
        )

    assert rec.status == STATUS_AUTO_MIN_PRICE_VIOLATION
    assert rec.recommended_price is None
    assert "minPrice" in rec.reason


# Test 5: minPrice violation takes precedence over MRC bounds
# required_price=820, min_price=870, mrc=930, lower_bound=837
# Both minPrice and MRC bounds are violated, but minPrice should be reported first
@pytest.mark.asyncio
async def test_min_price_violation_takes_precedence_over_mrc():
    """Required price 820 is below both minPrice 870 AND lower bound 837.
    minPrice violation should be reported first.
    => AUTO_PROMOTION_MIN_PRICE_VIOLATION (not PRICE_VIOLATION)
    """
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=Decimal("930"),
            required_price=Decimal("820"),
            min_price=Decimal("870"),
        )

    assert rec.status == STATUS_AUTO_MIN_PRICE_VIOLATION
    assert rec.status != STATUS_AUTO_PRICE_VIOLATION


# Test 6: Auto active without condition
# active_auto_promotions_count > 0, conditions empty
# expected: AUTO_PROMOTION_REQUIRED_PRICE_UNKNOWN, not NO_PROMOTION
@pytest.mark.asyncio
async def test_auto_active_without_condition():
    """Auto promotions exist but no required price known.
    => AUTO_PROMOTION_REQUIRED_PRICE_UNKNOWN
    """
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=None,
            required_price=None,
        )

    assert rec.status == STATUS_AUTO_REQUIRED_PRICE_UNKNOWN
    assert rec.recommended_price is None


# Test 7: Price above upper bound
# mrc=930, required_price=1100, deviation=10, upper_bound=1023
# current_wb_price must be > required to trigger the check
@pytest.mark.asyncio
async def test_price_above_upper_bound():
    """Required price 1100 is above upper bound 1023.
    current_wb_price=1200 > required=1100, so we check bounds.
    => AUTO_PROMOTION_PRICE_VIOLATION
    """
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=Decimal("1200"),
            required_price=Decimal("1100"),
        )

    assert rec.status == STATUS_AUTO_PRICE_VIOLATION
    assert rec.recommended_price is None


# Test 8: Current price below required (but still OK)
# mrc=930, required_price=846, current_wb_price=840
# current <= required => AUTO_PROMOTION_PRICE_OK
@pytest.mark.asyncio
async def test_current_below_required_is_ok():
    """Current price 840 is below required 846, so it qualifies.
    => AUTO_PROMOTION_PRICE_OK
    """
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=Decimal("840"),
            required_price=Decimal("846"),
        )

    assert rec.status == STATUS_AUTO_PRICE_OK
    assert rec.recommended_price is None


# Test 9: No nmID
@pytest.mark.asyncio
async def test_no_nm_id():
    """No nmID => AUTO_PROMOTION_WAITING_WB_SYNC"""
    product = _make_product(
        mrc_price=Decimal("930"),
        marketplace_article="",
        external_product_id="",
    )
    session = AsyncMock()

    service = WbAutoPromoPriceService(session)
    rec = await service.build_recommendation(
        product=product,
        current_wb_price=None,
        required_price=Decimal("846"),
    )

    assert rec.status == STATUS_AUTO_WAITING_WB_SYNC


# Test 10: Required price is zero or negative
@pytest.mark.asyncio
async def test_required_price_zero():
    """Required price <= 0 => AUTO_PROMOTION_PRICE_VIOLATION"""
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=Decimal("930"),
            required_price=Decimal("0"),
        )

    assert rec.status == STATUS_AUTO_PRICE_VIOLATION
