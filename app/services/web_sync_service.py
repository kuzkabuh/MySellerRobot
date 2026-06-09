"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.web_sync_service.
updated: 2026-06-09
"""

from app.services.common.web_sync_service import (  # noqa: F401
    WebSyncRequestResult,
    WebSyncService,
    WebSyncType,
)

__all__ = ['WebSyncRequestResult', 'WebSyncService', 'WebSyncType']
