"""Unit tests for web-triggered synchronization queue facade."""

from app.core.redis import redis_settings_from_url
from app.services import web_sync_service
from app.services.web_sync_service import WebSyncService


class _RedisStub:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.keys: list[str] = []

    async def set(self, key: str, value: str, *, ex: int, nx: bool):  # type: ignore[no-untyped-def]
        self.keys.append(key)
        return self.allowed


class _QueueStub:
    def __init__(self) -> None:
        self.jobs: list[str] = []
        self.closed = False

    async def enqueue_job(self, name: str) -> None:
        self.jobs.append(name)

    async def close(self) -> None:
        self.closed = True


async def test_web_sync_enqueues_known_task(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    queue = _QueueStub()

    async def create_pool(_settings):  # type: ignore[no-untyped-def]
        return queue

    monkeypatch.setattr(web_sync_service, "create_pool", create_pool)
    redis = _RedisStub(allowed=True)

    result = await WebSyncService(redis=redis).request_sync("stocks", user_id=42)

    assert result.queued is True
    assert queue.jobs == ["check_low_stocks"]
    assert queue.closed is True
    assert redis.keys == ["web-sync:42:stocks"]


async def test_web_sync_skips_recent_duplicate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    queue = _QueueStub()

    async def create_pool(_settings):  # type: ignore[no-untyped-def]
        return queue

    monkeypatch.setattr(web_sync_service, "create_pool", create_pool)

    result = await WebSyncService(redis=_RedisStub(allowed=False)).request_sync(
        "stocks",
        user_id=42,
    )

    assert result.queued is False
    assert queue.jobs == []


async def test_web_sync_enqueues_product_and_profile_tasks(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    queue = _QueueStub()

    async def create_pool(_settings):  # type: ignore[no-untyped-def]
        return queue

    monkeypatch.setattr(web_sync_service, "create_pool", create_pool)

    products = await WebSyncService(redis=_RedisStub(allowed=True)).request_sync(
        "products",
        user_id=42,
    )
    profile = await WebSyncService(redis=_RedisStub(allowed=True)).request_sync(
        "wb-profile",
        user_id=42,
    )

    assert products.queued is True
    assert profile.queued is True
    assert queue.jobs == ["sync_products", "sync_wb_account_profiles"]


def test_redis_settings_from_url_preserves_auth_and_ssl() -> None:
    settings = redis_settings_from_url("rediss://worker:secret@redis.example:6380/2")

    assert settings.host == "redis.example"
    assert settings.port == 6380
    assert settings.database == 2
    assert settings.username == "worker"
    assert settings.password == "secret"
    assert settings.ssl is True
