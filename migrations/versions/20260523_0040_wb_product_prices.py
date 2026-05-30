"""Create wb_product_prices table for storing current WB product prices.

Revision ID: 20260523_0040_wb_product_prices
Revises: 20260523_0039_price_history_upload_fields
Create Date: 2026-05-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20260523_0040_wb_product_prices"
down_revision = "20260523_0039_price_history_upload_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "wb_product_prices" not in existing_tables:
        op.create_table(
            "wb_product_prices",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "marketplace_account_id",
                sa.Integer(),
                sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("wb_nm_id", sa.BigInteger(), nullable=False, index=True),
            sa.Column("price", sa.Numeric(12, 2), nullable=False),
            sa.Column("discount", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("discounted_price", sa.Numeric(12, 2), nullable=False),
            sa.Column(
                "currency_code", sa.String(16), nullable=False, server_default=sa.text("'RUB'")
            ),
            sa.Column("raw_payload", sa.JSON(), nullable=True),
            sa.Column(
                "synced_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "marketplace_account_id", "wb_nm_id", name="uq_wb_product_prices_account_nm"
            ),
        )
        op.create_index(
            "ix_wb_product_prices_account", "wb_product_prices", ["marketplace_account_id"]
        )
        op.create_index("ix_wb_product_prices_nm", "wb_product_prices", ["wb_nm_id"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "wb_product_prices" in existing_tables:
        op.drop_table("wb_product_prices")
