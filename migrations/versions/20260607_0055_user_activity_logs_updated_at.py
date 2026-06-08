"""Add updated_at to user_activity_logs.

Revision ID: 20260607_0055
Revises: 20260602_0054
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260607_0055"
down_revision: str | None = "20260602_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "user_activity_logs"
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = {c["name"]: c for c in inspector.get_columns(table)}

    if "updated_at" not in cols:
        op.add_column(table, sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        op.execute("UPDATE user_activity_logs SET updated_at = created_at WHERE updated_at IS NULL")
        op.alter_column(
            table,
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
        return

    if cols["updated_at"].get("nullable", True):
        op.execute("UPDATE user_activity_logs SET updated_at = created_at WHERE updated_at IS NULL")
        op.alter_column(
            table,
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )

    if cols["updated_at"].get("default") is None:
        op.alter_column(
            table,
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        )


def downgrade() -> None:
    table = "user_activity_logs"
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = {c["name"] for c in inspector.get_columns(table)}

    if "updated_at" in cols:
        op.drop_column(table, "updated_at")
