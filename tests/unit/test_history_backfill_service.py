"""version: 1.0.0
description: Unit tests for historical backfill planning, statuses, and messages.
updated: 2026-05-14
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.domain import SyncJob
from app.models.enums import Marketplace, SyncJobStatus, SyncJobType
from app.services.history_backfill_service import BackfillCounters, HistoryBackfillService


class FakeSyncJobs:
    def __init__(self) -> None:
        self.created: dict[str, object] | None = None

    async def create_history_backfill(self, **kwargs: object) -> SyncJob:
        self.created = kwargs
        return SyncJob(
            id=123,
            user_id=1,
            marketplace_account_id=10,
            marketplace=Marketplace.OZON,
            job_type=str(kwargs["job_type"]),
            date_from=kwargs["date_from"],
            date_to=kwargs["date_to"],
            status=SyncJobStatus.PENDING,
            total_chunks=int(kwargs["total_chunks"]),
            payload={},
            job_metadata={},
        )


class FakeSession:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_initial_backfill_job_is_created_for_connected_account() -> None:
    service = object.__new__(HistoryBackfillService)
    service.jobs = FakeSyncJobs()
    service.session = FakeSession()
    service.chunk_days = 7
    account = SimpleNamespace(id=10, user_id=1, marketplace=Marketplace.OZON)

    job = await service.schedule_initial(account, days=30)

    assert job.job_type == SyncJobType.INITIAL_HISTORY_BACKFILL
    assert job.total_chunks == 5
    assert service.jobs.created is not None


def test_backfill_chunks_cover_requested_period_without_overlap() -> None:
    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = start + timedelta(days=30)

    chunks = HistoryBackfillService.build_chunks(start, end, chunk_days=7)

    assert len(chunks) == 5
    assert chunks[0][0] == start
    assert chunks[-1][1] == end
    assert all(left[1] == right[0] for left, right in zip(chunks, chunks[1:], strict=False))


def test_completion_message_for_completed_job_contains_counts() -> None:
    job = SyncJob(
        id=1,
        user_id=1,
        marketplace_account_id=1,
        marketplace=Marketplace.WB,
        job_type=SyncJobType.INITIAL_HISTORY_BACKFILL.value,
        status=SyncJobStatus.COMPLETED,
        payload={},
        job_metadata={},
    )
    counters = BackfillCounters(orders=10, sales=7, returns=1, financial_rows=5, profit_items=10)

    text = HistoryBackfillService.format_completion_message(job, counters)

    assert "Первичная синхронизация завершена" in text
    assert "— заказов: 10" in text
    assert "— финансовых строк: 5" in text


def test_completion_message_for_warnings_is_partial() -> None:
    job = SyncJob(
        id=1,
        user_id=1,
        marketplace_account_id=1,
        marketplace=Marketplace.OZON,
        job_type=SyncJobType.INITIAL_HISTORY_BACKFILL.value,
        status=SyncJobStatus.COMPLETED_WITH_WARNINGS,
        payload={},
        job_metadata={},
    )
    counters = BackfillCounters(orders=3, warnings=["Финансовые отчёты пока недоступны."])

    text = HistoryBackfillService.format_completion_message(job, counters)

    assert "завершена частично" in text
    assert "Финансовые отчёты пока недоступны" in text


def test_block_statuses_mark_finance_partial_when_no_financial_rows() -> None:
    counters = BackfillCounters(orders=1, sales=1)

    statuses = HistoryBackfillService._block_statuses(counters)

    assert statuses["orders"] == "completed"
    assert statuses["financial_rows"] == "partial"


def test_extract_rows_supports_nested_marketplace_payloads() -> None:
    payload = {"result": {"returns": [{"id": 1}]}}

    rows = HistoryBackfillService._extract_rows(payload)

    assert rows == [{"id": 1}]
