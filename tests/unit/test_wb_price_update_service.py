"""Tests for WbPriceUpdateService - safety checks and history recording."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.pricing.wb_price_update_service import (
    STATUS_APPLIED,
    WbPriceUpdateService,
)


def _make_product(
    product_id: int = 1,
    account_id: int = 1,
    marketplace_article: str = "345455998",
    external_product_id: str = "345455998",
) -> MagicMock:
    product = MagicMock()
    product.id = product_id
    product.marketplace_account_id = account_id
    product.marketplace_article = marketplace_article
    product.external_product_id = external_product_id
    return product


def _make_rec(
    product_id: int = 1,
    wb_nm_id: int = 345455998,
    recommended_price: Decimal = Decimal("846"),
    mrc_lower_bound: Decimal = Decimal("837"),
    mrc_upper_bound: Decimal = Decimal("1023"),
    min_price: Decimal | None = Decimal("800"),
) -> MagicMock:
    rec = MagicMock()
    rec.product_id = product_id
    rec.wb_nm_id = wb_nm_id
    rec.recommended_price = recommended_price
    rec.mrc_lower_bound = mrc_lower_bound
    rec.mrc_upper_bound = mrc_upper_bound
    rec.min_price = min_price
    return rec


# Test 1: Price below min_price => no WB request sent
@pytest.mark.asyncio
async def test_price_below_min_price_no_wb_request():
    """recommended_price below min_price => skipped, no WB request."""
    session = AsyncMock()
    product = _make_product()
    rec = _make_rec(
        recommended_price=Decimal("750"),
        min_price=Decimal("800"),
    )

    service = WbPriceUpdateService(session)

    can_change, reason = await service._can_change_price(
        product=product,
        new_price=Decimal("750"),
        rec=rec,
    )

    assert can_change is False
    assert "minPrice" in reason


# Test 2: Price below MRC lower bound => no WB request sent
@pytest.mark.asyncio
async def test_price_below_mrc_lower_bound_no_wb_request():
    """recommended_price below mrc_lower_bound => skipped."""
    session = AsyncMock()
    product = _make_product()
    rec = _make_rec(
        recommended_price=Decimal("830"),
        mrc_lower_bound=Decimal("837"),
        min_price=Decimal("800"),
    )

    service = WbPriceUpdateService(session)

    can_change, reason = await service._can_change_price(
        product=product,
        new_price=Decimal("830"),
        rec=rec,
    )

    assert can_change is False
    assert "МРЦ" in reason


# Test 3: Price above MRC upper bound => no WB request sent
@pytest.mark.asyncio
async def test_price_above_mrc_upper_bound_no_wb_request():
    """recommended_price above mrc_upper_bound => skipped."""
    session = AsyncMock()
    product = _make_product()
    rec = _make_rec(
        recommended_price=Decimal("1100"),
        mrc_upper_bound=Decimal("1023"),
        min_price=Decimal("800"),
    )

    service = WbPriceUpdateService(session)

    can_change, reason = await service._can_change_price(
        product=product,
        new_price=Decimal("1100"),
        rec=rec,
    )

    assert can_change is False
    assert "МРЦ" in reason


# Test 4: Price already equals recommended => no WB request sent
@pytest.mark.asyncio
async def test_price_already_equals_recommended():
    """Current WB price equals recommended => skipped."""
    session = AsyncMock()
    product = _make_product()
    rec = _make_rec(
        recommended_price=Decimal("846"),
        mrc_lower_bound=Decimal("837"),
        mrc_upper_bound=Decimal("1023"),
        min_price=Decimal("800"),
    )

    service = WbPriceUpdateService(session)

    with (
        patch.object(service, "_get_current_wb_price", new=AsyncMock(return_value=Decimal("846"))),
        patch.object(service, "_get_last_price_change", new=AsyncMock(return_value=None)),
    ):
        can_change, reason = await service._can_change_price(
            product=product,
            new_price=Decimal("846"),
            rec=rec,
        )

    assert can_change is False
    assert "уже равна" in reason


# Test 5: Price changed recently => cooldown
@pytest.mark.asyncio
async def test_price_changed_recently_cooldown():
    """Price changed < 6 hours ago => skipped."""
    session = AsyncMock()
    product = _make_product()
    rec = _make_rec(
        recommended_price=Decimal("846"),
        mrc_lower_bound=Decimal("837"),
        mrc_upper_bound=Decimal("1023"),
        min_price=Decimal("800"),
    )

    service = WbPriceUpdateService(session)

    recent_time = datetime.now(tz=UTC) - timedelta(hours=2)
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


# Test 6: Valid price change passes all checks
@pytest.mark.asyncio
async def test_valid_price_change_passes_all_checks():
    """Price within all bounds, no recent change, not equal => can change."""
    session = AsyncMock()
    product = _make_product()
    rec = _make_rec(
        recommended_price=Decimal("846"),
        mrc_lower_bound=Decimal("837"),
        mrc_upper_bound=Decimal("1023"),
        min_price=Decimal("800"),
    )

    service = WbPriceUpdateService(session)

    with (
        patch.object(service, "_get_current_wb_price", new=AsyncMock(return_value=Decimal("930"))),
        patch.object(service, "_get_last_price_change", new=AsyncMock(return_value=None)),
    ):
        can_change, reason = await service._can_change_price(
            product=product,
            new_price=Decimal("846"),
            rec=rec,
        )

    assert can_change is True
    assert reason is None


# Test 7: _get_current_wb_price returns price from wb_product_prices first
@pytest.mark.asyncio
async def test_get_current_wb_price_from_product_prices():
    """_get_current_wb_price should return price from WbProductPrice first."""
    session = AsyncMock()
    product = _make_product()

    prices_scalar = AsyncMock()
    prices_scalar.scalar_one_or_none = MagicMock(return_value=Decimal("1200"))
    nom_scalar = AsyncMock()
    nom_scalar.scalar_one_or_none = MagicMock(return_value=Decimal("930"))
    cond_scalar = AsyncMock()
    cond_scalar.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(side_effect=[prices_scalar, nom_scalar, cond_scalar])

    service = WbPriceUpdateService(session)
    price = await service._get_current_wb_price(product)

    assert price == Decimal("1200")


# Test 8: _get_current_wb_price returns price from nomenclatures
@pytest.mark.asyncio
async def test_get_current_wb_price_from_nomenclatures():
    """_get_current_wb_price should return price from WbPromotionNomenclature."""
    session = AsyncMock()
    product = _make_product()

    prices_scalar = AsyncMock()
    prices_scalar.scalar_one_or_none = MagicMock(return_value=None)
    nom_scalar = AsyncMock()
    nom_scalar.scalar_one_or_none = MagicMock(return_value=Decimal("930"))
    cond_scalar = AsyncMock()
    cond_scalar.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(side_effect=[prices_scalar, nom_scalar, cond_scalar])

    service = WbPriceUpdateService(session)
    price = await service._get_current_wb_price(product)

    assert price == Decimal("930")


# Test 8: _get_current_wb_price falls back to conditions
@pytest.mark.asyncio
async def test_get_current_wb_price_fallback_to_conditions():
    """_get_current_wb_price should fall back to WbAutoPromotionCondition."""
    session = AsyncMock()
    product = _make_product()

    prices_scalar = AsyncMock()
    prices_scalar.scalar_one_or_none = MagicMock(return_value=None)
    nom_scalar = AsyncMock()
    nom_scalar.scalar_one_or_none = MagicMock(return_value=None)
    cond_scalar = AsyncMock()
    cond_scalar.scalar_one_or_none = MagicMock(return_value=Decimal("846"))
    session.execute = AsyncMock(side_effect=[nom_scalar, cond_scalar])

    service = WbPriceUpdateService(session)
    price = await service._get_current_wb_price(product)

    assert price == Decimal("846")


# Test 9: _get_current_wb_price returns None when no data
@pytest.mark.asyncio
async def test_get_current_wb_price_no_data():
    """_get_current_wb_price returns None when no price data available."""
    session = AsyncMock()
    product = _make_product()

    prices_scalar = AsyncMock()
    prices_scalar.scalar_one_or_none = MagicMock(return_value=None)
    nom_scalar = AsyncMock()
    nom_scalar.scalar_one_or_none = MagicMock(return_value=None)
    cond_scalar = AsyncMock()
    cond_scalar.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(side_effect=[prices_scalar, nom_scalar, cond_scalar])

    service = WbPriceUpdateService(session)
    price = await service._get_current_wb_price(product)

    assert price is None


# Test 10: _get_current_wb_price returns None for invalid nmID
@pytest.mark.asyncio
async def test_get_current_wb_price_invalid_nm_id():
    """_get_current_wb_price returns None when product has no valid nmID."""
    session = AsyncMock()
    product = _make_product(
        marketplace_article="",
        external_product_id="",
    )

    service = WbPriceUpdateService(session)
    price = await service._get_current_wb_price(product)

    assert price is None


# Test 11: _record_history saves new fields
@pytest.mark.asyncio
async def test_record_history_saves_bounds():
    """_record_history should save min_price, mrc_lower_bound, mrc_upper_bound."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    service = WbPriceUpdateService(session)
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
    record = session.add.call_args[0][0]
    assert record.min_price == Decimal("800")
    assert record.mrc_lower_bound == Decimal("837")
    assert record.mrc_upper_bound == Decimal("1023")
    assert record.status == STATUS_APPLIED
    assert record.dry_run is False
    assert record.source == "auto"
