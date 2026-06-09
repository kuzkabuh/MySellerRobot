"""version: 1.1.0
description: Compatibility facade. Moved to app.services.alerts.daily_report_service.
updated: 2026-06-09
"""

from app.services.alerts.daily_report_service import (  # noqa: F401
    DailyReportService,
)

__all__ = ['DailyReportService']
