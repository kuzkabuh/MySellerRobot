"""Add Ozon balance fields to account_balance_snapshots.

Revision ID: 20260520_0030_ozon_balance
Revises: 20260520_0029_wb_logistics
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_0030_ozon_balance"
down_revision: str | None = "20260520_0029_wb_logistics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "account_balance_snapshots",
        sa.Column("opening_balance", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "account_balance_snapshots",
        sa.Column("accrued", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "account_balance_snapshots",
        sa.Column("payments_total", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "account_balance_snapshots",
        sa.Column("period_from", sa.Date(), nullable=True),
    )
    op.add_column(
        "account_balance_snapshots",
        sa.Column("period_to", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("account_balance_snapshots", "period_to")
    op.drop_column("account_balance_snapshots", "period_from")
    op.drop_column("account_balance_snapshots", "payments_total")
    op.drop_column("account_balance_snapshots", "accrued")
    op.drop_column("account_balance_snapshots", "opening_balance")
