"""version: 1.1.0
description: Compatibility facade. Moved to app.services.admin.user_activity_service.
updated: 2026-06-09
"""

from app.services.admin.user_activity_service import (  # noqa: F401
    ActivityLogEntry,
    UserActivityService,
    action_label,
)

__all__ = ['ActivityLogEntry', 'UserActivityService', 'action_label']
