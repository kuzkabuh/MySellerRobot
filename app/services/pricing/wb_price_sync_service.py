"""WB current price synchronization service for the pricing section."""

from app.services.wb.wb_current_prices_sync_service import (
    WbCurrentPricesSyncService as WbPriceSyncService,
)
from app.services.wb.wb_current_prices_sync_service import (
    WbCurrentPricesSyncStats as WbPriceSyncStats,
)

__all__ = ["WbPriceSyncService", "WbPriceSyncStats"]
