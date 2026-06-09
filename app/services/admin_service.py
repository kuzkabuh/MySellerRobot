"""version: 1.1.0
description: Compatibility facade. Moved to app.services.admin.admin_service.
updated: 2026-06-09
"""

from app.services.admin.admin_service import (  # noqa: F401
    AdminService,
)

__all__ = ['AdminService']
