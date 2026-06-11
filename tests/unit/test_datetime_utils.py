"""version: 1.1.0
description: Unit tests for user timezone datetime helpers.
updated: 2026-06-11
"""

from datetime import UTC, datetime, timezone

from zoneinfo import ZoneInfo

from app.utils.datetime import (
    DEFAULT_TIMEZONE,
    format_datetime_for_user,
    format_user_datetime,
    get_user_timezone,
)


def test_moscow_timezone_converts_utc_notification_time() -> None:
    value = datetime(2026, 5, 15, 11, 33, tzinfo=UTC)

    assert format_datetime_for_user(value, "Europe/Moscow") == "15.05.2026 14:33"


def test_format_user_datetime_uses_empty_value() -> None:
    assert format_user_datetime(None) == "не указано"


def test_format_user_datetime_falls_back_to_moscow_timezone() -> None:
    value = datetime(2026, 5, 15, 11, 33, tzinfo=UTC)

    assert format_user_datetime(value, "bad/timezone") == "15.05.2026 14:33"


def test_get_user_timezone_returns_moscow_when_none() -> None:
    tz = get_user_timezone(None)
    assert tz == ZoneInfo("Europe/Moscow")


def test_get_user_timezone_returns_moscow_when_empty_string() -> None:
    tz = get_user_timezone("")
    assert tz == ZoneInfo("Europe/Moscow")


def test_get_user_timezone_returns_moscow_when_blank_string() -> None:
    tz = get_user_timezone("  ")
    assert tz == ZoneInfo("Europe/Moscow")


def test_get_user_timezone_returns_correct_zone_for_valid_name() -> None:
    tz = get_user_timezone("Asia/Vladivostok")
    assert tz == ZoneInfo("Asia/Vladivostok")


def test_get_user_timezone_returns_moscow_when_unknown_zone() -> None:
    tz = get_user_timezone("Mars/Olympus")
    assert tz == ZoneInfo("Europe/Moscow")


def test_get_user_timezone_does_not_crash_on_timezone_object() -> None:
    """This simulates the bug: passing a datetime.timezone object instead of a string."""
    tz = get_user_timezone(timezone.utc)  # type: ignore[arg-type]
    assert tz == ZoneInfo("Europe/Moscow")


def test_get_user_timezone_does_not_crash_on_int() -> None:
    tz = get_user_timezone(123)  # type: ignore[arg-type]
    assert tz == ZoneInfo("Europe/Moscow")


def test_get_user_timezone_does_not_crash_on_none_default() -> None:
    tz = get_user_timezone()
    assert tz == ZoneInfo("Europe/Moscow")


def test_format_datetime_for_user_accepts_none_timezone_name() -> None:
    value = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    result = format_datetime_for_user(value, None)
    assert result == "11.06.2026 15:00"


def test_format_datetime_for_user_does_not_crash_on_timezone_object() -> None:
    """Passing a datetime.timezone object must not crash, use default instead."""
    value = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    result = format_datetime_for_user(value, timezone.utc)  # type: ignore[arg-type]
    assert result == "11.06.2026 15:00"


def test_format_datetime_for_user_none_value_returns_nd() -> None:
    assert format_datetime_for_user(None, "Europe/Moscow") == "н/д"
