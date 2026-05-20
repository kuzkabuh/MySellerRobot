"""Add Ozon commission base price and commission tracking fields to order_items.

Revision ID: 20260520_0028_ozon_commission_fields
Revises: 20260520_0027_commission_tariffs
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_0028_ozon_commission_fields"
down_revision: str | None = "20260520_0027_commission_tariffs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("ozon_commission_base_price", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("commission_percent_planned", sa.Numeric(7, 4), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("commission_amount_planned", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "commission_rate_version_id",
            sa.Integer,
            sa.ForeignKey("marketplace_commission_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "commission_rate_id",
            sa.Integer,
            sa.ForeignKey("marketplace_commission_rates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "order_items",
        sa.Column("commission_match_status", sa.String(32), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("commission_calculation_confidence", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "commission_calculation_confidence")
    op.drop_column("order_items", "commission_match_status")
    op.drop_column("order_items", "commission_rate_id")
    op.drop_column("order_items", "commission_rate_version_id")
    op.drop_column("order_items", "commission_amount_planned")
    op.drop_column("order_items", "commission_percent_planned")
    op.drop_column("order_items", "ozon_commission_base_price")
