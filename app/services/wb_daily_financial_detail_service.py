"""version: 1.1.0
description: Compatibility facade. Moved to app.services.wb_reports.financial_detail_service.
updated: 2026-06-09
"""

from app.services.wb.reports.financial_detail_service import (  # noqa: F401
    DETAILED_REPORT_FIELDS,
    SyncCounters,
    WbDailyFinancialDetailService,
)

__all__ = [
    "DETAILED_REPORT_FIELDS",
    "SyncCounters",
    "WbDailyFinancialDetailService",
]
