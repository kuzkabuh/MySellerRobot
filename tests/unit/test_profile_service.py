"""Tests for profile_service."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.account.profile_service import (
    ProfileService,
    ProfileUpdateData,
    ProfileValidationError,
)


def _make_user(**kwargs):
    user = MagicMock()
    user.id = kwargs.get("id", 1)
    user.telegram_id = kwargs.get("telegram_id", 123456)
    user.username = kwargs.get("username", "testuser")
    user.first_name = kwargs.get("first_name", "Test")
    user.last_name = kwargs.get("last_name", None)
    user.phone = kwargs.get("phone", None)
    user.email = kwargs.get("email", None)
    user.company_name = kwargs.get("company_name", None)
    user.inn = kwargs.get("inn", None)
    user.ogrn = kwargs.get("ogrn", None)
    user.timezone = kwargs.get("timezone", "Europe/Moscow")
    user.tariff = kwargs.get("tariff", "Free")
    user.notifications_enabled = kwargs.get("notifications_enabled", True)
    user.created_at = kwargs.get("created_at", datetime(2026, 1, 1, tzinfo=UTC))
    user.last_activity_at = kwargs.get("last_activity_at", None)
    user.last_login_at = kwargs.get("last_login_at", None)
    user.last_login_ip = kwargs.get("last_login_ip", None)
    return user


class _CurrentSubscription:
    def __init__(self, tier_name: str = "Free", tier_code: str = "free") -> None:
        self.tier = SimpleNamespace(name=tier_name, code=tier_code)


class _SubscriptionService:
    def __init__(self, session) -> None:
        self.session = session

    async def get_user_current_subscription(self, user_id: int) -> _CurrentSubscription:
        return _CurrentSubscription("PRO", "pro")


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_get_profile_returns_profile_data(mock_session, monkeypatch):
    monkeypatch.setattr("app.services.account.profile_service.SubscriptionService", _SubscriptionService)
    user = _make_user(first_name="Иван", last_name="Петров", tariff="Free")
    mock_session.get = AsyncMock(return_value=user)

    service = ProfileService(mock_session)
    profile = await service.get_profile(1)

    assert profile.user_id == 1
    assert profile.first_name == "Иван"
    assert profile.last_name == "Петров"
    assert profile.display_name == "Иван Петров"
    assert profile.tariff == "PRO"


@pytest.mark.asyncio
async def test_get_profile_not_found_raises(mock_session):
    mock_session.get = AsyncMock(return_value=None)

    service = ProfileService(mock_session)
    with pytest.raises(ProfileValidationError, match="не найден"):
        await service.get_profile(999)


@pytest.mark.asyncio
async def test_update_profile_email(mock_session):
    user = _make_user()
    mock_session.get = AsyncMock(return_value=user)

    service = ProfileService(mock_session)
    await service.update_profile(1, ProfileUpdateData(email="test@example.com"))

    assert user.email == "test@example.com"
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_profile_invalid_email(mock_session):
    user = _make_user()
    mock_session.get = AsyncMock(return_value=user)

    service = ProfileService(mock_session)
    with pytest.raises(ProfileValidationError, match="email"):
        await service.update_profile(1, ProfileUpdateData(email="invalid-email"))


@pytest.mark.asyncio
async def test_update_profile_phone(mock_session):
    user = _make_user()
    mock_session.get = AsyncMock(return_value=user)

    service = ProfileService(mock_session)
    await service.update_profile(1, ProfileUpdateData(phone="+7 900 123-45-67"))

    assert user.phone == "+7 900 123-45-67"


@pytest.mark.asyncio
async def test_update_profile_invalid_phone(mock_session):
    user = _make_user()
    mock_session.get = AsyncMock(return_value=user)

    service = ProfileService(mock_session)
    with pytest.raises(ProfileValidationError, match="телефон"):
        await service.update_profile(1, ProfileUpdateData(phone="abc"))


@pytest.mark.asyncio
async def test_update_profile_inn_valid(mock_session):
    user = _make_user()
    mock_session.get = AsyncMock(return_value=user)

    service = ProfileService(mock_session)
    await service.update_profile(1, ProfileUpdateData(inn="1234567890"))

    assert user.inn == "1234567890"


@pytest.mark.asyncio
async def test_update_profile_inn_invalid(mock_session):
    user = _make_user()
    mock_session.get = AsyncMock(return_value=user)

    service = ProfileService(mock_session)
    with pytest.raises(ProfileValidationError, match="ИНН"):
        await service.update_profile(1, ProfileUpdateData(inn="123"))


@pytest.mark.asyncio
async def test_update_profile_ogrn_valid(mock_session):
    user = _make_user()
    mock_session.get = AsyncMock(return_value=user)

    service = ProfileService(mock_session)
    await service.update_profile(1, ProfileUpdateData(ogrn="1234567890123"))

    assert user.ogrn == "1234567890123"


@pytest.mark.asyncio
async def test_update_profile_ogrn_invalid(mock_session):
    user = _make_user()
    mock_session.get = AsyncMock(return_value=user)

    service = ProfileService(mock_session)
    with pytest.raises(ProfileValidationError, match="ОГРН"):
        await service.update_profile(1, ProfileUpdateData(ogrn="123"))


@pytest.mark.asyncio
async def test_update_profile_timezone(mock_session):
    user = _make_user()
    mock_session.get = AsyncMock(return_value=user)

    service = ProfileService(mock_session)
    await service.update_profile(1, ProfileUpdateData(timezone="Asia/Yekaterinburg"))

    assert user.timezone == "Asia/Yekaterinburg"


@pytest.mark.asyncio
async def test_update_profile_company_name(mock_session):
    user = _make_user()
    mock_session.get = AsyncMock(return_value=user)

    service = ProfileService(mock_session)
    await service.update_profile(1, ProfileUpdateData(company_name="ООО Тест"))

    assert user.company_name == "ООО Тест"


@pytest.mark.asyncio
async def test_record_login(mock_session):
    user = _make_user()
    mock_session.get = AsyncMock(return_value=user)

    service = ProfileService(mock_session)
    await service.record_login(1, "192.168.1.1", "Mozilla/5.0")

    assert user.last_login_ip == "192.168.1.1"
    assert user.last_login_user_agent == "Mozilla/5.0"
    assert user.last_login_at is not None
    mock_session.commit.assert_called_once()
