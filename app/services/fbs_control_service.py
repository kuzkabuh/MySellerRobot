"""version: 1.1.0
description: Compatibility facade. Moved to app.services.alerts.fbs_control_service.
updated: 2026-06-09
"""

from app.services.alerts.fbs_control_service import (  # noqa: F401
    FbsControlService,
)

__all__ = ['FbsControlService']
