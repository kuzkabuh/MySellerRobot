"""version: 1.0.0
description: ARQ worker configuration.
updated: 2026-05-14
"""

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.workers.tasks import (
    check_fbs_deadlines,
    check_low_stocks,
    poll_new_orders,
    send_daily_reports,
)

settings = get_settings()


def _redis_settings() -> RedisSettings:
    redis_url = settings.redis_url.replace("redis://", "")
    host_port, _, database = redis_url.partition("/")
    host, _, port = host_port.partition(":")
    return RedisSettings(host=host, port=int(port or 6379), database=int(database or 0))


class WorkerSettings:
    functions = [poll_new_orders, send_daily_reports, check_fbs_deadlines, check_low_stocks]
    redis_settings = _redis_settings()
    max_jobs = 10
    job_timeout = 300
