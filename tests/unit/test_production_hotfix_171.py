"""Regression tests for production hotfix 1.7.1.

Covers:
- SaleModel enum value mapping (RFBS -> rFBS)
- WB FBS period polling with pagination
- Partial polling failure does not advance cursor
- MissingGreenlet safety in error paths
- send_sale_completed photo fallback
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.enums import Marketplace, SaleModel


class TestSaleModelEnumValueMapping:
    """Verify SaleModel enum values match PostgreSQL enum values."""

    def test_rfbs_value_is_rFBS(self) -> None:
        assert SaleModel.RFBS.value == "rFBS"

    def test_fbs_value_is_FBS(self) -> None:
        assert SaleModel.FBS.value == "FBS"

    def test_fbo_value_is_FBO(self) -> None:
        assert SaleModel.FBO.value == "FBO"

    def test_dbs_value_is_DBS(self) -> None:
        assert SaleModel.DBS.value == "DBS"

    def test_dbw_value_is_DBW(self) -> None:
        assert SaleModel.DBW.value == "DBW"

    def test_all_sale_model_values(self) -> None:
        expected = {"FBS", "FBO", "rFBS", "DBS", "DBW"}
        actual = {m.value for m in SaleModel}
        assert actual == expected

    def test_str_enum_comparison(self) -> None:
        assert SaleModel.RFBS == "rFBS"
        assert SaleModel.FBS == "FBS"

    def test_in_operator_with_values(self) -> None:
        db_values = {"FBS", "rFBS", "DBS", "DBW", "FBO"}
        assert SaleModel.RFBS.value in db_values
        assert SaleModel.FBS.value in db_values


class TestWbFbsOrdersPagination:
    """Verify WB get_fbs_orders builds correct query params and handles pagination."""

    @pytest.mark.asyncio
    async def test_date_format_uses_unix_timestamp(self) -> None:
        from app.integrations.wb import _wb_unix_timestamp_utc

        date_from = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)
        date_to = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)

        assert _wb_unix_timestamp_utc(date_from) == 1779098400
        assert _wb_unix_timestamp_utc(date_to) == 1779105600

    @pytest.mark.asyncio
    async def test_single_page_fetch(self) -> None:
        from app.integrations.wb import WildberriesClient

        client = WildberriesClient("test-key")
        mock_request = AsyncMock(
            return_value={
                "orders": [{"id": 1}, {"id": 2}],
            }
        )
        client.marketplace.request = mock_request

        date_from = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)
        date_to = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
        result = await client.get_fbs_orders(date_from=date_from, date_to=date_to)

        assert len(result) == 2
        mock_request.assert_called_once()
        call_params = mock_request.call_args[1]["params"]
        assert call_params["dateFrom"] == 1779098400
        assert call_params["dateTo"] == 1779105600
        assert call_params["limit"] == 1000
        assert call_params["next"] == 0

    @pytest.mark.asyncio
    async def test_pagination_with_next_cursor(self) -> None:
        from app.integrations.wb import WildberriesClient

        client = WildberriesClient("test-key")
        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"orders": [{"id": i} for i in range(1000)], "next": "cursor123"}
            elif call_count == 2:
                return {"orders": [{"id": i} for i in range(1000, 1500)]}
            return {"orders": []}

        client.marketplace.request = mock_request

        date_from = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)
        date_to = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
        result = await client.get_fbs_orders(date_from=date_from, date_to=date_to)

        assert len(result) == 1500
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_pagination_passes_next_cursor(self) -> None:
        from app.integrations.wb import WildberriesClient

        client = WildberriesClient("test-key")
        captured_params = []

        async def mock_request(*args, **kwargs):
            captured_params.append(kwargs.get("params", {}))
            if len(captured_params) == 1:
                return {"orders": [{"id": 1}], "next": "abc"}
            return {"orders": [{"id": 2}]}

        client.marketplace.request = mock_request

        date_from = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)
        date_to = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
        await client.get_fbs_orders(date_from=date_from, date_to=date_to)

        assert len(captured_params) == 2
        assert captured_params[0]["next"] == 0
        assert captured_params[1]["next"] == "abc"


class TestPartialPollingFailure:
    """Verify that recovery polling failure does not advance last_order_poll_at."""

    @pytest.mark.asyncio
    async def test_recovery_failure_sets_flag(self) -> None:
        from app.services.common.order_processing_service import OrderProcessingService

        session = AsyncMock()
        service = OrderProcessingService(session)

        async def fetch_orders(account):
            return [], True

        service._fetch_orders = fetch_orders
        service.notification_policy = AsyncMock()
        service.notification_policy.resolve = AsyncMock(
            return_value=MagicMock(
                fbs_enabled=True,
                is_instant_enabled_for=lambda sm: True,
                should_queue_fbo_digest=lambda sm: False,
            )
        )
        service.orders = AsyncMock()
        service.orders.pending_unnotified_for_account = AsyncMock(return_value=[])
        service.profits = AsyncMock()
        service.profits.calculate_estimated_profit = AsyncMock()
        service.cards = AsyncMock()

        account = MagicMock()
        account.id = 1
        account.marketplace = Marketplace.WB
        account.user_id = 10
        account.user = MagicMock()
        account.user.notifications_enabled = True
        account.user.telegram_id = 100
        account.user.timezone = "Europe/Moscow"
        account.last_order_poll_at = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)

        result = await service.poll_account_with_stats(account)

        assert result.fetched == 0
        session.commit.assert_called_once()
        assert account.last_order_poll_at == datetime(2026, 5, 18, 10, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_success_advances_cursor(self) -> None:
        from app.services.common.order_processing_service import OrderProcessingService

        session = AsyncMock()
        service = OrderProcessingService(session)

        async def fetch_orders(account):
            return [], False

        service._fetch_orders = fetch_orders
        service.notification_policy = AsyncMock()
        service.notification_policy.resolve = AsyncMock(
            return_value=MagicMock(
                fbs_enabled=True,
                is_instant_enabled_for=lambda sm: True,
                should_queue_fbo_digest=lambda sm: False,
            )
        )
        service.orders = AsyncMock()
        service.orders.pending_unnotified_for_account = AsyncMock(return_value=[])
        service.profits = AsyncMock()
        service.profits.calculate_estimated_profit = AsyncMock()
        service.cards = AsyncMock()

        account = MagicMock()
        account.id = 1
        account.marketplace = Marketplace.WB
        account.user_id = 10
        account.user = MagicMock()
        account.user.notifications_enabled = True
        account.user.telegram_id = 100
        account.user.timezone = "Europe/Moscow"
        old_poll_at = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)
        account.last_order_poll_at = old_poll_at

        result = await service.poll_account_with_stats(account)

        assert result.fetched == 0
        assert account.last_order_poll_at > old_poll_at


class TestMissingGreenletSafety:
    """Verify that error paths use saved primitive values, not expired ORM objects."""

    @pytest.mark.asyncio
    async def test_poll_failure_uses_saved_primitives(self) -> None:
        from app.core.exceptions import IntegrationError
        from app.services.common.order_processing_service import OrderProcessingService

        session = AsyncMock()
        session.rollback = AsyncMock()
        service = OrderProcessingService(session)

        async def fetch_orders(account):
            raise RuntimeError("marketplace down")

        service._fetch_orders = fetch_orders

        account = MagicMock()
        account.id = 42
        account.marketplace = Marketplace.WB
        account.user_id = 7

        with pytest.raises(IntegrationError) as exc_info:
            await service.poll_account_with_stats(account)

        assert "WB" in str(exc_info.value)
        assert exc_info.value.details["account_id"] == 42
        session.rollback.assert_called_once()


class TestSaleNotificationPhotoFallback:
    """Verify send_sale_completed falls back to text when photo fails."""

    @pytest.mark.asyncio
    async def test_photo_success_no_fallback(self) -> None:
        from app.services.alerts.notification_service import NotificationService

        bot = AsyncMock()
        notifier = NotificationService(bot)

        await notifier.send_sale_completed(
            100,
            "Sale completed",
            image_url="https://example.com/img.jpg",
            marketplace=Marketplace.WB,
            parse_mode="HTML",
        )

        bot.send_photo.assert_called_once()
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_photo_failure_falls_back_to_text(self) -> None:
        from app.services.alerts.notification_service import NotificationService

        bot = AsyncMock()
        bot.send_photo = AsyncMock(side_effect=Exception("wrong type of the web page content"))
        notifier = NotificationService(bot)

        await notifier.send_sale_completed(
            100,
            "Sale completed",
            image_url="https://example.com/bad",
            marketplace=Marketplace.WB,
            parse_mode="HTML",
        )

        bot.send_photo.assert_called_once()
        bot.send_message.assert_called_once()
        call_kwargs = bot.send_message.call_args[1]
        assert call_kwargs["text"] == "Sale completed"
        assert call_kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_no_image_uses_text_directly(self) -> None:
        from app.services.alerts.notification_service import NotificationService

        bot = AsyncMock()
        notifier = NotificationService(bot)

        await notifier.send_sale_completed(
            100,
            "Sale completed",
            marketplace=Marketplace.OZON,
            parse_mode="HTML",
        )

        bot.send_photo.assert_not_called()
        bot.send_message.assert_called_once()


class TestRecoveryTaskExists:
    """Verify the resend_unnotified_orders task is properly defined."""

    def test_task_function_exists(self) -> None:
        from app.workers.tasks import resend_unnotified_orders

        assert callable(resend_unnotified_orders)

    def test_task_in_worker_functions(self) -> None:
        from app.workers.settings import WorkerSettings
        from app.workers.tasks import resend_unnotified_orders

        assert resend_unnotified_orders in WorkerSettings.functions

    def test_task_in_cron_jobs(self) -> None:
        from app.workers.settings import WorkerSettings

        task_names = [job.coroutine.__name__ for job in WorkerSettings.cron_jobs]
        assert "resend_unnotified_orders" in task_names


class TestOrderModelIndex:
    """Verify the Order model has the unnotified index."""

    def test_index_exists_on_model(self) -> None:
        from app.models.domain import Order

        index_names = [idx.name for idx in Order.__table__.indexes]
        assert "ix_orders_account_unnotified" in index_names

    def test_index_columns(self) -> None:
        from app.models.domain import Order

        for idx in Order.__table__.indexes:
            if idx.name == "ix_orders_account_unnotified":
                cols = [c.name for c in idx.columns]
                assert "marketplace_account_id" in cols
                assert "first_notified_at" in cols
                assert "sale_model" in cols
                break
        else:
            pytest.fail("Index ix_orders_account_unnotified not found")


class TestSaleModelEnumColumnMapping:
    """Verify the SQLAlchemy Enum column uses values_callable for correct DB mapping."""

    def test_sale_model_column_uses_values_callable(self) -> None:
        from app.models.domain import Order

        col = Order.__table__.c.sale_model
        assert col.type is not None
        enum_type = col.type
        assert hasattr(enum_type, "_values_callable") or enum_type.values_callable is not None
