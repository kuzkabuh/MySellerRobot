"""Add per-sales-model WB commission columns to products.

Revision ID: 20260520_0025
Revises: 20260520_0024
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_0025"
down_revision: str | None = "20260520_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("commission_fbw", sa.Numeric(7, 4), nullable=True))
    op.add_column("products", sa.Column("commission_fbs", sa.Numeric(7, 4), nullable=True))
    op.add_column("products", sa.Column("commission_dbs", sa.Numeric(7, 4), nullable=True))
    op.add_column("products", sa.Column("commission_edbs", sa.Numeric(7, 4), nullable=True))
    op.add_column("products", sa.Column("commission_pickup", sa.Numeric(7, 4), nullable=True))
    op.add_column("products", sa.Column("commission_booking", sa.Numeric(7, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "commission_booking")
    op.drop_column("products", "commission_pickup")
    op.drop_column("products", "commission_edbs")
    op.drop_column("products", "commission_dbs")
    op.drop_column("products", "commission_fbs")
    op.drop_column("products", "commission_fbw")
