"""version: 1.0.0
description: User timezone helpers for bot, web, and notification formatting.
updated: 2026-05-15
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Moscow"
USER_DATETIME_FORMAT = "%d.%m.%Y %H:%M"


def get_user_timezone(timezone_name: str | None) -> ZoneInfo:
    """Return a safe user timezone with Moscow fallback."""

    try:
        return ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def ensure_aware_utc(value: datetime) -> datetime:
    """Treat legacy naive datetimes as UTC and return an aware UTC datetime."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def format_datetime_for_user(
    value: datetime | None,
    timezone_name: str | None = DEFAULT_TIMEZONE,
    fmt: str = USER_DATETIME_FORMAT,
) -> str:
    """Format UTC datetime in the user's timezone."""

    if value is None:
        return "н/д"
    return ensure_aware_utc(value).astimezone(get_user_timezone(timezone_name)).strftime(fmt)


def user_day_bounds_utc(
    day: date,
    timezone_name: str | None = DEFAULT_TIMEZONE,
) -> tuple[datetime, datetime]:
    """Return UTC bounds for a user's local calendar day."""

    timezone = get_user_timezone(timezone_name)
    start = datetime.combine(day, time.min, tzinfo=timezone).astimezone(UTC)
    end = datetime.combine(day, time.max, tzinfo=timezone).astimezone(UTC)
    return start, end
