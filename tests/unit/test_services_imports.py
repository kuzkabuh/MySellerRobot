"""version: 1.0.0
description: Import compatibility tests for MP Control service layer.
updated: 2026-06-09
"""

import importlib
from pathlib import Path

import pytest

# Modules that require external dependencies (playwright, openpyxl, etc.)
# and may not be available in all test environments.
_HEAVY_DEP_MODULES: set[str] = {
    "app.services.wb.reports.parser",
    "app.services.wb_daily_report_parser",
    "app.services.ozon.commissions.ozon_commission_browser_fetcher",
    "app.services.wb.pricing.mrc_import_service",
    "app.services.wb.pricing.wb_auto_promo_file_import_service",
    "app.services.wb.pricing.wb_auto_promo_import_service",
    "app.services.unit_economics.excel_cost_import",
}


def _get_all_service_modules() -> list[str]:
    services_dir = Path("app/services")
    modules = []
    for path in services_dir.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        if path.name.startswith("_"):
            continue
        parts = path.with_suffix("").parts
        app_index = parts.index("app")
        module_path = ".".join(parts[app_index:])
        modules.append(module_path)
    return sorted(modules)


def test_all_service_modules_basic_import() -> None:
    """All service modules can be imported without errors (skip heavy-dep modules)."""
    modules = _get_all_service_modules()
    failed = []
    for module_path in modules:
        if module_path in _HEAVY_DEP_MODULES:
            continue
        try:
            importlib.import_module(module_path)
        except Exception as exc:
            failed.append(f"{module_path}: {exc!r}")
    assert not failed, "\n".join(failed)


def test_wb_reports_package_imports() -> None:
    """wb_reports package and all submodules import correctly."""
    import app.services.wb.reports
    import app.services.wb.reports.financial_detail_service
    import app.services.wb.reports.import_service
    import app.services.wb.reports.parser
    import app.services.wb.reports.relink_service
    import app.services.wb.reports.report_service
    assert app.services.wb.reports.WbDailyReportImportService is not None


def test_old_facade_paths_compatible() -> None:
    """Old import paths still work after wb_reports reorganization."""
    from app.services.wb_daily_financial_detail_service import (
        WbDailyFinancialDetailService as OldDetailService,
    )
    from app.services.wb_daily_report_import_service import (
        WbDailyReportImportService as OldImportService,
    )
    from app.services.wb_daily_report_parser import (
        WbDailyReportParsed as OldParsed,
    )
    from app.services.wb_report_relink_service import (
        WbReportRelinkService as OldRelinkService,
    )
    from app.services.wb_report_service import (
        WbFinancialReportService as OldReportService,
    )
    from app.services.wb.reports.financial_detail_service import (
        WbDailyFinancialDetailService as NewDetailService,
    )
    from app.services.wb.reports.import_service import (
        WbDailyReportImportService as NewImportService,
    )
    from app.services.wb.reports.parser import WbDailyReportParsed as NewParsed
    from app.services.wb.reports.relink_service import WbReportRelinkService as NewRelinkService
    from app.services.wb.reports.report_service import WbFinancialReportService as NewReportService
    assert OldImportService is NewImportService
    assert OldParsed is NewParsed
    assert OldDetailService is NewDetailService
    assert OldRelinkService is NewRelinkService
    assert OldReportService is NewReportService


def test_payments_init_fix() -> None:
    """payments.__init__ correctly re-exports PaymentService."""
    from app.services.payments.payment_service import PaymentService as RootService
    from app.services.payments import PaymentService as PaymentsPkgService
    assert PaymentsPkgService is RootService


def test_wb_reports_private_functions_re_exported() -> None:
    """Private functions tested from old paths are still accessible."""
    from app.services.wb.reports.import_service import _finance_components_for_row
    assert callable(_finance_components_for_row)

    from app.services.wb.reports.report_service import _date_or_none, _extract_report_rows
    assert callable(_extract_report_rows)
    assert callable(_date_or_none)


@pytest.mark.skip(reason="Requires openpyxl or playwright")
def test_heavy_dep_modules() -> None:
    """Heavy dependency modules can be imported (manual run only)."""
    for module_path in _HEAVY_DEP_MODULES:
        importlib.import_module(module_path)
