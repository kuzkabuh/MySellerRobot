"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.message_formatter.
updated: 2026-06-09
"""

from app.services.common.message_formatter import (  # noqa: F401
    MessageFormatter,
    format_user_datetime,
    rub,
    safe_text,
)

__all__ = ['MessageFormatter', 'format_user_datetime', 'rub', 'safe_text']
