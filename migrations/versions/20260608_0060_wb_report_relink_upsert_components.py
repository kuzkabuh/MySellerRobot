"""Add WB report relink, upsert and finance component fields.

Revision ID: 20260608_0060
Revises: 20260608_0059
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260608_0060"
down_revision: str | None = "20260608_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("wb_daily_report_imports", sa.Column("rows_created_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("wb_daily_report_imports", sa.Column("rows_updated_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("wb_daily_report_imports", sa.Column("rows_unchanged_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("wb_daily_report_imports", sa.Column("rows_pending_match_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("wb_daily_report_imports", sa.Column("rows_matched_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("wb_daily_report_imports", sa.Column("rows_ambiguous_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("wb_daily_report_imports", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wb_daily_report_imports", sa.Column("deleted_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("wb_daily_report_imports", sa.Column("delete_reason", sa.Text(), nullable=True))
    op.add_column("wb_daily_report_imports", sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wb_daily_report_imports", sa.Column("restored_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_wb_daily_report_imports_deleted", "wb_daily_report_imports", ["deleted_at"])

    op.add_column("wb_daily_report_rows", sa.Column("stable_business_key", sa.String(length=128), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("source_row_hash", sa.String(length=64), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("wb_daily_report_rows", sa.Column("previous_payload", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("changed_fields", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("srid_raw", sa.String(length=255), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("srid_normalized", sa.String(length=255), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("rid_normalized", sa.String(length=255), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("product_match_reason", sa.String(length=255), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("order_match_reason", sa.String(length=255), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("order_required", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("wb_daily_report_rows", sa.Column("match_attempts_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("wb_daily_report_rows", sa.Column("last_match_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("last_match_error", sa.Text(), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("matched_order_id", sa.Integer(), nullable=True))
    op.add_column("wb_daily_report_rows", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("wb_daily_report_rows", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE wb_daily_report_rows SET source_row_hash = row_hash WHERE source_row_hash IS NULL")
    op.execute("UPDATE wb_daily_report_rows SET srid_raw = srid, srid_normalized = lower(trim(srid)) WHERE srid IS NOT NULL")
    op.execute("UPDATE wb_daily_report_rows SET order_id = linked_order_id WHERE order_id IS NULL")
    op.execute("UPDATE wb_daily_report_rows SET product_id = linked_product_id WHERE product_id IS NULL")

    op.create_index("ux_wb_daily_report_rows_stable_business_key_active", "wb_daily_report_rows", ["stable_business_key"], unique=True, postgresql_where=sa.text("deleted_at IS NULL AND stable_business_key IS NOT NULL"))
    op.create_index("ix_wb_daily_report_rows_source_hash", "wb_daily_report_rows", ["source_row_hash"])
    op.create_index("ix_wb_daily_report_rows_stable_key", "wb_daily_report_rows", ["stable_business_key"])
    op.create_index("ix_wb_daily_report_rows_srid_raw", "wb_daily_report_rows", ["srid_raw"])
    op.create_index("ix_wb_daily_report_rows_srid_normalized", "wb_daily_report_rows", ["srid_normalized"])
    op.create_index("ix_wb_daily_report_rows_rid_normalized", "wb_daily_report_rows", ["rid_normalized"])
    op.create_index("ix_wb_daily_report_rows_basket_id", "wb_daily_report_rows", ["basket_id"])
    op.create_index("ix_wb_daily_report_rows_order_match_status", "wb_daily_report_rows", ["order_match_status"])
    op.create_index("ix_wb_daily_report_rows_order_required", "wb_daily_report_rows", ["order_required"])
    op.create_index("ix_wb_daily_report_rows_deleted", "wb_daily_report_rows", ["deleted_at"])
    op.create_index("ix_wb_daily_report_rows_order_id", "wb_daily_report_rows", ["order_id"])
    op.create_index("ix_wb_daily_report_rows_product_id", "wb_daily_report_rows", ["product_id"])

    op.create_table(
        "wb_report_finance_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_import_id", sa.Integer(), sa.ForeignKey("wb_daily_report_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_row_id", sa.Integer(), sa.ForeignKey("wb_daily_report_rows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("finance_category", sa.String(length=64), nullable=False),
        sa.Column("operation_type", sa.String(length=32), nullable=False),
        sa.Column("original_column_name", sa.String(length=255), nullable=False),
        sa.Column("original_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("normalized_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("sign_rule", sa.String(length=64), nullable=False),
        sa.Column("is_order_fact", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_product_fact", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_global_fact", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_wb_report_components_import", "wb_report_finance_components", ["report_import_id"])
    op.create_index("ix_wb_report_components_row", "wb_report_finance_components", ["report_row_id"])
    op.create_index("ix_wb_report_components_account", "wb_report_finance_components", ["marketplace_account_id"])
    op.create_index("ix_wb_report_components_order", "wb_report_finance_components", ["order_id"])
    op.create_index("ix_wb_report_components_product", "wb_report_finance_components", ["product_id"])
    op.create_index("ix_wb_report_components_category", "wb_report_finance_components", ["finance_category"])
    op.create_index("ix_wb_report_components_active", "wb_report_finance_components", ["is_active"])
    op.create_index("ix_wb_report_components_deleted", "wb_report_finance_components", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_wb_report_components_deleted", table_name="wb_report_finance_components")
    op.drop_index("ix_wb_report_components_active", table_name="wb_report_finance_components")
    op.drop_index("ix_wb_report_components_category", table_name="wb_report_finance_components")
    op.drop_index("ix_wb_report_components_product", table_name="wb_report_finance_components")
    op.drop_index("ix_wb_report_components_order", table_name="wb_report_finance_components")
    op.drop_index("ix_wb_report_components_account", table_name="wb_report_finance_components")
    op.drop_index("ix_wb_report_components_row", table_name="wb_report_finance_components")
    op.drop_index("ix_wb_report_components_import", table_name="wb_report_finance_components")
    op.drop_table("wb_report_finance_components")

    for index_name in (
        "ix_wb_daily_report_rows_product_id",
        "ix_wb_daily_report_rows_order_id",
        "ix_wb_daily_report_rows_deleted",
        "ix_wb_daily_report_rows_order_required",
        "ix_wb_daily_report_rows_order_match_status",
        "ix_wb_daily_report_rows_basket_id",
        "ix_wb_daily_report_rows_rid_normalized",
        "ix_wb_daily_report_rows_srid_normalized",
        "ix_wb_daily_report_rows_srid_raw",
        "ix_wb_daily_report_rows_stable_key",
        "ix_wb_daily_report_rows_source_hash",
        "ux_wb_daily_report_rows_stable_business_key_active",
    ):
        op.drop_index(index_name, table_name="wb_daily_report_rows")

    for column_name in (
        "deleted_at",
        "is_active",
        "matched_order_id",
        "matched_at",
        "last_match_error",
        "last_match_attempt_at",
        "match_attempts_count",
        "order_required",
        "order_match_reason",
        "product_match_reason",
        "product_id",
        "order_id",
        "rid_normalized",
        "srid_normalized",
        "srid_raw",
        "changed_fields",
        "previous_payload",
        "version",
        "source_row_hash",
        "stable_business_key",
    ):
        op.drop_column("wb_daily_report_rows", column_name)

    op.drop_index("ix_wb_daily_report_imports_deleted", table_name="wb_daily_report_imports")
    for column_name in (
        "restored_by_user_id",
        "restored_at",
        "delete_reason",
        "deleted_by_user_id",
        "deleted_at",
        "rows_ambiguous_count",
        "rows_matched_count",
        "rows_pending_match_count",
        "rows_unchanged_count",
        "rows_updated_count",
        "rows_created_count",
    ):
        op.drop_column("wb_daily_report_imports", column_name)
