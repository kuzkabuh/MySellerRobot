"""Add marketplace tariff fields to products.

Revision ID: 20260515_0008
Revises: 20260515_0007
Create Date: 2026-05-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260515_0008"
down_revision: str | None = "20260515_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("marketplace_category_id", sa.String(length=128)))
    op.add_column("products", sa.Column("marketplace_commission_rate", sa.Numeric(7, 4)))
    op.add_column("products", sa.Column("marketplace_commission_source", sa.String(length=128)))
    op.create_index(
        "ix_products_marketplace_category",
        "products",
        ["marketplace", "marketplace_category_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_products_marketplace_category", table_name="products")
    op.drop_column("products", "marketplace_commission_source")
    op.drop_column("products", "marketplace_commission_rate")
    op.drop_column("products", "marketplace_category_id")
