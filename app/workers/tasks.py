"""version: 1.5.0
description: ARQ tasks for sync, Ozon enrichment, WB daily sales, reports, and alerts.
updated: 2026-05-17
"""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.models.domain import AlertEvent, MarketplaceAccount, User
from app.models.enums import Marketplace, SaleModel
from app.repositories.orders import OrderRepository
from app.repositories.sync_jobs import SyncJobRepository
from app.services.account_profile_service import AccountProfileService
from app.services.daily_report_service import DailyReportService
from app.services.fbo_digest_service import FboDigestService
from app.services.fbs_control_service import FbsControlService
from app.services.history_backfill_service import BackfillCounters, HistoryBackfillService
from app.services.notification_service import NotificationService
from app.services.order_processing_service import NewOrderNotification, OrderProcessingService
from app.services.ozon_catalog_enrichment_service import OzonCatalogEnrichmentService
from app.services.product_sync_service import ProductSyncService
from app.services.sales_event_sync_service import (
    OrderLifecycleNotification,
    SaleNotification,
    SalesEventSyncService,
)
from app.services.stock_service import StockService
from app.services.wb_report_service import WbFinancialReportService

logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


async def poll_new_orders(ctx: dict[str, Any]) -> None:
    """Poll active marketplace accounts and store unseen orders."""

    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
    notifier = NotificationService(bot)
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MarketplaceAccount)
            .options(selectinload(MarketplaceAccount.user))
            .where(MarketplaceAccount.is_active.is_(True))
        )
        accounts = list(result.scalars().all())
        logger.info("order_poll_started", extra={"accounts": len(accounts)})
        for account in accounts:
            account_id = account.id
            marketplace = account.marketplace.value
            try:
                poll_result = await OrderProcessingService(session).poll_account_with_stats(account)
                sent, failed = await _deliver_new_order_notifications(
                    session,
                    notifier,
                    poll_result.notifications or [],
                )
                logger.info(
                    "order_poll_notifications_sent",
                    extra={
                        "account_id": account_id,
                        "marketplace": marketplace,
                        "fetched": poll_result.fetched,
                        "orders_created": poll_result.created,
                        "duplicates": poll_result.duplicated,
                        "recovered_unnotified": poll_result.recovered_unnotified,
                        "skipped_by_policy": poll_result.skipped_by_policy,
                        "skipped_without_user": poll_result.skipped_without_user,
                        "notifications_prepared": poll_result.notification_count,
                        "notifications_attempted": poll_result.notification_count,
                        "notifications_sent": sent,
                        "notifications_failed": failed,
                    },
                )
            except Exception as exc:
                logger.exception(
                    "marketplace_poll_failed",
                    extra={"account_id": account_id, "marketplace": marketplace},
                )
                account.last_error_at = datetime.now(tz=UTC)
                account.last_error_message = str(exc)[:2000]
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
    await bot.session.close()


def _is_fbs_like_notification(sale_model: str | None) -> bool:
    return sale_model in {
        SaleModel.FBS.value,
        SaleModel.RFBS.value,
        SaleModel.DBS.value,
        SaleModel.DBW.value,
    }


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
        logger.info("fbs_deadline_alerts_created", extra={"alerts_created": created})


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


async def send_alert_notifications(ctx: dict[str, Any]) -> None:
    """Deliver pending alert events to Telegram after they are safely persisted."""

    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(AlertEvent, User.telegram_id)
            .join(User, User.id == AlertEvent.user_id)
            .where(AlertEvent.sent_at.is_(None))
            .where(AlertEvent.resolved_at.is_(None))
            .where(User.notifications_enabled.is_(True))
            .order_by(AlertEvent.created_at.asc())
            .limit(100)
        )
        rows = [(event, int(telegram_id)) for event, telegram_id in result.all()]
        await _deliver_alert_notifications(session, bot, rows)
    await bot.session.close()


async def _deliver_alert_notifications(
    session: AsyncSession,
    bot: Bot,
    rows: list[tuple[AlertEvent, int]],
) -> tuple[int, int]:
    sent = 0
    failed = 0
    for event, telegram_id in rows:
        try:
            logger.info(
                "alert_notification_send_attempt",
                extra=_alert_notification_log_extra(event),
            )
            await bot.send_message(int(telegram_id), event.message, parse_mode="HTML")
            event.sent_at = datetime.now(tz=UTC)
            await session.commit()
            sent += 1
            logger.info(
                "alert_notification_send_success",
                extra=_alert_notification_log_extra(event),
            )
        except Exception as exc:
            failed += 1
            await session.rollback()
            logger.exception(
                "alert_notification_send_failure",
                extra={
                    **_alert_notification_log_extra(event),
                    "exception_class": type(exc).__name__,
                    "error": str(exc)[:300],
                },
            )
    return sent, failed


async def sync_sale_events(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
    notifier = NotificationService(bot)
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MarketplaceAccount)
            .options(selectinload(MarketplaceAccount.user))
            .where(MarketplaceAccount.is_active.is_(True))
        )
        accounts = list(result.scalars().all())
        service = SalesEventSyncService(session)
        for account in accounts:
            try:
                sync_result = await service.sync_account(account)
                logger.info(
                    "sale_events_sync_finished",
                    extra={
                        "account_id": sync_result.account_id,
                        "marketplace": sync_result.marketplace.value,
                        "orders_fetched": sync_result.orders_fetched,
                        "orders_created": sync_result.orders_created,
                        "sales_fetched": sync_result.sales_fetched,
                        "sales_created": sync_result.sales_created,
                        "returns_fetched": sync_result.returns_fetched,
                        "returns_created": sync_result.returns_created,
                        "failed": sync_result.failed,
                    },
                )
            except Exception:
                logger.exception(
                    "sale_events_sync_failed",
                    extra={"account_id": account.id, "marketplace": account.marketplace.value},
                )
                await session.rollback()
        notifications = await service.pending_notifications(limit=100)
        await _deliver_sale_notifications(session, service, notifier, notifications)
        lifecycle_notifications = await service.pending_order_lifecycle_notifications(limit=100)
        await _deliver_order_lifecycle_notifications(
            session,
            service,
            notifier,
            lifecycle_notifications,
        )
    await bot.session.close()


async def _deliver_new_order_notifications(
    session: AsyncSession,
    notifier: NotificationService,
    notifications: list[NewOrderNotification],
) -> tuple[int, int]:
    sent = 0
    failed = 0
    for notification in notifications:
        logger.info(
            "notification_send_attempt",
            extra=_order_notification_log_extra(notification),
        )
        try:
            await notifier.send_new_order(
                notification.telegram_id,
                notification.text,
                notification.order_id,
                image_url=notification.image_url,
                product_url=notification.product_url,
                marketplace=notification.marketplace,
                parse_mode=notification.parse_mode,
            )
            await OrderRepository(session).mark_notified(notification.order_id)
            await session.commit()
            sent += 1
            logger.info(
                "notification_send_success",
                extra=_order_notification_log_extra(notification),
            )
            if _is_fbs_like_notification(notification.sale_model):
                logger.info(
                    "fbs_order_notification_sent",
                    extra=_order_notification_log_extra(notification),
                )
        except Exception as exc:
            failed += 1
            await session.rollback()
            logger.exception(
                "notification_send_failure",
                extra={
                    **_order_notification_log_extra(notification),
                    "exception_class": type(exc).__name__,
                    "error": str(exc)[:300],
                },
            )
            if _is_fbs_like_notification(notification.sale_model):
                logger.warning(
                    "fbs_order_notification_retry_scheduled",
                    extra=_order_notification_log_extra(notification),
                )
    return sent, failed


async def _deliver_sale_notifications(
    session: AsyncSession,
    service: SalesEventSyncService,
    notifier: NotificationService,
    notifications: list[SaleNotification],
) -> tuple[int, int]:
    sent = 0
    failed = 0
    for notification in notifications:
        logger.info(
            "notification_send_attempt",
            extra=_sale_notification_log_extra(notification),
        )
        try:
            await notifier.send_sale_completed(
                notification.telegram_id,
                notification.text,
                image_url=notification.image_url,
                product_url=notification.product_url,
                marketplace=notification.marketplace,
                parse_mode=notification.parse_mode,
            )
            await service.mark_notified(notification.event_id)
            await session.commit()
            sent += 1
            logger.info(
                "notification_send_success",
                extra=_sale_notification_log_extra(notification),
            )
        except Exception as exc:
            failed += 1
            await session.rollback()
            logger.exception(
                "notification_send_failure",
                extra={
                    **_sale_notification_log_extra(notification),
                    "exception_class": type(exc).__name__,
                    "error": str(exc)[:300],
                },
            )
            logger.warning(
                "sale_notification_retry_left_pending",
                extra=_sale_notification_log_extra(notification),
            )
    return sent, failed


async def _deliver_order_lifecycle_notifications(
    session: AsyncSession,
    service: SalesEventSyncService,
    notifier: NotificationService,
    notifications: list[OrderLifecycleNotification],
) -> tuple[int, int]:
    sent = 0
    failed = 0
    for notification in notifications:
        logger.info(
            "notification_send_attempt",
            extra=_lifecycle_notification_log_extra(notification),
        )
        try:
            await notifier.send_order_lifecycle_event(
                notification.telegram_id,
                notification.text,
                order_id=notification.order_id,
                image_url=notification.image_url,
                product_url=notification.product_url,
                marketplace=notification.marketplace,
                parse_mode=notification.parse_mode,
            )
            await service.mark_lifecycle_notified(
                event_type=notification.event_type,
                event_id=notification.event_id,
            )
            await session.commit()
            sent += 1
            logger.info(
                "notification_send_success",
                extra=_lifecycle_notification_log_extra(notification),
            )
        except Exception as exc:
            failed += 1
            await session.rollback()
            logger.exception(
                "notification_send_failure",
                extra={
                    **_lifecycle_notification_log_extra(notification),
                    "exception_class": type(exc).__name__,
                    "error": str(exc)[:300],
                },
            )
            logger.warning(
                "order_lifecycle_notification_retry_left_pending",
                extra=_lifecycle_notification_log_extra(notification),
            )
    return sent, failed


def _order_notification_log_extra(notification: NewOrderNotification) -> dict[str, object]:
    return {
        "event_type": notification.event_type,
        "account_id": notification.account_id,
        "user_id": notification.user_id,
        "order_id": notification.order_id,
        "telegram_id": notification.telegram_id,
        "marketplace": notification.marketplace.value,
        "fulfillment_type": notification.fulfillment_type,
        "sale_model": notification.sale_model,
    }


def _sale_notification_log_extra(notification: SaleNotification) -> dict[str, object]:
    return {
        "event_type": notification.event_type,
        "event_id": notification.event_id,
        "external_event_id": notification.external_event_id,
        "account_id": notification.account_id,
        "user_id": notification.user_id,
        "telegram_id": notification.telegram_id,
        "marketplace": notification.marketplace.value,
    }


def _lifecycle_notification_log_extra(
    notification: OrderLifecycleNotification,
) -> dict[str, object]:
    return {
        "event_type": notification.event_type,
        "event_id": notification.event_id,
        "external_event_id": notification.external_event_id,
        "account_id": notification.account_id,
        "user_id": notification.user_id,
        "order_id": notification.order_id,
        "telegram_id": notification.telegram_id,
        "marketplace": notification.marketplace.value,
    }


def _alert_notification_log_extra(event: AlertEvent) -> dict[str, object]:
    return {
        "event_type": event.alert_type.value,
        "event_id": event.id,
        "user_id": event.user_id,
        "idempotency_key": event.idempotency_key,
    }


async def sync_wb_daily_sales_reports(ctx: dict[str, Any]) -> None:
    moscow_today = datetime.now(tz=MOSCOW_TZ).date()
    report_dates = [moscow_today - timedelta(days=days) for days in (1, 2, 3)]
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MarketplaceAccount)
            .where(MarketplaceAccount.is_active.is_(True))
            .where(MarketplaceAccount.marketplace == Marketplace.WB)
        )
        accounts = list(result.scalars().all())
        service = SalesEventSyncService(session)
        for account in accounts:
            for report_date in report_dates:
                try:
                    await service.sync_wb_sales_report_day(account, report_date)
                except Exception:
                    logger.exception(
                        "daily_wb_sales_account_sync_failed",
                        extra={"account_id": account.id, "report_date": report_date.isoformat()},
                    )
                    account.last_error_at = datetime.now(tz=UTC)
                    account.last_error_message = "Ошибка ежедневной загрузки отчёта WB sales"
                    await session.commit()


async def sync_wb_account_profiles(ctx: dict[str, Any]) -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MarketplaceAccount)
            .where(MarketplaceAccount.is_active.is_(True))
            .where(MarketplaceAccount.marketplace == Marketplace.WB)
        )
        service = AccountProfileService(session)
        for account in result.scalars().all():
            try:
                await service.refresh_wb_account(account)
                await session.commit()
            except Exception:
                logger.exception("wb_account_profile_sync_failed", extra={"account_id": account.id})
                await session.rollback()


async def check_wb_financial_reports(ctx: dict[str, Any]) -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MarketplaceAccount)
            .where(MarketplaceAccount.is_active.is_(True))
            .where(MarketplaceAccount.marketplace == Marketplace.WB)
        )
        service = WbFinancialReportService(session)
        for account in result.scalars().all():
            try:
                results = await service.check_recent(account)
                await session.commit()
                logger.info(
                    "wb_financial_reports_checked",
                    extra={
                        "account_id": account.id,
                        "daily_status": results[0].status,
                        "weekly_status": results[1].status,
                    },
                )
            except Exception:
                logger.exception(
                    "wb_financial_reports_check_failed",
                    extra={"account_id": account.id},
                )
                await session.rollback()


async def sync_ozon_catalog_enrichment(ctx: dict[str, Any]) -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MarketplaceAccount)
            .where(MarketplaceAccount.is_active.is_(True))
            .where(MarketplaceAccount.marketplace == Marketplace.OZON)
        )
        accounts = list(result.scalars().all())
        service = OzonCatalogEnrichmentService(session)
        for account in accounts:
            try:
                stats = await service.sync_account(account)
                logger.info(
                    "ozon_catalog_enrichment_finished",
                    extra={
                        "account_id": account.id,
                        "warehouses": stats.warehouses_upserted,
                        "prices": stats.prices_upserted,
                        "promo_products": stats.promo_products_upserted,
                        "failed": stats.failed,
                    },
                )
            except Exception:
                logger.exception(
                    "ozon_catalog_enrichment_failed",
                    extra={"account_id": account.id},
                )
                await session.rollback()


async def sync_products(ctx: dict[str, Any]) -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MarketplaceAccount).where(MarketplaceAccount.is_active.is_(True))
        )
        accounts = list(result.scalars().all())
        service = ProductSyncService(session)
        total = 0
        failed = 0
        for account in accounts:
            try:
                synced = await service.sync_account_products(account)
                total += synced
                logger.info(
                    "manual_product_sync_finished",
                    extra={
                        "account_id": account.id,
                        "user_id": account.user_id,
                        "marketplace": account.marketplace.value,
                        "products_synced": synced,
                    },
                )
            except Exception:
                failed += 1
                logger.exception(
                    "manual_product_sync_failed",
                    extra={
                        "account_id": account.id,
                        "user_id": account.user_id,
                        "marketplace": account.marketplace.value,
                    },
                )
                await session.rollback()
        logger.info(
            "manual_product_sync_completed",
            extra={"accounts": len(accounts), "products_synced": total, "failed": failed},
        )


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
        forecast_created = await service.create_stockout_forecast_alerts()
        logger.info(
            "stock_alerts_created",
            extra={"low_stock_created": created, "stockout_forecast_created": forecast_created},
        )


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
