"""Ensure all auto-promo columns and tables exist.

Follow-up migration for production instances where 0044 may not have been
applied or was partially applied. Adds any missing columns with inspector
guards and creates missing tables so it is safe to run multiple times.

Revision ID: 20260525_0045_ensure_auto_promo_columns
Revises: 20260524_0044_auto_promo_participation_fields
Create Date: 2026-05-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260525_0045_ensure_auto_promo_columns"
down_revision = "20260524_0044_auto_promo_participation_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    # ============================================================
    # TABLES: ensure wb_auto_promo_file_imports and rows exist
    # ============================================================

    if "wb_auto_promo_file_imports" not in existing_tables:
        op.create_table(
            "wb_auto_promo_file_imports",
            sa.Column("id", sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("original_file_name", sa.String(512), nullable=True),
            sa.Column("promotion_name", sa.String(512), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="preview"),
            sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("warning_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_text", sa.Text(), nullable=True),
        )
        op.create_index("ix_wb_auto_promo_file_imports_user_created", "wb_auto_promo_file_imports", ["user_id", "created_at"])
        op.create_index("ix_wb_auto_promo_file_imports_marketplace_account_id", "wb_auto_promo_file_imports", ["marketplace_account_id"])

    if "wb_auto_promo_file_import_rows" not in existing_tables:
        op.create_table(
            "wb_auto_promo_file_import_rows",
            sa.Column("id", sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
            sa.Column("import_id", sa.Integer(), sa.ForeignKey("wb_auto_promo_file_imports.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("row_number", sa.Integer(), nullable=False),
            sa.Column("wb_nm_id", sa.BigInteger(), nullable=True, index=True),
            sa.Column("seller_article", sa.String(255), nullable=True),
            sa.Column("title", sa.String(1024), nullable=True),
            sa.Column("plan_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("current_full_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("current_discount_percent", sa.Numeric(5, 2), nullable=True),
            sa.Column("current_discounted_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("wb_upload_discount_percent", sa.Numeric(5, 2), nullable=True),
            sa.Column("wb_status", sa.String(512), nullable=True),
            sa.Column("already_participating", sa.Boolean(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("raw_payload", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        )
        op.create_index("ix_wb_auto_promo_file_rows_import_id", "wb_auto_promo_file_import_rows", ["import_id"])
        op.create_index("ix_wb_auto_promo_file_import_rows_wb_nm_id", "wb_auto_promo_file_import_rows", ["wb_nm_id"])

    # ============================================================
    # COLUMNS: wb_auto_promotion_conditions
    # ============================================================

    condition_columns = {
        col["name"]
        for col in inspector.get_columns("wb_auto_promotion_conditions")
    }
    condition_table = "wb_auto_promotion_conditions"

    condition_additions = [
        ("max_auto_promo_price", sa.Numeric(12, 2), True),
        ("wb_condition_discount_percent", sa.Numeric(10, 2), True),
        ("current_full_price", sa.Numeric(12, 2), True),
        ("current_discount", sa.Integer(), True),
        ("current_discounted_price", sa.Numeric(12, 2), True),
        ("candidate_discounted_price", sa.Numeric(12, 2), True),
        ("condition_type", sa.String(32), False, "unknown"),
    ]

    for addition in condition_additions:
        name = addition[0]
        col_type = addition[1]
        nullable = addition[2]
        if name not in condition_columns:
            if len(addition) == 4:
                op.add_column(
                    condition_table,
                    sa.Column(
                        name,
                        col_type,
                        nullable=nullable,
                        server_default=addition[3],
                    ),
                )
                op.alter_column(condition_table, name, server_default=None)
            else:
                op.add_column(
                    condition_table,
                    sa.Column(name, col_type, nullable=nullable),
                )

    # ============================================================
    # COLUMNS: wb_auto_promo_price_recommendations
    # ============================================================

    rec_columns = {
        col["name"]
        for col in inspector.get_columns("wb_auto_promo_price_recommendations")
    }
    rec_table = "wb_auto_promo_price_recommendations"

    rec_additions = [
        ("current_full_price", sa.Numeric(12, 2), True),
        ("current_discount", sa.Integer(), True),
        ("current_discounted_price", sa.Numeric(12, 2), True),
        ("max_auto_promo_price", sa.Numeric(12, 2), True),
        ("wb_condition_discount_percent", sa.Numeric(10, 2), True),
        ("candidate_discounted_price", sa.Numeric(12, 2), True),
        ("recommended_discounted_price", sa.Numeric(12, 2), True),
        ("recommended_full_price", sa.Numeric(12, 2), True),
        ("recommended_discount", sa.Integer(), True),
        ("safe_discounted_price", sa.Numeric(12, 2), True),
        ("safe_full_price", sa.Numeric(12, 2), True),
        ("safe_discount", sa.Integer(), True),
        ("condition_type", sa.String(32), False, "unknown"),
        ("raw_payload", sa.JSON(), True),
        ("applied_at", sa.DateTime(timezone=True), True),
    ]

    for addition in rec_additions:
        name = addition[0]
        col_type = addition[1]
        nullable = addition[2]
        if name not in rec_columns:
            if len(addition) == 4:
                op.add_column(
                    rec_table,
                    sa.Column(
                        name,
                        col_type,
                        nullable=nullable,
                        server_default=addition[3],
                    ),
                )
                op.alter_column(rec_table, name, server_default=None)
            else:
                op.add_column(
                    rec_table,
                    sa.Column(name, col_type, nullable=nullable),
                )

    # ============================================================
    # COLUMNS: wb_price_change_history
    # ============================================================

    hist_columns = {
        col["name"]
        for col in inspector.get_columns("wb_price_change_history")
    }
    hist_table = "wb_price_change_history"

    hist_additions = [
        ("wb_upload_id", sa.BigInteger(), True),
        ("target_discounted_price", sa.Numeric(12, 2), True),
        ("wb_price", sa.Integer(), True),
        ("wb_discount", sa.Integer(), True),
        ("final_discounted_price", sa.Numeric(12, 2), True),
        ("min_price", sa.Numeric(12, 2), True),
        ("mrc_lower_bound", sa.Numeric(12, 2), True),
        ("mrc_upper_bound", sa.Numeric(12, 2), True),
        ("raw_payload", sa.JSON(), True),
        ("raw_response", sa.JSON(), True),
        ("updated_at", sa.DateTime(timezone=True), False, sa.func.now()),
    ]

    for addition in hist_additions:
        name = addition[0]
        col_type = addition[1]
        nullable = addition[2]
        if name not in hist_columns:
            if len(addition) == 4:
                op.add_column(
                    hist_table,
                    sa.Column(
                        name,
                        col_type,
                        nullable=nullable,
                        server_default=addition[3],
                    ),
                )
                op.alter_column(hist_table, name, server_default=None)
            else:
                op.add_column(
                    hist_table,
                    sa.Column(name, col_type, nullable=nullable),
                )

    # ============================================================
    # COLUMNS: wb_product_prices
    # ============================================================

    price_columns = {
        col["name"]
        for col in inspector.get_columns("wb_product_prices")
    }
    price_table = "wb_product_prices"

    price_additions = [
        ("club_discount", sa.Integer(), True, 0),
        ("club_discounted_price", sa.Numeric(12, 2), True),
    ]

    for addition in price_additions:
        name = addition[0]
        col_type = addition[1]
        nullable = addition[2]
        if name not in price_columns:
            if len(addition) == 4:
                op.add_column(
                    price_table,
                    sa.Column(
                        name,
                        col_type,
                        nullable=nullable,
                        server_default=addition[3],
                    ),
                )
                op.alter_column(price_table, name, server_default=None)
            else:
                op.add_column(
                    price_table,
                    sa.Column(name, col_type, nullable=nullable),
                )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Drop columns (safe: only if they exist)
    condition_columns = {
        col["name"]
        for col in inspector.get_columns("wb_auto_promotion_conditions")
    }
    for name in (
        "condition_type",
        "candidate_discounted_price",
        "current_discounted_price",
        "current_discount",
        "current_full_price",
        "wb_condition_discount_percent",
        "max_auto_promo_price",
    ):
        if name in condition_columns:
            op.drop_column("wb_auto_promotion_conditions", name)

    rec_columns = {
        col["name"]
        for col in inspector.get_columns("wb_auto_promo_price_recommendations")
    }
    for name in (
        "applied_at",
        "raw_payload",
        "condition_type",
        "safe_discount",
        "safe_full_price",
        "safe_discounted_price",
        "recommended_discount",
        "recommended_full_price",
        "recommended_discounted_price",
        "candidate_discounted_price",
        "wb_condition_discount_percent",
        "max_auto_promo_price",
        "current_discounted_price",
        "current_discount",
        "current_full_price",
    ):
        if name in rec_columns:
            op.drop_column("wb_auto_promo_price_recommendations", name)

    hist_columns = {
        col["name"]
        for col in inspector.get_columns("wb_price_change_history")
    }
    for name in (
        "updated_at",
        "raw_response",
        "raw_payload",
        "mrc_upper_bound",
        "mrc_lower_bound",
        "min_price",
        "final_discounted_price",
        "wb_discount",
        "wb_price",
        "target_discounted_price",
        "wb_upload_id",
    ):
        if name in hist_columns:
            op.drop_column("wb_price_change_history", name)

    price_columns = {
        col["name"]
        for col in inspector.get_columns("wb_product_prices")
    }
    for name in (
        "club_discounted_price",
        "club_discount",
    ):
        if name in price_columns:
            op.drop_column("wb_product_prices", name)

    # Drop tables (safe: only if they exist)
    if inspector.has_table("wb_auto_promo_file_import_rows"):
        op.drop_table("wb_auto_promo_file_import_rows")
    if inspector.has_table("wb_auto_promo_file_imports"):
        op.drop_table("wb_auto_promo_file_imports")
