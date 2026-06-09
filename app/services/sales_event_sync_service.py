"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.sales_event_sync_service.
updated: 2026-06-09
"""

from app.services.common.sales_event_sync_service import (  # noqa: F401
    OrderLifecycleNotification,
    SaleNotification,
    SalesEventSyncService,
    SalesSyncResult,
)

__all__ = ['OrderLifecycleNotification', 'SaleNotification', 'SalesEventSyncService', 'SalesSyncResult']
