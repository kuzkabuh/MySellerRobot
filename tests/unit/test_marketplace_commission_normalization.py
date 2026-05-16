"""version: 1.1.0
description: Unit tests for WB/Ozon marketplace commission and tariff normalization.
updated: 2026-05-15
"""

from decimal import Decimal

from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import Order, OrderItem, Product
from app.models.enums import EconomyConfidence, ExpenseSource, Marketplace, SaleModel
from app.services.marketplace_estimates import calculate_planned_economics
from app.services.product_sync_service import ProductSyncService


def test_wb_report_order_uses_commission_percent_when_amount_absent() -> None:
    order = WildberriesClient("token").normalize_report_order(
        {
            "srid": "wb-1",
            "orderDate": "2026-05-15T10:00:00Z",
            "nmID": 123,
            "supplierArticle": "SKU-1",
            "retailPriceWithDiscRub": "1000",
            "commissionPercent": "12.5",
        }
    )

    assert order.items[0].commission_estimated == Decimal("125.00")


def test_wb_report_order_uses_exact_commission_amount() -> None:
    order = WildberriesClient("token").normalize_report_order(
        {
            "srid": "wb-2",
            "orderDate": "2026-05-15T10:00:00Z",
            "nmID": 124,
            "supplierArticle": "SKU-2",
            "retailPriceWithDiscRub": "1000",
            "ppvzReward": "-180",
        }
    )

    assert order.items[0].commission_estimated == Decimal("180")


def test_ozon_order_uses_financial_commission_and_services() -> None:
    order = OzonClient("client", "key").normalize_fbo_posting(
        {
            "posting_number": "ozon-1",
            "created_at": "2026-05-15T10:00:00Z",
            "status": "delivered",
            "products": [
                {
                    "sku": 999,
                    "offer_id": "SKU-1",
                    "name": "Товар",
                    "quantity": 1,
                    "price": "1000",
                }
            ],
            "financial_data": {
                "products": [
                    {
                        "sku": 999,
                        "commission_amount": "-150",
                        "payout": "800",
                        "services": [
                            {"name": "MarketplaceServiceItemDirectFlowLogistic", "price": "-70"},
                            {"name": "MarketplaceServiceItemReturnProcessing", "price": "-20"},
                        ],
                    }
                ]
            },
        }
    )

    item = order.items[0]
    assert item.commission_estimated == Decimal("150")
    assert item.logistics_estimated == Decimal("70")
    assert item.other_marketplace_expenses_estimated == Decimal("20")


def test_product_sync_applies_official_wb_commission_tariff() -> None:
    product = WildberriesClient("token").normalize_card_product(
        payload={
            "nmID": 303948126,
            "vendorCode": "W4079",
            "title": "Салфетки",
            "subjectID": 99,
            "subjectName": "Салфетки для уборки",
        },
        user_id=1,
        account_id=10,
    )

    ProductSyncService._apply_wb_commission_tariff(
        product,
        {"subjectID": 99, "subjectName": "Салфетки для уборки"},
        {"99": Decimal("0.1250")},
    )

    assert product.marketplace_category_id == "99"
    assert product.marketplace_commission_rate == Decimal("0.1250")
    assert product.marketplace_commission_source == "WB tariffs /api/v1/tariffs/commission"


def test_wb_planned_economics_uses_product_tariff_instead_of_fixed_guess() -> None:
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.FBS)
    item = OrderItem(discounted_price=Decimal("1000"), quantity=1)
    product = Product(marketplace_commission_rate=Decimal("0.1250"))

    economics = calculate_planned_economics(
        order,
        item,
        product_commission_rate=product.marketplace_commission_rate,
    )

    assert economics.commission == Decimal("125.00")
    assert economics.commission_rate == Decimal("0.1250")
    assert economics.commission_is_known is True
    assert economics.commission_is_baseline is True
    assert economics.commission_source == ExpenseSource.WB_TARIFF_API
    assert economics.confidence == EconomyConfidence.PRELIMINARY


def test_wb_planned_economics_does_not_fake_unknown_commission() -> None:
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.FBS)
    item = OrderItem(discounted_price=Decimal("1000"), quantity=1)

    economics = calculate_planned_economics(order, item)

    assert economics.commission == Decimal("0.00")
    assert economics.commission_rate is None
    assert economics.commission_is_known is False
    assert economics.confidence == EconomyConfidence.PRELIMINARY


def test_exact_economy_when_marketplace_expenses_are_fact_based() -> None:
    order = Order(marketplace=Marketplace.OZON, sale_model=SaleModel.FBO)
    item = OrderItem(
        discounted_price=Decimal("1000"),
        quantity=1,
        commission_estimated=Decimal("150"),
        logistics_estimated=Decimal("70"),
    )

    economics = calculate_planned_economics(order, item)

    assert economics.commission_source == ExpenseSource.OZON_FINANCIAL_DATA
    assert economics.logistics_source == ExpenseSource.OZON_FINANCIAL_DATA
    assert economics.confidence == EconomyConfidence.EXACT


def test_wb_fbs_fallback_logistics_is_not_exact() -> None:
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.FBS)
    item = OrderItem(
        discounted_price=Decimal("1000"),
        quantity=1,
        commission_estimated=Decimal("120"),
        logistics_estimated=Decimal("0"),
    )

    economics = calculate_planned_economics(order, item)

    assert economics.logistics == Decimal("92.00")
    assert economics.logistics_is_known is False
    assert economics.logistics_source == ExpenseSource.FALLBACK_DEFAULT
    assert economics.confidence == EconomyConfidence.PRELIMINARY
