"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.storage_order_cleanup_service.
updated: 2026-06-09
"""

from app.services.common.storage_order_cleanup_service import (  # noqa: F401
    StorageFakeOrderCandidate,
    StorageFakeOrderCleanupResult,
    StorageOrderCleanupService,
)

__all__ = ['StorageFakeOrderCandidate', 'StorageFakeOrderCleanupResult', 'StorageOrderCleanupService']
