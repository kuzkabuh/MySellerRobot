"""version: 1.0.0
description: Tests for production polling fixes.

Covers Ozon financial_data=None, WB recovery, and partial failure.
updated: 2026-05-20
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import MarketplaceApiError
from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import ApiRequestLog
from app.models.enums import Marketplace


class TestOzonFinancialDataNone:
    """Test that Ozon normalizers handle financial_data=None gracefully."""

    def test_normalize_fbs_posting_with_financial_data_none(self) -> None:
        client = OzonClient(client_id="test", api_key="test")
        posting = {
            "posting_number": "test-123",
            "in_process_at": "2026-05-20T10:00:00Z",
            "status": "awaiting_packaging",
            "financial_data": None,
            "products": [
                {
                    "sku": "111",
                    "offer_id": "ART-1",
                    "product_id": "222",
                    "name": "Test Product",
                    "price": 1000,
                    "quantity": 1,
                }
            ],
            "delivery_method": {"warehouse": "Test Warehouse"},
        }

        order = client.normalize_fbs_posting(posting)

        assert order.order_external_id == "test-123"
        assert len(order.items) == 1
        item = order.items[0]
        assert item.buyer_price == Decimal("1000")
        assert item.quantity == 1

    def test_normalize_fbs_posting_without_financial_data_key(self) -> None:
        client = OzonClient(client_id="test", api_key="test")
        posting = {
            "posting_number": "test-456",
            "in_process_at": "2026-05-20T10:00:00Z",
            "status": "awaiting_packaging",
            "products": [
                {
                    "sku": "333",
                    "offer_id": "ART-2",
                    "product_id": "444",
                    "name": "Test Product 2",
                    "price": 2000,
                    "quantity": 2,
                }
            ],
            "delivery_method": {"warehouse": "Test Warehouse"},
        }

        order = client.normalize_fbs_posting(posting)

        assert order.order_external_id == "test-456"
        assert len(order.items) == 1
        item = order.items[0]
        assert item.buyer_price == Decimal("2000")
        assert item.quantity == 2

    def test_normalize_fbo_posting_with_analytics_data_none(self) -> None:
        client = OzonClient(client_id="test", api_key="test")
        posting = {
            "posting_number": "fbo-789",
            "in_process_at": "2026-05-20T10:00:00Z",
            "status": "delivered",
            "analytics_data": None,
            "products": [
                {
                    "sku": "555",
                    "offer_id": "ART-3",
                    "name": "FBO Product",
                    "price": 500,
                    "quantity": 1,
                }
            ],
        }

        order = client.normalize_fbo_posting(posting)

        assert order.order_external_id == "fbo-789"
        assert order.warehouse is None
        assert len(order.items) == 1

    def test_normalize_fbs_posting_with_delivery_method_none(self) -> None:
        client = OzonClient(client_id="test", api_key="test")
        posting = {
            "posting_number": "test-nodelivery",
            "in_process_at": "2026-05-20T10:00:00Z",
            "status": "awaiting_packaging",
            "delivery_method": None,
            "products": [
                {
                    "sku": "666",
                    "offer_id": "ART-4",
                    "name": "No Delivery Product",
                    "price": 300,
                    "quantity": 1,
                }
            ],
        }

        order = client.normalize_fbs_posting(posting)

        assert order.order_external_id == "test-nodelivery"
        assert order.warehouse is None

    def test_normalize_fbs_posting_with_full_financial_data(self) -> None:
        client = OzonClient(client_id="test", api_key="test")
        posting = {
            "posting_number": "test-full",
            "in_process_at": "2026-05-20T10:00:00Z",
            "status": "awaiting_packaging",
            "financial_data": {
                "products": [
                    {
                        "sku": "111",
                        "product_id": "222",
                        "offer_id": "ART-1",
                        "price": 1000,
                        "commission_amount": 100,
                        "payout": 850,
                        "services": [
                            {"name": "Delivery", "price": 50},
                        ],
                    }
                ]
            },
            "products": [
                {
                    "sku": "111",
                    "offer_id": "ART-1",
                    "product_id": "222",
                    "name": "Full Product",
                    "price": 1000,
                    "quantity": 1,
                }
            ],
            "delivery_method": {"warehouse": "Main Warehouse"},
        }

        order = client.normalize_fbs_posting(posting)

        assert len(order.items) == 1
        item = order.items[0]
        assert item.buyer_price == Decimal("1000")
        assert item.commission_estimated == Decimal("100")
        assert item.payout_amount_estimated == Decimal("850")


class TestWBFbsOrdersDateFormat:
    """Test that WB get_fbs_orders uses correct date format."""

    @pytest.mark.asyncio
    async def test_get_fbs_orders_uses_correct_date_format(self) -> None:
        captured_params = {}

        class MockMarketplace:
            async def request(self, method, path, headers=None, params=None):
                captured_params["params"] = params
                return {"orders": [], "next": None}

        wb = WildberriesClient("token")
        wb.marketplace = MockMarketplace()

        orders = await wb.get_fbs_orders(
            date_from=datetime(2026, 5, 13, 0, 0, 0, tzinfo=UTC),
            date_to=datetime(2026, 5, 14, 0, 0, 0, tzinfo=UTC),
        )

        assert orders == []
        params = captured_params["params"]
        assert params["dateFrom"] == 1778630400
        assert params["dateTo"] == 1778716800
        assert params["limit"] == 1000
        assert params["next"] == 0

    @pytest.mark.asyncio
    async def test_get_fbs_orders_pagination_with_cursor(self) -> None:
        call_count = 0
        captured_params_list = []

        class MockMarketplace:
            async def request(self, method, path, headers=None, params=None):
                nonlocal call_count
                call_count += 1
                captured_params_list.append(dict(params) if params else {})
                if call_count == 1:
                    return {
                        "orders": [{"id": 1}],
                        "next": "cursor-abc",
                    }
                return {
                    "orders": [{"id": 2}],
                    "next": None,
                }

        wb = WildberriesClient("token")
        wb.marketplace = MockMarketplace()

        orders = await wb.get_fbs_orders(
            date_from=datetime(2026, 5, 13, tzinfo=UTC),
            date_to=datetime(2026, 5, 14, tzinfo=UTC),
        )

        assert len(orders) == 2
        assert call_count == 2
        assert captured_params_list[0].get("next") == 0
        assert captured_params_list[1].get("next") == "cursor-abc"

    @pytest.mark.asyncio
    async def test_get_fbs_orders_clamps_limit_and_omits_empty_params(self) -> None:
        captured_params = {}

        class MockMarketplace:
            async def request(self, method, path, headers=None, params=None):
                captured_params["params"] = params
                return {"orders": []}

        wb = WildberriesClient("token")
        wb.marketplace = MockMarketplace()

        await wb.get_fbs_orders(
            date_from=datetime(2026, 5, 13, tzinfo=UTC),
            date_to=datetime(2026, 5, 14, tzinfo=UTC),
            limit=5000,
        )

        params = captured_params["params"]
        assert params == {
            "dateFrom": 1778630400,
            "dateTo": 1778716800,
            "limit": 1000,
            "next": 0,
        }
        assert all(value is not None and value != "" for value in params.values())


class TestPartialFailureSemantics:
    """Test that last_order_poll_at is not advanced when recovery fails."""

    @pytest.mark.asyncio
    async def test_wb_live_poll_updates_timestamp_on_recovery_failure(self) -> None:
        from app.services.order_processing_service import (
            OrderProcessingService,
        )

        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.add = MagicMock()

        account = MagicMock()
        account.id = 1
        account.marketplace = Marketplace.WB
        account.user_id = 100
        account.user = MagicMock()
        account.user.notifications_enabled = True
        account.encrypted_api_key = "encrypted-key"
        account.encrypted_client_id = None
        account.last_order_poll_at = None
        account.last_orders_sync_at = None
        account.last_success_sync_at = None

        mock_repo = MagicMock()
        mock_repo.get_by_external = AsyncMock(return_value=None)
        mock_repo.mark_notified = AsyncMock()
        mock_repo.pending_unnotified_for_account = AsyncMock(return_value=[])

        mock_fbo_queue = MagicMock()
        mock_fbo_queue.add_once = AsyncMock()

        mock_notification_policy_service = MagicMock()
        mock_policy = MagicMock()
        mock_policy.is_instant_enabled_for.return_value = False
        mock_policy.should_queue_fbo_digest.return_value = False
        mock_notification_policy_service.resolve = AsyncMock(return_value=mock_policy)

        mock_profit_service = MagicMock()
        mock_profit_service.calculate_estimated_profit = AsyncMock()

        mock_card_service = MagicMock()

        def mock_init(self, session):
            self.session = session
            from app.core.security import TokenCipher

            self.cipher = TokenCipher()
            self.orders = mock_repo
            self.fbo_queue = mock_fbo_queue
            self.notification_policy = mock_notification_policy_service
            self.profits = mock_profit_service
            self.cards = mock_card_service

        with patch.object(
            OrderProcessingService,
            "__init__",
            mock_init,
        ):
            with patch(
                "app.core.security.TokenCipher.decrypt",
                return_value="test-api-key",
            ):
                with patch(
                    "app.services.order_processing_service.WildberriesClient"
                ) as mock_wb_class:
                    mock_wb = MagicMock()
                    mock_wb.get_new_fbs_orders = AsyncMock(return_value=[])
                    mock_wb.get_fbs_orders = AsyncMock(
                        side_effect=MarketplaceApiError(
                            '{"code":"IncorrectParameter","message":"Incorrect parameter"}',
                            status_code=400,
                            marketplace="Wildberries",
                            details={
                                "payload": {
                                    "code": "IncorrectParameter",
                                    "message": "Incorrect parameter",
                                }
                            },
                        )
                    )
                    mock_wb_class.return_value = mock_wb

                    service = OrderProcessingService(mock_session)

                    result = await service.poll_account_with_stats(account)

                    assert account.last_order_poll_at is None
                    assert account.last_orders_sync_at is None
                    assert account.last_success_sync_at is None
                    assert account.last_error_at is not None
                    assert "WB FBS recovery poll failed" in account.last_error_message
                    api_log = mock_session.add.call_args.args[0]
                    assert isinstance(api_log, ApiRequestLog)
                    assert api_log.marketplace_account_id == 1
                    assert api_log.status_code == 400
                    assert "/api/v3/orders" in api_log.url
                    assert "IncorrectParameter" in api_log.error_message
                    assert result.fetched == 0
                    assert result.recovery_failed is True

    @pytest.mark.asyncio
    async def test_ozon_poll_updates_timestamp(self) -> None:
        from app.services.order_processing_service import (
            OrderProcessingService,
        )

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        account = MagicMock()
        account.id = 2
        account.marketplace = Marketplace.OZON
        account.user_id = 100
        account.user = MagicMock()
        account.user.notifications_enabled = True
        account.encrypted_api_key = "encrypted-ozon-key"
        account.encrypted_client_id = "encrypted-client-id"
        account.last_order_poll_at = None
        account.last_orders_sync_at = None
        account.last_success_sync_at = None

        mock_repo = MagicMock()
        mock_repo.get_by_external = AsyncMock(return_value=None)
        mock_repo.mark_notified = AsyncMock()
        mock_repo.pending_unnotified_for_account = AsyncMock(return_value=[])

        mock_fbo_queue = MagicMock()
        mock_fbo_queue.add_once = AsyncMock()

        mock_notification_policy_service = MagicMock()
        mock_policy = MagicMock()
        mock_policy.is_instant_enabled_for.return_value = False
        mock_policy.should_queue_fbo_digest.return_value = False
        mock_notification_policy_service.resolve = AsyncMock(return_value=mock_policy)

        mock_profit_service = MagicMock()
        mock_profit_service.calculate_estimated_profit = AsyncMock()

        mock_card_service = MagicMock()

        def mock_init(self, session):
            self.session = session
            from app.core.security import TokenCipher

            self.cipher = TokenCipher()
            self.orders = mock_repo
            self.fbo_queue = mock_fbo_queue
            self.notification_policy = mock_notification_policy_service
            self.profits = mock_profit_service
            self.cards = mock_card_service

        with patch.object(
            OrderProcessingService,
            "__init__",
            mock_init,
        ):
            with patch(
                "app.core.security.TokenCipher.decrypt",
                side_effect=lambda x: f"decrypted-{x}",
            ):
                with patch("app.services.order_processing_service.OzonClient") as mock_ozon_class:
                    mock_ozon = MagicMock()
                    mock_ozon.get_fbs_postings = AsyncMock(
                        return_value={"result": {"postings": []}}
                    )
                    mock_ozon.get_fbs_unfulfilled = AsyncMock(
                        return_value={"result": {"postings": []}}
                    )
                    mock_ozon.get_fbo_postings = AsyncMock(return_value={"result": []})
                    mock_ozon_class.return_value = mock_ozon

                    service = OrderProcessingService(mock_session)

                    result = await service.poll_account_with_stats(account)

                    assert account.last_order_poll_at is not None
                    assert account.last_orders_sync_at is not None
                    assert account.last_success_sync_at is not None
                    assert result.fetched == 0


class TestMixedAccountPolling:
    """Test that poll_new_orders handles mixed WB+Ozon accounts without cascading failures."""

    @pytest.mark.asyncio
    async def test_poll_new_orders_handles_mixed_accounts(self) -> None:
        from app.workers.tasks import poll_new_orders

        with (
            patch("app.workers.tasks._load_account_refs") as mock_load_refs,
            patch("app.workers.tasks._load_account_by_id") as mock_load_account,
            patch("app.workers.tasks.OrderProcessingService") as mock_service_class,
            patch(
                "app.workers.tasks._deliver_new_order_notifications",
                new_callable=AsyncMock,
                return_value=(0, 0),
            ),
            patch("app.workers.tasks.Bot") as mock_bot_class,
            patch("app.workers.tasks.AsyncSessionFactory"),
        ):
            mock_load_refs.return_value = [
                MagicMock(id=1, marketplace="WB", user_id=100),
                MagicMock(id=2, marketplace="Ozon", user_id=100),
            ]

            mock_account_wb = MagicMock()
            mock_account_wb.id = 1
            mock_account_wb.marketplace = Marketplace.WB
            mock_account_ozon = MagicMock()
            mock_account_ozon.id = 2
            mock_account_ozon.marketplace = Marketplace.OZON

            mock_load_account.side_effect = lambda session, acc_id: (
                mock_account_wb if acc_id == 1 else mock_account_ozon
            )

            poll_result_wb = MagicMock()
            poll_result_wb.notifications = []
            poll_result_wb.fetched = 0
            poll_result_wb.created = 0
            poll_result_wb.duplicated = 0
            poll_result_wb.recovered_unnotified = 0
            poll_result_wb.skipped_by_policy = 0
            poll_result_wb.skipped_without_user = 0
            poll_result_wb.skipped_without_items = 0
            poll_result_wb.notification_count = 0

            poll_result_ozon = MagicMock()
            poll_result_ozon.notifications = []
            poll_result_ozon.fetched = 1
            poll_result_ozon.created = 1
            poll_result_ozon.duplicated = 0
            poll_result_ozon.recovered_unnotified = 0
            poll_result_ozon.skipped_by_policy = 0
            poll_result_ozon.skipped_without_user = 0
            poll_result_ozon.skipped_without_items = 0
            poll_result_ozon.notification_count = 0

            mock_instance = MagicMock()
            mock_instance.poll_account_with_stats = AsyncMock(
                side_effect=[poll_result_wb, poll_result_ozon]
            )
            mock_service_class.return_value = mock_instance

            mock_bot = MagicMock()
            mock_bot.session.close = AsyncMock()
            mock_bot_class.return_value = mock_bot

            await poll_new_orders({})

            assert mock_instance.poll_account_with_stats.call_count == 2
            mock_bot.session.close.assert_called_once()
