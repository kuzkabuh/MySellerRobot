"""version: 1.1.0
description: ARQ worker configuration for polling, reports, stocks, and enrichment.
updated: 2026-05-17
"""

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.redis import redis_settings_from_url
from app.workers.tasks import (
    check_fbs_deadlines,
    check_low_stocks,
    check_ozon_commission_source,
    check_wb_financial_reports,
    poll_new_orders,
    process_history_backfills,
    reconcile_pending_payments,
    resend_unnotified_orders,
    send_alert_notifications,
    send_daily_reports,
    send_fbo_digests,
    sync_ozon_balances,
    sync_ozon_catalog_enrichment,
    sync_products,
    sync_sale_events,
    sync_wb_account_profiles,
    sync_wb_commissions,
    sync_wb_daily_financial_details,
    sync_wb_daily_promotions,
    sync_wb_daily_sales_reports,
    sync_wb_logistics_tariffs,
)

settings = get_settings()


def _redis_settings() -> RedisSettings:
    return redis_settings_from_url(settings.redis_url)


class WorkerSettings:
    functions = [
        poll_new_orders,
        send_daily_reports,
        send_alert_notifications,
        send_fbo_digests,
        process_history_backfills,
        check_fbs_deadlines,
        check_low_stocks,
        sync_sale_events,
        sync_products,
        sync_wb_daily_sales_reports,
        sync_ozon_catalog_enrichment,
        sync_ozon_balances,
        sync_wb_account_profiles,
        check_wb_financial_reports,
        sync_wb_daily_financial_details,
        reconcile_pending_payments,
        resend_unnotified_orders,
        sync_wb_commissions,
        check_ozon_commission_source,
        sync_wb_logistics_tariffs,
        sync_wb_daily_promotions,
    ]
    order_poll_minutes = {
        0,
        3,
        6,
        9,
        12,
        15,
        18,
        21,
        24,
        27,
        30,
        33,
        36,
        39,
        42,
        45,
        48,
        51,
        54,
        57,
    }
    cron_jobs = [
        cron(
            poll_new_orders,
            minute=order_poll_minutes,
        ),
        cron(send_daily_reports, hour=settings.daily_report_hour, minute=0),
        cron(send_alert_notifications, minute={1, 6, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56}),
        cron(send_fbo_digests, minute={0, 30}),
        cron(sync_sale_events, minute={5, 20, 35, 50}),
        cron(process_history_backfills, minute={2, 12, 22, 32, 42, 52}),
        cron(check_fbs_deadlines, minute={0, 15, 30, 45}),
        cron(check_low_stocks, hour={8, 14, 20}, minute=10),
        cron(sync_wb_daily_sales_reports, hour=2, minute=0),
        cron(sync_ozon_catalog_enrichment, hour=3, minute=20),
        cron(sync_ozon_balances, hour={8, 14, 20}, minute=25),
        cron(sync_wb_account_profiles, hour={7, 19}, minute=40),
        cron(check_wb_financial_reports, hour=4, minute=10),
        cron(sync_wb_daily_financial_details, hour=5, minute=0),
        cron(reconcile_pending_payments, minute={5, 25, 45}),
        cron(resend_unnotified_orders, minute={7, 22, 37, 52}),
        cron(sync_products, hour=1, minute=20),
        cron(sync_wb_commissions, hour=3, minute=10),
        cron(check_ozon_commission_source, hour=3, minute=30),
        cron(sync_wb_logistics_tariffs, hour=3, minute=50),
        cron(sync_wb_daily_promotions, minute={15, 45}),
    ]
    redis_settings = _redis_settings()
    max_jobs = 10
    job_timeout = 300
