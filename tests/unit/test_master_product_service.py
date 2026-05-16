"""version: 1.0.0
description: Unit tests for master product matching and web rendering.
updated: 2026-05-15
"""

from decimal import Decimal

from app.models.enums import Marketplace
from app.services.master_product_service import (
    MarketplaceComparisonRow,
    MarketplaceProductInfo,
    MasterProductAnalyticsRow,
    MasterProductDetail,
    normalize_master_sku,
)
from app.web.routes import _master_product_detail_content, _products_content


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
    assert "/web/products/1" in html


def test_master_product_detail_content_renders_marketplace_comparison() -> None:
    html = _master_product_detail_content(
        MasterProductDetail(
            master_product_id=1,
            canonical_sku="SKU001",
            title="Полотенце Fresh",
            brand="Fresh",
            category="Полотенца",
            image_url=None,
            marketplace_products=(
                MarketplaceProductInfo(
                    marketplace=Marketplace.WB,
                    seller_article="SKU001",
                    marketplace_article="123",
                    title="Полотенце WB",
                    brand="Fresh",
                ),
            ),
            marketplace_comparison=(
                MarketplaceComparisonRow(
                    marketplace=Marketplace.WB,
                    orders=5,
                    sales=3,
                    revenue=Decimal("5000"),
                    estimated_profit=Decimal("1000"),
                    actual_profit=Decimal("800"),
                    margin_percent=Decimal("20.0"),
                    stock_quantity=7,
                ),
                MarketplaceComparisonRow(
                    marketplace=Marketplace.OZON,
                    orders=2,
                    sales=1,
                    revenue=Decimal("1800"),
                    estimated_profit=Decimal("500"),
                    actual_profit=Decimal("450"),
                    margin_percent=Decimal("27.8"),
                    stock_quantity=4,
                ),
            ),
            recommendations=("На Ozon маржа выше, чем на Wildberries.",),
        )
    )

    assert "Сравнение WB / Ozon" in html
    assert "На Ozon маржа выше" in html
    assert "5 000 ₽" in html
