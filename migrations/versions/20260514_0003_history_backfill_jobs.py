"""history backfill jobs

version: 1.0.0
description: Extend sync_jobs for initial and manual historical marketplace backfills.
updated: 2026-05-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260514_0003"
down_revision: str | None = "20260514_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for value in ["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED"]:
        op.execute(f"ALTER TYPE syncjobstatus ADD VALUE IF NOT EXISTS '{value}'")

    marketplace = postgresql.ENUM("WB", "OZON", name="marketplace", create_type=False)
    op.add_column("sync_jobs", sa.Column("marketplace", marketplace, nullable=True))
    op.add_column("sync_jobs", sa.Column("date_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sync_jobs", sa.Column("date_to", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "sync_jobs",
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sync_jobs",
        sa.Column("processed_chunks", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sync_jobs",
        sa.Column("total_chunks", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sync_jobs",
        sa.Column("records_loaded", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sync_jobs",
        sa.Column("records_skipped", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sync_jobs",
        sa.Column("records_failed", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("sync_jobs", sa.Column("metadata", postgresql.JSONB(), nullable=True))
    op.create_index(
        "ix_sync_jobs_period",
        "sync_jobs",
        ["marketplace_account_id", "date_from", "date_to"],
    )
    op.execute("UPDATE sync_jobs SET metadata = '{}'::jsonb WHERE metadata IS NULL")
    op.alter_column("sync_jobs", "metadata", nullable=False)


def downgrade() -> None:
    op.drop_index("ix_sync_jobs_period", table_name="sync_jobs")
    for column in [
        "metadata",
        "records_failed",
        "records_skipped",
        "records_loaded",
        "total_chunks",
        "processed_chunks",
        "progress_percent",
        "date_to",
        "date_from",
        "marketplace",
    ]:
        op.drop_column("sync_jobs", column)
    # PostgreSQL does not support dropping individual enum values safely.
