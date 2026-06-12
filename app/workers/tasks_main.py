"""version: 2.1.0
description: ARQ tasks — legacy module. New tasks go into app/workers/tasks/. All symbols are re-exported from app/workers/tasks/__init__.py.
updated: 2026-06-10
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import wraps
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.models.domain import AlertEvent, MarketplaceAccount, Order, OrderItem, User
from app.models.enums import Marketplace, SaleModel
from app.repositories.orders import OrderRepository
from app.repositories.sync_jobs import SyncJobRepository
from app.services.account.account_profile_service import AccountProfileService
from app.services.alerts.daily_report_service import DailyReportService
from app.services.alerts.fbo_digest_service import FboDigestService
from app.services.alerts.fbs_control_service import FbsControlService
from app.services.alerts.notification_service import NotificationService
from app.services.common.history_backfill_service import BackfillCounters, HistoryBackfillService
from app.services.common.order_processing_service import (
    NewOrderNotification,
    OrderProcessingService,
)
from app.services.common.product_sync_service import ProductSyncService
from app.services.common.sales_event_sync_service import (
    OrderLifecycleNotification,
    SaleNotification,
    SalesEventSyncService,
)
from app.services.common.stock_service import StockService
from app.services.ozon.api.ozon_catalog_enrichment_service import OzonCatalogEnrichmentService
from app.services.ozon.finance.ozon_balance_service import OzonBalanceService
from app.services.ozon.finance.ozon_finance_aggregation_service import (
    OzonFinanceAggregationService,
)
from app.services.wb_daily_financial_detail_service import WbDailyFinancialDetailService
from app.services.wb_report_relink_service import WbReportRelinkService
from app.services.wb_report_service import WbFinancialReportService

logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
MAX_API_PAGES = 1000
# Период дозагрузки финансовых данных WB по умолчанию.
WB_FINANCIAL_BACKFILL_DAYS = 15
WB_FINANCIAL_BACKFILL_ALLOWED_PERIODS = [15, 30, 45, 60, 90]

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
    """Plain-data snapshot of a MarketplaceAccount to avoid expired-ORM issues after rollback."""

    id: int
    marketplace: str
    user_id: int


async def _load_account_refs(async_session_factory: Any) -> list[AccountRef]:
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


async def _load_account_by_id(session: AsyncSession, account_id: int) -> MarketplaceAccount | None:
    result = await session.execute(
        select(MarketplaceAccount)
        .options(selectinload(MarketplaceAccount.user))
        .where(MarketplaceAccount.id == account_id)
    )
    return result.scalar_one_or_none()


def _task_stats(
    counters: dict[str, int],
    *,
    failed_count: int = 0,
    last_error: str | None = None,
) -> dict[str, Any]:
    return {
        "task_stats": counters,
        "records_processed": sum(counters.values()),
        "success_count": int(counters.get("accounts_success", 0)),
        "failed_count": failed_count,
        "last_error": last_error,
        "status": "completed_with_warnings" if failed_count else "success",
    }


async def poll_new_orders(ctx: dict[str, Any], payload: dict | None = None) -> dict[str, Any]:
    """Poll active marketplace accounts and store unseen orders."""
    payload = payload or {}

    async with bot_session() as bot:
        notifier = NotificationService(bot)
        account_refs = await _load_account_refs(AsyncSessionFactory)
        stats: dict[str, int] = {
            "accounts_total": len(account_refs),
            "accounts_success": 0,
            "accounts_failed": 0,
            "orders_fetched": 0,
            "orders_created": 0,
            "duplicates": 0,
            "notifications_sent": 0,
            "notifications_failed": 0,
            "recovery_warnings": 0,
        }
        logger.info("order_poll_started", extra={"accounts": len(account_refs)})
        for ref in account_refs:
            try:
                async with AsyncSessionFactory() as session:
                    account = await _load_account_by_id(session, ref.id)
                    if account is None:
                        continue
                    poll_result = await OrderProcessingService(session).poll_account_with_stats(
                        account
                    )
                    sent, failed = await _deliver_new_order_notifications(
                        session,
                        notifier,
                        poll_result.notifications or [],
                    )
                    stats["accounts_success"] += 1
                    stats["orders_fetched"] += poll_result.fetched
                    stats["orders_created"] += poll_result.created
                    stats["duplicates"] += poll_result.duplicated
                    stats["notifications_sent"] += sent
                    stats["notifications_failed"] += failed
                    stats["recovery_warnings"] += int(
                        getattr(poll_result, "recovery_failed", False) is True
                    )
                    if account.marketplace == Marketplace.WB and poll_result.fetched:
                        relink = await WbReportRelinkService(session).relink_pending_rows(
                            marketplace_account_id=account.id
                        )
                        stats["wb_report_rows_relinked"] = (
                            stats.get("wb_report_rows_relinked", 0) + relink.matched
                        )
                    await session.commit()
                    logger.info(
                        "order_poll_notifications_sent",
                        extra={
                            "account_id": ref.id,
                            "marketplace": ref.marketplace,
                            "fetched": poll_result.fetched,
                            "orders_created": poll_result.created,
                            "duplicates": poll_result.duplicated,
                            "recovered_unnotified": poll_result.recovered_unnotified,
                            "skipped_by_policy": poll_result.skipped_by_policy,
                            "skipped_without_user": poll_result.skipped_without_user,
                            "skipped_without_items": poll_result.skipped_without_items,
                            "notifications_prepared": poll_result.notification_count,
                            "notifications_attempted": poll_result.notification_count,
                            "notifications_sent": sent,
                            "notifications_failed": failed,
                        },
                    )
            except Exception:
                stats["accounts_failed"] += 1
                logger.exception(
                    "marketplace_poll_failed",
                    extra={
                        "account_id": ref.id,
                        "marketplace": ref.marketplace,
                        "user_id": ref.user_id,
                    },
                )
        failed_count = (
            stats["accounts_failed"] + stats["notifications_failed"] + stats["recovery_warnings"]
        )
        return _task_stats(
            stats,
            failed_count=failed_count,
            last_error="poll_new_orders completed with warnings" if failed_count else None,
        )


def _is_permanent_failure(exc: Exception) -> bool:
    if isinstance(exc, _PERMANENT_FAILURE_TYPES):
        return True
    if isinstance(exc, TelegramBadRequest):
        msg = str(exc).lower()
        return "bot was blocked" in msg or "chat not found" in msg
    return False


def _is_fbs_like_notification(sale_model: str | None) -> bool:
    return sale_model in {
        SaleModel.FBS.value,
        SaleModel.RFBS.value,
        SaleModel.DBS.value,
        SaleModel.DBW.value,
    }


async def send_daily_reports(ctx: dict[str, Any], payload: dict | None = None) -> None:
    payload = payload or {}
    async with bot_session() as bot:
        async with AsyncSessionFactory() as session:
            users = (
                await session.execute(
                    select(User)
                    .join(MarketplaceAccount, MarketplaceAccount.user_id == User.id)
                    .where(User.notifications_enabled.is_(True))
                    .where(MarketplaceAccount.is_active.is_(True))
                    .distinct()
                )
            ).scalars()
            for user in users:
                report_date = date.today() - timedelta(days=1)
                service = DailyReportService(session)
                payload = await service.build_payload(user.id, report_date)
                if not payload:
                    continue
                await bot.send_message(
                    user.telegram_id,
                    service.format_report(report_date, payload),
                )


async def check_fbs_deadlines(ctx: dict[str, Any], payload: dict | None = None) -> None:
    payload = payload or {}
    async with AsyncSessionFactory() as session:
        created = await FbsControlService(session).create_deadline_alerts()
        logger.info("fbs_deadline_alerts_created", extra={"alerts_created": created})


async def send_fbo_digests(ctx: dict[str, Any], payload: dict | None = None) -> None:
    payload = payload or {}
    async with bot_session() as bot:
        notifier = NotificationService(bot)
        async with AsyncSessionFactory() as session:
            service = FboDigestService(session)
            notifications = await service.collect_pending()
            for notification in notifications:
                try:
                    await notifier.send_fbo_digest(notification.telegram_id, notification.text)
                    await service.mark_sent(notification.row_ids)
                    await session.commit()
                except Exception:
                    logger.exception(
                        "fbo_digest_send_failed",
                        extra={"user_id": notification.user_id},
                    )
                    try:
                        await session.rollback()
                    except Exception:
                        pass


async def send_alert_notifications(ctx: dict[str, Any], payload: dict | None = None) -> None:
    """Deliver pending alert events to Telegram after they are safely persisted."""
    payload = payload or {}

    async with bot_session() as bot:
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


async def _deliver_alert_notifications(
    session: AsyncSession,
    bot: Bot,
    rows: list[tuple[AlertEvent, int]],
) -> tuple[int, int]:
    sent = 0
    failed = 0
    for event, telegram_id in rows:
        event_id = event.id
        event_type = event.alert_type.value
        try:
            logger.info(
                "alert_notification_send_attempt",
                extra={
                    "event_type": event_type,
                    "event_id": event_id,
                    "user_id": event.user_id,
                    "idempotency_key": event.idempotency_key,
                },
            )
            await bot.send_message(int(telegram_id), event.message, parse_mode="HTML")
            event.sent_at = datetime.now(tz=UTC)
            await session.commit()
            sent += 1
            logger.info(
                "alert_notification_send_success",
                extra={
                    "event_type": event_type,
                    "event_id": event_id,
                },
            )
        except Exception as exc:
            failed += 1
            try:
                await session.rollback()
            except Exception:
                pass
            logger.exception(
                "alert_notification_send_failure",
                extra={
                    "event_type": event_type,
                    "event_id": event_id,
                    "exception_class": type(exc).__name__,
                    "error": str(exc)[:300],
                },
            )
    return sent, failed


async def sync_sale_events(ctx: dict[str, Any], payload: dict | None = None) -> dict[str, Any]:
    payload = payload or {}
    async with bot_session() as bot:
        notifier = NotificationService(bot)
        account_refs = await _load_account_refs(AsyncSessionFactory)
        stats: dict[str, int] = {
            "accounts_total": len(account_refs),
            "orders_fetched": 0,
            "sales_fetched": 0,
            "returns_fetched": 0,
            "created": 0,
            "updated": 0,
            "failed": 0,
        }
        logger.info("sale_events_sync_started", extra={"accounts": len(account_refs)})
        for ref in account_refs:
            try:
                async with AsyncSessionFactory() as session:
                    account = await _load_account_by_id(session, ref.id)
                    if account is None:
                        continue
                    service = SalesEventSyncService(session)
                    sync_result = await service.sync_account(account)
                    stats["orders_fetched"] += sync_result.orders_fetched
                    stats["sales_fetched"] += sync_result.sales_fetched
                    stats["returns_fetched"] += sync_result.returns_fetched
                    stats["created"] += (
                        sync_result.orders_created
                        + sync_result.sales_created
                        + sync_result.returns_created
                    )
                    stats["updated"] += (
                        sync_result.orders_updated
                        + sync_result.sales_updated
                        + sync_result.returns_updated
                    )
                    stats["failed"] += sync_result.failed
                    logger.info(
                        "sale_events_sync_finished",
                        extra={
                            "account_id": ref.id,
                            "marketplace": ref.marketplace,
                            "orders_fetched": sync_result.orders_fetched,
                            "orders_created": sync_result.orders_created,
                            "orders_updated": sync_result.orders_updated,
                            "sales_fetched": sync_result.sales_fetched,
                            "sales_created": sync_result.sales_created,
                            "sales_updated": sync_result.sales_updated,
                            "returns_fetched": sync_result.returns_fetched,
                            "returns_created": sync_result.returns_created,
                            "failed": sync_result.failed,
                        },
                    )
                    order_notifications = await OrderProcessingService(
                        session
                    ).collect_saved_unnotified_notifications(account)
                    sent, failed = await _deliver_new_order_notifications(
                        session,
                        notifier,
                        order_notifications,
                    )
                    if order_notifications:
                        logger.info(
                            "sale_sync_order_notifications_sent",
                            extra={
                                "account_id": ref.id,
                                "marketplace": ref.marketplace,
                                "notifications_prepared": len(order_notifications),
                                "notifications_sent": sent,
                                "notifications_failed": failed,
                            },
                        )
            except Exception as exc:
                stats["failed"] += 1
                logger.exception(
                    "sale_events_sync_failed",
                    extra={
                        "account_id": ref.id,
                        "marketplace": ref.marketplace,
                        "user_id": ref.user_id,
                        "exception_class": type(exc).__name__,
                        "error": str(exc)[:500],
                    },
                )

        async with AsyncSessionFactory() as session:
            sale_service = SalesEventSyncService(session)
            notifications = await sale_service.pending_notifications(limit=100)
            await _deliver_sale_notifications(session, sale_service, notifier, notifications)
            lifecycle_notifications = await sale_service.pending_order_lifecycle_notifications(
                limit=100
            )
            await _deliver_order_lifecycle_notifications(
                session,
                sale_service,
                notifier,
                lifecycle_notifications,
            )
        return _task_stats(
            stats,
            failed_count=stats["failed"],
            last_error="sync_sale_events completed with failures" if stats["failed"] else None,
        )


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
            try:
                await session.rollback()
            except Exception:
                pass
            is_permanent = _is_permanent_failure(exc)
            if is_permanent:
                await OrderRepository(session).mark_notified(notification.order_id)
                try:
                    await session.commit()
                except Exception:
                    pass
                logger.warning(
                    "notification_marked_permanently_failed",
                    extra={
                        **_order_notification_log_extra(notification),
                        "exception_class": type(exc).__name__,
                        "error": str(exc)[:300],
                    },
                )
            else:
                logger.exception(
                    "notification_send_failure",
                    extra={
                        **_order_notification_log_extra(notification),
                        "exception_class": type(exc).__name__,
                        "error": str(exc)[:300],
                    },
                )
            if _is_fbs_like_notification(notification.sale_model):
                retry_msg = (
                    "fbs_order_notification_permanently_failed"
                    if is_permanent
                    else "fbs_order_notification_retry_scheduled"
                )
                logger.warning(
                    retry_msg,
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
            try:
                await session.rollback()
            except Exception:
                pass
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
            try:
                await session.rollback()
            except Exception:
                pass
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


async def resend_unnotified_orders(ctx: dict[str, Any], payload: dict | None = None) -> None:
    """Recovery task: deliver saved FBS-like orders with first_notified_at IS NULL.

    Runs independently of API polling to catch orders that were persisted
    but never notified due to polling failures or worker crashes.
    """
    payload = payload or {}
    async with bot_session() as bot:
        notifier = NotificationService(bot)
        account_refs = await _load_account_refs(AsyncSessionFactory)
        logger.info("unnotified_recovery_started", extra={"accounts": len(account_refs)})
        total_sent = 0
        total_failed = 0
        for ref in account_refs:
            try:
                async with AsyncSessionFactory() as session:
                    account = await _load_account_by_id(session, ref.id)
                    if account is None:
                        continue
                    notifications = await OrderProcessingService(
                        session
                    ).collect_saved_unnotified_notifications(account)
                    if not notifications:
                        continue
                    sent, failed = await _deliver_new_order_notifications(
                        session,
                        notifier,
                        notifications,
                    )
                    total_sent += sent
                    total_failed += failed
                    logger.info(
                        "unnotified_recovery_account_done",
                        extra={
                            "account_id": ref.id,
                            "marketplace": ref.marketplace,
                            "notifications_prepared": len(notifications),
                            "sent": sent,
                            "failed": failed,
                        },
                    )
            except Exception:
                logger.exception(
                    "unnotified_recovery_account_failed",
                    extra={
                        "account_id": ref.id,
                        "marketplace": ref.marketplace,
                        "user_id": ref.user_id,
                    },
                )
        logger.info(
            "unnotified_recovery_completed",
            extra={
                "accounts_processed": len(account_refs),
                "total_sent": total_sent,
                "total_failed": total_failed,
            },
        )


async def sync_wb_daily_sales_reports(ctx: dict[str, Any], payload: dict | None = None) -> None:
    payload = payload or {}
    moscow_today = datetime.now(tz=MOSCOW_TZ).date()
    report_dates = [moscow_today - timedelta(days=days) for days in (1, 2, 3)]
    async with AsyncSessionFactory() as session:
        account_refs = await _load_account_refs_wb(session)
        for ref in account_refs:
            for report_date in report_dates:
                try:
                    account = await _load_account_by_id(session, ref.id)
                    if account is None:
                        continue
                    service = SalesEventSyncService(session)
                    await service.sync_wb_sales_report_day(account, report_date)
                except Exception:
                    logger.exception(
                        "daily_wb_sales_account_sync_failed",
                        extra={"account_id": ref.id, "report_date": report_date.isoformat()},
                    )
                    try:
                        await session.rollback()
                    except Exception:
                        pass


async def sync_wb_account_profiles(ctx: dict[str, Any], payload: dict | None = None) -> None:
    payload = payload or {}
    async with AsyncSessionFactory() as session:
        account_refs = await _load_account_refs_wb(session)
        service = AccountProfileService(session)
        for ref in account_refs:
            try:
                account = await _load_account_by_id(session, ref.id)
                if account is None:
                    continue
                await service.refresh_wb_account(account)
                await session.commit()
            except Exception:
                logger.exception("wb_account_profile_sync_failed", extra={"account_id": ref.id})
                try:
                    await session.rollback()
                except Exception:
                    pass


async def check_wb_financial_reports(ctx: dict[str, Any], payload: dict | None = None) -> None:
    payload = payload or {}
    async with AsyncSessionFactory() as session:
        account_refs = await _load_account_refs_wb(session)
        service = WbFinancialReportService(session)
        for ref in account_refs:
            try:
                account = await _load_account_by_id(session, ref.id)
                if account is None:
                    continue
                results = await service.check_recent(account)
                await session.commit()
                logger.info(
                    "wb_financial_reports_checked",
                    extra={
                        "account_id": ref.id,
                        "daily_status": results[0].status,
                        "weekly_status": results[1].status,
                    },
                )
            except Exception:
                logger.exception(
                    "wb_financial_reports_check_failed",
                    extra={"account_id": ref.id},
                )
                try:
                    await session.rollback()
                except Exception:
                    pass


async def sync_wb_daily_financial_details(ctx: dict[str, Any], payload: dict | None = None) -> None:
    payload = payload or {}
    moscow_yesterday = (datetime.now(tz=MOSCOW_TZ) - timedelta(days=1)).date()
    async with AsyncSessionFactory() as session:
        account_refs = await _load_account_refs_wb(session)
        for ref in account_refs:
            try:
                account = await _load_account_by_id(session, ref.id)
                if account is None:
                    continue
                service = WbDailyFinancialDetailService(session)
                counters = await service.sync_account_for_date(account, moscow_yesterday)
                await session.commit()
                logger.info(
                    "wb_daily_financial_detail_sync_finished",
                    extra={
                        "account_id": ref.id,
                        "report_date": moscow_yesterday.isoformat(),
                        "pages_fetched": counters.pages_fetched,
                        "rows_fetched": counters.total_rows_fetched,
                        "rows_upserted": counters.rows_upserted,
                        "rows_matched": counters.rows_matched,
                        "rows_unmatched": counters.rows_unmatched,
                        "orders_reconciled": counters.orders_reconciled,
                        "snapshots_upserted": counters.snapshots_upserted,
                        "failed_rows": counters.failed_rows,
                    },
                )
            except Exception:
                logger.exception(
                    "wb_daily_financial_detail_sync_account_failed",
                    extra={"account_id": ref.id, "report_date": moscow_yesterday.isoformat()},
                )
                try:
                    await session.rollback()
                except Exception:
                    pass


async def relink_wb_report_rows(ctx: dict[str, Any], payload: dict | None = None) -> dict[str, int]:
    payload = payload or {}
    async with AsyncSessionFactory() as session:
        result = await WbReportRelinkService(session).relink_pending_rows(limit=2000)
        await session.commit()
        logger.info(
            "wb_report_rows_relinked",
            extra={
                "scanned": result.scanned,
                "matched": result.matched,
                "pending": result.pending,
                "ambiguous": result.ambiguous,
                "errors": result.errors,
            },
        )
        return {
            "scanned": result.scanned,
            "matched": result.matched,
            "pending": result.pending,
            "ambiguous": result.ambiguous,
            "errors": result.errors,
        }


async def sync_ozon_catalog_enrichment(ctx: dict[str, Any], payload: dict | None = None) -> None:
    payload = payload or {}
    async with AsyncSessionFactory() as session:
        account_refs = await _load_account_refs_ozon(session)
        service = OzonCatalogEnrichmentService(session)
        for ref in account_refs:
            try:
                account = await _load_account_by_id(session, ref.id)
                if account is None:
                    continue
                stats = await service.sync_account(account)
                logger.info(
                    "ozon_catalog_enrichment_finished",
                    extra={
                        "account_id": ref.id,
                        "warehouses": stats.warehouses_upserted,
                        "prices": stats.prices_upserted,
                        "promo_products": stats.promo_products_upserted,
                        "failed": stats.failed,
                    },
                )
            except Exception:
                logger.exception(
                    "ozon_catalog_enrichment_failed",
                    extra={"account_id": ref.id},
                )
                try:
                    await session.rollback()
                except Exception:
                    pass


async def sync_ozon_balances(ctx: dict[str, Any], payload: dict | None = None) -> None:
    """Sync Ozon account balances via POST /v1/finance/balance."""
    payload = payload or {}
    async with AsyncSessionFactory() as session:
        account_refs = await _load_account_refs_ozon(session)
        success = 0
        failed = 0
        for ref in account_refs:
            try:
                account = await _load_account_by_id(session, ref.id)
                if account is None:
                    continue
                if not account.encrypted_client_id:
                    logger.info(
                        "ozon_balance_sync_skipped_no_client_id",
                        extra={"account_id": ref.id},
                    )
                    continue
                snapshot = await OzonBalanceService(session).sync_balance(account)
                await session.commit()
                if snapshot.current is not None:
                    success += 1
                else:
                    failed += 1
                logger.info(
                    "ozon_balance_sync_account_finished",
                    extra={
                        "account_id": ref.id,
                        "user_id": ref.user_id,
                        "closing_balance": str(snapshot.current),
                        "currency": snapshot.currency,
                        "status": snapshot.status,
                    },
                )
            except Exception:
                failed += 1
                logger.exception(
                    "ozon_balance_sync_account_failed",
                    extra={
                        "account_id": ref.id,
                        "marketplace": ref.marketplace,
                        "user_id": ref.user_id,
                    },
                )
                try:
                    await session.rollback()
                except Exception:
                    pass
        logger.info(
            "ozon_balance_sync_completed",
            extra={
                "accounts_processed": len(account_refs),
                "success": success,
                "failed": failed,
            },
        )


async def reconcile_ozon_finance(ctx: dict[str, Any], payload: dict | None = None) -> None:
    """Reconcile Ozon orders against FinancialReportRow entries.

    Creates ACTUAL profit snapshots for Ozon orders that have financial data
    but no actual snapshots yet.
    """
    payload = payload or {}
    async with AsyncSessionFactory() as session:
        account_refs = await _load_account_refs_ozon(session)
        reconciled = 0
        failed = 0
        for ref in account_refs:
            try:
                account = await _load_account_by_id(session, ref.id)
                if account is None:
                    continue
                service = OzonFinanceAggregationService(session)
                orders = await _load_ozon_orders_without_actual(session, account.id)
                for order in orders:
                    try:
                        created = await service.aggregate_order_finance(order)
                        if created > 0:
                            await service.reconcile_ozon_order(order)
                            reconciled += 1
                    except Exception:
                        logger.exception(
                            "ozon_finance_reconcile_order_failed",
                            extra={"order_id": order.id, "account_id": ref.id},
                        )
                        failed += 1
                from datetime import UTC, datetime
                account.last_ozon_finance_sync_at = datetime.now(tz=UTC)
                await session.commit()
            except Exception:
                failed += 1
                logger.exception(
                    "ozon_finance_reconcile_account_failed",
                    extra={"account_id": ref.id},
                )
                try:
                    await session.rollback()
                except Exception:
                    pass
        logger.info(
            "ozon_finance_reconciliation_completed",
            extra={
                "accounts_processed": len(account_refs),
                "reconciled": reconciled,
                "failed": failed,
            },
        )


async def _load_ozon_orders_without_actual(
    session: AsyncSession,
    account_id: int,
    limit: int = 500,
) -> list[Order]:
    """Load Ozon orders that have estimated but no actual profit snapshots."""
    from app.models.finance import ProfitSnapshot
    from app.models.enums import CalculationType

    subq = (
        select(ProfitSnapshot.order_item_id)
        .where(ProfitSnapshot.calculation_type == CalculationType.ACTUAL)
        .join(OrderItem, OrderItem.id == ProfitSnapshot.order_item_id)
    )
    result = await session.execute(
        select(Order)
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .where(
            Order.marketplace_account_id == account_id,
            Order.marketplace == Marketplace.OZON,
            OrderItem.id.isnot(None),
            OrderItem.commission_estimated.isnot(None),
            ~OrderItem.id.in_(subq),
        )
        .limit(limit)
    )
    return list(result.scalars().unique().all())


async def sync_products(ctx: dict[str, Any], payload: dict | None = None) -> None:
    payload = payload or {}
    account_refs = await _load_account_refs(AsyncSessionFactory)
    total = 0
    failed = 0
    for ref in account_refs:
        try:
            async with AsyncSessionFactory() as session:
                account = await _load_account_by_id(session, ref.id)
                if account is None:
                    continue
                synced = await ProductSyncService(session).sync_account_products(account)
                total += synced
                logger.info(
                    "product_sync_account_finished",
                    extra={
                        "account_id": ref.id,
                        "user_id": ref.user_id,
                        "marketplace": ref.marketplace,
                        "products_synced": synced,
                    },
                )
        except Exception:
            failed += 1
            logger.exception(
                "product_sync_account_failed",
                extra={
                    "account_id": ref.id,
                    "user_id": ref.user_id,
                    "marketplace": ref.marketplace,
                },
            )
    logger.info(
        "product_sync_completed",
        extra={"accounts": len(account_refs), "products_synced": total, "failed": failed},
    )


async def check_low_stocks(ctx: dict[str, Any], payload: dict | None = None) -> None:
    payload = payload or {}
    async with AsyncSessionFactory() as session:
        account_refs = await _load_account_refs(AsyncSessionFactory)
        service = StockService(session)
        failed = 0
        for ref in account_refs:
            try:
                account = await _load_account_by_id(session, ref.id)
                if account is None:
                    continue
                await service.sync_account_stocks(account)
            except Exception:
                failed += 1
                logger.exception(
                    "stock_sync_failed",
                    extra={
                        "account_id": ref.id,
                        "marketplace": ref.marketplace,
                    },
                )
        try:
            created = await service.create_low_stock_alerts()
            forecast_created = await service.create_stockout_forecast_alerts()
            logger.info(
                "stock_alerts_created",
                extra={
                    "low_stock_created": created,
                    "stockout_forecast_created": forecast_created,
                    "failed": failed,
                },
            )
        except Exception:
            logger.exception("stock_alert_creation_failed")


async def process_history_backfills(ctx: dict[str, Any], payload: dict | None = None) -> None:
    payload = payload or {}
    async with bot_session() as bot:
        async with AsyncSessionFactory() as session:
            jobs = await SyncJobRepository(session).pending_history_jobs(limit=3)
            for job in jobs:
                job_id = job.id
                job_user_id = job.user_id
                try:
                    service = HistoryBackfillService(session)
                    counters = await service.run_job(job_id)
                    refreshed_job = await SyncJobRepository(session).get(job_id)
                    user = (
                        await session.execute(select(User).where(User.id == job_user_id))
                    ).scalar_one_or_none()
                    if user and refreshed_job:
                        await bot.send_message(
                            user.telegram_id,
                            service.format_completion_message(refreshed_job, counters),
                        )
                except Exception:
                    logger.exception("history_backfill_worker_failed", extra={"job_id": job_id})
                    try:
                        await session.rollback()
                    except Exception:
                        pass
                    refreshed_job = await SyncJobRepository(session).get(job_id)
                    user = (
                        await session.execute(select(User).where(User.id == job_user_id))
                    ).scalar_one_or_none()
                    if user and refreshed_job:
                        await bot.send_message(
                            user.telegram_id,
                            HistoryBackfillService.format_completion_message(
                                refreshed_job,
                                BackfillCounters(),
                            ),
                        )


async def reconcile_pending_payments(ctx: dict[str, Any], payload: dict | None = None) -> None:
    """Check PENDING YooKassa payments against the API and update status."""
    payload = payload or {}
    from app.services.payments.payment_service import PaymentService

    async with AsyncSessionFactory() as session:
        service = PaymentService(session)
        try:
            reconciled = await service.reconcile_pending_payments()
            await session.commit()
            if reconciled:
                logger.info(
                    "yookassa_reconciliation_completed",
                    extra={"reconciled_count": reconciled},
                )
        except Exception:
            logger.exception("yookassa_reconciliation_failed")
            try:
                await session.rollback()
            except Exception:
                pass


async def _load_account_refs_wb(session: AsyncSession) -> list[AccountRef]:
    result = await session.execute(
        select(MarketplaceAccount.id, MarketplaceAccount.marketplace, MarketplaceAccount.user_id)
        .where(MarketplaceAccount.is_active.is_(True))
        .where(MarketplaceAccount.marketplace == Marketplace.WB)
    )
    return [AccountRef(id=row[0], marketplace=row[1].value, user_id=row[2]) for row in result.all()]


async def _load_account_refs_ozon(session: AsyncSession) -> list[AccountRef]:
    result = await session.execute(
        select(MarketplaceAccount.id, MarketplaceAccount.marketplace, MarketplaceAccount.user_id)
        .where(MarketplaceAccount.is_active.is_(True))
        .where(MarketplaceAccount.marketplace == Marketplace.OZON)
    )
    return [AccountRef(id=row[0], marketplace=row[1].value, user_id=row[2]) for row in result.all()]


async def sync_wb_commissions(ctx: dict[str, Any], payload: dict | None = None) -> None:
    """Daily sync of WB commission tariffs from the official API."""
    payload = payload or {}
    from app.services.commissions.admin_notifications import (
        format_wb_sync_notification,
        notify_admins,
    )
    from app.services.wb.commissions.wb_commission_sync_service import WbCommissionSyncService

    async with bot_session() as bot:
        async with AsyncSessionFactory() as session:
            account_refs = await _load_account_refs_wb(session)
            if not account_refs:
                logger.info("wb_commission_sync_no_accounts")
                return

            ref = account_refs[0]
            account = await _load_account_by_id(session, ref.id)
            if account is None:
                return

            from app.core.security import TokenCipher

            try:
                api_key = TokenCipher().decrypt(account.encrypted_api_key)
            except Exception:
                logger.exception("wb_commission_sync_decrypt_failed")
                return

            service = WbCommissionSyncService(session)
            result = await service.sync(api_key)

            notification = format_wb_sync_notification(result)
            if result.get("changed") or not result.get("success"):
                await notify_admins(bot, notification)


async def check_ozon_commission_source(ctx: dict[str, Any], payload: dict | None = None) -> None:
    """Daily check of the Ozon commissions page for new tariff tables."""
    payload = payload or {}
    from app.services.commissions.admin_notifications import (
        format_ozon_monitor_notification,
        notify_admins,
    )
    from app.services.ozon.commissions.ozon_commission_source_monitor_service import (
        OzonCommissionSourceMonitorService,
    )

    async with bot_session() as bot:
        async with AsyncSessionFactory() as session:
            service = OzonCommissionSourceMonitorService(session)
            result = await service.check()

            notification = format_ozon_monitor_notification(result)
            if notification:
                await notify_admins(bot, notification)


async def sync_wb_logistics_tariffs(ctx: dict[str, Any], payload: dict | None = None) -> None:
    """Daily sync of WB box delivery logistics tariffs from /api/v1/tariffs/box."""
    payload = payload or {}
    from app.services.commissions.admin_notifications import notify_admins
    from app.services.wb.logistics.wb_logistics_tariff_sync_service import (
        WbLogisticsTariffSyncService,
    )

    async with bot_session() as bot:
        async with AsyncSessionFactory() as session:
            account_refs = await _load_account_refs_wb(session)
            if not account_refs:
                logger.info("wb_logistics_sync_no_accounts")
                return

            ref = account_refs[0]
            account = await _load_account_by_id(session, ref.id)
            if account is None:
                return

            from app.core.security import TokenCipher

            try:
                api_key = TokenCipher().decrypt(account.encrypted_api_key)
            except Exception:
                logger.exception("wb_logistics_sync_decrypt_failed")
                return

            from app.integrations.wb import WildberriesClient

            wb_client = WildberriesClient(api_key=api_key)
            service = WbLogisticsTariffSyncService(session, wb_client)
            result = await service.sync()

            status_emoji = {"new_version": "✅", "no_changes": "ℹ️", "error": "❌"}.get(
                result["status"], "❓"
            )
            if result["status"] == "error":
                account.last_error_at = datetime.now(UTC)
                account.last_error_message = str(result["message"])[:1000]
                await session.commit()
                message = (
                    f"{status_emoji} Логистика WB не обновлена\n\n"
                    f"Кабинет: {account.name} (#{account.id})\n"
                    f"{result['message']}\n"
                    f"Время: {datetime.now(ZoneInfo('Europe/Moscow')):%d.%m.%Y %H:%M}"
                )
            else:
                message = f"{status_emoji} Логистика WB: {result['message']}"

            if result["status"] in ("new_version", "error"):
                await notify_admins(bot, message)


async def sync_wb_daily_promotions(ctx: dict[str, Any], payload: dict | None = None) -> dict[str, Any]:
    """Daily sync of WB calendar promotions and product nomenclatures.

    Runs at configured time (default 00:15 Moscow time).
    Fetches promotions active today, then fetches product lists for
    regular (non-auto) promotions.
    """
    payload = payload or {}
    from app.core.config import get_settings
    from app.core.security import TokenCipher
    from app.services.wb.promotions.wb_promotions_sync_service import WbPromotionsSyncService

    settings = get_settings()
    if not settings.wb_promotions_sync_enabled:
        logger.info("wb_promotions_sync_disabled_by_config")
        return _task_stats(
            {
                "accounts_total": 0,
                "promotions_fetched": 0,
                "nomenclatures_fetched": 0,
                "failed": 0,
            }
        )

    async with AsyncSessionFactory() as session:
        service = WbPromotionsSyncService(session, cipher=TokenCipher())
        acquired = False
        try:
            acquired, message = await service.try_acquire_sync_lock()
            if not acquired:
                logger.info("wb_promotions_sync_task_skipped", extra={"reason": message})
                return _task_stats(
                    {
                        "accounts_total": 0,
                        "promotions_fetched": 0,
                        "nomenclatures_fetched": 0,
                        "failed": 0,
                    }
                )
            stats = await service.sync_all_accounts()
            await session.commit()
            logger.info(
                "wb_promotions_sync_task_completed",
                extra={
                    "accounts_processed": stats.accounts_processed,
                    "accounts_failed": stats.accounts_failed,
                    "promotions_fetched": stats.promotions_fetched,
                    "promotions_upserted": stats.promotions_upserted,
                    "nomenclatures_fetched": stats.nomenclatures_fetched,
                    "nomenclatures_upserted": stats.nomenclatures_upserted,
                    "products_matched": stats.products_matched,
                    "errors_count": len(stats.errors),
                },
            )
            return _task_stats(
                {
                    "accounts_total": stats.accounts_processed + stats.accounts_failed,
                    "promotions_fetched": stats.promotions_fetched,
                    "nomenclatures_fetched": stats.nomenclatures_fetched,
                    "failed": stats.accounts_failed,
                },
                failed_count=stats.accounts_failed,
                last_error=stats.errors[0] if stats.errors else None,
            )
        except Exception:
            logger.exception("wb_promotions_sync_task_failed")
            try:
                await session.rollback()
            except Exception:
                pass
            return _task_stats(
                {
                    "accounts_total": 0,
                    "promotions_fetched": 0,
                    "nomenclatures_fetched": 0,
                    "failed": 1,
                },
                failed_count=1,
                last_error="wb_promotions_sync_task_failed",
            )
        finally:
            if acquired:
                await service.release_sync_lock()


async def check_auto_promo_prices(ctx: dict[str, Any], payload: dict | None = None) -> None:
    """Check auto promotion prices and optionally apply safe changes.

    Runs every 30 minutes. For accounts with auto_price_for_auto_promotions enabled,
    builds recommendations and applies only safe price changes.
    """
    payload = payload or {}
    from app.core.security import TokenCipher
    from app.models.domain import MrcPricingSettings
    from app.services.wb.pricing.wb_auto_promo_price_service import (
        STATUS_AUTO_MIN_PRICE_VIOLATION,
        STATUS_AUTO_PRICE_OK,
        STATUS_AUTO_PRICE_VIOLATION,
        STATUS_AUTO_REQUIRED_PRICE_UNKNOWN,
        STATUS_AUTO_SET_PRICE,
        WbAutoPromoPriceService,
    )
    from app.services.wb.pricing.wb_price_update_service import (
        SOURCE_AUTO,
        WbPriceUpdateService,
    )

    async with AsyncSessionFactory() as session:
        try:
            settings_result = await session.execute(
                select(MrcPricingSettings).where(
                    MrcPricingSettings.auto_promo_check_enabled.is_(True),
                )
            )
            settings_list = list(settings_result.scalars().all())

            if not settings_list:
                return

            auto_price_service = WbAutoPromoPriceService(session)
            price_update_service = WbPriceUpdateService(session)

            total_recommendations = 0
            total_applied = 0
            total_skipped = 0
            total_set_price = 0
            total_price_ok = 0
            total_violation = 0
            total_min_price_violation = 0
            total_unknown = 0
            cipher = TokenCipher()

            for settings in settings_list:
                if settings.marketplace_account_id is None:
                    continue

                recommendations = (
                    await auto_price_service.build_recommendations_for_active_auto_promos(
                        user_id=settings.user_id,
                        marketplace_account_id=settings.marketplace_account_id,
                    )
                )

                for rec in recommendations:
                    await auto_price_service.save_recommendation(
                        rec=rec,
                        user_id=settings.user_id,
                        marketplace_account_id=settings.marketplace_account_id,
                    )
                    total_recommendations += 1
                    if rec.status == STATUS_AUTO_SET_PRICE:
                        total_set_price += 1
                    elif rec.status == STATUS_AUTO_PRICE_OK:
                        total_price_ok += 1
                    elif rec.status == STATUS_AUTO_PRICE_VIOLATION:
                        total_violation += 1
                    elif rec.status == STATUS_AUTO_MIN_PRICE_VIOLATION:
                        total_min_price_violation += 1
                    elif rec.status == STATUS_AUTO_REQUIRED_PRICE_UNKNOWN:
                        total_unknown += 1

                if settings.auto_price_for_auto_promotions:
                    account_result = await session.execute(
                        select(MarketplaceAccount).where(
                            MarketplaceAccount.id == settings.marketplace_account_id,
                        )
                    )
                    account = account_result.scalar_one_or_none()
                    if account and account.encrypted_api_key:
                        try:
                            api_key = cipher.decrypt(account.encrypted_api_key)
                            results = await price_update_service.apply_price_changes(
                                user_id=settings.user_id,
                                marketplace_account_id=settings.marketplace_account_id,
                                wb_api_key=api_key,
                                dry_run=False,
                                source=SOURCE_AUTO,
                            )
                            for r in results:
                                if r["status"] == "applied":
                                    total_applied += 1
                                elif r["status"] in ("skipped", "failed"):
                                    total_skipped += 1
                        except Exception:
                            logger.exception(
                                "auto_promo_price_apply_failed",
                                extra={"account_id": settings.marketplace_account_id},
                            )

            await session.commit()

            if total_recommendations > 0 or total_applied > 0:
                logger.info(
                    "auto_promo_price_check_completed",
                    extra={
                        "recommendations": total_recommendations,
                        "set_price": total_set_price,
                        "price_ok": total_price_ok,
                        "violations": total_violation,
                        "min_price_violations": total_min_price_violation,
                        "unknown": total_unknown,
                        "prices_applied": total_applied,
                        "prices_skipped": total_skipped,
                    },
                )

                if total_applied > 0:
                    try:
                        async with bot_session() as bot:
                            for settings in settings_list:
                                if settings.auto_price_for_auto_promotions:
                                    user_result = await session.execute(
                                        select(User).where(User.id == settings.user_id)
                                    )
                                    user = user_result.scalar_one_or_none()
                                    if user and user.telegram_id:
                                        await bot.send_message(
                                            chat_id=user.telegram_id,
                                            text=(
                                                f"🤖 Автоакции WB:\n"
                                                f"Рекомендаций: {total_recommendations}\n"
                                                f"Можно изменить: {total_set_price}\n"
                                                f"Уже подходят: {total_price_ok}\n"
                                                f"Нарушают МРЦ: {total_violation}\n"
                                                f"Нарушают minPrice: {total_min_price_violation}\n"
                                                f"Нет цены входа: {total_unknown}\n"
                                                f"Изменено цен: {total_applied}\n"
                                                f"Пропущено: {total_skipped}"
                                            ),
                                        )
                    except Exception:
                        logger.exception("auto_promo_telegram_notification_failed")

        except Exception:
            logger.exception("auto_promo_price_check_task_failed")
            try:
                await session.rollback()
            except Exception:
                pass


async def backfill_wb_daily_financial_details(ctx: dict[str, Any], payload: dict | None = None, days: int = WB_FINANCIAL_BACKFILL_DAYS) -> dict[str, Any]:
    """Backfill WB financial details for recent days.

    Re-syncs the last N days of financial data for all WB accounts.
    Useful for picking up updated/corrected report rows (выкупы, возвраты, логистика).
    """
    if days not in WB_FINANCIAL_BACKFILL_ALLOWED_PERIODS:
        raise ValueError(f"Недопустимый период дозагрузки: {days}. Допустимые значения: {WB_FINANCIAL_BACKFILL_ALLOWED_PERIODS}")
    logger.info(f"Запуск дозагрузки финансов WB за последние {days} дней")
    payload = payload or {}
    moscow_tz = ZoneInfo("Europe/Moscow")
    moscow_today = datetime.now(tz=moscow_tz).date()
    days_to_sync = days
    async with AsyncSessionFactory() as session:
        account_refs = await _load_account_refs_wb(session)
        total_accounts = len(account_refs)
        success_count = 0
        failed_count = 0
        last_error: str | None = None
        total_rows_fetched = 0
        total_rows_upserted = 0
        total_rows_matched = 0
        total_rows_unmatched = 0
        total_orders_reconciled = 0
        total_snapshots = 0
        total_pages = 0
        total_failed_rows = 0

        for ref in account_refs:
            account = await _load_account_by_id(session, ref.id)
            if account is None:
                continue
            try:
                service = WbDailyFinancialDetailService(session)
                for day_offset in range(1, days_to_sync + 1):
                    report_date = moscow_today - timedelta(days=day_offset)
                    counters = await service.sync_account_for_date(account, report_date)
                    total_rows_fetched += counters.total_rows_fetched
                    total_rows_upserted += counters.rows_upserted
                    total_rows_matched += counters.rows_matched
                    total_rows_unmatched += counters.rows_unmatched
                    total_orders_reconciled += counters.orders_reconciled
                    total_snapshots += counters.snapshots_upserted
                    total_pages += counters.pages_fetched
                    total_failed_rows += counters.failed_rows
                    if counters.errors:
                        logger.warning(
                            "wb_financial_detail_backfill_date_warnings",
                            extra={
                                "account_id": ref.id,
                                "report_date": report_date.isoformat(),
                                "errors": counters.errors[:3],
                            },
                        )
                await session.commit()
                success_count += 1
                logger.info(
                    "wb_financial_detail_backfill_account_done",
                    extra={
                        "account_id": ref.id,
                        "rows_fetched": total_rows_fetched,
                        "rows_upserted": total_rows_upserted,
                        "snapshots_upserted": total_snapshots,
                    },
                )
            except Exception as exc:
                failed_count += 1
                last_error = str(exc)[:500]
                logger.exception(
                    "wb_financial_detail_backfill_failed",
                    extra={"account_id": ref.id, "error": last_error},
                )
                try:
                    await session.rollback()
                except Exception:
                    pass
        return _task_stats(
            {
                "accounts_total": total_accounts,
                "accounts_success": success_count,
                "accounts_failed": failed_count,
                "period_days": days_to_sync,
                "pages_fetched": total_pages,
                "rows_fetched": total_rows_fetched,
                "rows_upserted": total_rows_upserted,
                "orders_linked": total_rows_matched,
                "orders_not_found": total_rows_unmatched,
                "orders_reconciled": total_orders_reconciled,
                "snapshots_upserted": total_snapshots,
                "failed_rows": total_failed_rows,
            },
            failed_count=failed_count,
            last_error=last_error,
        )


async def sync_wb_product_prices(ctx: dict[str, Any], payload: dict | None = None) -> dict[str, Any]:
    """Sync current WB product prices from /api/v2/prices into wb_product_prices table.

    Runs every 30 minutes. Fetches all current prices and upserts into wb_product_prices.
    """
    payload = payload or {}
    from app.core.security import TokenCipher
    from app.services.wb.pricing.wb_current_prices_sync_service import WbCurrentPricesSyncService

    async with AsyncSessionFactory() as session:
        service = WbCurrentPricesSyncService(session, cipher=TokenCipher())
        try:
            stats = await service.sync_all_accounts()
            await session.commit()
            logger.info(
                "wb_product_prices_sync_task_completed",
                extra={
                    "accounts_processed": stats.accounts_processed,
                    "accounts_failed": stats.accounts_failed,
                    "prices_fetched": stats.prices_fetched,
                    "prices_upserted": stats.prices_upserted,
                },
            )
            return _task_stats(
                {
                    "accounts_total": stats.accounts_processed + stats.accounts_failed,
                    "products_fetched": stats.prices_fetched,
                    "prices_updated": stats.prices_upserted,
                    "failed": stats.accounts_failed,
                },
                failed_count=stats.accounts_failed,
            )
        except Exception:
            logger.exception("wb_product_prices_sync_task_failed")
            try:
                await session.rollback()
            except Exception:
                pass
            return _task_stats(
                {
                    "accounts_total": 0,
                    "products_fetched": 0,
                    "prices_updated": 0,
                    "failed": 1,
                },
                failed_count=1,
                last_error="wb_product_prices_sync_task_failed",
            )


async def _process_wb_supplier_order(
    session: AsyncSession,
    account: MarketplaceAccount,
    order_payload: dict,
    counts: dict[str, int],
) -> None:
    from app.integrations.wb import WildberriesClient
    from app.repositories.orders import OrderRepository
    from app.services.unit_economics.order_profit_service import OrderProfitService
    from app.models.finance import ProfitSnapshot
    from app.models.enums import CalculationType
    from app.models.orders import OrderItem
    from sqlalchemy import select, delete

    normalized = WildberriesClient(api_key="").normalize_statistics_order(order_payload)
    repo = OrderRepository(session)
    order, created = await repo.upsert(account.user_id, account.id, normalized)
    counts["records_loaded"] += 1
    if created:
        counts["records_created"] += 1
    else:
        counts["records_updated"] += 1

    try:
        await session.execute(
            delete(ProfitSnapshot).where(
                ProfitSnapshot.order_item_id.in_(
                    select(OrderItem.id).where(OrderItem.order_id == order.id)
                ),
                ProfitSnapshot.calculation_type == CalculationType.ESTIMATED,
            )
        )
        profit_svc = OrderProfitService(session)
        await profit_svc.calculate_estimated_profit(
            account, order, normalized,
            calculation_source="sync_center_orders_stats",
        )
    except Exception:
        logger.exception("order_profit_recalculate_failed", extra={"order_id": order.id})


async def sync_wb_orders_stats(ctx: dict[str, Any], payload: dict | None = None) -> dict[str, Any]:
    """Sync WB orders statistics via /api/v1/supplier/orders with pagination by lastChangeDate.

    Supports manual sync with period params from Sync Center.
    For cron: processes all active WB accounts.
    """
    payload = payload or {}
    from app.core.security import TokenCipher
    from app.integrations.wb import WildberriesClient
    cipher = TokenCipher()
    counts: dict[str, int] = {
        "records_loaded": 0, "records_created": 0, "records_updated": 0,
        "records_skipped": 0, "pages_loaded": 0, "accounts_total": 0, "accounts_success": 0,
    }
    details: dict[str, Any] = {"source_api": "/api/v1/supplier/orders"}

    date_from_str = payload.get("date_from") or ctx.get("date_from")
    date_to_str = payload.get("date_to") or ctx.get("date_to")
    if date_from_str:
        details["date_from"] = date_from_str
    if date_to_str:
        details["date_to"] = date_to_str
    period_days = payload.get("period_days") or ctx.get("period_days")

    account_id = payload.get("marketplace_account_id") or ctx.get("marketplace_account_id")

    async def _process_account(account: MarketplaceAccount) -> dict[str, int]:
        ac_counts: dict[str, int] = {
            "records_loaded": 0, "records_created": 0, "records_updated": 0,
            "records_skipped": 0, "pages_loaded": 0,
        }
        try:
            api_key = cipher.decrypt(account.encrypted_api_key)
        except Exception:
            logger.exception("wb_orders_stats_decrypt_failed", extra={"account_id": account.id})
            return ac_counts

        wb_client = WildberriesClient(api_key=api_key)

        now_moscow = datetime.now(tz=MOSCOW_TZ)
        effective_from = now_moscow - timedelta(days=90)
        if date_from_str:
            try:
                effective_from = datetime.fromisoformat(date_from_str).replace(tzinfo=MOSCOW_TZ)
            except ValueError:
                effective_from = datetime.strptime(date_from_str, "%Y-%m-%d").replace(tzinfo=MOSCOW_TZ)

        pages = 0
        cursor_date = effective_from
        seen_srids: set[str] = set()
        last_cursor_str = ""

        while pages < MAX_API_PAGES:
            try:
                orders_data = await wb_client.get_supplier_orders(cursor_date)
            except Exception as exc:
                logger.error(
                    "wb_orders_stats_api_failed",
                    extra={"account_id": account.id, "cursor_date": cursor_date.isoformat(), "error": str(exc)},
                )
                break

            pages += 1
            ac_counts["pages_loaded"] = pages

            if not orders_data:
                break

            for order_payload in orders_data:
                srid = str(order_payload.get("srid") or "")
                if srid and srid in seen_srids:
                    ac_counts["records_skipped"] += 1
                    continue
                if srid:
                    seen_srids.add(srid)

                try:
                    async with AsyncSessionFactory() as write_session:
                        write_account = await _load_account_by_id(write_session, account.id)
                        if write_account is None:
                            continue
                        await _process_wb_supplier_order(write_session, write_account, order_payload, ac_counts)
                        await write_session.commit()
                except Exception as exc:
                    logger.exception(
                        "wb_orders_stats_upsert_failed",
                        extra={"account_id": account.id, "srid": srid, "error": str(exc)},
                    )
                    ac_counts["records_skipped"] += 1

            last_change = orders_data[-1].get("lastChangeDate")
            if last_change:
                cursor_str = str(last_change)
                if cursor_str == last_cursor_str:
                    logger.warning(
                        "wb_orders_stats_infinite_loop_guard",
                        extra={"account_id": account.id, "last_change": cursor_str},
                    )
                    break
                last_cursor_str = cursor_str
                try:
                    cursor_date = datetime.fromisoformat(cursor_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    cursor_date = cursor_date + timedelta(seconds=1)
            else:
                break

        return ac_counts

    if account_id:
        async with AsyncSessionFactory() as session:
            account = await _load_account_by_id(session, account_id)
            if account:
                ac_counts = await _process_account(account)
                for k in counts:
                    counts[k] += ac_counts.get(k, 0)
                counts["accounts_total"] = 1
                counts["accounts_success"] = 1 if ac_counts["records_loaded"] > 0 else 0
            else:
                logger.warning("wb_orders_stats_account_not_found", extra={"account_id": account_id})
    else:
        account_refs = await _load_account_refs(AsyncSessionFactory)
        counts["accounts_total"] = len(account_refs)
        for ref in account_refs:
            if ref.marketplace != "WB":
                continue
            async with AsyncSessionFactory() as session:
                account = await _load_account_by_id(session, ref.id)
                if account is None:
                    continue
                ac_counts = await _process_account(account)
                for k in counts:
                    counts[k] += ac_counts.get(k, 0)
                if ac_counts["records_loaded"] > 0:
                    counts["accounts_success"] += 1

    details["pages_loaded"] = counts["pages_loaded"]
    if period_days:
        details["period_days"] = period_days

    logger.info(
        "wb_orders_stats_sync_finished",
        extra={"counts": counts},
    )

    failed_count = counts["accounts_total"] - counts["accounts_success"]
    return {
        "task_stats": counts,
        "records_processed": counts["records_loaded"],
        "success_count": counts["accounts_success"],
        "failed_count": failed_count,
        "last_error": None if failed_count == 0 else "wb_orders_stats completed with failures",
        "status": "success" if failed_count == 0 else "completed_with_warnings",
    }


async def _process_wb_fbs_order(
    session: AsyncSession,
    account: MarketplaceAccount,
    order_payload: dict,
    counts: dict[str, int],
) -> None:
    from app.integrations.wb import WildberriesClient
    from app.core.security import TokenCipher
    from app.repositories.orders import OrderRepository
    from app.models.finance import ProfitSnapshot
    from app.models.enums import CalculationType
    from app.models.orders import OrderItem
    from sqlalchemy import select, delete

    normalized = WildberriesClient(api_key="").normalize_historical_fbs_order(order_payload)
    repo = OrderRepository(session)
    order, created = await repo.upsert(account.user_id, account.id, normalized)
    counts["records_loaded"] += 1
    if created:
        counts["records_created"] += 1
    else:
        counts["records_updated"] += 1

    await session.execute(
        delete(ProfitSnapshot).where(
            ProfitSnapshot.order_item_id.in_(
                select(OrderItem.id).where(OrderItem.order_id == order.id)
            ),
            ProfitSnapshot.calculation_type == CalculationType.ESTIMATED,
        )
    )
    try:
        from app.services.unit_economics.order_profit_service import OrderProfitService
        profit_svc = OrderProfitService(session)
        await profit_svc.calculate_estimated_profit(
            account, order, normalized,
            calculation_source="sync_center_fbs_assembly",
        )
    except Exception:
        logger.exception("order_profit_recalculate_failed", extra={"order_id": order.id})


async def sync_wb_fbs_assembly_orders(ctx: dict[str, Any], payload: dict | None = None) -> dict[str, Any]:
    """Sync WB FBS assembly orders via /api/v3/orders with pagination.

    Supports manual sync with period params from Sync Center.
    Splits periods >30 days into 30-day windows.
    For cron: processes all active WB accounts.
    """
    payload = payload or {}
    from app.core.security import TokenCipher
    from app.integrations.wb import WildberriesClient

    cipher = TokenCipher()
    counts: dict[str, int] = {
        "records_loaded": 0, "records_created": 0, "records_updated": 0,
        "records_skipped": 0, "pages_loaded": 0, "request_windows": 0,
        "accounts_total": 0, "accounts_success": 0,
    }
    details: dict[str, Any] = {"source_api": "/api/v3/orders"}

    date_from_str = payload.get("date_from") or ctx.get("date_from")
    date_to_str = payload.get("date_to") or ctx.get("date_to")
    if date_from_str:
        details["date_from"] = date_from_str
    if date_to_str:
        details["date_to"] = date_to_str
    period_days = payload.get("period_days") or ctx.get("period_days")

    account_id = payload.get("marketplace_account_id") or ctx.get("marketplace_account_id")

    async def _process_account(account: MarketplaceAccount) -> dict[str, int]:
        ac_counts: dict[str, int] = {
            "records_loaded": 0, "records_created": 0, "records_updated": 0,
            "records_skipped": 0, "pages_loaded": 0, "request_windows": 0,
        }
        try:
            api_key = cipher.decrypt(account.encrypted_api_key)
        except Exception:
            logger.exception("wb_fbs_assembly_decrypt_failed", extra={"account_id": account.id})
            return ac_counts

        wb_client = WildberriesClient(api_key=api_key)

        now_utc = datetime.now(tz=UTC)
        effective_from = now_utc - timedelta(days=30)
        effective_to = now_utc
        if date_from_str:
            try:
                effective_from = datetime.fromisoformat(date_from_str).replace(tzinfo=UTC)
            except ValueError:
                effective_from = datetime.strptime(date_from_str, "%Y-%m-%d").replace(tzinfo=UTC)
        if date_to_str:
            try:
                effective_to = datetime.fromisoformat(date_to_str).replace(tzinfo=UTC)
            except ValueError:
                effective_to = datetime.strptime(date_to_str, "%Y-%m-%d").replace(tzinfo=UTC)

        ws = []
        window_start = effective_from
        while window_start < effective_to:
            window_end = min(window_start + timedelta(days=30), effective_to)
            ws.append((window_start, window_end))
            window_start = window_end

        ac_counts["request_windows"] = len(ws)

        for w_start, w_end in ws:
            try:
                orders = await wb_client.get_fbs_orders(
                    date_from=w_start, date_to=w_end, limit=1000,
                )
            except Exception as exc:
                logger.error(
                    "wb_fbs_assembly_api_failed",
                    extra={
                        "account_id": account.id,
                        "date_from": w_start.isoformat(),
                        "date_to": w_end.isoformat(),
                        "error": str(exc),
                    },
                )
                continue

            ac_counts["pages_loaded"] += 1

            for order_payload in orders:
                try:
                    async with AsyncSessionFactory() as write_session:
                        write_account = await _load_account_by_id(write_session, account.id)
                        if write_account is None:
                            continue
                        await _process_wb_fbs_order(write_session, write_account, order_payload, ac_counts)
                        await write_session.commit()
                except Exception as exc:
                    logger.exception(
                        "wb_fbs_assembly_upsert_failed",
                        extra={"account_id": account.id, "order_id": order_payload.get("id"), "error": str(exc)},
                    )
                    ac_counts["records_skipped"] += 1

        return ac_counts

    if account_id:
        async with AsyncSessionFactory() as session:
            account = await _load_account_by_id(session, account_id)
            if account:
                ac_counts = await _process_account(account)
                for k in counts:
                    counts[k] += ac_counts.get(k, 0)
                counts["accounts_total"] = 1
                counts["accounts_success"] = 1 if ac_counts["records_loaded"] > 0 else 0
    else:
        account_refs = await _load_account_refs(AsyncSessionFactory)
        counts["accounts_total"] = len(account_refs)
        for ref in account_refs:
            if ref.marketplace != "WB":
                continue
            async with AsyncSessionFactory() as session:
                account = await _load_account_by_id(session, ref.id)
                if account is None:
                    continue
                ac_counts = await _process_account(account)
                for k in counts:
                    counts[k] += ac_counts.get(k, 0)
                if ac_counts["records_loaded"] > 0:
                    counts["accounts_success"] += 1

    details["pages_loaded"] = counts["pages_loaded"]
    details["request_windows"] = counts["request_windows"]
    if period_days:
        details["period_days"] = period_days

    logger.info(
        "wb_fbs_assembly_sync_finished",
        extra={"counts": counts},
    )

    failed_count = counts["accounts_total"] - counts["accounts_success"]
    return {
        "task_stats": counts,
        "records_processed": counts["records_loaded"],
        "success_count": counts["accounts_success"],
        "failed_count": failed_count,
        "last_error": None if failed_count == 0 else "wb_fbs_assembly completed with failures",
        "status": "success" if failed_count == 0 else "completed_with_warnings",
    }


async def _start_sync_run(session: AsyncSession, sync_run_id: int) -> None:
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


def _tracked_task(
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
                await _start_sync_run(session, sync_run_id)
            await session.commit()
            if sync_run_id is not None:
                await _send_sync_notification(session, sync_run_id, "start")
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
                    await _update_sync_run(
                        session, sync_run_id, "timeout",
                        error_message="Задача отменена: превышено время выполнения.",
                    )
                    await _send_sync_notification(session, sync_run_id, "finish")
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
                    await _update_sync_run(
                        session, sync_run_id, "error",
                        error_message=str(exc)[:5000],
                    )
                    await _send_sync_notification(session, sync_run_id, "finish")
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
                task_stats = result if isinstance(result, dict) else {}
                records_processed = int(task_stats.get("records_processed") or 0)
                success_count = int(task_stats.get("success_count") or 0)
                failed_count = int(task_stats.get("failed_count") or 0)
                last_error = task_stats.get("last_error")
                if "task_stats" in task_stats:
                    metadata = (
                        dict(db_run.run_metadata) if isinstance(db_run.run_metadata, dict) else {}
                    )
                    metadata["stats"] = task_stats["task_stats"]
                    db_run.run_metadata = metadata
                if task_stats.get("status") == "completed_with_warnings" or failed_count > 0:
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
                    sync_status = "warning" if (task_stats.get("status") == "completed_with_warnings" or failed_count > 0) else "success"
                    inner_stats = task_stats.get("task_stats", {})
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
                    await _update_sync_run(
                        session, sync_run_id, sync_status,
                        records_loaded=records_processed,
                        records_created=records_created_val,
                        records_updated=records_updated_val,
                        records_skipped=records_skipped,
                        error_message=last_error if sync_status == "warning" else None,
                        details=task_details or None,
                    )
                    await _send_sync_notification(session, sync_run_id, "finish")

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


async def _update_sync_run(
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


async def _send_sync_notification(session: AsyncSession, sync_run_id: int, event: str = "finish") -> None:
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


async def check_stale_sync_runs(ctx: dict[str, Any], payload: dict | None = None) -> dict[str, int]:
    payload = payload or {}
    from app.services.common.sync_status_service import SyncStatusService
    from app.services.common.web_sync_run_service import WebSyncRunService

    stats: dict[str, int] = {"sync_runs_cleaned": 0, "task_runs_cleaned": 0}
    async with AsyncSessionFactory() as session:
        sync_run_svc = WebSyncRunService(session)
        stats["sync_runs_cleaned"] = await sync_run_svc.mark_stale_syncs_as_failed()
        task_svc = SyncStatusService(session)
        stats["task_runs_cleaned"] = await task_svc.mark_stale_task_runs_failed()
        await session.commit()
    if stats["sync_runs_cleaned"] or stats["task_runs_cleaned"]:
        logger.info(
            "stale_sync_runs_cleaned",
            extra=stats,
        )
    return stats


for _task_name in (
    "poll_new_orders",
    "send_daily_reports",
    "send_alert_notifications",
    "send_fbo_digests",
    "process_history_backfills",
    "relink_wb_report_rows",
    "check_fbs_deadlines",
    "check_low_stocks",
    "sync_sale_events",
    "sync_products",
    "sync_wb_daily_sales_reports",
    "sync_ozon_catalog_enrichment",
    "sync_ozon_balances",
    "reconcile_ozon_finance",
    "sync_wb_account_profiles",
    "check_wb_financial_reports",
    "sync_wb_daily_financial_details",
    "backfill_wb_daily_financial_details",
    "reconcile_pending_payments",
    "resend_unnotified_orders",
    "sync_wb_commissions",
    "check_ozon_commission_source",
    "sync_wb_logistics_tariffs",
    "sync_wb_daily_promotions",
    "check_auto_promo_prices",
    "sync_wb_product_prices",
    "sync_wb_orders_stats",
    "sync_wb_fbs_assembly_orders",
):
    globals()[_task_name] = _tracked_task(globals()[_task_name])
