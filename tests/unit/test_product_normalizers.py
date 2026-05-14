"""version: 1.0.0
description: Unit tests for marketplace product normalization.
updated: 2026-05-14
"""

from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.enums import Marketplace


def test_wb_card_product_normalization() -> None:
    product = WildberriesClient("token").normalize_card_product(
        payload={
            "nmID": 123456789,
            "vendorCode": "SKU-001",
            "title": "Полотенце Fresh",
            "brand": "Fresh",
            "subjectName": "Полотенца",
            "photos": [{"big": "https://example.com/image.jpg"}],
        },
        user_id=1,
        account_id=2,
    )

    assert product.marketplace == Marketplace.WB
    assert product.external_product_id == "123456789"
    assert product.seller_article == "SKU-001"
    assert product.image_url == "https://example.com/image.jpg"


def test_ozon_product_normalization() -> None:
    product = OzonClient("client", "key").normalize_product(
        payload={
            "product_id": 987,
            "offer_id": "OZON-SKU-001",
            "sku": 555,
            "name": "Полотенце Ozon",
            "visibility": "VISIBLE",
        },
        user_id=1,
        account_id=2,
    )

    assert product.marketplace == Marketplace.OZON
    assert product.external_product_id == "987"
    assert product.seller_article == "OZON-SKU-001"
    assert product.marketplace_article == "555"
