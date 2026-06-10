"""version: 1.0.0
description: Smoke tests for worker settings and task imports.
updated: 2026-06-10
"""

import importlib
from typing import Any

import pytest

# All worker tasks that must be importable
WORKER_TASK_NAMES = [
    "poll_new_orders",
    "resend_unnotified_orders",
    "sync_wb_fbs_assembly_orders",
    "sync_sale_events",
    "sync_wb_daily_sales_reports",
    "check_wb_financial_reports",
    "sync_wb_daily_financial_details",
    "backfill_wb_daily_financial_details",
    "relink_wb_report_rows",
    "sync_ozon_balances",
    "reconcile_ozon_finance",
    "sync_products",
    "sync_ozon_catalog_enrichment",
    "sync_wb_product_prices",
    "send_daily_reports",
    "send_alert_notifications",
    "send_fbo_digests",
    "check_fbs_deadlines",
    "check_low_stocks",
    "check_auto_promo_prices",
    "reconcile_pending_payments",
    "process_history_backfills",
    "check_stale_sync_runs",
    "check_ozon_commission_source",
    "sync_wb_commissions",
    "sync_wb_logistics_tariffs",
    "sync_wb_daily_promotions",
    "sync_wb_account_profiles",
    "sync_wb_orders_stats",
]


def test_worker_settings_import() -> None:
    """WorkerSettings must import without errors."""
    from app.workers.settings import WorkerSettings

    assert WorkerSettings is not None
    assert hasattr(WorkerSettings, "functions")
    assert hasattr(WorkerSettings, "cron_jobs")


def test_worker_settings_functions_callable() -> None:
    """All functions in WorkerSettings.functions must be callable."""
    from app.workers.settings import WorkerSettings

    for func in WorkerSettings.functions:
        assert callable(func), f"{func.__name__} is not callable"


def test_worker_settings_has_all_tasks() -> None:
    """All expected worker tasks are registered in WorkerSettings.functions."""
    from app.workers.settings import WorkerSettings

    registered = {f.__name__ for f in WorkerSettings.functions}
    missing = set(WORKER_TASK_NAMES) - registered
    extra = registered - set(WORKER_TASK_NAMES)
    errors = []
    if missing:
        errors.append(f"Tasks missing from WorkerSettings.functions: {missing}")
    if extra:
        errors.append(f"Unexpected tasks in WorkerSettings.functions: {extra}")
    assert not errors, "\n".join(errors)


def test_each_worker_task_importable() -> None:
    """Each worker task can be imported individually from app.workers.tasks."""
    from app.workers import tasks

    failed = []
    for name in WORKER_TASK_NAMES:
        func = getattr(tasks, name, None)
        if func is None:
            failed.append(name)
    assert not failed, f"Tasks not found in app.workers.tasks: {failed}"


def test_worker_tasks_module_import() -> None:
    """app.workers.tasks module imports without errors."""
    import app.workers.tasks as _
    assert _ is not None


def test_tracked_task_import() -> None:
    """_tracked_task decorator is importable from canonical location."""
    from app.workers.tasks_main import _tracked_task
    assert callable(_tracked_task)


def test_sales_event_sync_service_import() -> None:
    """SalesEventSyncService imports without errors (no _get_profit_service)."""
    from app.services.common.sales_event_sync_service import (
        SalesEventSyncService,
        SaleNotification,
        OrderLifecycleNotification,
        SalesSyncResult,
    )
    assert SalesEventSyncService is not None
    assert SaleNotification is not None
    assert OrderLifecycleNotification is not None
    assert SalesSyncResult is not None


def test_old_facade_sales_event_sync_import() -> None:
    """Old import facade app.services.sales_event_sync_service works."""
    from app.services.sales_event_sync_service import (
        SalesEventSyncService as OldService,
        SalesSyncResult as OldResult,
    )
    from app.services.common.sales_event_sync_service import (
        SalesEventSyncService as NewService,
        SalesSyncResult as NewResult,
    )
    assert OldService is NewService
    assert OldResult is NewResult
