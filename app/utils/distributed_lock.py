"""version: 1.0.0
description: Reusable distributed lock manager for Redis.
updated: 2026-06-08
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import uuid4

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class DistributedLock:
    """Redis-based distributed lock with automatic cleanup."""

    def __init__(
        self,
        redis: Redis,
        key: str,
        ttl_seconds: int = 300,
        retry_delay_seconds: float = 1.0,
        max_retries: int = 0,
        cooldown_seconds: int = 0,
    ) -> None:
        """
        Args:
            redis: Redis client instance
            key: Lock key name
            ttl_seconds: Lock TTL in seconds (default 5 minutes)
            retry_delay_seconds: Delay between acquisition retries
            max_retries: Max number of retries (0 = no retries)
            cooldown_seconds: Cooldown period between lock acquisitions (0 = no cooldown)
        """
        self.redis = redis
        self.key = key
        self.ttl_seconds = ttl_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self.max_retries = max_retries
        self.cooldown_seconds = cooldown_seconds
        self._token: str | None = None
        self._cooldown_key = f"{key}:cooldown" if cooldown_seconds > 0 else None

    async def acquire(self) -> bool:
        """Try to acquire the lock.

        Returns:
            True if lock acquired, False otherwise
        """
        # Check cooldown period
        if self._cooldown_key:
            last_acquisition = await self.redis.get(self._cooldown_key)
            if last_acquisition:
                elapsed = int(time.time()) - int(last_acquisition)
                if elapsed < self.cooldown_seconds:
                    logger.debug(
                        f"Lock in cooldown: {self.key}, remaining: {self.cooldown_seconds - elapsed}s"
                    )
                    return False

        self._token = uuid4().hex
        attempts = 0

        while attempts <= self.max_retries:
            acquired = await self.redis.set(
                self.key,
                self._token,
                ex=self.ttl_seconds,
                nx=True,
            )

            if acquired:
                # Set cooldown timestamp
                if self._cooldown_key:
                    await self.redis.set(
                        self._cooldown_key,
                        str(int(time.time())),
                        ex=self.cooldown_seconds * 2,
                    )
                logger.debug(f"Lock acquired: {self.key}")
                return True

            attempts += 1
            if attempts <= self.max_retries:
                await asyncio.sleep(self.retry_delay_seconds)

        logger.debug(f"Failed to acquire lock: {self.key}")
        return False

    async def release(self) -> bool:
        """Release the lock if we own it.

        Returns:
            True if lock released, False if we didn't own it
        """
        if not self._token:
            return False

        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """

        result = await self.redis.eval(lua_script, 1, self.key, self._token)
        released = bool(result)

        if released:
            logger.debug(f"Lock released: {self.key}")
        else:
            logger.warning(f"Lock not owned or already expired: {self.key}")

        self._token = None
        return released

    async def is_locked(self) -> bool:
        """Check if the lock exists (by anyone).

        Returns:
            True if lock exists, False otherwise
        """
        exists = await self.redis.exists(self.key)
        return bool(exists)

    async def extend(self, additional_seconds: int) -> bool:
        """Extend lock TTL if we own it.

        Args:
            additional_seconds: Seconds to add to current TTL

        Returns:
            True if extended, False if we don't own the lock
        """
        if not self._token:
            return False

        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            local ttl = redis.call("ttl", KEYS[1])
            if ttl > 0 then
                return redis.call("expire", KEYS[1], ttl + tonumber(ARGV[2]))
            end
        end
        return 0
        """

        result = await self.redis.eval(
            lua_script,
            1,
            self.key,
            self._token,
            additional_seconds,
        )
        return bool(result)

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[bool]:
        """Context manager interface.

        Yields:
            True if lock acquired, False otherwise

        Example:
            async with DistributedLock(redis, "my-lock") as acquired:
                if not acquired:
                    return
                # Do work with lock held
        """
        acquired = await self.acquire()
        try:
            yield acquired
        finally:
            if acquired:
                await self.release()


@asynccontextmanager
async def distributed_lock(
    redis: Redis,
    key: str,
    ttl_seconds: int = 300,
    retry_delay_seconds: float = 1.0,
    max_retries: int = 0,
    cooldown_seconds: int = 0,
) -> AsyncIterator[bool]:
    """Convenience context manager for distributed locks.

    Args:
        redis: Redis client instance
        key: Lock key name
        ttl_seconds: Lock TTL in seconds (default 5 minutes)
        retry_delay_seconds: Delay between acquisition retries
        max_retries: Max number of retries (0 = no retries)
        cooldown_seconds: Cooldown period between lock acquisitions (0 = no cooldown)

    Yields:
        True if lock acquired, False otherwise

    Example:
        async with distributed_lock(redis, "sync:user:123") as acquired:
            if not acquired:
                logger.info("Already syncing")
                return
            # Do work with lock held
    """
    lock = DistributedLock(
        redis, key, ttl_seconds, retry_delay_seconds, max_retries, cooldown_seconds
    )
    async with lock() as acquired:
        yield acquired
