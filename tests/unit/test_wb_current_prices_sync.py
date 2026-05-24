"""Tests for WB current prices sync service and response parsing."""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.services.wb.wb_current_prices_sync_service import WbCurrentPricesSyncService


class TestParseWbGoodsFilterResponse:
    """Test parsing of WB /api/v2/list/goods/filter response with sizes array."""

    def test_parse_price_from_sizes_array(self):
        """Price should be extracted from sizes[0].price when not at top level."""
        item = {
            "nmID": 581624275,
            "vendorCode": "600221",
            "sizes": [
                {
                    "sizeID": 795352166,
                    "price": 10072,
                    "discountedPrice": 2518,
                    "clubDiscountedPrice": 2518,
                    "techSizeName": "0",
                }
            ],
            "currencyIsoCode4217": "RUB",
            "discount": 75,
            "clubDiscount": 0,
            "editableSizePrice": False,
        }

        price = WbCurrentPricesSyncService._parse_price(item)
        assert price == Decimal("10072")

    def test_parse_price_from_top_level(self):
        """Price should be extracted from top level if present."""
        item = {"nmID": 123, "price": 5000, "discount": 50}

        price = WbCurrentPricesSyncService._parse_price(item)
        assert price == Decimal("5000")

    def test_parse_price_returns_none_when_missing(self):
        """Price should be None when not present anywhere."""
        item = {"nmID": 123, "vendorCode": "ABC"}

        price = WbCurrentPricesSyncService._parse_price(item)
        assert price is None

    def test_parse_discount_from_top_level(self):
        """Discount should be extracted from top level."""
        item = {"nmID": 123, "discount": 75}

        discount = WbCurrentPricesSyncService._parse_discount(item)
        assert discount == 75

    def test_parse_discounted_price_from_sizes(self):
        """Discounted price should be extracted from sizes[0].discountedPrice."""
        item = {
            "nmID": 581624275,
            "sizes": [
                {
                    "sizeID": 795352166,
                    "price": 10072,
                    "discountedPrice": 2518,
                    "clubDiscountedPrice": 2518,
                }
            ],
            "discount": 75,
        }

        discounted_price = WbCurrentPricesSyncService._parse_discounted_price(item)
        assert discounted_price == Decimal("2518")

    def test_parse_discounted_price_from_top_level(self):
        """Discounted price should be extracted from top level if present."""
        item = {"nmID": 123, "discountedPrice": 3000}

        discounted_price = WbCurrentPricesSyncService._parse_discounted_price(item)
        assert discounted_price == Decimal("3000")

    def test_parse_club_discount_from_top_level(self):
        """Club discount should be extracted from top level."""
        item = {"nmID": 123, "clubDiscount": 10}

        club_discount = WbCurrentPricesSyncService._parse_club_discount(item)
        assert club_discount == 10

    def test_parse_club_discounted_price_from_sizes(self):
        """Club discounted price should be extracted from sizes[0].clubDiscountedPrice."""
        item = {
            "nmID": 581624275,
            "sizes": [
                {
                    "sizeID": 795352166,
                    "price": 10072,
                    "discountedPrice": 2518,
                    "clubDiscountedPrice": 2000,
                }
            ],
            "clubDiscount": 20,
        }

        club_discounted_price = WbCurrentPricesSyncService._parse_club_discounted_price(item)
        assert club_discounted_price == Decimal("2000")

    def test_parse_club_discounted_price_from_top_level(self):
        """Club discounted price should be extracted from top level if present."""
        item = {"nmID": 123, "clubDiscountedPrice": 4500}

        club_discounted_price = WbCurrentPricesSyncService._parse_club_discounted_price(item)
        assert club_discounted_price == Decimal("4500")

    def test_full_item_parsing_with_sizes(self):
        """Full parsing of a realistic WB response with sizes array."""
        item = {
            "nmID": 581624275,
            "vendorCode": "600221",
            "sizes": [
                {
                    "sizeID": 795352166,
                    "price": 10072,
                    "discountedPrice": 2518,
                    "clubDiscountedPrice": 2518,
                    "techSizeName": "0",
                }
            ],
            "currencyIsoCode4217": "RUB",
            "discount": 75,
            "clubDiscount": 0,
            "editableSizePrice": False,
        }

        price = WbCurrentPricesSyncService._parse_price(item)
        discount = WbCurrentPricesSyncService._parse_discount(item)
        discounted_price = WbCurrentPricesSyncService._parse_discounted_price(item)
        club_discount = WbCurrentPricesSyncService._parse_club_discount(item)
        club_discounted_price = WbCurrentPricesSyncService._parse_club_discounted_price(item)

        assert price == Decimal("10072")
        assert discount == 75
        assert discounted_price == Decimal("2518")
        assert club_discount == 0
        assert club_discounted_price == Decimal("2518")

    def test_price_nullable_when_missing(self):
        """When price is missing and sizes empty, parser returns None (not crash)."""
        item = {
            "nmID": 123,
            "vendorCode": "ABC",
            "sizes": [],
            "currencyIsoCode4217": "RUB",
        }

        price = WbCurrentPricesSyncService._parse_price(item)
        assert price is None

    def test_empty_sizes_array(self):
        """Empty sizes array should not cause errors."""
        item = {
            "nmID": 123,
            "sizes": [],
            "discount": 50,
        }

        price = WbCurrentPricesSyncService._parse_price(item)
        assert price is None

        discounted_price = WbCurrentPricesSyncService._parse_discounted_price(item)
        assert discounted_price is None

    def test_currency_code_parsing(self):
        """Currency code should be extracted from currencyIsoCode4217."""
        item = {"nmID": 123, "currencyIsoCode4217": "RUB"}
        currency = item.get("currencyIsoCode4217") or item.get("currencyCode") or "RUB"
        assert currency == "RUB"

    def test_currency_code_fallback(self):
        """Currency code should fallback to RUB if not present."""
        item = {"nmID": 123}
        currency = item.get("currencyIsoCode4217") or item.get("currencyCode") or "RUB"
        assert currency == "RUB"


class TestExtractNmId:
    """Test nmID extraction from products."""

    def test_extract_from_external_product_id(self):
        """nmID should be extracted from external_product_id."""
        product = MagicMock()
        product.external_product_id = "345455998"
        product.marketplace_article = "ART-123"
        product.marketplace = "WB"

        nm_id = WbCurrentPricesSyncService._extract_nm_id(product)
        assert nm_id == 345455998

    def test_extract_from_marketplace_article(self):
        """nmID should fallback to marketplace_article if external_product_id is None."""
        product = MagicMock()
        product.external_product_id = None
        product.marketplace_article = "345455998"
        product.marketplace = "WB"

        nm_id = WbCurrentPricesSyncService._extract_nm_id(product)
        assert nm_id == 345455998

    def test_returns_none_for_non_wb(self):
        """nmID should be None for non-WB marketplace."""
        product = MagicMock()
        product.external_product_id = "345455998"
        product.marketplace_article = "345455998"
        product.marketplace = "OZON"

        nm_id = WbCurrentPricesSyncService._extract_nm_id(product)
        assert nm_id is None

    def test_returns_none_for_invalid_nm_id(self):
        """nmID should be None for non-numeric values."""
        product = MagicMock()
        product.external_product_id = "ART-123"
        product.marketplace_article = "SKU-456"
        product.marketplace = "WB"

        nm_id = WbCurrentPricesSyncService._extract_nm_id(product)
        assert nm_id is None

    def test_strips_whitespace(self):
        """nmID should be extracted after stripping whitespace."""
        product = MagicMock()
        product.external_product_id = "  345455998  "
        product.marketplace_article = "ART-123"
        product.marketplace = "WB"

        nm_id = WbCurrentPricesSyncService._extract_nm_id(product)
        assert nm_id == 345455998
