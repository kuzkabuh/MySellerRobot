"""Add MRC import history tables.

Revision ID: 20260521_0033_mrc_import
Revises: 20260521_0032_mrc_feature_flag
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260521_0033_mrc_import"
down_revision: str | None = "20260521_0032_mrc_feature_flag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    # Create mrc_imports table if it doesn't exist
    if "mrc_imports" not in existing_tables:
        op.create_table(
            "mrc_imports",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=True),
            sa.Column("source", sa.String(16), nullable=False),
            sa.Column("original_file_name", sa.String(512), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="preview"),
            sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cleared_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("warning_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_text", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    else:
        # Table exists but may be missing columns from partial run
        mrc_imports_cols = {col["name"] for col in inspector.get_columns("mrc_imports")}
        if "updated_at" not in mrc_imports_cols:
            op.execute(
                "ALTER TABLE mrc_imports ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
            )

    # Create mrc_import_rows table if it doesn't exist
    if "mrc_import_rows" not in existing_tables:
        op.create_table(
            "mrc_import_rows",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("import_id", sa.Integer(), sa.ForeignKey("mrc_imports.id", ondelete="CASCADE"), nullable=False),
            sa.Column("row_number", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=True),
            sa.Column("wb_nm_id", sa.Integer(), nullable=True),
            sa.Column("seller_sku", sa.String(255), nullable=True),
            sa.Column("product_name", sa.String(512), nullable=True),
            sa.Column("old_mrc_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("new_mrc_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("status", sa.String(64), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    else:
        # Table exists but may be missing columns from partial run
        mrc_import_rows_cols = {col["name"] for col in inspector.get_columns("mrc_import_rows")}
        if "updated_at" not in mrc_import_rows_cols:
            op.execute(
                "ALTER TABLE mrc_import_rows ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
            )

    # Create indexes explicitly (only if they don't exist)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("mrc_imports")} | \
                       {idx["name"] for idx in inspector.get_indexes("mrc_import_rows")}

    if "ix_mrc_imports_user_id" not in existing_indexes:
        op.create_index("ix_mrc_imports_user_id", "mrc_imports", ["user_id"])

    if "ix_mrc_imports_account_id" not in existing_indexes:
        op.create_index("ix_mrc_imports_account_id", "mrc_imports", ["account_id"])

    if "ix_mrc_import_rows_import_id" not in existing_indexes:
        op.create_index("ix_mrc_import_rows_import_id", "mrc_import_rows", ["import_id"])


def downgrade() -> None:
    op.drop_table("mrc_import_rows")
    op.drop_table("mrc_imports")
