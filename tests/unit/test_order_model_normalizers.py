"""version: 1.0.0
description: Unit tests for FBO, FBS, and rFBS order normalization.
updated: 2026-05-14
"""

from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.enums import Marketplace, SaleModel, SourceEventType, UrgencyType


def test_wb_fbs_order_requires_seller_action() -> None:
    order = WildberriesClient("token").normalize_fbs_order(
        {
            "id": 13833711,
            "createdAt": "2026-05-14T09:00:00Z",
            "sellerDate": "2026-05-14T15:00:00Z",
            "warehouseId": 658434,
            "nmId": 123456789,
            "article": "TOWEL-FRESH",
            "subject": "Полотенце Fresh",
            "convertedFinalPrice": 1490,
        }
    )

    assert order.marketplace == Marketplace.WB
    assert order.sale_model == SaleModel.FBS
    assert order.urgency_type == UrgencyType.ACTION_REQUIRED
    assert order.source_event_type == SourceEventType.LIVE_ORDER
    assert order.requires_seller_action is True
    assert order.processing_deadline_at is not None


def test_wb_report_order_is_fbo_informational() -> None:
    order = WildberriesClient("token").normalize_report_order(
        {
            "srid": "wb-srid-1",
            "orderDate": "2026-05-14T09:00:00Z",
            "nmID": 123456789,
            "supplierArticle": "TOWEL-FRESH",
            "subjectName": "Полотенце Fresh",
            "retailPriceWithDiscRub": 1490,
            "ppvzForPay": 1280,
            "warehouseName": "Коледино",
        }
    )

    assert order.sale_model == SaleModel.FBO
    assert order.urgency_type == UrgencyType.INFORMATIONAL
    assert order.source_event_type == SourceEventType.REPORT_ORDER
    assert order.requires_seller_action is False


def test_wb_historical_fbs_order_is_not_urgent() -> None:
    order = WildberriesClient("token").normalize_historical_fbs_order(
        {
            "id": 13833712,
            "createdAt": "2026-05-13T09:00:00Z",
            "warehouseId": 658434,
            "nmId": 123456789,
            "article": "TOWEL-FRESH",
            "convertedFinalPrice": 1490,
            "status": "complete",
        }
    )

    assert order.sale_model == SaleModel.FBS
    assert order.source_event_type == SourceEventType.STATISTICS_ORDER
    assert order.urgency_type == UrgencyType.INFORMATIONAL
    assert order.requires_seller_action is False


def test_ozon_fbs_posting_requires_seller_action() -> None:
    order = OzonClient("client", "key").normalize_fbs_posting(
        {
            "posting_number": "123-1",
            "in_process_at": "2026-05-14T09:00:00Z",
            "shipment_date": "2026-05-14T15:00:00Z",
            "status": "awaiting_packaging",
            "delivery_method": {"warehouse": "Склад продавца"},
            "products": [
                {
                    "sku": 123,
                    "offer_id": "TOWEL-FRESH",
                    "name": "Полотенце Fresh",
                    "quantity": 1,
                    "price": "1490",
                }
            ],
            "financial_data": {"products": [{"sku": 123, "commission_amount": "-256"}]},
        }
    )

    assert order.sale_model == SaleModel.FBS
    assert order.urgency_type == UrgencyType.ACTION_REQUIRED
    assert order.source_event_type == SourceEventType.POSTING_EVENT
    assert order.requires_seller_action is True
    assert order.processing_deadline_at is not None


def test_ozon_rfbs_posting_detected_by_delivery_schema() -> None:
    order = OzonClient("client", "key").normalize_fbs_posting(
        {
            "posting_number": "rfbs-1",
            "in_process_at": "2026-05-14T09:00:00Z",
            "shipment_date": "2026-05-14T15:00:00Z",
            "status": "awaiting_packaging",
            "delivery_schema": "rFBS",
            "products": [{"offer_id": "SKU-1", "price": "500"}],
        }
    )

    assert order.sale_model == SaleModel.RFBS
    assert order.delivery_schema == "rFBS"
    assert order.requires_seller_action is True


def test_ozon_fbo_posting_is_informational() -> None:
    order = OzonClient("client", "key").normalize_fbo_posting(
        {
            "posting_number": "fbo-1",
            "in_process_at": "2026-05-14T09:00:00Z",
            "status": "delivering",
            "analytics_data": {"warehouse_name": "Ozon Fulfillment"},
            "products": [
                {
                    "sku": 456,
                    "offer_id": "TOWEL-FRESH",
                    "name": "Полотенце Fresh",
                    "quantity": 1,
                    "price": "1490",
                }
            ],
        }
    )

    assert order.sale_model == SaleModel.FBO
    assert order.urgency_type == UrgencyType.INFORMATIONAL
    assert order.requires_seller_action is False
    assert order.warehouse_type == "marketplace"
