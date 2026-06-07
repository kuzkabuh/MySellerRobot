"""Tests for user_activity_service."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.user_activity_service import UserActivityService, action_label


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_log_activity_creates_entry(mock_session):
    mock_session.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 1))

    service = UserActivityService(mock_session)
    await service.log_activity(
        user_id=1,
        action="profile_update",
        entity_type="user",
        entity_id=1,
        details={"field": "email"},
        ip_address="192.168.1.1",
    )

    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_recent_activity(mock_session):
    mock_entry = MagicMock()
    mock_entry.id = 1
    mock_entry.user_id = 1
    mock_entry.action = "profile_update"
    mock_entry.entity_type = "user"
    mock_entry.entity_id = 1
    mock_entry.details = {"field": "email"}
    mock_entry.ip_address = "192.168.1.1"
    mock_entry.created_at = datetime(2026, 1, 1, tzinfo=UTC)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_entry]
    mock_session.execute = AsyncMock(return_value=mock_result)

    service = UserActivityService(mock_session)
    entries = await service.get_recent_activity(1, limit=10)

    assert len(entries) == 1
    assert entries[0].action == "profile_update"


def test_action_label_known():
    assert action_label("profile_update") == "Обновление профиля"
    assert action_label("api_key_added") == "Добавлен API-ключ"
    assert action_label("login") == "Вход в систему"


def test_action_label_unknown():
    assert action_label("unknown_action") == "unknown_action"
