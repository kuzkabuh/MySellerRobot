"""version: 1.0.0
description: Common user display helpers used by web, bot and admin views.
updated: 2026-06-07
"""

from __future__ import annotations

from html import escape

from app.models.domain import User

MISSING_USERNAME_LABEL = "не указан"
MISSING_VALUE_LABEL = "—"


def user_display_name(user: User | None) -> str:
    """Return a stable human-readable name for the user.

    Priority: first_name → last_name → username → telegram_id.
    """
    if user is None:
        return "селлер"
    first = (getattr(user, "first_name", None) or "").strip()
    if first:
        return first
    last = (getattr(user, "last_name", None) or "").strip()
    if last:
        return last
    username = (getattr(user, "username", None) or "").strip()
    if username:
        return username
    telegram_id = getattr(user, "telegram_id", None)
    if telegram_id is not None:
        return str(telegram_id)
    return "селлер"


def username_label(user: User | None) -> str:
    """Return the username with @ prefix or "не указан" if missing."""
    if user is None:
        return MISSING_USERNAME_LABEL
    username = (getattr(user, "username", None) or "").strip()
    if not username:
        return MISSING_USERNAME_LABEL
    return f"@{escape(username)}"


def safe_username_value(user: User | None) -> str:
    """Return the raw username or empty string for forms."""
    if user is None:
        return ""
    return (getattr(user, "username", None) or "").strip()
