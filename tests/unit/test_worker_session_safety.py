"""version: 1.2.0
description: Regression tests for worker session safety after rollback.
updated: 2026-05-20
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
async def test_poll_new_orders_uses_isolated_sessions() -> None:
    """Each account should use its own session so errors in one
    do not affect processing of other accounts."""
    sessions: list[FakeAsyncSession] = []
    session_call_index = [0]

    account1 = SimpleNamespace(
        id=1,
        marketplace=Marketplace.WB,
        user_id=1,
        last_error_at=None,
        last_error_message=None,
    )
    account2 = SimpleNamespace(
        id=2,
        marketplace=Marketplace.OZON,
        user_id=1,
        last_error_at=None,
        last_error_message=None,
    )

    poll_results = []

    async def fake_poll_account_with_stats(account):
        if account.id == 1:
            raise RuntimeError("API error for account 1")
        poll_results.append(account.id)
        return SimpleNamespace(
            fetched=1,
            created=1,
            duplicated=0,
            queued_digest=0,
            skipped_by_policy=0,
            skipped_without_user=0,
            skipped_without_items=0,
            retried_unnotified=0,
            recovered_unnotified=0,
            notifications=[],
            notification_count=0,
        )

    def make_session():
        s = FakeAsyncSession()
        sessions.append(s)
        idx = session_call_index[0]
        session_call_index[0] += 1
        if idx == 0:
            s._execute_results.append(
                FakeResult(
                    [
                        (1, Marketplace.WB, 1),
                        (2, Marketplace.OZON, 1),
                    ]
                )
            )
        elif idx == 1:
            s._execute_results.append(FakeResult([account1]))
        elif idx == 2:
            s._execute_results.append(FakeResult([account2]))
        return s

    class FakeAsyncCM:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *args):
            return False

    def mock_factory():
        s = make_session()
        return FakeAsyncCM(s)

    with patch("app.workers.tasks_main.AsyncSessionFactory", mock_factory):
        with patch("app.workers.tasks_main.OrderProcessingService") as mock_service:
            mock_service.return_value.poll_account_with_stats = fake_poll_account_with_stats

            with patch("app.workers.tasks_main.get_settings"):
                with patch("app.workers.tasks_main.Bot") as mock_bot:
                    mock_bot.return_value.session.close = AsyncMock()

                    from app.workers.tasks import poll_new_orders

                    await poll_new_orders({})

    assert len(sessions) >= 2
    assert 2 in poll_results


@pytest.mark.asyncio
async def test_sync_products_survives_rollback_and_continues() -> None:
    """sync_products should survive errors without MissingGreenlet."""
    sessions: list[FakeAsyncSession] = []
    session_call_index = [0]

    account = SimpleNamespace(
        id=10,
        marketplace=Marketplace.WB,
        user_id=5,
        last_error_at=None,
        last_error_message=None,
    )

    async def fake_sync_account_products(account):
        raise RuntimeError("Sync failed")

    def make_session():
        s = FakeAsyncSession()
        sessions.append(s)
        idx = session_call_index[0]
        session_call_index[0] += 1
        if idx == 0:
            s._execute_results.append(
                FakeResult(
                    [
                        (10, Marketplace.WB, 5),
                    ]
                )
            )
        elif idx == 1:
            s._execute_results.append(FakeResult([account]))
        return s

    class FakeAsyncCM:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *args):
            return False

    def mock_factory():
        s = make_session()
        return FakeAsyncCM(s)

    with patch("app.workers.tasks_main.AsyncSessionFactory", mock_factory):
        with patch("app.workers.tasks_main.ProductSyncService") as mock_service:
            mock_service.return_value.sync_account_products = fake_sync_account_products

            with patch("app.workers.tasks_main.get_settings"):
                from app.workers.tasks import sync_products

                await sync_products({})

    assert len(sessions) >= 1


def test_account_ref_is_plain_data() -> None:
    """AccountRef should be a simple dataclass, not an ORM object."""
    ref = AccountRef(id=1, marketplace="wb", user_id=42)
    assert ref.id == 1
    assert ref.marketplace == "wb"
    assert ref.user_id == 42
