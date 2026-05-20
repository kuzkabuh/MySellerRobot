"""version: 1.6.0
description: ARQ tasks for sync, Ozon enrichment, WB daily sales, reports, and alerts.
updated: 2026-05-20
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
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
from app.services.ozon_balance_service import OzonBalanceService
from app.services.ozon_catalog_enrichment_service import OzonCatalogEnrichmentService
from app.services.product_sync_service import ProductSyncService
from app.services.sales_event_sync_service import (
    OrderLifecycleNotification,
    SaleNotification,
    SalesEventSyncService,
)
from app.services.stock_service import StockService
from app.services.wb_daily_financial_detail_service import WbDailyFinancialDetailService
from app.services.wb_report_service import WbFinancialReportService

logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

_PERMANENT_FAILURE_TYPES = (TelegramForbiddenError,)


@dataclass(slots=True)
class AccountRef:
    """Plain-data snapshot of a MarketplaceAccount to avoid expired-ORM issues after rollback."""

    id: int
    marketplace: str
    user_id: int


async def _load_account_refs(async_session_factory) -> list[AccountRef]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(
                MarketplaceAccount.id,
                MarketplaceAccount.marketplace,
                MarketplaceAccount.user_id,
            )
            .where(MarketplaceAccount.is_active.is_(True))
        )
        return [
            AccountRef(id=row[0], marketplace=row[1].value, user_id=row[2])
            for row in result.all()
        ]


async def _load_account_by_id(session: AsyncSession, account_id: int) -> MarketplaceAccount | None:
    result = await session.execute(
        select(MarketplaceAccount)
        .options(selectinload(MarketplaceAccount.user))
        .where(MarketplaceAccount.id == account_id)
    )
    return result.scalar_one_or_none()


async def poll_new_orders(ctx: dict[str, Any]) -> None:
    """Poll active marketplace accounts and store unseen orders."""

    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
    notifier = NotificationService(bot)
    account_refs = await _load_account_refs(AsyncSessionFactory)
    logger.info("order_poll_started", extra={"accounts": len(account_refs)})
    for ref in account_refs:
        try:
            async with AsyncSessionFactory() as session:
                account = await _load_account_by_id(session, ref.id)
                if account is None:
                    continue
                poll_result = await OrderProcessingService(session).poll_account_with_stats(account)
                sent, failed = await _deliver_new_order_notifications(
                    session,
                    notifier,
                    poll_result.notifications or [],
                )
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
            logger.exception(
                "marketplace_poll_failed",
                extra={
                    "account_id": ref.id,
                    "marketplace": ref.marketplace,
                    "user_id": ref.user_id,
                },
            )
    await bot.session.close()


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


async def send_daily_reports(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
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


async def sync_sale_events(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
    notifier = NotificationService(bot)
    account_refs = await _load_account_refs(AsyncSessionFactory)
    logger.info("sale_events_sync_started", extra={"accounts": len(account_refs)})
    for ref in account_refs:
        try:
            async with AsyncSessionFactory() as session:
                account = await _load_account_by_id(session, ref.id)
                if account is None:
                    continue
                service = SalesEventSyncService(session)
                sync_result = await service.sync_account(account)
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
                order_notifications = (
                    await OrderProcessingService(session).collect_saved_unnotified_notifications(
                        account
                    )
                )
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
        lifecycle_notifications = (
            await sale_service.pending_order_lifecycle_notifications(limit=100)
        )
        await _deliver_order_lifecycle_notifications(
            session,
            sale_service,
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


async def resend_unnotified_orders(ctx: dict[str, Any]) -> None:
    """Recovery task: deliver saved FBS-like orders with first_notified_at IS NULL.

    Runs independently of API polling to catch orders that were persisted
    but never notified due to polling failures or worker crashes.
    """
    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
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
    await bot.session.close()


async def sync_wb_daily_sales_reports(ctx: dict[str, Any]) -> None:
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


async def sync_wb_account_profiles(ctx: dict[str, Any]) -> None:
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


async def check_wb_financial_reports(ctx: dict[str, Any]) -> None:
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


async def sync_wb_daily_financial_details(ctx: dict[str, Any]) -> None:
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


async def sync_ozon_catalog_enrichment(ctx: dict[str, Any]) -> None:
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


async def sync_ozon_balances(ctx: dict[str, Any]) -> None:
    """Sync Ozon account balances via POST /v1/finance/balance."""
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


async def sync_products(ctx: dict[str, Any]) -> None:
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


async def check_low_stocks(ctx: dict[str, Any]) -> None:
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


async def process_history_backfills(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())
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
    await bot.session.close()


async def reconcile_pending_payments(ctx: dict[str, Any]) -> None:
    """Check PENDING YooKassa payments against the API and update status."""
    from app.services.payment_service import PaymentService

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
    return [
        AccountRef(id=row[0], marketplace=row[1].value, user_id=row[2])
        for row in result.all()
    ]


async def _load_account_refs_ozon(session: AsyncSession) -> list[AccountRef]:
    result = await session.execute(
        select(MarketplaceAccount.id, MarketplaceAccount.marketplace, MarketplaceAccount.user_id)
        .where(MarketplaceAccount.is_active.is_(True))
        .where(MarketplaceAccount.marketplace == Marketplace.OZON)
    )
    return [
        AccountRef(id=row[0], marketplace=row[1].value, user_id=row[2])
        for row in result.all()
    ]


async def sync_wb_commissions(ctx: dict[str, Any]) -> None:
    """Daily sync of WB commission tariffs from the official API."""
    from app.core.config import get_settings
    from app.services.commission_tariffs.admin_notifications import (
        format_wb_sync_notification,
        notify_admins,
    )
    from app.services.commission_tariffs.wb_commission_sync_service import WbCommissionSyncService

    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())

    async with AsyncSessionFactory() as session:
        account_refs = await _load_account_refs_wb(session)
        if not account_refs:
            logger.info("wb_commission_sync_no_accounts")
            await bot.session.close()
            return

        ref = account_refs[0]
        account = await _load_account_by_id(session, ref.id)
        if account is None:
            await bot.session.close()
            return

        from app.core.security import TokenCipher

        try:
            api_key = TokenCipher().decrypt(account.encrypted_api_key)
        except Exception:
            logger.exception("wb_commission_sync_decrypt_failed")
            await bot.session.close()
            return

        service = WbCommissionSyncService(session)
        result = await service.sync(api_key)

        notification = format_wb_sync_notification(result)
        if result.get("changed") or not result.get("success"):
            await notify_admins(bot, notification)

    await bot.session.close()


async def check_ozon_commission_source(ctx: dict[str, Any]) -> None:
    """Daily check of the Ozon commissions page for new tariff tables."""
    from app.core.config import get_settings
    from app.services.commission_tariffs.admin_notifications import (
        format_ozon_monitor_notification,
        notify_admins,
    )
    from app.services.commission_tariffs.ozon_commission_source_monitor_service import (
        OzonCommissionSourceMonitorService,
    )

    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())

    async with AsyncSessionFactory() as session:
        service = OzonCommissionSourceMonitorService(session)
        result = await service.check()

        notification = format_ozon_monitor_notification(result)
        if notification:
            await notify_admins(bot, notification)

    await bot.session.close()


async def sync_wb_logistics_tariffs(ctx: dict[str, Any]) -> None:
    """Daily sync of WB box delivery logistics tariffs from /api/v1/tariffs/box."""
    from app.core.config import get_settings
    from app.services.commission_tariffs.admin_notifications import notify_admins
    from app.services.wb_logistics.wb_logistics_tariff_sync_service import (
        WbLogisticsTariffSyncService,
    )

    settings = get_settings()
    bot = Bot(settings.bot_token.get_secret_value())

    async with AsyncSessionFactory() as session:
        account_refs = await _load_account_refs_wb(session)
        if not account_refs:
            logger.info("wb_logistics_sync_no_accounts")
            await bot.session.close()
            return

        ref = account_refs[0]
        account = await _load_account_by_id(session, ref.id)
        if account is None:
            await bot.session.close()
            return

        from app.core.security import TokenCipher

        try:
            api_key = TokenCipher().decrypt(account.encrypted_api_key)
        except Exception:
            logger.exception("wb_logistics_sync_decrypt_failed")
            await bot.session.close()
            return

        from app.integrations.wb import WildberriesClient

        wb_client = WildberriesClient(api_key=api_key)
        service = WbLogisticsTariffSyncService(session, wb_client)
        result = await service.sync()

        status_emoji = {"new_version": "✅", "no_changes": "ℹ️", "error": "❌"}.get(
            result["status"], "❓"
        )
        message = f"{status_emoji} Логистика WB: {result['message']}"

        if result["status"] in ("new_version", "error"):
            await notify_admins(bot, message)

    await bot.session.close()
