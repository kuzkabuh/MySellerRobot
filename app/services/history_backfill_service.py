"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.history_backfill_service.
updated: 2026-06-09
"""

from app.services.common.history_backfill_service import (  # noqa: F401
    BackfillCounters,
    HistoryBackfillService,
)

__all__ = ['BackfillCounters', 'HistoryBackfillService']
