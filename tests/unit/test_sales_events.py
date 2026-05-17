"""version: 1.1.0
description: Unit tests for buyout, WB daily sales report, and completed sale events.
updated: 2026-05-17
"""

from datetime import UTC, datetime
from decimal import Decimal

from app.integrations.wb import WildberriesClient
from app.models.domain import SalesEvent
from app.models.enums import Marketplace, SaleEventType
from app.services.sales_event_sync_service import SalesEventSyncService


def test_wb_buyout_notification_text() -> None:
    event = SalesEvent(
        user_id=1,
        marketplace_account_id=1,
        marketplace=Marketplace.WB,
        external_event_id="wb-sale-1",
        order_external_id="srid-1",
        event_type=SaleEventType.BUYOUT,
        event_date=datetime(2026, 5, 14, 16, 42, tzinfo=UTC),
        seller_article="TOWEL-FRESH-MINT",
        marketplace_article="123456789",
        quantity=1,
        amount=Decimal("1490"),
        estimated_profit=Decimal("282"),
        raw_payload={},
    )

    text = SalesEventSyncService.format_sale_notification(event)

    assert "✅ Выкуп товара — Wildberries" in text
    assert "Сумма продажи: 1 490 ₽" in text
    assert "Плановая прибыль: 282 ₽" in text


def test_ozon_completed_sale_notification_without_profit() -> None:
    event = SalesEvent(
        user_id=1,
        marketplace_account_id=2,
        marketplace=Marketplace.OZON,
        external_event_id="ozon-sale-1",
        order_external_id="posting-1",
        event_type=SaleEventType.DELIVERED_TO_CUSTOMER,
        event_date=datetime(2026, 5, 14, 16, 42, tzinfo=UTC),
        seller_article="OFFER-1",
        marketplace_article="987654",
        quantity=1,
        amount=Decimal("1190"),
        raw_payload={},
    )

    text = SalesEventSyncService.format_sale_notification(event)

    assert "✅ Продажа завершена — Ozon" in text
    assert "Плановая прибыль: пока не рассчитана" in text


def test_wb_supplier_sales_return_detection() -> None:
    assert WildberriesClient.is_supplier_sales_return({"saleID": "R123"}) is True
    assert WildberriesClient.is_supplier_sales_return({"docTypeName": "Возврат"}) is True
    assert WildberriesClient.is_supplier_sales_return({"saleID": "S123"}) is False


def test_wb_supplier_return_normalization() -> None:
    row = WildberriesClient("token").normalize_supplier_return(
        {
            "saleID": "R123",
            "srid": "srid-1",
            "date": "2026-05-17T10:00:00Z",
            "quantity": -1,
            "forPay": "-450.25",
        }
    )

    assert row["external_event_id"] == "wb-return-R123"
    assert row["quantity"] == 1
    assert row["amount"] == Decimal("450.25")
