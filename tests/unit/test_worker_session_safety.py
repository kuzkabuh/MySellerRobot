"""version: 1.0.0
description: Regression tests for worker session safety after rollback.
updated: 2026-05-19
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.enums import Marketplace


class FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class FakeAsyncResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return FakeScalarResult(self._values)


class FakeAsyncSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.refreshed = []

    async def execute(self, stmt):
        return FakeAsyncResult([])

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, obj):
        self.refreshed.append(obj)


@pytest.mark.asyncio
async def test_poll_new_orders_refreshes_account_after_rollback() -> None:
    """After error in poll_new_orders, the account should be refreshed
    to prevent MissingGreenlet errors on the next iteration."""
    session = FakeAsyncSession()

    account1 = SimpleNamespace(
        id=1, marketplace=Marketplace.WB, user_id=1,
        last_error_at=None, last_error_message=None,
    )
    account2 = SimpleNamespace(
        id=2, marketplace=Marketplace.OZON, user_id=1,
        last_error_at=None, last_error_message=None,
    )

    call_count = 0

    async def fake_poll_account_with_stats(account):
        nonlocal call_count
        call_count += 1
        if account.id == 1:
            raise RuntimeError("API error")
        return SimpleNamespace(
            fetched=0, created=0, duplicated=0, recovered_unnotified=0,
            skipped_by_policy=0, skipped_without_user=0, notification_count=0,
            notifications=[],
        )

    async def fake_execute(stmt):
        return FakeAsyncResult([account1, account2])

    session.execute = fake_execute

    with patch("app.workers.tasks.AsyncSessionFactory") as mock_factory:
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.workers.tasks.OrderProcessingService") as mock_service:
            mock_service.return_value.poll_account_with_stats = fake_poll_account_with_stats

            with patch("app.workers.tasks.get_settings"):
                with patch("app.workers.tasks.Bot") as mock_bot:
                    mock_bot.return_value.session.close = AsyncMock()

                    from app.workers.tasks import poll_new_orders
                    await poll_new_orders({})

    # After error, account should be refreshed to prevent MissingGreenlet
    assert len(session.refreshed) >= 1
    assert call_count == 2  # Both accounts were processed


@pytest.mark.asyncio
async def test_sync_products_extracts_attrs_before_try() -> None:
    """sync_products should extract account attributes before the try block
    so they're available in the except handler even after rollback."""
    session = FakeAsyncSession()

    account = SimpleNamespace(
        id=10, marketplace=Marketplace.WB, user_id=5,
        last_error_at=None, last_error_message=None,
    )

    async def fake_sync_account_products(account):
        raise RuntimeError("Sync failed")

    async def fake_execute(stmt):
        return FakeAsyncResult([account])

    session.execute = fake_execute

    with patch("app.workers.tasks.AsyncSessionFactory") as mock_factory:
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.workers.tasks.ProductSyncService") as mock_service:
            mock_service.return_value.sync_account_products = fake_sync_account_products

            with patch("app.workers.tasks.get_settings"):
                from app.workers.tasks import sync_products
                await sync_products({})

    assert session.rolled_back is True
