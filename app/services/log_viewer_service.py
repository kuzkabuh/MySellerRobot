"""version: 1.1.0
description: Compatibility facade. Moved to app.services.admin.log_viewer_service.
updated: 2026-06-09
"""

from app.services.admin.log_viewer_service import (  # noqa: F401
    LogEntry,
    LogStats,
    LogViewerService,
)

__all__ = ['LogEntry', 'LogStats', 'LogViewerService']
