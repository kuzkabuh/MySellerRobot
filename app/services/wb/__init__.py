"""Wildberries-specific services."""

from app.services.wb.promotions.wb_promotions_sync_service import (
    WbPromotionsSyncService,
    WbPromotionsSyncStats,
)

__all__ = ["WbPromotionsSyncService", "WbPromotionsSyncStats"]
