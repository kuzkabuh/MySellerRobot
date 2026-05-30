"""Comprehensive tests for WB auto promotion price control block.

Covers:
- build_recommendation for key business scenarios
- calculate_wb_price_payload_for_target
- TokenCipher decryption for saved API keys
- WbProductPrice parsing from sizes
- Skipping items with no price data
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.pricing.wb_auto_promo_price_service import (
    STATUS_AUTO_MIN_PRICE_VIOLATION,
    STATUS_AUTO_PRICE_OK,
    STATUS_AUTO_PRICE_VIOLATION,
    STATUS_AUTO_REQUIRED_PRICE_UNKNOWN,
    STATUS_AUTO_SET_PRICE,
    WbAutoPromoPriceService,
)
from app.services.pricing.wb_price_update_service import (
    calculate_wb_price_payload_for_target,
    is_quarantine_risk,
)
from app.services.wb.wb_current_prices_sync_service import WbCurrentPricesSyncService


def _make_product(
    product_id: int = 1,
    user_id: int = 1,
    account_id: int = 1,
    mrc_price: Decimal | None = Decimal("1000"),
    marketplace_article: str = "12345678",
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


class TestBuildRecommendationBusinessScenario:
    """Test the exact business scenario from the audit task."""

    @pytest.mark.asyncio
    async def test_mrc_1000_required_950_deviation_10_set_price(self):
        """MRC=1000, required=950, deviation=10%, current=1000
        lower_bound=900, 950>=900 => AUTO_PROMOTION_SET_PRICE, recommended=950
        """
        product = _make_product(mrc_price=Decimal("1000"))
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
                required_price=Decimal("950"),
                min_price=Decimal("800"),
            )

        assert rec.status == STATUS_AUTO_SET_PRICE
        assert rec.recommended_price == Decimal("950")
        assert rec.mrc_lower_bound == Decimal("900")
        assert rec.mrc_upper_bound == Decimal("1100")
        assert rec.required_price == Decimal("950")

    @pytest.mark.asyncio
    async def test_required_850_below_lower_bound_900_violation(self):
        """MRC=1000, required=850, deviation=10%
        lower_bound=900, 850<900 => AUTO_PROMOTION_PRICE_VIOLATION
        """
        product = _make_product(mrc_price=Decimal("1000"))
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
                required_price=Decimal("850"),
                min_price=Decimal("700"),
            )

        assert rec.status == STATUS_AUTO_PRICE_VIOLATION
        assert rec.recommended_price is None
        assert rec.mrc_lower_bound == Decimal("900")

    @pytest.mark.asyncio
    async def test_current_940_already_below_required_950_price_ok(self):
        """MRC=1000, required=950, current=940
        940<=950 => AUTO_PROMOTION_PRICE_OK
        """
        product = _make_product(mrc_price=Decimal("1000"))
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
                current_wb_price=Decimal("940"),
                required_price=Decimal("950"),
                min_price=Decimal("800"),
            )

        assert rec.status == STATUS_AUTO_PRICE_OK
        assert rec.recommended_price is None

    @pytest.mark.asyncio
    async def test_min_price_violation(self):
        """required=850, minPrice=870 => AUTO_PROMOTION_MIN_PRICE_VIOLATION"""
        product = _make_product(mrc_price=Decimal("1000"))
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
    async def test_required_price_unknown(self):
        """required_price=None => AUTO_PROMOTION_REQUIRED_PRICE_UNKNOWN"""
        product = _make_product(mrc_price=Decimal("1000"))
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


class TestWbPricePayload:
    """Test WB price/discount payload calculation."""

    def test_payload_950_target_75_discount(self):
        """target=950, discount=75% => price=3800, discount=75, final=950"""
        payload = calculate_wb_price_payload_for_target(
            target_discounted_price=Decimal("950"),
            discount_percent=Decimal("75"),
            nm_id=12345678,
        )

        assert payload.price == 3800
        assert payload.discount == 75
        assert payload.final_discounted_price == Decimal("950")
        assert payload.target_discounted_price == Decimal("950")
        assert payload.nm_id == 12345678

    def test_payload_2518_target_75_discount(self):
        """target=2518, discount=75% => price=10072, discount=75, final=2518"""
        payload = calculate_wb_price_payload_for_target(
            target_discounted_price=Decimal("2518"),
            discount_percent=Decimal("75"),
        )

        assert payload.price == 10072
        assert payload.discount == 75
        assert payload.final_discounted_price == Decimal("2518")

    def test_payload_1000_target_50_discount(self):
        """target=1000, discount=50% => price=2000, discount=50, final=1000"""
        payload = calculate_wb_price_payload_for_target(
            target_discounted_price=Decimal("1000"),
            discount_percent=Decimal("50"),
        )

        assert payload.price == 2000
        assert payload.discount == 50
        assert payload.final_discounted_price == Decimal("1000")

    def test_payload_rounding_adjustment(self):
        """When rounding causes final > target, price should be reduced by 1."""
        payload = calculate_wb_price_payload_for_target(
            target_discounted_price=Decimal("999"),
            discount_percent=Decimal("75"),
        )

        assert payload.final_discounted_price <= Decimal("999")
        assert payload.price * Decimal("0.25") >= Decimal("998")


class TestQuarantineRisk:
    """Test quarantine risk detection."""

    def test_no_risk_when_price_similar(self):
        assert is_quarantine_risk(Decimal("1000"), Decimal("950")) is False

    def test_risk_when_price_3x_lower(self):
        assert is_quarantine_risk(Decimal("3000"), Decimal("1000")) is True

    def test_no_risk_when_old_price_none(self):
        assert is_quarantine_risk(None, Decimal("950")) is False

    def test_no_risk_when_old_price_zero(self):
        assert is_quarantine_risk(Decimal("0"), Decimal("950")) is False


class TestWbProductPriceParsing:
    """Test WB price parsing from sizes array."""

    def test_parse_price_from_sizes(self):
        item = {
            "nmID": 581624275,
            "sizes": [{"sizeID": 1, "price": 10072, "discountedPrice": 2518}],
            "discount": 75,
        }
        assert WbCurrentPricesSyncService._parse_price(item) == Decimal("10072")

    def test_parse_discounted_price_from_sizes(self):
        item = {
            "nmID": 581624275,
            "sizes": [{"sizeID": 1, "price": 10072, "discountedPrice": 2518}],
        }
        assert WbCurrentPricesSyncService._parse_discounted_price(item) == Decimal("2518")

    def test_parse_price_returns_none_when_no_data(self):
        item = {"nmID": 123, "vendorCode": "ABC"}
        assert WbCurrentPricesSyncService._parse_price(item) is None

    def test_parse_discounted_price_returns_none_when_no_data(self):
        item = {"nmID": 123}
        assert WbCurrentPricesSyncService._parse_discounted_price(item) is None

    def test_multiple_sizes_uses_first_price_and_minimum_discounted(self):
        item = {
            "nmID": 123,
            "sizes": [
                {"sizeID": 1, "price": 15000, "discountedPrice": 5000},
                {"sizeID": 2, "price": 10000, "discountedPrice": 3000},
            ],
        }
        assert WbCurrentPricesSyncService._parse_price(item) == Decimal("15000")
        assert WbCurrentPricesSyncService._parse_discounted_price(item) == Decimal("3000")


class TestTokenCipher:
    """Test TokenCipher encryption/decryption."""

    def test_encrypt_decrypt_roundtrip(self):
        from app.core.security import TokenCipher

        cipher = TokenCipher()
        original = "test-api-key-12345"
        encrypted = cipher.encrypt(original)
        decrypted = cipher.decrypt(encrypted)
        assert decrypted == original

    def test_decrypt_invalid_token_raises(self):
        from cryptography.fernet import InvalidToken

        from app.core.security import TokenCipher

        cipher = TokenCipher()
        with pytest.raises((ValueError, InvalidToken)):
            cipher.decrypt("not-a-valid-token")


class TestExtractAutoPromoRequiredPrices:
    """Test automatic extraction of required prices from WB auto promotion details."""

    def test_extract_from_nomenclatures_with_plan_price(self):
        """Should extract required_price from planPrice in nomenclatures list."""
        from app.services.wb.wb_promotions_sync_service import (
            extract_auto_promo_required_prices,
        )

        detail = {
            "nomenclatures": [
                {
                    "id": 12345678,
                    "price": 4000,
                    "planPrice": 950,
                    "inAction": False,
                }
            ]
        }

        conditions = extract_auto_promo_required_prices(
            detail=detail,
            promotion_id=100,
            promotion_name="Test Auto Promo",
        )

        assert len(conditions) == 1
        assert conditions[0].wb_nm_id == 12345678
        assert conditions[0].required_price == Decimal("950")
        assert conditions[0].current_wb_price == Decimal("4000")
        assert conditions[0].promotion_id == 100
        assert conditions[0].promotion_name == "Test Auto Promo"

    def test_extract_from_products_with_required_price(self):
        """Should extract from products list with requiredPrice field."""
        from app.services.wb.wb_promotions_sync_service import (
            extract_auto_promo_required_prices,
        )

        detail = {
            "products": [
                {
                    "nmId": 87654321,
                    "requiredPrice": 850,
                    "maxPrice": 900,
                }
            ]
        }

        conditions = extract_auto_promo_required_prices(detail=detail)

        assert len(conditions) == 1
        assert conditions[0].wb_nm_id == 87654321
        assert conditions[0].required_price == Decimal("850")

    def test_extract_from_data_nomenclatures(self):
        """Should extract from data.nomenclatures nested structure."""
        from app.services.wb.wb_promotions_sync_service import (
            extract_auto_promo_required_prices,
        )

        detail = {
            "data": {
                "nomenclatures": [
                    {
                        "id": 11111111,
                        "maxPrice": 950,
                    }
                ]
            }
        }

        conditions = extract_auto_promo_required_prices(detail=detail)

        assert len(conditions) == 1
        assert conditions[0].wb_nm_id == 11111111
        assert conditions[0].required_price == Decimal("950")

    def test_extract_uses_plan_price_over_max_price(self):
        """planPrice should take priority over maxPrice."""
        from app.services.wb.wb_promotions_sync_service import (
            extract_auto_promo_required_prices,
        )

        detail = {
            "nomenclatures": [
                {
                    "id": 22222222,
                    "planPrice": 950,
                    "maxPrice": 1000,
                }
            ]
        }

        conditions = extract_auto_promo_required_prices(detail=detail)

        assert conditions[0].required_price == Decimal("950")

    def test_extract_multiple_products(self):
        """Should extract conditions for all products in the list."""
        from app.services.wb.wb_promotions_sync_service import (
            extract_auto_promo_required_prices,
        )

        detail = {
            "nomenclatures": [
                {"id": 1, "planPrice": 950},
                {"id": 2, "planPrice": 850},
                {"id": 3, "planPrice": 1000},
            ]
        }

        conditions = extract_auto_promo_required_prices(detail=detail)

        assert len(conditions) == 3
        assert conditions[0].required_price == Decimal("950")
        assert conditions[1].required_price == Decimal("850")
        assert conditions[2].required_price == Decimal("1000")

    def test_extract_skips_items_without_price(self):
        """Items without any price field should still be extracted but with None required_price."""
        from app.services.wb.wb_promotions_sync_service import (
            extract_auto_promo_required_prices,
        )

        detail = {
            "nomenclatures": [
                {"id": 1, "planPrice": 950},
                {"id": 2},
            ]
        }

        conditions = extract_auto_promo_required_prices(detail=detail)

        assert len(conditions) == 2
        assert conditions[0].required_price == Decimal("950")
        assert conditions[1].required_price is None

    def test_extract_from_items_list(self):
        """Should extract from items list as fallback."""
        from app.services.wb.wb_promotions_sync_service import (
            extract_auto_promo_required_prices,
        )

        detail = {"items": [{"nmID": 33333333, "targetPrice": 750}]}

        conditions = extract_auto_promo_required_prices(detail=detail)

        assert len(conditions) == 1
        assert conditions[0].wb_nm_id == 33333333
        assert conditions[0].required_price == Decimal("750")

    def test_extract_from_data_products(self):
        """Should extract from data.products nested structure."""
        from app.services.wb.wb_promotions_sync_service import (
            extract_auto_promo_required_prices,
        )

        detail = {"data": {"products": [{"id": 44444444, "participationPrice": 880}]}}

        conditions = extract_auto_promo_required_prices(detail=detail)

        assert len(conditions) == 1
        assert conditions[0].required_price == Decimal("880")
