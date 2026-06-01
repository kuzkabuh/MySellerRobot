"""Tests for admin visibility service primitives."""

import pytest

from app.services.audit_log_service import AuditLogService
from app.services.sync_status_service import (
    STATUS_COMPLETED_WITH_WARNINGS,
    STATUS_FAILED,
    STATUS_SUCCESS,
    SyncStatusService,
)


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for idx, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                obj.id = idx


@pytest.mark.asyncio
async def test_audit_log_creation() -> None:
    session = FakeSession()

    row = await AuditLogService(session).log(
        "tariff_changed",
        user_id=1,
        actor_user_id=2,
        details={"tier": "pro"},
    )

    assert row.action == "tariff_changed"
    assert row.user_id == 1
    assert row.details == {"tier": "pro"}


@pytest.mark.asyncio
async def test_sync_task_runs_success_failure() -> None:
    session = FakeSession()
    service = SyncStatusService(session)

    success = await service.start("poll_new_orders")
    await service.mark_success(success, records_processed=3, success_count=3)

    failure = await service.start("sync_products")
    await service.mark_failed(failure, "boom", records_processed=2, failed_count=1)

    assert success.status == STATUS_SUCCESS
    assert success.duration_ms is not None
    assert failure.status == STATUS_FAILED
    assert failure.last_error == "boom"


@pytest.mark.asyncio
async def test_sync_task_runs_warning_status() -> None:
    session = FakeSession()
    service = SyncStatusService(session)

    warning = await service.start("poll_new_orders")
    await service.mark_completed_with_warnings(
        warning,
        "recovery failed",
        records_processed=2,
        success_count=1,
        failed_count=1,
    )

    assert warning.status == STATUS_COMPLETED_WITH_WARNINGS
    assert warning.failed_count == 1
    assert warning.last_error == "recovery failed"
