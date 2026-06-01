"""Tests for support_service."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.support_service import (
    SupportService,
    TICKET_CATEGORIES,
    TICKET_STATUS_LABELS,
)


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_create_ticket(mock_session):
    mock_session.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 1))

    service = SupportService(mock_session)
    ticket = await service.create_ticket(
        user_id=1,
        subject="Тестовый вопрос",
        message="Описание проблемы",
        category="technical",
    )

    assert ticket.user_id == 1
    assert ticket.subject == "Тестовый вопрос"
    assert ticket.status == "open"
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_user_tickets(mock_session):
    mock_ticket = MagicMock()
    mock_ticket.id = 1
    mock_ticket.user_id = 1
    mock_ticket.subject = "Тест"
    mock_ticket.message = "Описание"
    mock_ticket.status = "open"
    mock_ticket.priority = "normal"
    mock_ticket.category = "general"
    mock_ticket.admin_response = None
    mock_ticket.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    mock_ticket.responded_at = None
    mock_ticket.closed_at = None

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_ticket]
    mock_session.execute = AsyncMock(return_value=mock_result)

    service = SupportService(mock_session)
    tickets = await service.get_user_tickets(1)

    assert len(tickets) == 1
    assert tickets[0].subject == "Тест"


@pytest.mark.asyncio
async def test_respond_ticket(mock_session):
    mock_ticket = MagicMock()
    mock_ticket.id = 1
    mock_session.get = AsyncMock(return_value=mock_ticket)

    service = SupportService(mock_session)
    result = await service.respond_ticket(1, admin_id=100, response="Ответ админа")

    assert result is True
    assert mock_ticket.admin_response == "Ответ админа"
    assert mock_ticket.status == "responded"
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_respond_ticket_not_found(mock_session):
    mock_session.get = AsyncMock(return_value=None)

    service = SupportService(mock_session)
    result = await service.respond_ticket(999, admin_id=100, response="Ответ")

    assert result is False


@pytest.mark.asyncio
async def test_close_ticket(mock_session):
    mock_ticket = MagicMock()
    mock_ticket.id = 1
    mock_session.get = AsyncMock(return_value=mock_ticket)

    service = SupportService(mock_session)
    result = await service.close_ticket(1)

    assert result is True
    assert mock_ticket.status == "closed"
    assert mock_ticket.closed_at is not None
    mock_session.commit.assert_called_once()


def test_ticket_categories_not_empty():
    assert len(TICKET_CATEGORIES) > 0
    codes = [code for code, _ in TICKET_CATEGORIES]
    assert "general" in codes
    assert "technical" in codes


def test_ticket_status_labels():
    assert "open" in TICKET_STATUS_LABELS
    assert "closed" in TICKET_STATUS_LABELS
