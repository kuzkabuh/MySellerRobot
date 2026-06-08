"""Add seller_payout_estimated and tax_rate fields for correct profit calculation.

Revision ID: 20260516_0010
Revises: 20260516_0009
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260516_0010"
down_revision: str | None = "20260516_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add seller_payout_estimated field to order_items
    # This represents the actual payout to seller after marketplace deductions
    op.add_column(
        "order_items",
        sa.Column("seller_payout_estimated", sa.Numeric(12, 2), nullable=True),
    )

    # Add tax_rate field to order_items
    # This stores the tax rate used for profit calculation
    op.add_column(
        "order_items",
        sa.Column("tax_rate", sa.Numeric(5, 4), nullable=True),
    )

    # Backfill seller_payout_estimated from payout_amount_estimated for existing records
    op.execute("""
        UPDATE order_items
        SET seller_payout_estimated = payout_amount_estimated
        WHERE payout_amount_estimated IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_column("order_items", "tax_rate")
    op.drop_column("order_items", "seller_payout_estimated")
