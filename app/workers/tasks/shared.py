"""version: 1.0.0
description: Shared helpers for worker task modules (logging, account loading, notifications).
updated: 2026-06-10
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.models.domain import MarketplaceAccount

logger = logging.getLogger(__name__)
_PERMANENT_FAILURE_TYPES = (TelegramForbiddenError,)


@asynccontextmanager
async def bot_session() -> AsyncGenerator[Bot, None]:
    settings = get_settings()
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        yield bot
    finally:
        try:
            await bot.session.close()
        except Exception:
            logger.exception("worker_bot_session_close_failed")


@dataclass(slots=True)
class AccountRef:
    id: int
    marketplace: str
    user_id: int


async def load_account_refs(async_session_factory: Any) -> list[AccountRef]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(
                MarketplaceAccount.id,
                MarketplaceAccount.marketplace,
                MarketplaceAccount.user_id,
            ).where(MarketplaceAccount.is_active.is_(True))
        )
        return [
            AccountRef(id=row[0], marketplace=row[1].value, user_id=row[2]) for row in result.all()
        ]


async def load_account_by_id(session: AsyncSession, account_id: int) -> MarketplaceAccount | None:
    result = await session.execute(
        select(MarketplaceAccount)
        .options(selectinload(MarketplaceAccount.user))
        .where(MarketplaceAccount.id == account_id)
    )
    return result.scalar_one_or_none()


def task_stats(
    counters: dict[str, int],
    *,
    failed_count: int = 0,
    last_error: str | None = None,
) -> dict[str, Any]:
    stats: dict[str, Any] = dict(counters)
    stats["records_processed"] = sum(
        v for k, v in counters.items() if k != "task_stats"
    )
    if failed_count > 0:
        stats["failed_count"] = failed_count
        stats["status"] = "completed_with_warnings"
    if last_error:
        stats["last_error"] = last_error[:5000]
    return stats


def is_permanent_failure(exc: Exception) -> bool:
    return isinstance(exc, _PERMANENT_FAILURE_TYPES)


def is_fbs_like_notification(sale_model: str | None) -> bool:
    if sale_model is None:
        return False
    return sale_model.upper() in ("FBS", "RFBS")


async def start_sync_run(session: AsyncSession, sync_run_id: int) -> None:
    from app.models.domain import SyncRun

    result = await session.execute(
        select(SyncRun).where(SyncRun.id == sync_run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        return
    now = datetime.now(tz=UTC)
    run.status = "running"
    if run.started_at is None:
        run.started_at = now
    await session.flush()


def tracked_task(
    func: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    @wraps(func)
    async def wrapper(ctx: dict[str, Any], **kwargs: Any) -> Any:
        from app.services.common.sync_status_service import SyncStatusService

        task_name = func.__name__
        if not hasattr(AsyncSessionFactory, "begin"):
            return await func(ctx)

        if kwargs and isinstance(ctx, dict):
            for k, v in kwargs.items():
                if v is not None:
                    ctx[k] = v

        sync_run_id = kwargs.get("sync_run_id") or (ctx.get("sync_run_id") if ctx else None)
        triggered_by = kwargs.get("triggered_by_user_id") or (ctx.get("triggered_by_user_id") if ctx else None)

        async with AsyncSessionFactory() as session:
            service = SyncStatusService(session)
            run = await service.start(
                task_name,
                triggered_by_user_id=triggered_by,
                metadata={"source": "arq"},
            )
            if sync_run_id is not None:
                await start_sync_run(session, sync_run_id)
            await session.commit()
            if sync_run_id is not None:
                await send_sync_notification(session, sync_run_id, "start")
        logger.info(
            "worker_task_started",
            extra={
                "task_name": task_name,
                "run_id": run.id,
                "sync_run_id": sync_run_id,
            },
        )

        try:
            result = await func(ctx)
        except asyncio.CancelledError:
            async with AsyncSessionFactory() as session:
                service = SyncStatusService(session)
                db_run = await session.get(type(run), run.id)
                if db_run is not None:
                    await service.mark_failed(db_run, "Задача отменена: превышено время выполнения.")
                    await session.commit()
                if sync_run_id is not None:
                    await update_sync_run(
                        session, sync_run_id, "timeout",
                        error_message="Задача отменена: превышено время выполнения.",
                    )
                    await send_sync_notification(session, sync_run_id, "finish")
            logger.warning(
                "worker_task_cancelled",
                extra={
                    "task_name": task_name,
                    "run_id": run.id,
                    "sync_run_id": sync_run_id,
                },
            )
            raise
        except Exception as exc:
            async with AsyncSessionFactory() as session:
                service = SyncStatusService(session)
                db_run = await session.get(type(run), run.id)
                if db_run is not None:
                    await service.mark_failed(db_run, str(exc))
                    await session.commit()
                if sync_run_id is not None:
                    await update_sync_run(
                        session, sync_run_id, "error",
                        error_message=str(exc)[:5000],
                    )
                    await send_sync_notification(session, sync_run_id, "finish")
            logger.exception(
                "worker_task_failed",
                extra={
                    "task_name": task_name,
                    "run_id": run.id,
                    "sync_run_id": sync_run_id,
                },
            )
            raise

        async with AsyncSessionFactory() as session:
            service = SyncStatusService(session)
            db_run = await session.get(type(run), run.id)
            if db_run is not None:
                task_stats_dict = result if isinstance(result, dict) else {}
                records_processed = int(task_stats_dict.get("records_processed") or 0)
                success_count = int(task_stats_dict.get("success_count") or 0)
                failed_count = int(task_stats_dict.get("failed_count") or 0)
                last_error = task_stats_dict.get("last_error")
                if "task_stats" in task_stats_dict:
                    metadata = (
                        dict(db_run.run_metadata) if isinstance(db_run.run_metadata, dict) else {}
                    )
                    metadata["stats"] = task_stats_dict["task_stats"]
                    db_run.run_metadata = metadata
                if task_stats_dict.get("status") == "completed_with_warnings" or failed_count > 0:
                    await service.mark_completed_with_warnings(
                        db_run,
                        str(last_error or "completed with warnings"),
                        records_processed=records_processed,
                        success_count=success_count,
                        failed_count=failed_count,
                    )
                else:
                    await service.mark_success(
                        db_run,
                        records_processed=records_processed,
                        success_count=success_count,
                        failed_count=failed_count,
                    )
                await session.commit()

                if sync_run_id is not None:
                    sync_status = "warning" if (task_stats_dict.get("status") == "completed_with_warnings" or failed_count > 0) else "success"
                    inner_stats = task_stats_dict.get("task_stats", {})
                    if isinstance(inner_stats, dict):
                        records_skipped = int(inner_stats.get("records_skipped") or 0)
                        records_created_val = int(inner_stats.get("records_created") or 0)
                        records_updated_val = int(inner_stats.get("records_updated") or 0)
                    else:
                        records_skipped = records_created_val = records_updated_val = 0
                    task_details = {}
                    if isinstance(inner_stats, dict):
                        for key in ("pages_loaded", "request_windows", "source_api", "date_from", "date_to", "period_days"):
                            if key in inner_stats:
                                task_details[key] = inner_stats[key]
                    await update_sync_run(
                        session, sync_run_id, sync_status,
                        records_loaded=records_processed,
                        records_created=records_created_val,
                        records_updated=records_updated_val,
                        records_skipped=records_skipped,
                        error_message=last_error if sync_status == "warning" else None,
                        details=task_details or None,
                    )
                    await send_sync_notification(session, sync_run_id, "finish")

                logger.info(
                    "worker_task_finished",
                    extra={
                        "task_name": task_name,
                        "run_id": run.id,
                        "sync_run_id": sync_run_id,
                        "duration_ms": db_run.duration_ms,
                    },
                )
        return result

    return wrapper


async def update_sync_run(
    session: AsyncSession,
    sync_run_id: int,
    status: str,
    *,
    records_loaded: int = 0,
    records_created: int = 0,
    records_updated: int = 0,
    records_skipped: int = 0,
    error_message: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    from app.services.common.web_sync_run_service import WebSyncRunService

    svc = WebSyncRunService(session)
    await svc.finish_run(
        sync_run_id,
        status=status,
        records_loaded=records_loaded,
        records_created=records_created,
        records_updated=records_updated,
        records_skipped=records_skipped,
        error_message=error_message,
        details=details,
    )
    await session.commit()


async def send_sync_notification(session: AsyncSession, sync_run_id: int, event: str = "finish") -> None:
    try:
        from app.models.domain import SyncRun
        from app.services.common.sync_notification_service import SyncNotificationService

        result = await session.execute(
            select(SyncRun)
            .options(
                joinedload(SyncRun.account),
                joinedload(SyncRun.user),
            )
            .where(SyncRun.id == sync_run_id)
        )
        run = result.scalar_one_or_none()
        if run is not None:
            notifier = SyncNotificationService()
            if event == "start":
                await notifier.send_sync_start(run)
            else:
                await notifier.send_sync_finish(run)
    except Exception:
        logger.exception(
            "sync_run_notification_failed",
            extra={"sync_run_id": sync_run_id, "event": event},
        )


__all__ = [
    "AccountRef",
    "bot_session",
    "is_permanent_failure",
    "is_fbs_like_notification",
    "load_account_by_id",
    "load_account_refs",
    "send_sync_notification",
    "start_sync_run",
    "task_stats",
    "tracked_task",
    "update_sync_run",
]
