"""Add economy confidence and low margin setting.

Revision ID: 20260516_0009
Revises: 20260515_0008
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260516_0009"
down_revision: str | None = "20260515_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "low_margin_threshold_percent",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="10.00",
        ),
    )
    op.add_column("order_items", sa.Column("commission_source", sa.String(64), nullable=True))
    op.add_column("order_items", sa.Column("logistics_source", sa.String(64), nullable=True))
    op.add_column(
        "order_items",
        sa.Column(
            "economy_confidence",
            sa.String(32),
            nullable=False,
            server_default="PRELIMINARY",
        ),
    )
    op.add_column(
        "profit_snapshots",
        sa.Column(
            "economy_confidence",
            sa.String(32),
            nullable=False,
            server_default="PRELIMINARY",
        ),
    )


def downgrade() -> None:
    op.drop_column("profit_snapshots", "economy_confidence")
    op.drop_column("order_items", "economy_confidence")
    op.drop_column("order_items", "logistics_source")
    op.drop_column("order_items", "commission_source")
    op.drop_column("users", "low_margin_threshold_percent")
