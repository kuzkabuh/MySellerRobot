"""version: 1.1.0
description: Compatibility facade. Moved to app.services.wb_reports.import_service.
updated: 2026-06-09
"""

from app.services.wb.reports.import_service import (  # noqa: F401
    DEDUP_DUPLICATE,
    WbDailyReportImportResult,
    WbDailyReportImportService,
    WbDailyReportImportSummary,
    WbDailyReportRowFilters,
    WbDailyReportRowsPage,
    _finance_components_for_row,
    _resolve_order_link,
    _resolve_product_link,
    _row_reason,
    _row_status,
)

__all__ = [
    "DEDUP_DUPLICATE",
    "WbDailyReportImportResult",
    "WbDailyReportImportService",
    "WbDailyReportImportSummary",
    "WbDailyReportRowFilters",
    "WbDailyReportRowsPage",
]
