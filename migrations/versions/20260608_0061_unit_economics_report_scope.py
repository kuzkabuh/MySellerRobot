"""Classify WB report operation scope and add order soft delete fields.

Revision ID: 20260608_0061
Revises: 20260608_0060
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260608_0061"
down_revision: str | None = "20260608_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("deleted_reason", sa.Text(), nullable=True))
    op.create_index("ix_orders_deleted", "orders", ["deleted_at"])

    op.add_column(
        "wb_daily_report_rows",
        sa.Column("operation_scope", sa.String(length=32), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "wb_daily_report_rows",
        sa.Column("product_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_wb_daily_report_rows_operation_scope",
        "wb_daily_report_rows",
        ["operation_scope"],
    )
    op.create_index(
        "ix_wb_daily_report_rows_product_required",
        "wb_daily_report_rows",
        ["product_required"],
    )

    op.add_column(
        "wb_report_finance_components",
        sa.Column("operation_scope", sa.String(length=32), nullable=False, server_default="unknown"),
    )
    op.create_index(
        "ix_wb_report_components_scope",
        "wb_report_finance_components",
        ["operation_scope"],
    )

    op.execute(
        """
        UPDATE wb_daily_report_rows
        SET operation_scope = 'period',
            order_required = false,
            product_required = false,
            order_id = NULL,
            linked_order_id = NULL,
            matched_order_id = NULL,
            product_id = NULL,
            linked_product_id = NULL,
            order_match_status = 'not_required',
            product_match_status = 'not_required',
            order_match_reason = 'Для строки хранения не требуется заказ',
            product_match_reason = 'Для строки хранения не требуется товар'
        WHERE lower(coalesce(payment_reason, '')) LIKE '%хран%'
        """
    )
    op.execute(
        """
        UPDATE wb_daily_report_rows
        SET operation_scope = 'order',
            order_required = true,
            product_required = true
        WHERE operation_scope = 'unknown'
          AND (
            lower(coalesce(payment_reason, '')) LIKE '%продаж%'
            OR lower(coalesce(payment_reason, '')) LIKE '%возврат%'
            OR lower(coalesce(payment_reason, '')) LIKE '%перечисл%'
          )
        """
    )
    op.execute(
        """
        UPDATE wb_daily_report_rows
        SET operation_scope = 'order',
            order_required = true,
            product_required = (
                barcode IS NOT NULL OR nm_id IS NOT NULL OR supplier_article IS NOT NULL
            )
        WHERE operation_scope = 'unknown'
          AND (srid IS NOT NULL OR shk IS NOT NULL OR basket_id IS NOT NULL)
        """
    )
    op.execute(
        """
        UPDATE wb_daily_report_rows
        SET operation_scope = 'product',
            order_required = false,
            product_required = true
        WHERE operation_scope = 'unknown'
          AND (barcode IS NOT NULL OR nm_id IS NOT NULL OR supplier_article IS NOT NULL)
        """
    )
    op.execute(
        """
        UPDATE wb_daily_report_rows
        SET operation_scope = 'account',
            order_required = false,
            product_required = false
        WHERE operation_scope = 'unknown'
          AND (
            lower(coalesce(payment_reason, '')) LIKE '%удерж%'
            OR lower(coalesce(payment_reason, '')) LIKE '%штраф%'
            OR lower(coalesce(payment_reason, '')) LIKE '%прием%'
            OR lower(coalesce(payment_reason, '')) LIKE '%приём%'
            OR lower(coalesce(payment_reason, '')) LIKE '%компенсац%'
            OR lower(coalesce(payment_reason, '')) LIKE '%возмещ%'
          )
        """
    )
    op.execute(
        """
        UPDATE wb_report_finance_components AS component
        SET operation_scope = row.operation_scope,
            order_id = CASE WHEN row.operation_scope = 'order' THEN component.order_id ELSE NULL END,
            product_id = CASE
                WHEN row.operation_scope IN ('order', 'product') THEN component.product_id
                ELSE NULL
            END,
            is_order_fact = (
                row.operation_scope = 'order'
                AND component.order_id IS NOT NULL
            ),
            is_product_fact = (
                row.operation_scope IN ('order', 'product')
                AND component.product_id IS NOT NULL
            ),
            is_global_fact = row.operation_scope IN ('account', 'warehouse', 'period', 'unknown')
        FROM wb_daily_report_rows AS row
        WHERE component.report_row_id = row.id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_wb_report_components_scope", table_name="wb_report_finance_components")
    op.drop_column("wb_report_finance_components", "operation_scope")
    op.drop_index("ix_wb_daily_report_rows_product_required", table_name="wb_daily_report_rows")
    op.drop_index("ix_wb_daily_report_rows_operation_scope", table_name="wb_daily_report_rows")
    op.drop_column("wb_daily_report_rows", "product_required")
    op.drop_column("wb_daily_report_rows", "operation_scope")
    op.drop_index("ix_orders_deleted", table_name="orders")
    op.drop_column("orders", "deleted_reason")
    op.drop_column("orders", "deleted_at")
