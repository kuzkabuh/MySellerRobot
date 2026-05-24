"""WB promotion synchronization service for the pricing section."""

from app.services.wb.wb_promotions_sync_service import (
    WbPromotionsSyncService as WbPromotionSyncService,
)
from app.services.wb.wb_promotions_sync_service import (
    WbPromotionsSyncStats as WbPromotionSyncStats,
)

__all__ = ["WbPromotionSyncService", "WbPromotionSyncStats"]
