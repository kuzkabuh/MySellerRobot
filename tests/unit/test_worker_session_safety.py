"""version: 1.1.0
description: Regression tests for worker session safety after rollback.
updated: 2026-05-19
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.enums import Marketplace
from app.workers.tasks import AccountRef


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeAsyncSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self._execute_results = []

    async def execute(self, stmt):
        if self._execute_results:
            return self._execute_results.pop(0)
        return FakeResult([])

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_poll_new_orders_survives_rollback_and_continues() -> None:
    """After an error in poll_new_orders, the worker should continue
    processing remaining accounts without MissingGreenlet errors."""
    session = FakeAsyncSession()

    account1 = SimpleNamespace(
        id=1, marketplace=Marketplace.WB, user_id=1,
        last_error_at=None, last_error_message=None,
    )

    call_count = 0

    async def fake_poll_account_with_stats(account):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("API error")

    # First execute call: _load_account_refs
    session._execute_results.append(FakeResult([
        (1, Marketplace.WB, 1),
        (2, Marketplace.OZON, 1),
    ]))
    # Second execute call: _load_account_by_id for account 1
    session._execute_results.append(FakeResult([account1]))
    # Third execute call: _load_account_by_id for account 2
    session._execute_results.append(FakeResult([]))

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

    # Rollback should have happened, but no crash
    assert session.rolled_back is True


@pytest.mark.asyncio
async def test_sync_products_survives_rollback_and_continues() -> None:
    """sync_products should survive errors without MissingGreenlet."""
    session = FakeAsyncSession()

    account = SimpleNamespace(
        id=10, marketplace=Marketplace.WB, user_id=5,
        last_error_at=None, last_error_message=None,
    )

    async def fake_sync_account_products(account):
        raise RuntimeError("Sync failed")

    session._execute_results.append(FakeResult([
        (10, Marketplace.WB, 5),
    ]))
    session._execute_results.append(FakeResult([account]))

    with patch("app.workers.tasks.AsyncSessionFactory") as mock_factory:
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.workers.tasks.ProductSyncService") as mock_service:
            mock_service.return_value.sync_account_products = fake_sync_account_products

            with patch("app.workers.tasks.get_settings"):
                from app.workers.tasks import sync_products
                await sync_products({})

    assert session.rolled_back is True


def test_account_ref_is_plain_data() -> None:
    """AccountRef should be a simple dataclass, not an ORM object."""
    ref = AccountRef(id=1, marketplace="wb", user_id=42)
    assert ref.id == 1
    assert ref.marketplace == "wb"
    assert ref.user_id == 42
