"""version: 1.0.1
description: Redis-based caching utilities with TTL support.
updated: 2026-05-15
"""

import json
import logging
from collections.abc import Callable
from typing import Any, TypeVar, cast

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CacheManager:
    """Async Redis cache manager with JSON serialization."""

    def __init__(self, redis_client: Redis | None = None) -> None:
        self.redis = redis_client

    async def get_redis(self) -> Redis:
        """Get or create Redis connection."""
        if self.redis is None:
            settings = get_settings()
            self.redis = cast(
                Redis,
                await aioredis.from_url(  # type: ignore[no-untyped-call]
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                ),
            )
        return self.redis

    async def get(self, key: str) -> Any | None:
        """Get value from cache."""
        try:
            redis = await self.get_redis()
            value = await redis.get(key)
            if value is None:
                return None
            return json.loads(value)
        except Exception as exc:
            logger.warning("cache_get_failed", extra={"key": key, "error": str(exc)})
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set value in cache with optional TTL in seconds."""
        try:
            redis = await self.get_redis()
            serialized = json.dumps(value, default=str)
            if ttl:
                await redis.setex(key, ttl, serialized)
            else:
                await redis.set(key, serialized)
            return True
        except Exception as exc:
            logger.warning("cache_set_failed", extra={"key": key, "error": str(exc)})
            return False

    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        try:
            redis = await self.get_redis()
            await redis.delete(key)
            return True
        except Exception as exc:
            logger.warning("cache_delete_failed", extra={"key": key, "error": str(exc)})
            return False

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        try:
            redis = await self.get_redis()
            return bool(await redis.exists(key))
        except Exception as exc:
            logger.warning("cache_exists_failed", extra={"key": key, "error": str(exc)})
            return False

    async def clear_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern."""
        try:
            redis = await self.get_redis()
            keys = []
            async for key in redis.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                return int(await redis.delete(*keys))
            return 0
        except Exception as exc:
            logger.warning(
                "cache_clear_pattern_failed",
                extra={"pattern": pattern, "error": str(exc)},
            )
            return 0

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl: int | None = None,
    ) -> Any:
        """Get value from cache or compute and cache it."""
        cached = await self.get(key)
        if cached is not None:
            return cached

        value = factory() if not callable(factory) else await factory()
        await self.set(key, value, ttl)
        return value

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()


_cache_manager: CacheManager | None = None


def get_cache_manager() -> CacheManager:
    """Get global cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager


def cache_key(*parts: str | int) -> str:
    """Build cache key from parts."""
    return ":".join(str(p) for p in parts)
