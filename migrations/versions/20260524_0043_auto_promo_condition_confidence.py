"""Add confidence to WB auto promotion conditions.

Revision ID: 20260524_0043_auto_promo_condition_confidence
Revises: 20260524_0042_wb_price_nullable
Create Date: 2026-05-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260524_0043_auto_promo_condition_confidence"
down_revision = "20260524_0042_wb_price_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("wb_auto_promotion_conditions")]
    if "confidence" not in columns:
        op.add_column(
            "wb_auto_promotion_conditions",
            sa.Column("confidence", sa.String(length=16), nullable=False, server_default="low"),
        )
        op.alter_column("wb_auto_promotion_conditions", "confidence", server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("wb_auto_promotion_conditions")]
    if "confidence" in columns:
        op.drop_column("wb_auto_promotion_conditions", "confidence")
