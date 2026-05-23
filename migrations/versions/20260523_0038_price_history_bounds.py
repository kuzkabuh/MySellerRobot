"""Add min_price, mrc_lower_bound, mrc_upper_bound to wb_price_change_history.

Revision ID: 20260523_0038_price_history_bounds
Revises: 20260522_0037_fix_auto_promo_columns
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa

revision = "20260523_0038_price_history_bounds"
down_revision = "20260522_0037_fix_auto_promo_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wb_price_change_history",
        sa.Column("min_price", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "wb_price_change_history",
        sa.Column("mrc_lower_bound", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "wb_price_change_history",
        sa.Column("mrc_upper_bound", sa.Numeric(12, 2), nullable=True),
    )
    op.create_index(
        "ix_price_change_hist_account_created",
        "wb_price_change_history",
        ["marketplace_account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_price_change_hist_account_created",
        table_name="wb_price_change_history",
    )
    op.drop_column("wb_price_change_history", "mrc_upper_bound")
    op.drop_column("wb_price_change_history", "mrc_lower_bound")
    op.drop_column("wb_price_change_history", "min_price")
