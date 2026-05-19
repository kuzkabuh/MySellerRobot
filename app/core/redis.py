"""Redis connection helpers shared by ARQ workers and web-triggered jobs."""

from urllib.parse import urlparse

from arq.connections import RedisSettings


def redis_settings_from_url(redis_url: str) -> RedisSettings:
    """Convert a Redis URL into ARQ RedisSettings."""

    parsed = urlparse(redis_url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise ValueError("REDIS_URL must use redis:// or rediss://")

    database = 0
    if parsed.path and parsed.path != "/":
        database = int(parsed.path.lstrip("/") or "0")

    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=database,
        username=parsed.username,
        password=parsed.password,
        ssl=parsed.scheme == "rediss",
    )
