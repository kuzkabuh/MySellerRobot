"""Add missing updated_at column to mrc_imports and mrc_import_rows.

Both models inherit TimestampMixin which provides updated_at,
but the column may be missing in existing databases if the initial
migration was applied before the column was added to the schema.

Revision ID: 20260522_0001_fix_mrc_imports_updated_at
Revises: 20260521_0033_mrc_import
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260522_0001_fix_mrc_imports_updated_at"
down_revision: str | None = "20260521_0033_mrc_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    for table in ("mrc_imports", "mrc_import_rows"):
        cols = {c["name"] for c in inspector.get_columns(table)}
        if "updated_at" not in cols:
            op.add_column(
                table,
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            )
            op.execute(f"UPDATE {table} SET updated_at = created_at WHERE updated_at IS NULL")
            op.alter_column(table, "updated_at", nullable=False, server_default=sa.func.now())
        else:
            # Column exists — ensure NOT NULL and server_default
            col_info = [c for c in inspector.get_columns(table) if c["name"] == "updated_at"][0]
            if col_info.get("nullable", True):
                op.execute(f"UPDATE {table} SET updated_at = created_at WHERE updated_at IS NULL")
                op.alter_column(table, "updated_at", nullable=False)
            if col_info.get("default") is None:
                op.alter_column(table, "updated_at", server_default=sa.func.now())


def downgrade() -> None:
    for table in ("mrc_imports", "mrc_import_rows"):
        op.drop_column(table, "updated_at")
