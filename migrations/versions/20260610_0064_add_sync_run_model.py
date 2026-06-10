"""Add SyncRun model for sync run history.

Revision ID: 20260610_0064
Revises: 20260610_0063
Create Date: 2026-06-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260610_0064"
down_revision: str | None = "20260610_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column(
            "marketplace_account_id",
            sa.Integer(),
            sa.ForeignKey("marketplace_accounts.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("marketplace", sa.String(16), nullable=False, index=True),
        sa.Column("sync_type", sa.String(64), nullable=False, index=True),
        sa.Column("trigger_source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("status", sa.String(32), nullable=False, index=True, server_default=sa.text("'queued'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Numeric(10, 2), nullable=True),
        sa.Column("records_loaded", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("records_created", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("records_updated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("records_skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sync_runs_account_started",
        "sync_runs",
        ["marketplace_account_id", "started_at"],
    )
    op.create_index(
        "ix_sync_runs_status_started",
        "sync_runs",
        ["status", "started_at"],
    )
    op.create_index(
        "ix_sync_runs_user_triggered",
        "sync_runs",
        ["user_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sync_runs_account_started", table_name="sync_runs")
    op.drop_index("ix_sync_runs_status_started", table_name="sync_runs")
    op.drop_index("ix_sync_runs_user_triggered", table_name="sync_runs")
    op.drop_table("sync_runs")
