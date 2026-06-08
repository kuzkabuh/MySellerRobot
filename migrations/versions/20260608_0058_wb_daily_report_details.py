"""Add WB daily report detail fields and row processing log.

Revision ID: 20260608_0058
Revises: 20260607_0057
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260608_0058"
down_revision: str | None = "20260607_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("wb_daily_report_rows", sa.Column("srid", sa.String(255), nullable=True))
    op.add_column(
        "wb_daily_report_rows",
        sa.Column(
            "linked_order_id",
            sa.Integer(),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "wb_daily_report_rows",
        sa.Column(
            "linked_product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "wb_daily_report_rows", sa.Column("commission_rub", sa.Numeric(14, 2), nullable=True)
    )
    op.add_column(
        "wb_daily_report_rows",
        sa.Column("row_status", sa.String(24), nullable=False, server_default="new"),
    )
    op.add_column("wb_daily_report_rows", sa.Column("skip_reason", sa.String(255), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("error_message", sa.Text(), nullable=True))
    op.create_index("ix_wb_daily_report_rows_barcode", "wb_daily_report_rows", ["barcode"])
    op.create_index("ix_wb_daily_report_rows_srid", "wb_daily_report_rows", ["srid"])
    op.create_index("ix_wb_daily_report_rows_status", "wb_daily_report_rows", ["row_status"])

    op.create_table(
        "wb_daily_report_import_row_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "import_id",
            sa.Integer(),
            sa.ForeignKey("wb_daily_report_imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("skip_reason", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "normalized_payload",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_wb_daily_report_row_logs_import",
        "wb_daily_report_import_row_logs",
        ["import_id"],
    )
    op.create_index(
        "ix_wb_daily_report_row_logs_source_hash",
        "wb_daily_report_import_row_logs",
        ["source_hash"],
    )
    op.create_index(
        "ix_wb_daily_report_row_logs_status",
        "wb_daily_report_import_row_logs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wb_daily_report_row_logs_status",
        table_name="wb_daily_report_import_row_logs",
    )
    op.drop_index(
        "ix_wb_daily_report_row_logs_source_hash",
        table_name="wb_daily_report_import_row_logs",
    )
    op.drop_index(
        "ix_wb_daily_report_row_logs_import",
        table_name="wb_daily_report_import_row_logs",
    )
    op.drop_table("wb_daily_report_import_row_logs")

    op.drop_index("ix_wb_daily_report_rows_status", table_name="wb_daily_report_rows")
    op.drop_index("ix_wb_daily_report_rows_srid", table_name="wb_daily_report_rows")
    op.drop_index("ix_wb_daily_report_rows_barcode", table_name="wb_daily_report_rows")
    op.drop_column("wb_daily_report_rows", "error_message")
    op.drop_column("wb_daily_report_rows", "skip_reason")
    op.drop_column("wb_daily_report_rows", "row_status")
    op.drop_column("wb_daily_report_rows", "commission_rub")
    op.drop_column("wb_daily_report_rows", "linked_product_id")
    op.drop_column("wb_daily_report_rows", "linked_order_id")
    op.drop_column("wb_daily_report_rows", "srid")
