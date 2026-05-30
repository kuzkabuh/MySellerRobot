"""Add missing promotion_name column to wb_auto_promo_price_recommendations.

This migration is defensive: if 0035 was partially applied or the table
was created before promotion_name was added, this ensures the column exists.

Revision ID: 20260522_0036_add_promotion_name_to_recs
Revises: 20260522_0035_auto_promo_price_control
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_0036_add_promotion_name_to_recs"
down_revision: str | None = "20260522_0035_auto_promo_price_control"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    columns = [col["name"] for col in inspector.get_columns("wb_auto_promo_price_recommendations")]

    if "promotion_name" not in columns:
        op.add_column(
            "wb_auto_promo_price_recommendations",
            sa.Column("promotion_name", sa.String(length=512), nullable=True),
        )

    # Also ensure wb_auto_promotion_conditions has all expected columns
    cond_columns = [col["name"] for col in inspector.get_columns("wb_auto_promotion_conditions")]
    expected_cond = [
        "title",
        "promotion_name",
        "is_participating",
    ]
    for col_name in expected_cond:
        if col_name not in cond_columns:
            if col_name == "is_participating":
                op.add_column(
                    "wb_auto_promotion_conditions",
                    sa.Column(col_name, sa.Boolean(), nullable=True),
                )
            else:
                length = 1024 if col_name == "title" else 512
                op.add_column(
                    "wb_auto_promotion_conditions",
                    sa.Column(col_name, sa.String(length=length), nullable=True),
                )

    # Ensure wb_price_change_history has source column
    hist_columns = [col["name"] for col in inspector.get_columns("wb_price_change_history")]
    if "source" not in hist_columns:
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

    rec_columns = [
        col["name"] for col in inspector.get_columns("wb_auto_promo_price_recommendations")
    ]
    if "promotion_name" in rec_columns:
        op.drop_column("wb_auto_promo_price_recommendations", "promotion_name")

    cond_columns = [col["name"] for col in inspector.get_columns("wb_auto_promotion_conditions")]
    for col_name in ("title", "promotion_name", "is_participating"):
        if col_name in cond_columns:
            op.drop_column("wb_auto_promotion_conditions", col_name)

    hist_columns = [col["name"] for col in inspector.get_columns("wb_price_change_history")]
    if "source" in hist_columns:
        op.drop_column("wb_price_change_history", "source")
