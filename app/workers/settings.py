"""version: 1.0.0
description: ARQ worker configuration.
updated: 2026-05-14
"""

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.workers.tasks import (
    check_fbs_deadlines,
    check_low_stocks,
    poll_new_orders,
    process_history_backfills,
    send_daily_reports,
    send_fbo_digests,
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
        cron(process_history_backfills, minute={2, 12, 22, 32, 42, 52}),
        cron(check_fbs_deadlines, minute={0, 15, 30, 45}),
        cron(check_low_stocks, hour={8, 14, 20}, minute=10),
    ]
    redis_settings = _redis_settings()
    max_jobs = 10
    job_timeout = 300
