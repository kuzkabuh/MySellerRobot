"""version: 1.1.0
description: Compatibility facade. Moved to app.services.wb_reports.report_service.
updated: 2026-06-09
"""

from app.services.wb.reports.report_service import (  # noqa: F401
    WbFinancialReportService,
    WbReportCheckResult,
    _date_or_none,
    _datetime_or_none,
    _decimal_or_none,
    _extract_report_rows,
)

__all__ = [
    "WbFinancialReportService",
    "WbReportCheckResult",
]
