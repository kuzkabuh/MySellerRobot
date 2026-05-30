"""Add WB auto promotion participation recommendation fields.

Revision ID: 20260524_0044_auto_promo_participation_fields
Revises: 20260524_0043_auto_promo_condition_confidence
Create Date: 2026-05-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260524_0044_auto_promo_participation_fields"
down_revision = "20260524_0043_auto_promo_condition_confidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {col["name"] for col in inspector.get_columns("wb_auto_promo_price_recommendations")}
    table = "wb_auto_promo_price_recommendations"
    additions = [
        ("current_full_price", sa.Numeric(12, 2)),
        ("current_discount", sa.Integer()),
        ("current_discounted_price", sa.Numeric(12, 2)),
        ("max_auto_promo_price", sa.Numeric(12, 2)),
        ("wb_condition_discount_percent", sa.Numeric(10, 2)),
        ("candidate_discounted_price", sa.Numeric(12, 2)),
        ("recommended_discounted_price", sa.Numeric(12, 2)),
        ("recommended_full_price", sa.Numeric(12, 2)),
        ("recommended_discount", sa.Integer()),
        ("safe_discounted_price", sa.Numeric(12, 2)),
        ("safe_full_price", sa.Numeric(12, 2)),
        ("safe_discount", sa.Integer()),
        ("condition_type", sa.String(32), "unknown"),
        ("raw_payload", sa.JSON()),
        ("applied_at", sa.DateTime(timezone=True)),
    ]
    for addition in additions:
        name = addition[0]
        col_type = addition[1]
        if name not in columns:
            if len(addition) == 3:
                op.add_column(
                    table,
                    sa.Column(
                        name,
                        col_type,
                        nullable=False,
                        server_default=addition[2],
                    ),
                )
                op.alter_column(table, name, server_default=None)
            else:
                op.add_column(table, sa.Column(name, col_type, nullable=True))
        elif name == "wb_condition_discount_percent":
            col_info = columns.get(name) if isinstance(columns, dict) else None
            if col_info is None:
                rec_cols = inspector.get_columns("wb_auto_promo_price_recommendations")
                col_info = next(
                    (c for c in rec_cols if c["name"] == name),
                    None,
                )
            if col_info is not None:
                existing_type = str(col_info.get("type", ""))
                if "NUMERIC(5" in existing_type or "numeric(5" in existing_type:
                    op.alter_column(
                        table,
                        name,
                        type_=sa.Numeric(10, 2),
                    )

    condition_columns = {
        col["name"] for col in inspector.get_columns("wb_auto_promotion_conditions")
    }
    condition_additions = [
        ("max_auto_promo_price", sa.Numeric(12, 2)),
        ("wb_condition_discount_percent", sa.Numeric(10, 2)),
        ("current_full_price", sa.Numeric(12, 2)),
        ("current_discount", sa.Integer()),
        ("current_discounted_price", sa.Numeric(12, 2)),
        ("candidate_discounted_price", sa.Numeric(12, 2)),
        ("condition_type", sa.String(32), "unknown"),
    ]
    for addition in condition_additions:
        name = addition[0]
        col_type = addition[1]
        if name not in condition_columns:
            if len(addition) == 3:
                op.add_column(
                    "wb_auto_promotion_conditions",
                    sa.Column(
                        name,
                        col_type,
                        nullable=False,
                        server_default=addition[2],
                    ),
                )
                op.alter_column(
                    "wb_auto_promotion_conditions",
                    name,
                    server_default=None,
                )
            else:
                op.add_column(
                    "wb_auto_promotion_conditions",
                    sa.Column(name, col_type, nullable=True),
                )
        elif name == "wb_condition_discount_percent":
            col_info = condition_columns.get(name) if isinstance(condition_columns, dict) else None
            if col_info is None:
                cond_cols = inspector.get_columns("wb_auto_promotion_conditions")
                col_info = next(
                    (c for c in cond_cols if c["name"] == name),
                    None,
                )
            if col_info is not None:
                existing_type = str(col_info.get("type", ""))
                if "NUMERIC(5" in existing_type or "numeric(5" in existing_type:
                    op.alter_column(
                        "wb_auto_promotion_conditions",
                        name,
                        type_=sa.Numeric(10, 2),
                    )

    if not inspector.has_table("wb_auto_promo_file_imports"):
        op.create_table(
            "wb_auto_promo_file_imports",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("marketplace_account_id", sa.Integer(), nullable=False),
            sa.Column("original_file_name", sa.String(512), nullable=True),
            sa.Column("promotion_name", sa.String(512), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="preview"),
            sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("warning_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_text", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["marketplace_account_id"],
                ["marketplace_accounts.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_wb_auto_promo_file_imports_user_created",
            "wb_auto_promo_file_imports",
            ["user_id", "created_at"],
        )
        op.create_index(
            "ix_wb_auto_promo_file_imports_marketplace_account_id",
            "wb_auto_promo_file_imports",
            ["marketplace_account_id"],
        )

    if not inspector.has_table("wb_auto_promo_file_import_rows"):
        op.create_table(
            "wb_auto_promo_file_import_rows",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("import_id", sa.Integer(), nullable=False),
            sa.Column("row_number", sa.Integer(), nullable=False),
            sa.Column("wb_nm_id", sa.BigInteger(), nullable=True),
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
            sa.ForeignKeyConstraint(
                ["import_id"],
                ["wb_auto_promo_file_imports.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_wb_auto_promo_file_rows_import_id",
            "wb_auto_promo_file_import_rows",
            ["import_id"],
        )
        op.create_index(
            "ix_wb_auto_promo_file_import_rows_wb_nm_id",
            "wb_auto_promo_file_import_rows",
            ["wb_nm_id"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {col["name"] for col in inspector.get_columns("wb_auto_promo_price_recommendations")}
    table = "wb_auto_promo_price_recommendations"
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
        if name in columns:
            op.drop_column(table, name)

    condition_columns = {
        col["name"] for col in inspector.get_columns("wb_auto_promotion_conditions")
    }
    for name in (
        "max_auto_promo_price",
        "condition_type",
        "candidate_discounted_price",
        "current_discounted_price",
        "current_discount",
        "current_full_price",
        "wb_condition_discount_percent",
    ):
        if name in condition_columns:
            op.drop_column("wb_auto_promotion_conditions", name)

    if inspector.has_table("wb_auto_promo_file_import_rows"):
        op.drop_table("wb_auto_promo_file_import_rows")
    if inspector.has_table("wb_auto_promo_file_imports"):
        op.drop_table("wb_auto_promo_file_imports")
