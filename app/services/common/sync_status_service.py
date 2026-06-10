"""Track worker task runs for admin visibility."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import SyncTaskRun

STATUS_STARTED = "started"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_COMPLETED_WITH_WARNINGS = "warning"


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

    async def recent_runs_by_task(self, task_name: str, limit: int = 10) -> list[SyncTaskRun]:
        query = (
            select(SyncTaskRun)
            .where(SyncTaskRun.task_name == task_name)
            .order_by(SyncTaskRun.started_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
