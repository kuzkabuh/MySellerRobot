"""version: 1.1.0
description: Compatibility facade. Moved to app.services.alerts.notification_service.
updated: 2026-06-09
"""

from app.services.alerts.notification_service import (  # noqa: F401
    NotificationService,
)

__all__ = ['NotificationService']
