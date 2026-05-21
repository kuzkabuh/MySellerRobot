"""Add MRC import history tables.

Revision ID: 20260521_0033_mrc_import
Revises: 20260521_0032_mrc_feature_flag
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260521_0033_mrc_import"
down_revision: str | None = "20260521_0032_mrc_feature_flag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mrc_imports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("original_file_name", sa.String(512), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, default="preview"),
        sa.Column("total_rows", sa.Integer(), nullable=False, default=0),
        sa.Column("valid_rows", sa.Integer(), nullable=False, default=0),
        sa.Column("updated_rows", sa.Integer(), nullable=False, default=0),
        sa.Column("cleared_rows", sa.Integer(), nullable=False, default=0),
        sa.Column("skipped_rows", sa.Integer(), nullable=False, default=0),
        sa.Column("warning_rows", sa.Integer(), nullable=False, default=0),
        sa.Column("error_rows", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "mrc_import_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("mrc_imports.id", ondelete="CASCADE"), nullable=False, index=True),
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
    )

    op.create_index("ix_mrc_import_rows_import_id", "mrc_import_rows", ["import_id"])


def downgrade() -> None:
    op.drop_table("mrc_import_rows")
    op.drop_table("mrc_imports")
