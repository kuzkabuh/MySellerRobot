"""Extend WB detail report rows for weekly reports and matching metadata.

Revision ID: 20260608_0059
Revises: 20260608_0058
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260608_0059"
down_revision: str | None = "20260608_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("barcode", sa.String(length=64), nullable=True))
    op.create_index("ix_products_barcode", "products", ["marketplace_account_id", "barcode"])

    op.add_column(
        "wb_daily_report_imports",
        sa.Column("report_type", sa.String(length=16), nullable=False, server_default="daily"),
    )
    op.add_column("wb_daily_report_imports", sa.Column("report_period_start", sa.Date()))
    op.add_column("wb_daily_report_imports", sa.Column("report_period_end", sa.Date()))

    op.add_column(
        "wb_daily_report_rows",
        sa.Column("report_type", sa.String(length=16), nullable=False, server_default="daily"),
    )
    op.drop_constraint(
        "ux_wb_daily_report_row_dedupe",
        "wb_daily_report_rows",
        type_="unique",
    )
    op.create_unique_constraint(
        "ux_wb_daily_report_row_dedupe",
        "wb_daily_report_rows",
        ["marketplace_account_id", "report_type", "report_number", "row_hash"],
    )
    op.add_column("wb_daily_report_rows", sa.Column("report_period_start", sa.Date()))
    op.add_column("wb_daily_report_rows", sa.Column("report_period_end", sa.Date()))
    op.add_column("wb_daily_report_rows", sa.Column("product_name", sa.String(length=512)))
    op.add_column("wb_daily_report_rows", sa.Column("size", sa.String(length=128)))
    op.add_column("wb_daily_report_rows", sa.Column("shk", sa.String(length=128)))
    op.add_column("wb_daily_report_rows", sa.Column("payment_reason", sa.String(length=255)))
    op.add_column("wb_daily_report_rows", sa.Column("delivery_count", sa.Integer()))
    op.add_column("wb_daily_report_rows", sa.Column("return_count", sa.Integer()))
    op.add_column(
        "wb_daily_report_rows",
        sa.Column("commission_correction_amount", sa.Numeric(14, 2)),
    )
    op.add_column("wb_daily_report_rows", sa.Column("reimbursement_amount", sa.Numeric(14, 2)))
    op.add_column(
        "wb_daily_report_rows",
        sa.Column("logistics_penalty_correction_type", sa.String(length=255)),
    )
    op.add_column("wb_daily_report_rows", sa.Column("basket_id", sa.String(length=128)))
    op.add_column("wb_daily_report_rows", sa.Column("sale_method", sa.String(length=255)))
    op.add_column(
        "wb_daily_report_rows",
        sa.Column(
            "product_match_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "wb_daily_report_rows",
        sa.Column(
            "order_match_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column("wb_daily_report_rows", sa.Column("product_match_method", sa.String(length=32)))
    op.add_column("wb_daily_report_rows", sa.Column("order_match_method", sa.String(length=32)))
    op.add_column(
        "wb_daily_report_rows",
        sa.Column(
            "finance_operation_type",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "wb_daily_report_rows",
        sa.Column(
            "finance_category",
            sa.String(length=64),
            nullable=False,
            server_default="other",
        ),
    )

    op.create_index("ix_wb_daily_report_rows_type", "wb_daily_report_rows", ["report_type"])
    op.create_index(
        "ix_wb_daily_report_rows_supplier_article",
        "wb_daily_report_rows",
        ["supplier_article"],
    )
    op.create_index("ix_wb_daily_report_rows_shk", "wb_daily_report_rows", ["shk"])
    op.create_index(
        "ix_wb_daily_report_rows_payment_reason",
        "wb_daily_report_rows",
        ["payment_reason"],
    )


def downgrade() -> None:
    op.drop_index("ix_wb_daily_report_rows_payment_reason", table_name="wb_daily_report_rows")
    op.drop_index("ix_wb_daily_report_rows_shk", table_name="wb_daily_report_rows")
    op.drop_index("ix_wb_daily_report_rows_supplier_article", table_name="wb_daily_report_rows")
    op.drop_index("ix_wb_daily_report_rows_type", table_name="wb_daily_report_rows")

    op.drop_column("wb_daily_report_rows", "finance_category")
    op.drop_column("wb_daily_report_rows", "finance_operation_type")
    op.drop_column("wb_daily_report_rows", "order_match_method")
    op.drop_column("wb_daily_report_rows", "product_match_method")
    op.drop_column("wb_daily_report_rows", "order_match_status")
    op.drop_column("wb_daily_report_rows", "product_match_status")
    op.drop_column("wb_daily_report_rows", "sale_method")
    op.drop_column("wb_daily_report_rows", "basket_id")
    op.drop_column("wb_daily_report_rows", "logistics_penalty_correction_type")
    op.drop_column("wb_daily_report_rows", "reimbursement_amount")
    op.drop_column("wb_daily_report_rows", "commission_correction_amount")
    op.drop_column("wb_daily_report_rows", "return_count")
    op.drop_column("wb_daily_report_rows", "delivery_count")
    op.drop_column("wb_daily_report_rows", "payment_reason")
    op.drop_column("wb_daily_report_rows", "shk")
    op.drop_column("wb_daily_report_rows", "size")
    op.drop_column("wb_daily_report_rows", "product_name")
    op.drop_column("wb_daily_report_rows", "report_period_end")
    op.drop_column("wb_daily_report_rows", "report_period_start")
    op.drop_constraint(
        "ux_wb_daily_report_row_dedupe",
        "wb_daily_report_rows",
        type_="unique",
    )
    op.create_unique_constraint(
        "ux_wb_daily_report_row_dedupe",
        "wb_daily_report_rows",
        ["marketplace_account_id", "report_number", "row_hash"],
    )
    op.drop_column("wb_daily_report_rows", "report_type")

    op.drop_column("wb_daily_report_imports", "report_period_end")
    op.drop_column("wb_daily_report_imports", "report_period_start")
    op.drop_column("wb_daily_report_imports", "report_type")

    op.drop_index("ix_products_barcode", table_name="products")
    op.drop_column("products", "barcode")
