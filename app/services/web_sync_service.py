"""Queue marketplace synchronization tasks requested from the web cabinet."""

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from arq.connections import RedisSettings, create_pool
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.redis import redis_settings_from_url


class WebSyncType(StrEnum):
    ORDERS = "orders"
    SALES = "sales"
    STOCKS = "stocks"
    PRODUCTS = "products"
    WB_PROFILE = "wb-profile"
    WB_REPORTS = "wb-reports"
    OZON_ENRICHMENT = "ozon-enrichment"


@dataclass(frozen=True, slots=True)
class WebSyncRequestResult:
    queued: bool
    message: str


SYNC_TASKS: dict[WebSyncType, tuple[str, str]] = {
    WebSyncType.ORDERS: ("poll_new_orders", "Синхронизация заказов поставлена в очередь."),
    WebSyncType.SALES: ("sync_sale_events", "Синхронизация продаж поставлена в очередь."),
    WebSyncType.STOCKS: ("check_low_stocks", "Синхронизация остатков поставлена в очередь."),
    WebSyncType.PRODUCTS: ("sync_products", "Синхронизация товаров поставлена в очередь."),
    WebSyncType.WB_PROFILE: (
        "sync_wb_account_profiles",
        "Обновление продавца и баланса WB поставлено в очередь.",
    ),
    WebSyncType.WB_REPORTS: (
        "check_wb_financial_reports",
        "Проверка финансовых отчётов WB поставлена в очередь.",
    ),
    WebSyncType.OZON_ENRICHMENT: (
        "sync_ozon_catalog_enrichment",
        "Обновление каталога Ozon поставлено в очередь.",
    ),
}


class WebSyncService:
    """Keep web routes away from worker queue details."""

    def __init__(self, redis: Redis | None = None) -> None:
        self.redis = redis

    async def request_sync(self, sync_type: str, user_id: int) -> WebSyncRequestResult:
        parsed = _parse_sync_type(sync_type)
        if parsed is None or parsed not in SYNC_TASKS:
            return WebSyncRequestResult(queued=False, message="Неизвестный тип синхронизации.")

        redis = self.redis or _redis()
        owns_redis = self.redis is None
        try:
            was_set = await redis.set(f"web-sync:{user_id}:{parsed.value}", "1", ex=120, nx=True)
            if not was_set:
                return WebSyncRequestResult(
                    queued=False,
                    message="Такая синхронизация уже недавно запускалась. Подождите пару минут.",
                )
        finally:
            if owns_redis:
                await redis.aclose()

        task_name, message = SYNC_TASKS[parsed]
        queue = await create_pool(_redis_settings())
        await queue.enqueue_job(task_name)
        await queue.close()
        return WebSyncRequestResult(queued=True, message=message)


def _redis() -> Redis:
    return cast(
        Redis,
        Redis.from_url(get_settings().redis_url, encoding="utf-8", decode_responses=True),
    )


def _redis_settings() -> RedisSettings:
    return redis_settings_from_url(get_settings().redis_url)


def _parse_sync_type(value: str) -> WebSyncType | None:
    try:
        return WebSyncType(value)
    except ValueError:
        return None
