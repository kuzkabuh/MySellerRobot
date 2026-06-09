"""version: 1.1.0
description: Compatibility facade. Moved to app.services.admin.support_service.
updated: 2026-06-09
"""

from app.services.admin.support_service import (  # noqa: F401
    SupportService,
    TicketData,
)

__all__ = ['SupportService', 'TicketData']
