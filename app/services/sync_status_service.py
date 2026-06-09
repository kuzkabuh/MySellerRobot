"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.sync_status_service.
updated: 2026-06-09
"""

from app.services.common.sync_status_service import (  # noqa: F401
    SyncStatusService,
)

__all__ = ['SyncStatusService']
