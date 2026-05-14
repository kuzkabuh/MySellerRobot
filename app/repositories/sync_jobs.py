"""version: 1.0.0
description: Sync job persistence helpers for historical backfill tasks.
updated: 2026-05-14
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, SyncJob
from app.models.enums import SyncJobStatus, SyncJobType


class SyncJobRepository:
    """Repository for background synchronization jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_history_backfill(
        self,
        *,
        account: MarketplaceAccount,
        job_type: SyncJobType,
        date_from: datetime,
        date_to: datetime,
        total_chunks: int,
        payload: dict[str, Any] | None = None,
    ) -> SyncJob:
        job = SyncJob(
            user_id=account.user_id,
            marketplace_account_id=account.id,
            marketplace=account.marketplace,
            job_type=job_type.value,
            date_from=date_from,
            date_to=date_to,
            status=SyncJobStatus.PENDING,
            progress_percent=0,
            processed_chunks=0,
            total_chunks=total_chunks,
            records_loaded=0,
            records_skipped=0,
            records_failed=0,
            payload=payload or {},
            job_metadata={"blocks": {}},
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: int) -> SyncJob | None:
        result = await self.session.execute(select(SyncJob).where(SyncJob.id == job_id))
        return result.scalar_one_or_none()

    async def pending_history_jobs(self, limit: int = 5) -> list[SyncJob]:
        result = await self.session.execute(
            select(SyncJob)
            .where(
                SyncJob.job_type.in_(
                    [
                        SyncJobType.INITIAL_HISTORY_BACKFILL.value,
                        SyncJobType.MANUAL_HISTORY_BACKFILL.value,
                        SyncJobType.FINANCIAL_HISTORY_BACKFILL.value,
                    ]
                ),
                SyncJob.status == SyncJobStatus.PENDING,
            )
            .order_by(SyncJob.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_running(self, job: SyncJob) -> None:
        job.status = SyncJobStatus.RUNNING
        job.started_at = datetime.now(tz=UTC)
        job.error_message = None
        await self.session.flush()

    async def update_progress(
        self,
        job: SyncJob,
        *,
        processed_chunks: int,
        records_loaded: int,
        records_skipped: int,
        records_failed: int,
        metadata: dict[str, Any],
    ) -> None:
        job.processed_chunks = processed_chunks
        job.records_loaded = records_loaded
        job.records_skipped = records_skipped
        job.records_failed = records_failed
        job.job_metadata = metadata
        job.progress_percent = (
            100
            if job.total_chunks <= 0
            else min(100, int(processed_chunks / job.total_chunks * 100))
        )
        await self.session.flush()

    async def mark_finished(
        self,
        job: SyncJob,
        *,
        status: SyncJobStatus,
        error_message: str | None = None,
    ) -> None:
        job.status = status
        job.finished_at = datetime.now(tz=UTC)
        job.progress_percent = (
            100
            if status
            in {
                SyncJobStatus.COMPLETED,
                SyncJobStatus.COMPLETED_WITH_WARNINGS,
                SyncJobStatus.SUCCESS,
            }
            else job.progress_percent
        )
        job.error_message = error_message
        await self.session.flush()

    async def get_account(self, job: SyncJob) -> MarketplaceAccount | None:
        if job.marketplace_account_id is None:
            return None
        result = await self.session.execute(
            select(MarketplaceAccount).where(MarketplaceAccount.id == job.marketplace_account_id)
        )
        return result.scalar_one_or_none()

    async def latest_for_account(
        self,
        *,
        account_id: int,
        job_type: SyncJobType | None = None,
    ) -> SyncJob | None:
        query = select(SyncJob).where(SyncJob.marketplace_account_id == account_id)
        if job_type:
            query = query.where(SyncJob.job_type == job_type.value)
        result = await self.session.execute(query.order_by(SyncJob.created_at.desc()).limit(1))
        return result.scalar_one_or_none()
