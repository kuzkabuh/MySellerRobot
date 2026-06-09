"""version: 1.1.0
description: Compatibility facade. Moved to app.services.alerts.notification_settings_service.
updated: 2026-06-09
"""

from app.services.alerts.notification_settings_service import (  # noqa: F401
    NotificationSettingsService,
)

__all__ = ['NotificationSettingsService']
