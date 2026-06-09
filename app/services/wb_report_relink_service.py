"""version: 1.1.0
description: Compatibility facade. Moved to app.services.wb_reports.relink_service.
updated: 2026-06-09
"""

from app.services.wb.reports.relink_service import (  # noqa: F401
    WbReportRelinkResult,
    WbReportRelinkService,
    normalize_report_srid,
)

__all__ = [
    "WbReportRelinkResult",
    "WbReportRelinkService",
    "normalize_report_srid",
]
