"""version: 1.2.0
description: Unit tests for marketplace product normalization, dimensions, and enriched fields.
updated: 2026-05-17
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
            "dimensions": {"length": 20, "width": 10, "height": 5},
            "sizes": [{"chrtID": 777001}],
            "photos": [{"big": "https://example.com/image.jpg"}],
        },
        user_id=1,
        account_id=2,
    )

    assert product.marketplace == Marketplace.WB
    assert product.external_product_id == "123456789"
    assert product.seller_article == "SKU-001"
    assert product.image_url == "https://example.com/image.jpg"
    assert product.chrt_id == "777001"
    assert product.length_cm == 20
    assert product.width_cm == 10
    assert product.height_cm == 5
    assert product.volume_liters is not None
    assert str(product.volume_liters) == "1.000"
    assert product.dimensions_source == "WB_CONTENT_API"


def test_ozon_product_normalization() -> None:
    product = OzonClient("client", "key").normalize_product(
        payload={
            "product_id": 987,
            "offer_id": "OZON-SKU-001",
            "sku": 555,
            "name": "Полотенце Ozon",
            "brand": "Fresh",
            "description_category_name": "Полотенца",
            "images": ["https://example.com/ozon.jpg"],
            "visibility": "VISIBLE",
        },
        user_id=1,
        account_id=2,
    )

    assert product.marketplace == Marketplace.OZON
    assert product.external_product_id == "987"
    assert product.seller_article == "OZON-SKU-001"
    assert product.marketplace_article == "555"
    assert product.brand == "Fresh"
    assert product.category == "Полотенца"
    assert product.image_url == "https://example.com/ozon.jpg"
