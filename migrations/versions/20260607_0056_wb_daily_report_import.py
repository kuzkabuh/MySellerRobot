"""Add WB daily realisation report import tables.

Revision ID: 20260607_0056
Revises: 20260607_0055
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260607_0056"
down_revision: str | None = "20260607_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wb_daily_report_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "marketplace_account_id",
            sa.Integer(),
            sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=16), nullable=False, server_default="file"),
        sa.Column("original_filename", sa.String(length=512), nullable=True),
        sa.Column("report_number", sa.String(length=128), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=True),
        sa.Column("file_hash", sa.String(length=128), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_wb_daily_report_imports_user", "wb_daily_report_imports", ["user_id"]
    )
    op.create_index(
        "ix_wb_daily_report_imports_account",
        "wb_daily_report_imports",
        ["marketplace_account_id"],
    )
    op.create_index(
        "ix_wb_daily_report_imports_created", "wb_daily_report_imports", ["created_at"]
    )
    op.create_index(
        "ix_wb_daily_report_imports_report_number",
        "wb_daily_report_imports",
        ["report_number"],
    )
    op.create_index(
        "ix_wb_daily_report_imports_file_hash",
        "wb_daily_report_imports",
        ["file_hash"],
    )

    op.create_table(
        "wb_daily_report_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "import_id",
            sa.Integer(),
            sa.ForeignKey("wb_daily_report_imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "marketplace_account_id",
            sa.Integer(),
            sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_number", sa.String(length=128), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("sale_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nm_id", sa.BigInteger(), nullable=True),
        sa.Column("supplier_article", sa.String(length=255), nullable=True),
        sa.Column("barcode", sa.String(length=64), nullable=True),
        sa.Column("doc_type_name", sa.String(length=128), nullable=True),
        sa.Column("subject_name", sa.String(length=255), nullable=True),
        sa.Column("brand_name", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("retail_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("retail_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("for_pay", sa.Numeric(14, 2), nullable=True),
        sa.Column("delivery_rub", sa.Numeric(14, 2), nullable=True),
        sa.Column("penalty", sa.Numeric(14, 2), nullable=True),
        sa.Column("storage_fee", sa.Numeric(14, 2), nullable=True),
        sa.Column("acceptance", sa.Numeric(14, 2), nullable=True),
        sa.Column("deduction", sa.Numeric(14, 2), nullable=True),
        sa.Column("raw_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "marketplace_account_id",
            "report_number",
            "row_hash",
            name="ux_wb_daily_report_row_dedupe",
        ),
    )
    op.create_index("ix_wb_daily_report_rows_user", "wb_daily_report_rows", ["user_id"])
    op.create_index(
        "ix_wb_daily_report_rows_account", "wb_daily_report_rows", ["marketplace_account_id"]
    )
    op.create_index("ix_wb_daily_report_rows_import", "wb_daily_report_rows", ["import_id"])
    op.create_index("ix_wb_daily_report_rows_sale_dt", "wb_daily_report_rows", ["sale_dt"])
    op.create_index("ix_wb_daily_report_rows_order_dt", "wb_daily_report_rows", ["order_dt"])
    op.create_index(
        "ix_wb_daily_report_rows_report_number",
        "wb_daily_report_rows",
        ["report_number"],
    )
    op.create_index("ix_wb_daily_report_rows_row_hash", "wb_daily_report_rows", ["row_hash"])
    op.create_index("ix_wb_daily_report_rows_nm_id", "wb_daily_report_rows", ["nm_id"])


def downgrade() -> None:
    op.drop_index("ix_wb_daily_report_rows_nm_id", table_name="wb_daily_report_rows")
    op.drop_index("ix_wb_daily_report_rows_row_hash", table_name="wb_daily_report_rows")
    op.drop_index(
        "ix_wb_daily_report_rows_report_number", table_name="wb_daily_report_rows"
    )
    op.drop_index("ix_wb_daily_report_rows_order_dt", table_name="wb_daily_report_rows")
    op.drop_index("ix_wb_daily_report_rows_sale_dt", table_name="wb_daily_report_rows")
    op.drop_index("ix_wb_daily_report_rows_import", table_name="wb_daily_report_rows")
    op.drop_index("ix_wb_daily_report_rows_account", table_name="wb_daily_report_rows")
    op.drop_index("ix_wb_daily_report_rows_user", table_name="wb_daily_report_rows")
    op.drop_table("wb_daily_report_rows")

    op.drop_index(
        "ix_wb_daily_report_imports_file_hash", table_name="wb_daily_report_imports"
    )
    op.drop_index(
        "ix_wb_daily_report_imports_report_number", table_name="wb_daily_report_imports"
    )
    op.drop_index(
        "ix_wb_daily_report_imports_created", table_name="wb_daily_report_imports"
    )
    op.drop_index(
        "ix_wb_daily_report_imports_account", table_name="wb_daily_report_imports"
    )
    op.drop_index("ix_wb_daily_report_imports_user", table_name="wb_daily_report_imports")
    op.drop_table("wb_daily_report_imports")
