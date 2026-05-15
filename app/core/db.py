"""version: 1.1.0
description: Enhanced SQLAlchemy async engine with connection pooling and monitoring.
updated: 2026-05-15
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Configure engine with optimized pool settings
engine_kwargs: dict[str, Any] = {
    "pool_pre_ping": True,
    "echo": settings.app_debug,
}

if settings.app_env == "test":
    engine_kwargs["poolclass"] = NullPool
else:
    # For async engines, pool settings are passed directly, not via poolclass
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20
    engine_kwargs["pool_timeout"] = 30
    engine_kwargs["pool_recycle"] = 3600

engine = create_async_engine(settings.database_url, **engine_kwargs)

AsyncSessionFactory = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


@event.listens_for(engine.sync_engine, "connect")
def receive_connect(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
    """Log database connections."""
    logger.debug("database_connection_established")


@event.listens_for(engine.sync_engine, "close")
def receive_close(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
    """Log database disconnections."""
    logger.debug("database_connection_closed")


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async database session."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_session_context() -> AsyncIterator[AsyncSession]:
    """Context manager for database session."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db() -> None:
    """Close database engine and connections."""
    await engine.dispose()
    logger.info("database_connections_closed")
