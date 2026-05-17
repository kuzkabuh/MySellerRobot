"""version: 1.1.0
description: ARQ worker configuration for polling, reports, stocks, and enrichment.
updated: 2026-05-17
"""

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.workers.tasks import (
    check_fbs_deadlines,
    check_low_stocks,
    check_wb_financial_reports,
    poll_new_orders,
    process_history_backfills,
    send_daily_reports,
    send_fbo_digests,
    sync_ozon_catalog_enrichment,
    sync_sale_events,
    sync_wb_account_profiles,
    sync_wb_daily_sales_reports,
)

settings = get_settings()


def _redis_settings() -> RedisSettings:
    redis_url = settings.redis_url.replace("redis://", "")
    host_port, _, database = redis_url.partition("/")
    host, _, port = host_port.partition(":")
    return RedisSettings(host=host, port=int(port or 6379), database=int(database or 0))


class WorkerSettings:
    functions = [
        poll_new_orders,
        send_daily_reports,
        send_fbo_digests,
        process_history_backfills,
        check_fbs_deadlines,
        check_low_stocks,
        sync_sale_events,
        sync_wb_daily_sales_reports,
        sync_ozon_catalog_enrichment,
        sync_wb_account_profiles,
        check_wb_financial_reports,
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
        cron(send_fbo_digests, minute={0, 30}),
        cron(sync_sale_events, minute={5, 20, 35, 50}),
        cron(process_history_backfills, minute={2, 12, 22, 32, 42, 52}),
        cron(check_fbs_deadlines, minute={0, 15, 30, 45}),
        cron(check_low_stocks, hour={8, 14, 20}, minute=10),
        cron(sync_wb_daily_sales_reports, hour=2, minute=0),
        cron(sync_ozon_catalog_enrichment, hour=3, minute=20),
        cron(sync_wb_account_profiles, hour={7, 19}, minute=40),
        cron(check_wb_financial_reports, hour=4, minute=10),
    ]
    redis_settings = _redis_settings()
    max_jobs = 10
    job_timeout = 300
