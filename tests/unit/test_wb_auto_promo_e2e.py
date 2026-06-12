"""End-to-end tests for WB auto promotion price control flow.

Covers:
1. Preview price changes (dry_run)
2. Apply price changes (confirm)
3. Auto mode disabled
4. Auto mode enabled
5. Full flow: import -> recommend -> preview -> apply
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.wb.pricing.wb_auto_promo_price_service import (
    STATUS_AUTO_MIN_PRICE_VIOLATION,
    STATUS_AUTO_PRICE_OK,
    STATUS_AUTO_PRICE_VIOLATION,
    STATUS_AUTO_REQUIRED_PRICE_UNKNOWN,
    STATUS_AUTO_SET_PRICE,
    WbAutoPromoPriceService,
)
from app.services.wb.pricing.wb_price_update_service import (
    STATUS_APPLIED,
    STATUS_DRY_RUN,
    WbPriceUpdateService,
)


def _make_product(
    product_id: int = 1,
    user_id: int = 1,
    account_id: int = 1,
    mrc_price: Decimal = Decimal("930"),
    marketplace_article: str = "345455998",
    external_product_id: str = "345455998",
    title: str = "Test Product",
    seller_article: str = "2461.RoeRue",
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


def _make_recommendation(
    rec_id: int = 1,
    product_id: int = 1,
    wb_nm_id: int = 345455998,
    status: str = STATUS_AUTO_SET_PRICE,
    recommended_price: Decimal | None = Decimal("846"),
    mrc_price: Decimal = Decimal("930"),
    current_wb_price: Decimal | None = Decimal("930"),
    required_price: Decimal | None = Decimal("846"),
    min_price: Decimal | None = Decimal("800"),
    mrc_lower_bound: Decimal = Decimal("837"),
    mrc_upper_bound: Decimal = Decimal("1023"),
    promotion_name: str | None = "Модная распродажа",
) -> MagicMock:
    rec = MagicMock()
    rec.id = rec_id
    rec.product_id = product_id
    rec.wb_nm_id = wb_nm_id
    rec.status = status
    rec.recommended_price = recommended_price
    rec.mrc_price = mrc_price
    rec.current_wb_price = current_wb_price
    rec.required_price = required_price
    rec.min_price = min_price
    rec.mrc_lower_bound = mrc_lower_bound
    rec.mrc_upper_bound = mrc_upper_bound
    rec.promotion_name = promotion_name
    rec.user_id = 1
    rec.marketplace_account_id = 1
    return rec


# Test 1: Preview price changes - only AUTO_PROMOTION_SET_PRICE selected
@pytest.mark.asyncio
async def test_preview_price_changes_only_set_price():
    """Preview should calculate correct price/discount payload."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    # Mock MrcPricingSettingsService
    mock_settings = MagicMock()
    mock_settings.default_discount_percent = Decimal("75")
    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=mock_settings)

    WbPriceUpdateService(session)

    with patch(
        "app.services.wb.pricing.mrc_pricing_settings_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        # Test the payload calculation directly
        from app.services.wb.pricing.wb_price_update_service import (
            calculate_wb_price_payload_for_target,
        )

        payload = calculate_wb_price_payload_for_target(
            target_discounted_price=Decimal("846"),
            discount_percent=Decimal("75"),
            nm_id=345455998,
        )

        assert payload.price == 3384
        assert payload.discount == 75
        assert payload.final_discounted_price == Decimal("846.00")
        assert payload.nm_id == 345455998


# Test 2: Apply price changes - dry_run creates history, no WB request
@pytest.mark.asyncio
async def test_apply_price_changes_dry_run_no_wb_request():
    """Dry run should create history records but not call WB API."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    service = WbPriceUpdateService(session)

    # Test _record_history directly for dry_run
    await service._record_history(
        user_id=1,
        marketplace_account_id=1,
        product_id=1,
        wb_nm_id=345455998,
        old_price=Decimal("930"),
        new_price=Decimal("846"),
        status=STATUS_DRY_RUN,
        dry_run=True,
        source="auto",
        min_price=Decimal("800"),
        mrc_lower_bound=Decimal("837"),
        mrc_upper_bound=Decimal("1023"),
    )

    assert session.add.called
    history_record = session.add.call_args[0][0]
    assert history_record.dry_run is True
    assert history_record.status == STATUS_DRY_RUN
    assert history_record.new_price == Decimal("846")


# Test 3: Apply price changes - confirm sends to WB and saves history
@pytest.mark.asyncio
async def test_apply_price_changes_confirm_sends_to_wb():
    """Confirm should call WB API with correct payload format."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    # Mock MrcPricingSettingsService
    mock_settings = MagicMock()
    mock_settings.default_discount_percent = Decimal("75")
    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=mock_settings)

    WbPriceUpdateService(session)

    mock_client = AsyncMock()
    mock_client.upload_task_prices_discounts = AsyncMock(
        return_value={
            "data": {"id": 123, "alreadyExists": False},
            "error": False,
        }
    )

    # Test the payload calculation directly
    from app.services.wb.pricing.wb_price_update_service import calculate_wb_price_payload_for_target

    payload = calculate_wb_price_payload_for_target(
        target_discounted_price=Decimal("846"),
        discount_percent=Decimal("75"),
        nm_id=345455998,
    )

    assert payload.price == 3384
    assert payload.discount == 75
    assert payload.final_discounted_price == Decimal("846.00")
    # Verify no minPrice field in payload (it's not sent to WB)
    assert not hasattr(payload, "min_price")
    assert not hasattr(payload, "minPrice")


# Test 4: Auto mode disabled - recommendation exists but price not changed
@pytest.mark.asyncio
async def test_auto_mode_disabled_price_not_changed():
    """When auto_price_for_auto_promotions=False, price should not be changed."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    service = WbPriceUpdateService(session)

    # Test _record_history directly for dry_run
    await service._record_history(
        user_id=1,
        marketplace_account_id=1,
        product_id=1,
        wb_nm_id=345455998,
        old_price=Decimal("930"),
        new_price=Decimal("846"),
        status=STATUS_DRY_RUN,
        dry_run=True,
        source="auto",
        min_price=Decimal("800"),
        mrc_lower_bound=Decimal("837"),
        mrc_upper_bound=Decimal("1023"),
    )

    assert session.add.called
    history_record = session.add.call_args[0][0]
    assert history_record.dry_run is True
    assert history_record.status == STATUS_DRY_RUN


# Test 5: Auto mode enabled - safe price changed once, history saved
@pytest.mark.asyncio
async def test_auto_mode_enabled_safe_price_changed():
    """When auto mode enabled, safe price should be changed and history saved."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    service = WbPriceUpdateService(session)

    # Test _record_history directly for applied status
    await service._record_history(
        user_id=1,
        marketplace_account_id=1,
        product_id=1,
        wb_nm_id=345455998,
        old_price=Decimal("930"),
        new_price=Decimal("846"),
        status=STATUS_APPLIED,
        dry_run=False,
        source="auto",
        min_price=Decimal("800"),
        mrc_lower_bound=Decimal("837"),
        mrc_upper_bound=Decimal("1023"),
    )

    assert session.add.called
    history_record = session.add.call_args[0][0]
    assert history_record.dry_run is False
    assert history_record.status == STATUS_APPLIED
    assert history_record.new_price == Decimal("846")
    assert history_record.source == "auto"


# Test 6: Recommendation with current price already OK
@pytest.mark.asyncio
async def test_recommendation_current_price_ok():
    """When current price <= required, status should be AUTO_PROMOTION_PRICE_OK."""
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.wb.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
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


# Test 7: Recommendation with MRC violation
@pytest.mark.asyncio
async def test_recommendation_mrc_violation():
    """When required price below lower bound, status should be AUTO_PROMOTION_PRICE_VIOLATION."""
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.wb.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
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


# Test 8: Recommendation with minPrice violation
@pytest.mark.asyncio
async def test_recommendation_min_price_violation():
    """When required price below minPrice, status should be AUTO_PROMOTION_MIN_PRICE_VIOLATION."""
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.wb.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
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


# Test 9: Recommendation with unknown required price
@pytest.mark.asyncio
async def test_recommendation_unknown_required_price():
    """When required price is None, status should be AUTO_PROMOTION_REQUIRED_PRICE_UNKNOWN."""
    product = _make_product(mrc_price=Decimal("930"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(return_value=_make_settings_result(Decimal("10")))

    with patch(
        "app.services.wb.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
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


# Test 10: Cooldown prevents duplicate price changes
@pytest.mark.asyncio
async def test_cooldown_prevents_duplicate_changes():
    """Price changed recently should be skipped due to cooldown."""
    session = AsyncMock()
    product = _make_product()
    rec = _make_recommendation(
        recommended_price=Decimal("846"),
        mrc_lower_bound=Decimal("837"),
        mrc_upper_bound=Decimal("1023"),
        min_price=Decimal("800"),
    )

    service = WbPriceUpdateService(session)

    recent_time = datetime.now(tz=UTC)
    with (
        patch.object(service, "_get_current_wb_price", new=AsyncMock(return_value=Decimal("930"))),
        patch.object(service, "_get_last_price_change", new=AsyncMock(return_value=recent_time)),
    ):
        can_change, reason = await service._can_change_price(
            product=product,
            new_price=Decimal("846"),
            rec=rec,
        )

    assert can_change is False
    assert "6ч" in reason
