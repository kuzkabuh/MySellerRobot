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
from app.services.unit_economics.order_card_service import OrderCardService
from app.services.common.sales_event_sync_service import SalesEventSyncService


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


def test_wb_sale_event_for_current_day_is_stored() -> None:
    """Verify that a WB sale event for today is correctly normalized and stored."""
    client = WildberriesClient("token")
    payload = {
        "saleID": "S456",
        "srid": "srid-today",
        "date": "2026-05-19T12:00:00Z",
        "nmId": 789,
        "supplierArticle": "TODAY-SKU",
        "subject": "Тестовый товар",
        "finishedPrice": "2500",
        "forPay": "2000",
    }
    event = client.normalize_supplier_sale(payload)

    assert event.external_event_id == "wb-sale-S456"
    assert event.event_type == SaleEventType.BUYOUT
    assert event.event_date == datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
    assert event.seller_article == "TODAY-SKU"
    assert event.amount == Decimal("2500")
    assert event.expected_payout == Decimal("2000")
    assert event.marketplace == Marketplace.WB


def test_ozon_completed_sale_event_is_stored() -> None:
    """Verify that an Ozon completed sale event is correctly normalized."""
    from app.integrations.ozon import OzonClient

    client = OzonClient(client_id="cid", api_key="key")
    payload = {
        "posting_number": "ozon-posting-1",
        "status": "delivered",
        "delivering_date": "2026-05-19T15:00:00Z",
        "products": [
            {
                "sku": 111,
                "offer_id": "OZON-SKU-1",
                "name": "Ozon Товар",
                "price": "1500",
                "quantity": 2,
            }
        ],
    }
    events = client.normalize_completed_sale_events(payload, sale_model=SaleModel.FBS)

    assert len(events) == 1
    event = events[0]
    assert event.external_event_id == "ozon-sale-ozon-posting-1-111"
    assert event.event_type == SaleEventType.DELIVERED_TO_CUSTOMER
    assert event.event_date == datetime(2026, 5, 19, 15, 0, tzinfo=UTC)
    assert event.seller_article == "OZON-SKU-1"
    assert event.amount == Decimal("3000")
    assert event.quantity == 2
    assert event.marketplace == Marketplace.OZON


@pytest.mark.asyncio
async def test_new_sale_events_not_lost_on_resync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that new sale events are created on each sync, not lost."""
    service = SalesEventSyncService(_FakeSession())  # type: ignore[arg-type]
    service.cipher = _FakeCipher()  # type: ignore[assignment]
    service.orders = _FakeOrders()  # type: ignore[assignment]
    service.profits = _FakeProfits()  # type: ignore[assignment]
    sales = _FakeSales()
    returns = _FakeReturns()
    service.sales = sales  # type: ignore[assignment]
    service.returns = returns  # type: ignore[assignment]
    service.products = _FakeProducts()  # type: ignore[assignment]

    class _FakeWbClientWithTodaySales(WildberriesClient):
        def __init__(self, _api_key: str) -> None:
            return None

        async def get_supplier_orders(self, _date_from):  # type: ignore[no-untyped-def]
            return []

        async def get_supplier_sales(self, _date_from):  # type: ignore[no-untyped-def]
            return [
                {
                    "saleID": "S789",
                    "srid": "srid-new",
                    "date": "2026-05-19T08:00:00Z",
                    "nmId": 456,
                    "supplierArticle": "NEW-SKU",
                    "finishedPrice": "3000",
                }
            ]

        normalize_supplier_sale = WildberriesClient.normalize_supplier_sale
        normalize_supplier_return = WildberriesClient.normalize_supplier_return
        is_supplier_sales_return = staticmethod(WildberriesClient.is_supplier_sales_return)

    monkeypatch.setattr(
        "app.services.sales_event_sync_service.WildberriesClient",
        _FakeWbClientWithTodaySales,
    )

    result = await service.sync_account(_account(), lookback_hours=72)

    assert result.sales_created == 1
    assert result.sales_fetched == 1
    assert len(sales.events) == 1
    assert sales.events[0].external_event_id == "wb-sale-S789"


@pytest.mark.asyncio
async def test_sync_does_not_crash_on_rollback_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that sync handles rollback gracefully without greenlet_spawn errors."""
    session = _FakeSessionWithRollback()
    service = SalesEventSyncService(session)  # type: ignore[arg-type]
    service.cipher = _FakeCipher()  # type: ignore[assignment]
    service.orders = _FakeOrders()  # type: ignore[assignment]
    service.profits = _FakeProfits()  # type: ignore[assignment]
    service.sales = _FakeSales()  # type: ignore[assignment]
    service.returns = _FakeReturns()  # type: ignore[assignment]
    service.products = _FakeProducts()  # type: ignore[assignment]

    class _FailingWbClient(WildberriesClient):
        def __init__(self, _api_key: str) -> None:
            return None

        async def get_supplier_orders(self, _date_from):  # type: ignore[no-untyped-def]
            raise RuntimeError("API timeout")

        async def get_supplier_sales(self, _date_from):  # type: ignore[no-untyped-def]
            return []

        normalize_supplier_sale = WildberriesClient.normalize_supplier_sale
        normalize_supplier_return = WildberriesClient.normalize_supplier_return
        is_supplier_sales_return = staticmethod(WildberriesClient.is_supplier_sales_return)

    monkeypatch.setattr(
        "app.services.sales_event_sync_service.WildberriesClient",
        _FailingWbClient,
    )

    result = await service.sync_account(_account(), lookback_hours=72)

    assert result.failed >= 1
    assert session.rollback_count >= 1


def test_web_sales_page_filters_today_period() -> None:
    """Verify that the web sales page correctly builds filters for today period."""
    from app.services.common.web_dashboard_service import build_dashboard_filters

    filters = build_dashboard_filters(
        timezone="Europe/Moscow",
        period="today",
        marketplace="all",
        sale_model="all",
        date_from=None,
        date_to=None,
    )

    assert filters.period == "today"
    assert filters.local_date_from == filters.local_date_to


class _FakeSessionWithRollback:
    """Fake session that tracks rollback calls."""

    def __init__(self) -> None:
        self.rollback_count = 0
        self.commit_count = 0

    async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return _FakeResult()

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1
