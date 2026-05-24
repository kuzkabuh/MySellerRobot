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
        ("wb_condition_discount_percent", sa.Numeric(5, 2)),
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

    condition_columns = {
        col["name"]
        for col in inspector.get_columns("wb_auto_promotion_conditions")
    }
    condition_additions = [
        ("wb_condition_discount_percent", sa.Numeric(5, 2)),
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
    ):
        if name in condition_columns:
            op.drop_column("wb_auto_promotion_conditions", name)
