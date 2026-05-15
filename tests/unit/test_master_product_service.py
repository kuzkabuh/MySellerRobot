"""version: 1.0.0
description: Unit tests for master product matching and web rendering.
updated: 2026-05-15
"""

from decimal import Decimal

from app.models.enums import Marketplace
from app.services.master_product_service import (
    MarketplaceProductInfo,
    MasterProductAnalyticsRow,
    normalize_master_sku,
)
from app.web.routes import _products_content


def test_normalize_master_sku_builds_stable_cross_marketplace_key() -> None:
    assert normalize_master_sku(" wb- 001 ") == "WB-001"
    assert normalize_master_sku("SKU 001") == "SKU001"
    assert normalize_master_sku("") is None
    assert normalize_master_sku(None) is None


def test_products_content_shows_wb_and_ozon_comparison() -> None:
    html = _products_content(
        [
            MasterProductAnalyticsRow(
                master_product_id=1,
                canonical_sku="SKU001",
                title="Полотенце Fresh",
                brand="Fresh",
                category="Полотенца",
                image_url=None,
                wb_products=1,
                ozon_products=1,
                orders=4,
                sales=2,
                revenue=Decimal("2400"),
                estimated_profit=Decimal("700"),
                stock_quantity=12,
                marketplace_products=(
                    MarketplaceProductInfo(
                        marketplace=Marketplace.WB,
                        seller_article="SKU001",
                        marketplace_article="123",
                        title="Полотенце Fresh WB",
                        brand="Fresh",
                    ),
                    MarketplaceProductInfo(
                        marketplace=Marketplace.OZON,
                        seller_article="SKU001",
                        marketplace_article="456",
                        title="Полотенце Fresh Ozon",
                        brand="Fresh",
                    ),
                ),
            )
        ]
    )

    assert "Единые карточки товаров" in html
    assert "WB: 1" in html
    assert "Ozon: 1" in html
    assert "SKU001" in html
    assert "2 400 ₽" in html
    assert "700 ₽" in html
