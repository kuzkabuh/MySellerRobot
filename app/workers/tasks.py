"""version: 1.0.0
description: ARQ background task functions.
updated: 2026-05-14
"""

import logging
from datetime import date, timedelta
from typing import Any

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.models.domain import MarketplaceAccount, User
from app.repositories.sync_jobs import SyncJobRepository
from app.services.daily_report_service import DailyReportService
from app.services.fbo_digest_service import FboDigestService
from app.services.fbs_control_service import FbsControlService
from app.services.history_backfill_service import BackfillCounters, HistoryBackfillService
from app.services.notification_service import NotificationService
from app.services.order_processing_service import OrderProcessingService
from app.services.stock_service import StockService

logger = logging.getLogger(__name__)


async def poll_new_orders(ctx: dict[str, Any]) -> None:
    """Poll active marketplace accounts and store unseen orders."""

    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
    notifier = NotificationService(bot)
    async with AsyncSessionFactory() as session:
        accounts = (
            await session.execute(
                select(MarketplaceAccount)
                .options(selectinload(MarketplaceAccount.user))
                .where(MarketplaceAccount.is_active.is_(True))
            )
        ).scalars()
        for account in accounts:
            try:
                notifications = await OrderProcessingService(session).poll_account(account)
                for notification in notifications:
                    await notifier.send_new_order(
                        notification.telegram_id,
                        notification.text,
                        notification.order_id,
                    )
            except Exception:
                logger.exception("marketplace_poll_failed", extra={"account_id": account.id})
                await session.rollback()
    await bot.session.close()


async def send_daily_reports(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
    async with AsyncSessionFactory() as session:
        users = (
            await session.execute(select(User).where(User.notifications_enabled.is_(True)))
        ).scalars()
        for user in users:
            report_date = date.today() - timedelta(days=1)
            service = DailyReportService(session)
            payload = await service.build_payload(user.id, report_date)
            if not payload:
                continue
            await bot.send_message(user.telegram_id, service.format_report(report_date, payload))
    await bot.session.close()


async def check_fbs_deadlines(ctx: dict[str, Any]) -> None:
    async with AsyncSessionFactory() as session:
        created = await FbsControlService(session).create_deadline_alerts()
        logger.info("fbs_deadline_alerts_created", extra={"created": created})


async def send_fbo_digests(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
    notifier = NotificationService(bot)
    async with AsyncSessionFactory() as session:
        service = FboDigestService(session)
        notifications = await service.collect_pending()
        for notification in notifications:
            try:
                await notifier.send_fbo_digest(notification.telegram_id, notification.text)
                await service.mark_sent(notification.row_ids)
            except Exception:
                logger.exception(
                    "fbo_digest_send_failed",
                    extra={"user_id": notification.user_id},
                )
                await session.rollback()
    await bot.session.close()


async def check_low_stocks(ctx: dict[str, Any]) -> None:
    async with AsyncSessionFactory() as session:
        accounts = (
            await session.execute(
                select(MarketplaceAccount).where(MarketplaceAccount.is_active.is_(True))
            )
        ).scalars()
        service = StockService(session)
        for account in accounts:
            await service.sync_account_stocks(account)
        created = await service.create_low_stock_alerts()
        logger.info("low_stock_alerts_created", extra={"created": created})


async def process_history_backfills(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
    async with AsyncSessionFactory() as session:
        jobs = await SyncJobRepository(session).pending_history_jobs(limit=3)
        for job in jobs:
            try:
                service = HistoryBackfillService(session)
                counters = await service.run_job(job.id)
                refreshed_job = await SyncJobRepository(session).get(job.id)
                user = (
                    await session.execute(select(User).where(User.id == job.user_id))
                ).scalar_one_or_none()
                if user and refreshed_job:
                    await bot.send_message(
                        user.telegram_id,
                        service.format_completion_message(refreshed_job, counters),
                    )
            except Exception:
                logger.exception("history_backfill_worker_failed", extra={"job_id": job.id})
                await session.rollback()
                refreshed_job = await SyncJobRepository(session).get(job.id)
                user = (
                    await session.execute(select(User).where(User.id == job.user_id))
                ).scalar_one_or_none()
                if user and refreshed_job:
                    await bot.send_message(
                        user.telegram_id,
                        HistoryBackfillService.format_completion_message(
                            refreshed_job,
                            BackfillCounters(),
                        ),
                    )
    await bot.session.close()
