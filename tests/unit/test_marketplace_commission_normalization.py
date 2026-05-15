"""version: 1.0.0
description: Unit tests for WB and Ozon marketplace commission normalization.
updated: 2026-05-15
"""

from decimal import Decimal

from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient


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
