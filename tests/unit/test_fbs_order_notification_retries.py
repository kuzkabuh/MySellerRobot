"""version: 1.1.0
description: Regression tests for retryable WB and Ozon FBS order notifications.
updated: 2026-05-17
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount, Order, OrderItem, User
from app.models.enums import Marketplace, SaleModel
from app.schemas.orders import NormalizedOrder, NormalizedOrderItem
from app.services.order_card_service import VisualNotification
from app.services.order_notification_policy import OrderNotificationPolicy
from app.services.order_processing_service import OrderProcessingService


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeOrders:
    def __init__(self, existing: Order | None = None) -> None:
        self.existing = existing
        self.created_order: Order | None = None
        self.mark_notified_called = False

    async def get_by_external(self, **_: Any) -> Order | None:
        return self.existing

    async def create(
        self,
        user_id: int,
        account_id: int,
        normalized: NormalizedOrder,
    ) -> Order:
        order = _order(
            order_id=101,
            user_id=user_id,
            account_id=account_id,
            external_id=normalized.order_external_id,
            sale_model=normalized.sale_model,
            fulfillment_type=normalized.fulfillment_type,
            first_notified_at=None,
        )
        self.created_order = order
        return order

    async def get_with_items(self, order_id: int) -> Order | None:
        if self.created_order and self.created_order.id == order_id:
            return self.created_order
        if self.existing and self.existing.id == order_id:
            return self.existing
        return None

    async def order_totals(self, _: int) -> tuple[Decimal, Decimal]:
        return Decimal("0"), Decimal("0")

    async def mark_notified(self, _: int) -> None:
        self.mark_notified_called = True

    async def pending_unnotified_for_account(self, **_: Any) -> list[Order]:
        if self.existing and self.existing.first_notified_at is None:
            return [self.existing]
        return []


class FakeProfitService:
    async def calculate_estimated_profit(self, *_: Any) -> None:
        return None


class FakeCardService:
    async def new_order_card(self, **_: Any) -> VisualNotification:
        return VisualNotification(
            text="🛒 <b>Новый FBS-заказ</b>",
            product_url="https://example.test/product",
        )


class FailingCardService:
    async def new_order_card(self, **_: Any) -> VisualNotification:
        raise RuntimeError("broken card")


class FakeNotificationPolicyService:
    async def resolve(self, _: MarketplaceAccount) -> OrderNotificationPolicy:
        return OrderNotificationPolicy(fbs_enabled=True)


@pytest.mark.asyncio
async def test_new_wb_fbs_order_prepares_notification_without_marking_notified() -> None:
    service, fake_orders = _service(existing=None)
    account = _account(Marketplace.WB)

    async def fetch_orders(_: MarketplaceAccount) -> list[NormalizedOrder]:
        return [_normalized_order(Marketplace.WB, "wb-fbs-1")]

    service._fetch_orders = fetch_orders  # type: ignore[method-assign]

    result = await service.poll_account_with_stats(account)

    assert result.created == 1
    assert result.notification_count == 1
    notification = result.notifications[0] if result.notifications else None
    assert notification is not None
    assert notification.marketplace == Marketplace.WB
    assert notification.sale_model == SaleModel.FBS.value
    assert notification.fulfillment_type == "FBS"
    assert notification.user_id == account.user_id
    assert fake_orders.mark_notified_called is False


@pytest.mark.asyncio
async def test_existing_unnotified_ozon_fbs_order_is_retried() -> None:
    existing = _order(
        order_id=202,
        user_id=7,
        account_id=55,
        external_id="ozon-fbs-1",
        sale_model=SaleModel.FBS,
        fulfillment_type="FBS",
        first_notified_at=None,
    )
    service, _ = _service(existing=existing)
    account = _account(Marketplace.OZON)

    async def fetch_orders(_: MarketplaceAccount) -> list[NormalizedOrder]:
        return [_normalized_order(Marketplace.OZON, "ozon-fbs-1")]

    service._fetch_orders = fetch_orders  # type: ignore[method-assign]

    result = await service.poll_account_with_stats(account)

    assert result.created == 0
    assert result.duplicated == 1
    assert result.retried_unnotified == 1
    assert result.notification_count == 1
    notification = result.notifications[0] if result.notifications else None
    assert notification is not None
    assert notification.marketplace == Marketplace.OZON
    assert notification.sale_model == SaleModel.FBS.value


@pytest.mark.asyncio
async def test_new_ozon_fbs_order_prepares_notification_without_marking_notified() -> None:
    service, fake_orders = _service(existing=None)
    account = _account(Marketplace.OZON)

    async def fetch_orders(_: MarketplaceAccount) -> list[NormalizedOrder]:
        return [_normalized_order(Marketplace.OZON, "ozon-fbs-new")]

    service._fetch_orders = fetch_orders  # type: ignore[method-assign]

    result = await service.poll_account_with_stats(account)

    assert result.created == 1
    assert result.notification_count == 1
    notification = result.notifications[0] if result.notifications else None
    assert notification is not None
    assert notification.marketplace == Marketplace.OZON
    assert notification.sale_model == SaleModel.FBS.value
    assert notification.fulfillment_type == "FBS"
    assert fake_orders.mark_notified_called is False


@pytest.mark.asyncio
async def test_existing_notified_fbs_order_does_not_duplicate_notification() -> None:
    existing = _order(
        order_id=303,
        user_id=7,
        account_id=55,
        external_id="wb-fbs-2",
        sale_model=SaleModel.FBS,
        fulfillment_type="FBS",
        first_notified_at=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
    )
    service, _ = _service(existing=existing)
    account = _account(Marketplace.WB)

    async def fetch_orders(_: MarketplaceAccount) -> list[NormalizedOrder]:
        return [_normalized_order(Marketplace.WB, "wb-fbs-2")]

    service._fetch_orders = fetch_orders  # type: ignore[method-assign]

    result = await service.poll_account_with_stats(account)

    assert result.created == 0
    assert result.duplicated == 1
    assert result.retried_unnotified == 0
    assert result.notification_count == 0


@pytest.mark.asyncio
async def test_ozon_unfulfilled_fbs_posting_is_polled_and_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _service(existing=None)
    service.cipher = _FakeCipher()  # type: ignore[assignment]
    account = _account(Marketplace.OZON)

    class FakeOzonClient:
        def __init__(self, client_id: str, api_key: str) -> None:
            self.client_id = client_id
            self.api_key = api_key

        async def get_fbs_postings(self, *_: Any) -> dict[str, Any]:
            return {"result": {"postings": [{"posting_number": "ozon-fbs-1"}]}}

        async def get_fbs_unfulfilled(self, *_: Any) -> dict[str, Any]:
            return {
                "result": {
                    "postings": [
                        {"posting_number": "ozon-fbs-1"},
                        {"posting_number": "ozon-fbs-2"},
                    ]
                }
            }

        async def get_fbo_postings(self, *_: Any) -> dict[str, Any]:
            return {"result": []}

        def normalize_fbs_posting(self, payload: dict[str, Any]) -> NormalizedOrder:
            return _normalized_order(Marketplace.OZON, str(payload["posting_number"]))

        def normalize_fbo_posting(self, payload: dict[str, Any]) -> NormalizedOrder:
            return _normalized_order(Marketplace.OZON, str(payload["posting_number"]))

    monkeypatch.setattr("app.services.order_processing_service.OzonClient", FakeOzonClient)

    normalized = await service._fetch_orders(account)

    assert [order.order_external_id for order in normalized] == ["ozon-fbs-1", "ozon-fbs-2"]
    assert all(order.sale_model == SaleModel.FBS for order in normalized)
    assert all(order.requires_seller_action for order in normalized)


@pytest.mark.asyncio
async def test_wb_period_fbs_orders_are_polled_for_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _service(existing=None)
    service.cipher = _FakeCipher()  # type: ignore[assignment]
    account = _account(Marketplace.WB)
    account.last_order_poll_at = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)

    class FakeWbClient(WildberriesClient):
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        async def get_new_fbs_orders(self) -> list[dict[str, Any]]:
            return [_wb_payload(1)]

        async def get_fbs_orders(self, **_: Any) -> list[dict[str, Any]]:
            return [_wb_payload(1), _wb_payload(2, status="confirm")]

    monkeypatch.setattr("app.services.order_processing_service.WildberriesClient", FakeWbClient)

    normalized = await service._fetch_orders(account)

    assert [order.order_external_id for order in normalized] == ["1", "2"]
    assert normalized[0].normalized_status == "new"
    assert normalized[0].requires_seller_action is True
    assert normalized[1].normalized_status == "confirm"


@pytest.mark.asyncio
async def test_card_build_error_does_not_mark_fbs_order_notified() -> None:
    service, fake_orders = _service(existing=None)
    service.cards = FailingCardService()  # type: ignore[assignment]
    account = _account(Marketplace.WB)

    async def fetch_orders(_: MarketplaceAccount) -> list[NormalizedOrder]:
        return [_normalized_order(Marketplace.WB, "wb-fbs-card-error")]

    service._fetch_orders = fetch_orders  # type: ignore[method-assign]

    result = await service.poll_account_with_stats(account)

    assert result.created == 1
    assert result.notification_count == 0
    assert fake_orders.created_order is not None
    assert fake_orders.created_order.first_notified_at is None
    assert fake_orders.mark_notified_called is False


@pytest.mark.asyncio
async def test_saved_unnotified_order_is_recovered_without_marketplace_duplicate() -> None:
    existing = _order(
        order_id=404,
        user_id=7,
        account_id=55,
        external_id="wb-fbs-recover",
        sale_model=SaleModel.FBS,
        fulfillment_type="FBS",
        first_notified_at=None,
    )
    service, _ = _service(existing=existing)
    account = _account(Marketplace.WB)

    async def fetch_orders(_: MarketplaceAccount) -> list[NormalizedOrder]:
        return []

    service._fetch_orders = fetch_orders  # type: ignore[method-assign]

    result = await service.poll_account_with_stats(account)

    assert result.fetched == 0
    assert result.recovered_unnotified == 1
    assert result.notification_count == 1
    notification = result.notifications[0] if result.notifications else None
    assert notification is not None
    assert notification.order_id == 404


@pytest.mark.asyncio
async def test_saved_unnotified_order_can_be_collected_without_marketplace_poll() -> None:
    existing = _order(
        order_id=405,
        user_id=7,
        account_id=55,
        external_id="wb-stat-fbs-recover",
        sale_model=SaleModel.FBS,
        fulfillment_type="FBS",
        first_notified_at=None,
    )
    service, _ = _service(existing=existing)

    async def fetch_orders(_: MarketplaceAccount) -> list[NormalizedOrder]:
        raise AssertionError("marketplace polling is not expected")

    service._fetch_orders = fetch_orders  # type: ignore[method-assign]

    notifications = await service.collect_saved_unnotified_notifications(_account(Marketplace.WB))

    assert len(notifications) == 1
    assert notifications[0].order_id == 405
    assert notifications[0].sale_model == SaleModel.FBS.value


def test_initial_ozon_poll_uses_wide_window_for_first_sync() -> None:
    now = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
    account = _account(Marketplace.OZON)
    account.last_order_poll_at = None

    assert OrderProcessingService._poll_window_start(account, now) == now - timedelta(hours=24)


def _service(existing: Order | None) -> tuple[OrderProcessingService, FakeOrders]:
    session = FakeSession()
    service = OrderProcessingService(session)  # type: ignore[arg-type]
    fake_orders = FakeOrders(existing=existing)
    service.orders = fake_orders  # type: ignore[assignment]
    service.profits = FakeProfitService()  # type: ignore[assignment]
    service.cards = FakeCardService()  # type: ignore[assignment]
    service.notification_policy = FakeNotificationPolicyService()  # type: ignore[assignment]
    return service, fake_orders


class _FakeCipher:
    def decrypt(self, value: str) -> str:
        return f"plain-{value}"


def _account(marketplace: Marketplace) -> MarketplaceAccount:
    user = User(
        id=7,
        telegram_id=700700,
        username="seller",
        first_name="Иван",
        timezone="Europe/Moscow",
        notifications_enabled=True,
    )
    account = MarketplaceAccount(
        id=55,
        user_id=7,
        marketplace=marketplace,
        name="Основной кабинет",
        encrypted_api_key="encrypted",
        encrypted_client_id="encrypted-client",
        is_active=True,
    )
    account.user = user
    return account


def _order(
    *,
    order_id: int,
    user_id: int,
    account_id: int,
    external_id: str,
    sale_model: SaleModel | None,
    fulfillment_type: str | None,
    first_notified_at: datetime | None,
) -> Order:
    order = Order(
        id=order_id,
        user_id=user_id,
        marketplace_account_id=account_id,
        marketplace=Marketplace.OZON if external_id.startswith("ozon") else Marketplace.WB,
        order_external_id=external_id,
        order_date=datetime(2026, 5, 17, 9, 0, tzinfo=UTC),
        event_received_at=datetime(2026, 5, 17, 9, 1, tzinfo=UTC),
        sale_model=sale_model,
        fulfillment_type=fulfillment_type,
        status="awaiting_packaging",
        requires_seller_action=True,
        first_notified_at=first_notified_at,
    )
    item = OrderItem(
        id=order_id + 1000,
        order_id=order_id,
        seller_article="SKU-1",
        marketplace_article="123456",
        title="Тестовый товар",
        quantity=1,
        buyer_price=Decimal("1000"),
        seller_price=Decimal("1000"),
        discounted_price=Decimal("1000"),
    )
    order.items = [item]
    return order


def _normalized_order(marketplace: Marketplace, external_id: str) -> NormalizedOrder:
    return NormalizedOrder(
        marketplace=marketplace,
        order_external_id=external_id,
        posting_number=external_id,
        order_date=datetime(2026, 5, 17, 9, 0, tzinfo=UTC),
        sale_model=SaleModel.FBS,
        fulfillment_type="FBS",
        status="awaiting_packaging",
        requires_seller_action=True,
        items=[
            NormalizedOrderItem(
                seller_article="SKU-1",
                marketplace_article="123456",
                title="Тестовый товар",
                quantity=1,
                buyer_price=Decimal("1000"),
                seller_price=Decimal("1000"),
                discounted_price=Decimal("1000"),
            )
        ],
    )


def _wb_payload(order_id: int, status: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": order_id,
        "createdAt": "2026-05-18T09:00:00Z",
        "nmId": 123456,
        "article": "WB-SKU",
        "subject": "Тестовый товар WB",
        "convertedFinalPrice": 100000,
        "rid": f"rid-{order_id}",
    }
    if status:
        payload["status"] = status
    return payload
