"""Track worker task runs for admin visibility."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import SyncTaskRun

STATUS_STARTED = "started"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_COMPLETED_WITH_WARNINGS = "warning"
STATUS_TIMEOUT = "timeout"

STALE_TASK_TIMEOUT_MINUTES = 120
STALE_BACKFILL_TASK_TIMEOUT_HOURS = 6


class SyncStatusService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def start(
        self,
        task_name: str,
        *,
        triggered_by_user_id: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> SyncTaskRun:
        run = SyncTaskRun(
            task_name=task_name,
            status=STATUS_STARTED,
            started_at=datetime.now(tz=UTC),
            triggered_by_user_id=triggered_by_user_id,
            run_metadata=dict(metadata) if metadata is not None else None,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def mark_success(
        self,
        run: SyncTaskRun,
        *,
        records_processed: int = 0,
        success_count: int = 0,
        failed_count: int = 0,
    ) -> SyncTaskRun:
        return await self._finish(
            run,
            STATUS_SUCCESS,
            records_processed=records_processed,
            success_count=success_count,
            failed_count=failed_count,
        )

    async def mark_failed(
        self,
        run: SyncTaskRun,
        error: str,
        *,
        records_processed: int = 0,
        success_count: int = 0,
        failed_count: int = 1,
    ) -> SyncTaskRun:
        return await self._finish(
            run,
            STATUS_FAILED,
            records_processed=records_processed,
            success_count=success_count,
            failed_count=failed_count,
            last_error=error[:2000],
        )

    async def mark_completed_with_warnings(
        self,
        run: SyncTaskRun,
        warning: str,
        *,
        records_processed: int = 0,
        success_count: int = 0,
        failed_count: int = 1,
    ) -> SyncTaskRun:
        return await self._finish(
            run,
            STATUS_COMPLETED_WITH_WARNINGS,
            records_processed=records_processed,
            success_count=success_count,
            failed_count=failed_count,
            last_error=warning[:2000],
        )

    async def _finish(
        self,
        run: SyncTaskRun,
        status: str,
        *,
        records_processed: int,
        success_count: int,
        failed_count: int,
        last_error: str | None = None,
    ) -> SyncTaskRun:
        finished_at = datetime.now(tz=UTC)
        run.status = status
        run.finished_at = finished_at
        run.duration_ms = int((finished_at - run.started_at).total_seconds() * 1000)
        run.records_processed = records_processed
        run.success_count = success_count
        run.failed_count = failed_count
        run.last_error = last_error
        await self.session.flush()
        return run

    async def recent_runs(
        self,
        *,
        task_name: str | None = None,
        limit: int = 100,
    ) -> list[SyncTaskRun]:
        query = select(SyncTaskRun).order_by(SyncTaskRun.started_at.desc()).limit(limit)
        if task_name:
            query = query.where(SyncTaskRun.task_name == task_name)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def latest_by_task(self, *, limit: int = 200) -> dict[str, SyncTaskRun]:
        runs = await self.recent_runs(limit=limit)
        latest: dict[str, SyncTaskRun] = {}
        for run in runs:
            latest.setdefault(run.task_name, run)
        return latest

    async def all_task_names(self) -> list[str]:
        result = await self.session.execute(
            select(SyncTaskRun.task_name).distinct().order_by(SyncTaskRun.task_name)
        )
        return [row[0] for row in result.all()]

    async def mark_stale_task_runs_failed(self) -> int:
        now = datetime.now(tz=UTC)
        running_cutoff = now - timedelta(minutes=STALE_TASK_TIMEOUT_MINUTES)
        backfill_cutoff = now - timedelta(hours=STALE_BACKFILL_TASK_TIMEOUT_HOURS)

        count = 0
        for cutoff, task_filter in [
            (running_cutoff, None),
            (backfill_cutoff, "backfill_wb_daily_financial_details"),
        ]:
            conditions = [
                SyncTaskRun.status.in_(["started", "running"]),
                SyncTaskRun.finished_at.is_(None),
                SyncTaskRun.started_at.isnot(None),
                SyncTaskRun.started_at < cutoff,
            ]
            if task_filter is not None:
                conditions.append(SyncTaskRun.task_name == task_filter)
            result = await self.session.execute(
                select(SyncTaskRun).where(and_(*conditions))
            )
            for run in result.scalars().all():
                finished_at = datetime.now(tz=UTC)
                run.status = STATUS_TIMEOUT
                run.finished_at = finished_at
                run.duration_ms = int((finished_at - run.started_at).total_seconds() * 1000)
                run.failed_count = max(run.failed_count or 0, 1)
                run.last_error = (
                    f"Фоновая задача не завершилась корректно: превышено время выполнения "
                    f"({STALE_TASK_TIMEOUT_MINUTES if task_filter is None else STALE_BACKFILL_TASK_TIMEOUT_HOURS} ч)."
                )[:2000]
                count += 1
        if count:
            await self.session.flush()
        return count

    async def recent_runs_by_task(self, task_name: str, limit: int = 10) -> list[SyncTaskRun]:
        query = (
            select(SyncTaskRun)
            .where(SyncTaskRun.task_name == task_name)
            .order_by(SyncTaskRun.started_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
