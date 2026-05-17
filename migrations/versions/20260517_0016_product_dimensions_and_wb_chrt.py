"""Add product dimensions and WB chrt identifiers.

Revision ID: 20260517_0016
Revises: 20260517_0015
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260517_0016"
down_revision: str | None = "20260517_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("chrt_id", sa.String(length=64), nullable=True))
    op.add_column("products", sa.Column("length_cm", sa.Numeric(10, 2), nullable=True))
    op.add_column("products", sa.Column("width_cm", sa.Numeric(10, 2), nullable=True))
    op.add_column("products", sa.Column("height_cm", sa.Numeric(10, 2), nullable=True))
    op.add_column("products", sa.Column("volume_liters", sa.Numeric(12, 3), nullable=True))
    op.add_column("products", sa.Column("dimensions_source", sa.String(length=64), nullable=True))
    op.create_index("ix_products_wb_chrt", "products", ["marketplace_account_id", "chrt_id"])


def downgrade() -> None:
    op.drop_index("ix_products_wb_chrt", table_name="products")
    op.drop_column("products", "dimensions_source")
    op.drop_column("products", "volume_liters")
    op.drop_column("products", "height_cm")
    op.drop_column("products", "width_cm")
    op.drop_column("products", "length_cm")
    op.drop_column("products", "chrt_id")
