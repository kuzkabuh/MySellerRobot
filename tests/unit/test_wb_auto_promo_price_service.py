"""Tests for WbAutoPromoPriceService."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.pricing.wb_auto_promo_price_service import (
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
    mrc_price: Decimal | None = Decimal("900"),
    marketplace_article: str = "345455998",
    external_product_id: str = "",
) -> MagicMock:
    product = MagicMock()
    product.id = product_id
    product.user_id = user_id
    product.marketplace_account_id = account_id
    product.mrc_price = mrc_price
    product.marketplace_article = marketplace_article
    product.external_product_id = external_product_id
    return product


def _make_settings_result(
    deviation: Decimal = Decimal("10"),
) -> MagicMock:
    settings = MagicMock()
    settings.allowed_action_price_deviation_percent = deviation
    return settings


@pytest.mark.asyncio
async def test_set_price_when_current_above_required():
    """current=1000, required=980, mrc=900, deviation=10, min=800
    => AUTO_PROMOTION_SET_PRICE, recommended=980
    """
    product = _make_product(mrc_price=Decimal("900"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(
        return_value=_make_settings_result(Decimal("10"))
    )

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=Decimal("1000"),
            required_price=Decimal("980"),
            min_price=Decimal("800"),
        )

    assert rec.status == STATUS_AUTO_SET_PRICE
    assert rec.recommended_price == Decimal("980")
    assert rec.mrc_lower_bound == Decimal("810")
    assert rec.mrc_upper_bound == Decimal("990")


@pytest.mark.asyncio
async def test_price_violation_when_required_below_lower_bound():
    """current=1000, required=790, mrc=900, deviation=10, min=700
    => AUTO_PROMOTION_PRICE_VIOLATION
    """
    product = _make_product(mrc_price=Decimal("900"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(
        return_value=_make_settings_result(Decimal("10"))
    )

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=Decimal("1000"),
            required_price=Decimal("790"),
            min_price=Decimal("700"),
        )

    assert rec.status == STATUS_AUTO_PRICE_VIOLATION
    assert rec.recommended_price is None


@pytest.mark.asyncio
async def test_price_ok_when_current_below_required():
    """current=970, required=980, mrc=900, deviation=10, min=800
    => AUTO_PROMOTION_PRICE_OK
    """
    product = _make_product(mrc_price=Decimal("900"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(
        return_value=_make_settings_result(Decimal("10"))
    )

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=Decimal("970"),
            required_price=Decimal("980"),
            min_price=Decimal("800"),
        )

    assert rec.status == STATUS_AUTO_PRICE_OK
    assert rec.recommended_price is None


@pytest.mark.asyncio
async def test_min_price_violation():
    """required=850, mrc=900, deviation=10, min=870
    => AUTO_PROMOTION_MIN_PRICE_VIOLATION
    """
    product = _make_product(mrc_price=Decimal("900"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(
        return_value=_make_settings_result(Decimal("10"))
    )

    with patch(
        "app.services.pricing.wb_auto_promo_price_service.MrcPricingSettingsService",
        return_value=mock_settings_svc,
    ):
        service = WbAutoPromoPriceService(session)

        rec = await service.build_recommendation(
            product=product,
            current_wb_price=None,
            required_price=Decimal("850"),
            min_price=Decimal("870"),
        )

    assert rec.status == STATUS_AUTO_MIN_PRICE_VIOLATION
    assert rec.recommended_price is None


@pytest.mark.asyncio
async def test_required_price_unknown():
    """required_price=None => AUTO_PROMOTION_REQUIRED_PRICE_UNKNOWN"""
    product = _make_product(mrc_price=Decimal("900"))
    session = AsyncMock()

    mock_settings_svc = MagicMock()
    mock_settings_svc.get_settings = AsyncMock(
        return_value=_make_settings_result(Decimal("10"))
    )

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


@pytest.mark.asyncio
async def test_no_nm_id():
    """No nmID => AUTO_PROMOTION_WAITING_WB_SYNC"""
    product = _make_product(
        mrc_price=Decimal("900"),
        marketplace_article="",
        external_product_id="",
    )
    session = AsyncMock()

    service = WbAutoPromoPriceService(session)
    rec = await service.build_recommendation(
        product=product,
        current_wb_price=None,
        required_price=Decimal("980"),
    )

    assert rec.status == STATUS_AUTO_WAITING_WB_SYNC
