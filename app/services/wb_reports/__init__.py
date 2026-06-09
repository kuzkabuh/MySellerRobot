"""WB reports package.

Provides grouped import paths for WB daily realization report services,
parsers, financial detail sync, report relinking, and financial report metadata.

Moved files:
  - wb_daily_report_import_service.py   → wb_reports.import_service
  - wb_daily_report_parser.py           → wb_reports.parser
  - wb_daily_financial_detail_service.py → wb_reports.financial_detail_service
  - wb_report_relink_service.py         → wb_reports.relink_service
  - wb_report_service.py                → wb_reports.report_service
"""

from app.services.wb.reports.financial_detail_service import (
    DETAILED_REPORT_FIELDS,
    SyncCounters,
    WbDailyFinancialDetailService,
)
from app.services.wb.reports.import_service import (
    DEDUP_DUPLICATE,
    WbDailyReportImportResult,
    WbDailyReportImportService,
    WbDailyReportImportSummary,
    WbDailyReportRowFilters,
    WbDailyReportRowsPage,
)
from app.services.wb.reports.parser import (
    DATE_KEYS,
    REPORT_NUMBER_PATTERN,
    REQUIRED_COLUMNS,
    WEEKLY_REPORT_EXPECTED_COLUMNS,
    WbDailyReportParsed,
    WbDailyReportParsedRow,
    classify_operation_scope,
    classify_payment_reason,
    compute_file_hash,
    extract_rid_from_srid,
    is_order_required,
    iter_wb_daily_report_rows,
    normalize_srid,
    parse_wb_daily_report_file,
    parse_wb_daily_report_upload,
)
from app.services.wb.reports.relink_service import (
    WbReportRelinkResult,
    WbReportRelinkService,
    normalize_report_srid,
)
from app.services.wb.reports.report_service import (
    WbFinancialReportService,
    WbReportCheckResult,
)

__all__ = [
    "DEDUP_DUPLICATE",
    "DATE_KEYS",
    "DETAILED_REPORT_FIELDS",
    "REPORT_NUMBER_PATTERN",
    "REQUIRED_COLUMNS",
    "SyncCounters",
    "WbDailyFinancialDetailService",
    "WbDailyReportImportResult",
    "WbDailyReportImportService",
    "WbDailyReportImportSummary",
    "WbDailyReportParsed",
    "WbDailyReportParsedRow",
    "WbDailyReportRowFilters",
    "WbDailyReportRowsPage",
    "WbFinancialReportService",
    "WbReportCheckResult",
    "WbReportRelinkResult",
    "WbReportRelinkService",
    "WEEKLY_REPORT_EXPECTED_COLUMNS",
    "classify_operation_scope",
    "classify_payment_reason",
    "compute_file_hash",
    "extract_rid_from_srid",
    "is_order_required",
    "iter_wb_daily_report_rows",
    "normalize_report_srid",
    "normalize_srid",
    "parse_wb_daily_report_file",
    "parse_wb_daily_report_upload",
]
