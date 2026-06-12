"""Break-even expense settings.

Revision ID: 20260613_0067
Revises: 20260612_0066
Create Date: 2026-06-13
"""

import sqlalchemy as sa
from alembic import op

revision = "20260613_0067"
down_revision = "20260612_0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "break_even_expense_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False, server_default="0.0600"),
        sa.Column("acquiring_rate", sa.Numeric(7, 4), nullable=False, server_default="0.0150"),
        sa.Column("advertising_rate", sa.Numeric(7, 4), nullable=False, server_default="0.0500"),
        sa.Column("packaging_cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("storage_cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("other_cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
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
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "scope",
            "category",
            "product_id",
            name="uq_break_even_expense_scope",
        ),
    )
    op.create_index(
        "ix_break_even_expense_product",
        "break_even_expense_settings",
        ["product_id"],
    )
    op.create_index(
        "ix_break_even_expense_user_scope",
        "break_even_expense_settings",
        ["user_id", "scope"],
    )
    op.create_index(
        "ix_break_even_expense_settings_user_id",
        "break_even_expense_settings",
        ["user_id"],
    )
    op.create_index(
        "ix_products_user_marketplace_active",
        "products",
        ["user_id", "marketplace", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_products_user_marketplace_active", table_name="products")
    op.drop_index(
        "ix_break_even_expense_settings_user_id",
        table_name="break_even_expense_settings",
    )
    op.drop_index("ix_break_even_expense_user_scope", table_name="break_even_expense_settings")
    op.drop_index("ix_break_even_expense_product", table_name="break_even_expense_settings")
    op.drop_table("break_even_expense_settings")
