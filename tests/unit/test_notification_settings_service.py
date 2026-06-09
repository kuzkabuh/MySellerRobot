"""version: 1.0.0
description: Тесты наследования настроек уведомлений.
updated: 2026-06-07
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.enums import NotificationType
from app.services.alerts.notification_settings_service import NotificationSettingsService


class _Result:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[SimpleNamespace]:
        return self._rows


def _row(notification_type: NotificationType, enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(notification_type=notification_type.value, is_enabled=enabled)


@pytest.mark.asyncio
async def test_account_settings_inherit_global_and_override_specific_types() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _Result([_row(NotificationType.NEW_ORDER, False)]),
            _Result([_row(NotificationType.DAILY_REPORT, False)]),
        ]
    )

    settings = await NotificationSettingsService(session).get_user_settings(
        1,
        marketplace_account_id=10,
    )

    assert settings[NotificationType.NEW_ORDER] is False
    assert settings[NotificationType.DAILY_REPORT] is False
    assert settings[NotificationType.ORDER_FBS] is True


@pytest.mark.asyncio
async def test_global_settings_do_not_query_account_rows() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Result([_row(NotificationType.NEW_ORDER, False)]))

    settings = await NotificationSettingsService(session).get_user_settings(1)

    assert settings[NotificationType.NEW_ORDER] is False
    assert session.execute.await_count == 1
