"""version: 1.1.0
description: Unit tests for buyout, WB daily sales report, and completed sale events.
updated: 2026-05-17
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount, Order, OrderItem, ReturnsEvent, SalesEvent
from app.models.enums import Marketplace, NotificationType, SaleEventType, SaleModel
from app.services.order_card_service import OrderCardService
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


@pytest.mark.asyncio
async def test_wb_cancellation_card_handles_partial_product_data() -> None:
    order = Order(
        id=10,
        user_id=7,
        marketplace_account_id=55,
        marketplace=Marketplace.WB,
        order_external_id="wb-order-10",
        order_date=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
        sale_model=SaleModel.FBS,
        status="cancelled",
        normalized_status="cancelled",
    )
    item = OrderItem(
        order_id=10,
        marketplace_article="123456",
        quantity=1,
        discounted_price=Decimal("500"),
    )

    card = await OrderCardService(_FakeSession()).cancellation_card(  # type: ignore[arg-type]
        order=order,
        item=item,
        timezone_name="Europe/Moscow",
    )

    assert "Отмена заказа — WB" in card.text
    assert card.product_url == "https://www.wildberries.ru/catalog/123456/detail.aspx?targetUrl=XS"


@pytest.mark.asyncio
async def test_wb_return_card_handles_missing_order_link() -> None:
    event = ReturnsEvent(
        id=99,
        user_id=7,
        marketplace_account_id=55,
        marketplace=Marketplace.WB,
        external_event_id="wb-return-R123",
        order_external_id=None,
        event_date=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
        quantity=1,
        amount=Decimal("500"),
        reason="Возврат Wildberries",
        raw_payload={},
    )

    card = await OrderCardService(_FakeSession()).return_card(
        event=event,
        timezone_name="Europe/Moscow",
    )

    assert "Возврат — WB" in card.text
    assert "Заказ: н/д" in card.text


def test_ozon_return_rows_are_extracted_from_supported_shapes() -> None:
    service = SalesEventSyncService(object())  # type: ignore[arg-type]

    assert service._extract_returns({"returns": [{"id": 1}]}) == [{"id": 1}]
    assert service._extract_returns({"result": {"returns": [{"id": 2}]}}) == [{"id": 2}]
    assert service._extract_returns({"result": [{"id": 3}]}) == [{"id": 3}]


def test_string_false_disables_sale_notifications() -> None:
    account = type("Account", (), {"notification_settings": {"SALE_COMPLETED": "false"}})()

    assert SalesEventSyncService._buyout_notifications_enabled(account) is False


def test_string_false_disables_return_notifications() -> None:
    account = type("Account", (), {"notification_settings": {"RETURN_CREATED": "false"}})()

    assert (
        SalesEventSyncService._lifecycle_notifications_enabled(
            account,
            NotificationType.RETURN_CREATED,
        )
        is False
    )


@pytest.mark.asyncio
async def test_wb_regular_sync_stores_returns_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SalesEventSyncService(_FakeSession())  # type: ignore[arg-type]
    service.cipher = _FakeCipher()  # type: ignore[assignment]
    service.orders = _FakeOrders()  # type: ignore[assignment]
    service.profits = _FakeProfits()  # type: ignore[assignment]
    sales = _FakeSales()
    returns = _FakeReturns()
    service.sales = sales  # type: ignore[assignment]
    service.returns = returns  # type: ignore[assignment]
    service.products = _FakeProducts()  # type: ignore[assignment]
    monkeypatch.setattr("app.services.sales_event_sync_service.WildberriesClient", _FakeWbClient)

    result = await service.sync_account(_account(), lookback_hours=72)

    assert result.sales_created == 1
    assert result.returns_created == 1
    assert [event.external_event_id for event in sales.events] == ["wb-sale-S123"]
    assert [event["external_event_id"] for event in returns.events] == ["wb-return-R123"]


class _FakeSession:
    async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return _FakeResult()

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _FakeResult:
    def scalar_one_or_none(self):  # type: ignore[no-untyped-def]
        return None


class _FakeCipher:
    def decrypt(self, value: str) -> str:
        return value


class _FakeOrders:
    async def upsert(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("orders are not expected in this test")

    async def get_by_external(self, **_kwargs):  # type: ignore[no-untyped-def]
        return None


class _FakeProfits:
    async def calculate_estimated_profit(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return None


class _FakeProducts:
    async def find_for_order_item(self, **_kwargs):  # type: ignore[no-untyped-def]
        return None


class _FakeSales:
    def __init__(self) -> None:
        self.events = []

    async def upsert_normalized(self, **kwargs):  # type: ignore[no-untyped-def]
        event = kwargs["event"]
        self.events.append(event)
        return SalesEvent(id=len(self.events), **_sale_event_kwargs(event)), True


class _FakeReturns:
    def __init__(self) -> None:
        self.events = []

    async def upsert(self, **kwargs):  # type: ignore[no-untyped-def]
        self.events.append(kwargs)
        return type("ReturnRow", (), {"id": len(self.events)})(), True


class _FakeWbClient(WildberriesClient):
    def __init__(self, _api_key: str) -> None:
        return None

    async def get_supplier_orders(self, _date_from):  # type: ignore[no-untyped-def]
        return []

    async def get_supplier_sales(self, _date_from):  # type: ignore[no-untyped-def]
        return [
            {
                "saleID": "S123",
                "srid": "srid-sale",
                "date": "2026-05-18T09:00:00Z",
                "nmId": 123,
                "supplierArticle": "WB-SKU",
                "finishedPrice": "1000",
            },
            {
                "saleID": "R123",
                "srid": "srid-return",
                "date": "2026-05-18T10:00:00Z",
                "nmId": 123,
                "supplierArticle": "WB-SKU",
                "quantity": -1,
                "forPay": "-500",
            },
        ]

    normalize_supplier_sale = WildberriesClient.normalize_supplier_sale
    normalize_supplier_return = WildberriesClient.normalize_supplier_return
    is_supplier_sales_return = staticmethod(WildberriesClient.is_supplier_sales_return)


def _account() -> MarketplaceAccount:
    return MarketplaceAccount(
        id=55,
        user_id=7,
        marketplace=Marketplace.WB,
        name="WB",
        encrypted_api_key="token",
        notification_settings={},
    )


def _sale_event_kwargs(event):  # type: ignore[no-untyped-def]
    return {
        "user_id": 7,
        "marketplace_account_id": 55,
        "marketplace": event.marketplace,
        "external_event_id": event.external_event_id,
        "order_external_id": event.order_external_id,
        "event_type": event.event_type,
        "event_date": event.event_date,
        "seller_article": event.seller_article,
        "marketplace_article": event.marketplace_article,
        "quantity": event.quantity,
        "amount": event.amount,
        "raw_payload": event.raw_payload,
    }
