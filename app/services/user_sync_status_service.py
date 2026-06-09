"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.user_sync_status_service.
updated: 2026-06-09
"""

from app.services.common.user_sync_status_service import (  # noqa: F401
    SyncStatusData,
    UserSyncStatusService,
)

__all__ = ['SyncStatusData', 'UserSyncStatusService']
