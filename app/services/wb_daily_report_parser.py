"""version: 1.1.0
description: Compatibility facade. Moved to app.services.wb_reports.parser.
updated: 2026-06-09
"""

from app.services.wb.reports.parser import (  # noqa: F401
    COLUMN_ALIASES,
    DATE_KEYS,
    REPORT_NUMBER_PATTERN,
    REQUIRED_COLUMNS,
    WEEKLY_REPORT_EXPECTED_COLUMNS,
    WbDailyReportParsed,
    WbDailyReportParsedRow,
    _build_row,
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

__all__ = [
    "COLUMN_ALIASES",
    "DATE_KEYS",
    "REPORT_NUMBER_PATTERN",
    "REQUIRED_COLUMNS",
    "WEEKLY_REPORT_EXPECTED_COLUMNS",
    "WbDailyReportParsed",
    "WbDailyReportParsedRow",
    "classify_operation_scope",
    "classify_payment_reason",
    "compute_file_hash",
    "extract_rid_from_srid",
    "is_order_required",
    "iter_wb_daily_report_rows",
    "normalize_srid",
    "parse_wb_daily_report_file",
    "parse_wb_daily_report_upload",
]
