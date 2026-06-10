"""Add partial unique index on active sync_runs.

Revision ID: 20260610_0065
Revises: 20260610_0064
Create Date: 2026-06-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260610_0065"
down_revision: str | None = "20260610_0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_sync_runs_active_manual",
        "sync_runs",
        ["user_id", "marketplace_account_id", "marketplace", "sync_type", "trigger_source"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_sync_runs_active_manual", table_name="sync_runs")
