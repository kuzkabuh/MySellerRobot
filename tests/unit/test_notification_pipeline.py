"""Regression tests for retry-safe Telegram notification delivery."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.domain import AlertEvent, MarketplaceAccount, Order, OrderItem, SalesEvent, User
from app.models.enums import AlertType, Marketplace, SaleEventType, SaleModel
from app.services.order_card_service import OrderCardService, VisualNotification
from app.services.sales_event_sync_service import SaleNotification, SalesEventSyncService
from app.workers import tasks
from app.workers.settings import WorkerSettings


class FakeSession:
    def __init__(self, rows=None) -> None:  # type: ignore[no-untyped-def]
        self.rows = rows or []
        self.commits = 0
        self.rollbacks = 0
        self.executed = []

    async def execute(self, query):  # type: ignore[no-untyped-def]
        self.executed.append(query)
        return FakeResult(self.rows)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeResult:
    def __init__(self, rows) -> None:  # type: ignore[no-untyped-def]
        self._rows = rows

    def all(self):  # type: ignore[no-untyped-def]
        return self._rows


class FakeBuyoutCards:
    async def buyout_card(self, **_kwargs):  # type: ignore[no-untyped-def]
        return VisualNotification(
            text="✅ Выкуп: Крем &lt;новый&gt; &amp; тест",
            product_url="https://www.wildberries.ru/catalog/123/detail.aspx?targetUrl=XS",
        )


class FailingBuyoutCards:
    async def buyout_card(self, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("card failed")


class FakeOrderNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def send_new_order(self, *_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail:
            raise RuntimeError("telegram down")


class FakeSaleNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def send_sale_completed(self, *_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail:
            raise RuntimeError("telegram down")


class FakeAlertBot:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[int, str, str | None]] = []

    async def send_message(self, telegram_id: int, text: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append((telegram_id, text, kwargs.get("parse_mode")))
        if self.fail:
            raise RuntimeError("telegram down")


class FakeOrderRepository:
    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        self.session = session

    async def mark_notified(self, order_id: int) -> None:
        self.session.executed.append(("mark_order_notified", order_id))


class FakeSalesDeliveryService:
    def __init__(self) -> None:
        self.marked: list[int] = []

    async def mark_notified(self, event_id: int) -> None:
        self.marked.append(event_id)


@pytest.mark.asyncio
async def test_sale_pending_notifications_do_not_lazy_load_account_user() -> None:
    event = _sale_event(Marketplace.WB)
    account = _account(Marketplace.WB)
    user = _user(notifications_enabled=True)
    session = FakeSession(rows=[(event, account, user)])
    service = SalesEventSyncService(session)  # type: ignore[arg-type]
    service.cards = FakeBuyoutCards()  # type: ignore[assignment]

    notifications = await service.pending_notifications()

    assert len(notifications) == 1
    assert notifications[0].event_id == event.id
    assert notifications[0].telegram_id == user.telegram_id
    assert notifications[0].event_type == SaleEventType.BUYOUT.value


@pytest.mark.asyncio
async def test_sale_card_error_leaves_event_pending() -> None:
    event = _sale_event(Marketplace.OZON)
    session = FakeSession(rows=[(event, _account(Marketplace.OZON), _user(True))])
    service = SalesEventSyncService(session)  # type: ignore[arg-type]
    service.cards = FailingBuyoutCards()  # type: ignore[assignment]

    notifications = await service.pending_notifications()

    assert notifications == []
    assert event.notification_sent_at is None


@pytest.mark.asyncio
async def test_missing_chat_owner_skips_sale_notification_without_marking_sent() -> None:
    event = _sale_event(Marketplace.WB)
    session = FakeSession(rows=[(event, _account(Marketplace.WB), None)])
    service = SalesEventSyncService(session)  # type: ignore[arg-type]
    service.cards = FakeBuyoutCards()  # type: ignore[assignment]

    notifications = await service.pending_notifications()

    assert notifications == []
    assert event.notification_sent_at is None


@pytest.mark.asyncio
async def test_disabled_user_skips_sale_notification_without_marking_sent() -> None:
    event = _sale_event(Marketplace.WB)
    session = FakeSession(rows=[(event, _account(Marketplace.WB), _user(False))])
    service = SalesEventSyncService(session)  # type: ignore[arg-type]
    service.cards = FakeBuyoutCards()  # type: ignore[assignment]

    notifications = await service.pending_notifications()

    assert notifications == []
    assert event.notification_sent_at is None


@pytest.mark.asyncio
async def test_new_order_send_success_marks_after_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "OrderRepository", FakeOrderRepository)
    session = FakeSession()
    notifier = FakeOrderNotifier()

    sent, failed = await tasks._deliver_new_order_notifications(
        session,
        notifier,  # type: ignore[arg-type]
        [_order_notification()],
    )

    assert (sent, failed) == (1, 0)
    assert notifier.calls == 1
    assert session.executed == [("mark_order_notified", 101)]
    assert session.commits == 1
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_new_order_send_failure_keeps_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "OrderRepository", FakeOrderRepository)
    session = FakeSession()
    notifier = FakeOrderNotifier(fail=True)

    sent, failed = await tasks._deliver_new_order_notifications(
        session,
        notifier,  # type: ignore[arg-type]
        [_order_notification()],
    )

    assert (sent, failed) == (0, 1)
    assert session.executed == []
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_failed_new_order_retry_can_send_later(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "OrderRepository", FakeOrderRepository)
    session = FakeSession()
    notification = _order_notification()

    await tasks._deliver_new_order_notifications(
        session,
        FakeOrderNotifier(fail=True),  # type: ignore[arg-type]
        [notification],
    )
    sent, failed = await tasks._deliver_new_order_notifications(
        session,
        FakeOrderNotifier(),  # type: ignore[arg-type]
        [notification],
    )

    assert (sent, failed) == (1, 0)
    assert session.executed == [("mark_order_notified", 101)]


@pytest.mark.asyncio
async def test_sale_send_success_marks_after_telegram() -> None:
    session = FakeSession()
    service = FakeSalesDeliveryService()
    notifier = FakeSaleNotifier()

    sent, failed = await tasks._deliver_sale_notifications(
        session,
        service,  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
        [_sale_notification(Marketplace.OZON)],
    )

    assert (sent, failed) == (1, 0)
    assert notifier.calls == 1
    assert service.marked == [501]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_sale_send_failure_keeps_event_pending_for_retry() -> None:
    session = FakeSession()
    service = FakeSalesDeliveryService()
    notifier = FakeSaleNotifier(fail=True)

    sent, failed = await tasks._deliver_sale_notifications(
        session,
        service,  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
        [_sale_notification(Marketplace.WB)],
    )

    assert (sent, failed) == (0, 1)
    assert service.marked == []
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_failed_sale_retry_can_send_later() -> None:
    session = FakeSession()
    service = FakeSalesDeliveryService()
    notification = _sale_notification(Marketplace.WB)

    await tasks._deliver_sale_notifications(
        session,
        service,  # type: ignore[arg-type]
        FakeSaleNotifier(fail=True),  # type: ignore[arg-type]
        [notification],
    )
    sent, failed = await tasks._deliver_sale_notifications(
        session,
        service,  # type: ignore[arg-type]
        FakeSaleNotifier(),  # type: ignore[arg-type]
        [notification],
    )

    assert (sent, failed) == (1, 0)
    assert service.marked == [501]


@pytest.mark.asyncio
async def test_alert_send_success_marks_sent_after_telegram() -> None:
    session = FakeSession()
    alert = _alert_event()
    bot = FakeAlertBot()

    sent, failed = await tasks._deliver_alert_notifications(  # type: ignore[arg-type]
        session,
        bot,
        [(alert, 777000)],
    )

    assert (sent, failed) == (1, 0)
    assert bot.calls == [(777000, "⚠️ <b>FBS риск</b>", "HTML")]
    assert alert.sent_at is not None
    assert session.commits == 1
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_alert_send_failure_keeps_event_pending() -> None:
    session = FakeSession()
    alert = _alert_event()

    sent, failed = await tasks._deliver_alert_notifications(  # type: ignore[arg-type]
        session,
        FakeAlertBot(fail=True),  # type: ignore[arg-type]
        [(alert, 777000)],
    )

    assert (sent, failed) == (0, 1)
    assert alert.sent_at is None
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_successful_sale_is_not_in_pending_query_again() -> None:
    session = FakeSession(rows=[])
    service = SalesEventSyncService(session)  # type: ignore[arg-type]
    service.cards = FakeBuyoutCards()  # type: ignore[assignment]

    notifications = await service.pending_notifications()

    assert notifications == []


def test_generic_order_card_escapes_html_title() -> None:
    order = Order(
        id=1,
        user_id=7,
        marketplace_account_id=55,
        marketplace=Marketplace.OZON,
        order_external_id="posting-1",
        order_date=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
        event_received_at=datetime(2026, 5, 18, 10, 1, tzinfo=UTC),
        sale_model=SaleModel.FBS,
        status="awaiting_packaging",
    )
    item = OrderItem(
        order_id=1,
        title="Крем <новый> & тест",
        quantity=1,
        discounted_price=Decimal("1000"),
    )

    text = OrderCardService(FakeSession())._format_generic_order(  # type: ignore[arg-type]
        order,
        item,
        product=None,
        timezone_name="Europe/Moscow",
    )

    assert "Крем &lt;новый&gt; &amp; тест" in text
    assert "Крем <новый> & тест" not in text


def test_worker_settings_register_order_and_sale_notification_jobs() -> None:
    functions = {function.__name__ for function in WorkerSettings.functions}
    cron_functions = {job.coroutine.__name__ for job in WorkerSettings.cron_jobs}

    assert "poll_new_orders" in functions
    assert "sync_sale_events" in functions
    assert "send_alert_notifications" in functions
    assert "sync_products" in functions
    assert "poll_new_orders" in cron_functions
    assert "sync_sale_events" in cron_functions
    assert "send_alert_notifications" in cron_functions


def _user(notifications_enabled: bool) -> User:
    return User(
        id=7,
        telegram_id=777000,
        first_name="Seller",
        timezone="Europe/Moscow",
        notifications_enabled=notifications_enabled,
    )


def _account(marketplace: Marketplace) -> MarketplaceAccount:
    return MarketplaceAccount(
        id=55,
        user_id=7,
        marketplace=marketplace,
        name="Кабинет",
        encrypted_api_key="secret",
        notification_settings={},
    )


def _sale_event(marketplace: Marketplace) -> SalesEvent:
    return SalesEvent(
        id=501,
        user_id=7,
        marketplace_account_id=55,
        marketplace=marketplace,
        external_event_id="sale-501",
        order_external_id="order-501",
        event_type=SaleEventType.BUYOUT
        if marketplace == Marketplace.WB
        else SaleEventType.DELIVERED_TO_CUSTOMER,
        event_date=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
        seller_article="SKU-1",
        marketplace_article="123456",
        quantity=1,
        amount=Decimal("990"),
        raw_payload={},
    )


def _order_notification():
    from app.services.order_processing_service import NewOrderNotification

    return NewOrderNotification(
        telegram_id=777000,
        user_id=7,
        account_id=55,
        order_id=101,
        text="Крем &lt;новый&gt; &amp; тест",
        marketplace=Marketplace.WB,
        sale_model="FBS",
        fulfillment_type="FBS",
    )


def _sale_notification(marketplace: Marketplace) -> SaleNotification:
    return SaleNotification(
        event_id=501,
        user_id=7,
        account_id=55,
        telegram_id=777000,
        text="Крем &lt;новый&gt; &amp; тест",
        marketplace=marketplace,
        event_type=SaleEventType.BUYOUT.value,
        external_event_id="sale-501",
    )


def _alert_event() -> AlertEvent:
    return AlertEvent(
        id=901,
        user_id=7,
        rule_id=None,
        alert_type=AlertType.FBS_DEADLINE_RISK,
        idempotency_key="fbs:901",
        title="FBS риск",
        message="⚠️ <b>FBS риск</b>",
        payload={},
    )
