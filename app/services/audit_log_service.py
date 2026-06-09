"""version: 1.1.0
description: Compatibility facade. Moved to app.services.admin.audit_log_service.
updated: 2026-06-09
"""

from app.services.admin.audit_log_service import (  # noqa: F401
    AuditLogService,
)

__all__ = ['AuditLogService']
