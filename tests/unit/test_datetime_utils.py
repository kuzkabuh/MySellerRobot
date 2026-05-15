"""version: 1.0.0
description: Unit tests for user timezone datetime helpers.
updated: 2026-05-15
"""

from datetime import UTC, datetime

from app.utils.datetime import format_datetime_for_user


def test_moscow_timezone_converts_utc_notification_time() -> None:
    value = datetime(2026, 5, 15, 11, 33, tzinfo=UTC)

    assert format_datetime_for_user(value, "Europe/Moscow") == "15.05.2026 14:33"
