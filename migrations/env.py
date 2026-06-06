"""version: 1.0.0
description: Alembic async migration environment.
updated: 2026-05-14
"""

from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", get_settings().database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def ensure_alembic_version_table(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        return

    connection.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(255) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            ALTER TABLE alembic_version
            ALTER COLUMN version_num TYPE VARCHAR(255)
            """
        )
    )


def do_run_migrations(connection: Connection) -> None:
    with connection.begin():
        ensure_alembic_version_table(connection)
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table="alembic_version",
        version_table_pk=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio

    asyncio.run(run_migrations_online())
