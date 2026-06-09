"""Tests for user_sync_status_service."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.common.user_sync_status_service import (
    SYNC_STATUS_LABELS,
    SYNC_TYPES,
    UserSyncStatusService,
)


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_get_statuses_returns_all_types(mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    service = UserSyncStatusService(mock_session)
    statuses = await service.get_statuses(1)

    assert len(statuses) == len(SYNC_TYPES)
    for s in statuses:
        assert s.status == "pending"


@pytest.mark.asyncio
async def test_get_statuses_with_existing(mock_session):
    mock_sync = MagicMock()
    mock_sync.sync_type = "orders"
    mock_sync.status = "success"
    mock_sync.last_run_at = datetime(2026, 1, 1, tzinfo=UTC)
    mock_sync.last_success_at = datetime(2026, 1, 1, tzinfo=UTC)
    mock_sync.last_error_at = None
    mock_sync.last_error_message = None
    mock_sync.items_processed = 10
    mock_sync.duration_seconds = 5.5

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_sync]
    mock_session.execute = AsyncMock(return_value=mock_result)

    service = UserSyncStatusService(mock_session)
    statuses = await service.get_statuses(1)

    orders_status = next(s for s in statuses if s.sync_type == "orders")
    assert orders_status.status == "success"
    assert orders_status.items_processed == 10


@pytest.mark.asyncio
async def test_update_status_creates_new(mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 1))

    service = UserSyncStatusService(mock_session)
    await service.update_status(
        user_id=1,
        sync_type="orders",
        status="success",
        items_processed=15,
    )

    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()


def test_sync_types_not_empty():
    assert len(SYNC_TYPES) > 0
    codes = [code for code, _ in SYNC_TYPES]
    assert "orders" in codes
    assert "stocks" in codes


def test_sync_status_labels():
    assert "pending" in SYNC_STATUS_LABELS
    assert "success" in SYNC_STATUS_LABELS
    assert "error" in SYNC_STATUS_LABELS
