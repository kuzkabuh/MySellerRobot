"""Make price and discounted_price nullable in wb_product_prices.

The WB goods/filter API may return prices only inside sizes[] without
a top-level price field. Allow NULL so a single missing price does not
break the entire sync.

Revision ID: 20260524_0042_wb_price_nullable
Revises: 20260524_0041_wb_price_club_discount
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa

revision = "20260524_0042_wb_price_nullable"
down_revision = "20260524_0041_wb_price_club_discount"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {col["name"]: col for col in inspector.get_columns("wb_product_prices")}

    price_col = columns.get("price")
    if price_col and not price_col.get("nullable", True):
        op.alter_column("wb_product_prices", "price", nullable=True)

    discounted_price_col = columns.get("discounted_price")
    if discounted_price_col and not discounted_price_col.get("nullable", True):
        op.alter_column("wb_product_prices", "discounted_price", nullable=True)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {col["name"]: col for col in inspector.get_columns("wb_product_prices")}

    price_col = columns.get("price")
    if price_col and price_col.get("nullable", True):
        op.alter_column("wb_product_prices", "price", nullable=False)

    discounted_price_col = columns.get("discounted_price")
    if discounted_price_col and discounted_price_col.get("nullable", True):
        op.alter_column("wb_product_prices", "discounted_price", nullable=False)
