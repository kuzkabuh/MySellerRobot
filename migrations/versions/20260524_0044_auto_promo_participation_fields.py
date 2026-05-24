"""Add WB auto promotion participation recommendation fields.

Revision ID: 20260524_0044_auto_promo_participation_fields
Revises: 20260524_0043_auto_promo_condition_confidence
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa

revision = "20260524_0044_auto_promo_participation_fields"
down_revision = "20260524_0043_auto_promo_condition_confidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {
        col["name"]
        for col in inspector.get_columns("wb_auto_promo_price_recommendations")
    }
    table = "wb_auto_promo_price_recommendations"
    additions = [
        ("current_full_price", sa.Numeric(12, 2)),
        ("current_discount", sa.Integer()),
        ("current_discounted_price", sa.Numeric(12, 2)),
        ("max_auto_promo_price", sa.Numeric(12, 2)),
        ("recommended_discounted_price", sa.Numeric(12, 2)),
        ("recommended_full_price", sa.Numeric(12, 2)),
        ("recommended_discount", sa.Integer()),
        ("raw_payload", sa.JSON()),
        ("applied_at", sa.DateTime(timezone=True)),
    ]
    for name, col_type in additions:
        if name not in columns:
            op.add_column(table, sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {
        col["name"]
        for col in inspector.get_columns("wb_auto_promo_price_recommendations")
    }
    table = "wb_auto_promo_price_recommendations"
    for name in (
        "applied_at",
        "raw_payload",
        "recommended_discount",
        "recommended_full_price",
        "recommended_discounted_price",
        "max_auto_promo_price",
        "current_discounted_price",
        "current_discount",
        "current_full_price",
    ):
        if name in columns:
            op.drop_column(table, name)
