"""Ensure wb_promotion_id is nullable in wb_auto_promotion_conditions
and add missing columns to all auto-promo tables.

This is a defensive migration for production instances where the table
was created before nullable=True was set.

Revision ID: 20260522_0037_fix_auto_promo_columns
Revises: 20260522_0036_add_promotion_name_to_recs
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_0037_fix_auto_promo_columns"
down_revision: str | None = "20260522_0036_add_promotion_name_to_recs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Fix wb_auto_promotion_conditions: ensure wb_promotion_id is nullable
    cond_cols = {
        col["name"]: col
        for col in inspector.get_columns("wb_auto_promotion_conditions")
    }
    if "wb_promotion_id" in cond_cols and not cond_cols["wb_promotion_id"]["nullable"]:
        op.alter_column(
            "wb_auto_promotion_conditions",
            "wb_promotion_id",
            nullable=True,
        )

    # Ensure all expected columns exist in wb_auto_promotion_conditions
    cond_col_names = set(cond_cols.keys())
    if "title" not in cond_col_names:
        op.add_column(
            "wb_auto_promotion_conditions",
            sa.Column("title", sa.String(1024), nullable=True),
        )
    if "promotion_name" not in cond_col_names:
        op.add_column(
            "wb_auto_promotion_conditions",
            sa.Column("promotion_name", sa.String(512), nullable=True),
        )
    if "is_participating" not in cond_col_names:
        op.add_column(
            "wb_auto_promotion_conditions",
            sa.Column("is_participating", sa.Boolean(), nullable=True),
        )

    # Fix wb_auto_promo_price_recommendations: ensure promotion_name exists
    rec_cols = {
        col["name"]: col
        for col in inspector.get_columns("wb_auto_promo_price_recommendations")
    }
    if "promotion_name" not in rec_cols:
        op.add_column(
            "wb_auto_promo_price_recommendations",
            sa.Column("promotion_name", sa.String(512), nullable=True),
        )

    # Ensure wb_price_change_history has source
    hist_cols = {
        col["name"]: col
        for col in inspector.get_columns("wb_price_change_history")
    }
    if "source" not in hist_cols:
        op.add_column(
            "wb_price_change_history",
            sa.Column(
                "source",
                sa.String(64),
                nullable=False,
                server_default=sa.text("'manual'"),
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    cond_cols = {
        col["name"]: col
        for col in inspector.get_columns("wb_auto_promotion_conditions")
    }
    if "wb_promotion_id" in cond_cols and cond_cols["wb_promotion_id"]["nullable"]:
        op.alter_column(
            "wb_auto_promotion_conditions",
            "wb_promotion_id",
            nullable=False,
        )
    for col_name in ("title", "promotion_name", "is_participating"):
        if col_name in cond_cols:
            op.drop_column("wb_auto_promotion_conditions", col_name)

    rec_cols = {
        col["name"]: col
        for col in inspector.get_columns("wb_auto_promo_price_recommendations")
    }
    if "promotion_name" in rec_cols:
        op.drop_column("wb_auto_promo_price_recommendations", "promotion_name")

    hist_cols = {
        col["name"]: col
        for col in inspector.get_columns("wb_price_change_history")
    }
    if "source" in hist_cols:
        op.drop_column("wb_price_change_history", "source")
