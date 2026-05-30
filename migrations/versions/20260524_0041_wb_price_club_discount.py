"""Add club_discount and club_discounted_price to wb_product_prices.

Revision ID: 20260524_0041_wb_price_club_discount
Revises: 20260523_0040_wb_product_prices
Create Date: 2026-05-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260524_0041_wb_price_club_discount"
down_revision = "20260523_0040_wb_product_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("wb_product_prices")]

    if "club_discount" not in columns:
        op.add_column(
            "wb_product_prices",
            sa.Column("club_discount", sa.Integer(), nullable=True, server_default=sa.text("0")),
        )

    if "club_discounted_price" not in columns:
        op.add_column(
            "wb_product_prices",
            sa.Column("club_discounted_price", sa.Numeric(12, 2), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("wb_product_prices")]

    if "club_discounted_price" in columns:
        op.drop_column("wb_product_prices", "club_discounted_price")

    if "club_discount" in columns:
        op.drop_column("wb_product_prices", "club_discount")
