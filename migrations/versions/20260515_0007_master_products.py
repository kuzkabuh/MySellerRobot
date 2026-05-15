"""Add master products and marketplace product links.

Revision ID: 20260515_0007
Revises: 20260514_0006
Create Date: 2026-05-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260515_0007"
down_revision: str | None = "20260514_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "master_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("canonical_sku", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=True),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "canonical_sku", name="uq_master_products_user_sku"),
    )
    op.create_index("ix_master_products_user_id", "master_products", ["user_id"])
    op.create_index(
        "ix_master_products_user_active",
        "master_products",
        ["user_id", "is_active"],
    )

    op.create_table(
        "master_product_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("master_product_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column(
            "marketplace",
            postgresql.ENUM("WB", "OZON", name="marketplace", create_type=False),
            nullable=False,
        ),
        sa.Column("seller_article", sa.String(length=255), nullable=True),
        sa.Column("marketplace_article", sa.String(length=255), nullable=True),
        sa.Column("match_method", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["master_product_id"],
            ["master_products.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_master_product_links_product"),
        sa.UniqueConstraint(
            "master_product_id",
            "marketplace",
            "seller_article",
            name="uq_master_product_links_marketplace_article",
        ),
    )
    op.create_index(
        "ix_master_product_links_master",
        "master_product_links",
        ["master_product_id", "marketplace"],
    )
    op.create_index(
        "ix_master_product_links_master_product_id",
        "master_product_links",
        ["master_product_id"],
    )
    op.create_index(
        "ix_master_product_links_marketplace",
        "master_product_links",
        ["marketplace"],
    )


def downgrade() -> None:
    op.drop_index("ix_master_product_links_marketplace", table_name="master_product_links")
    op.drop_index("ix_master_product_links_master_product_id", table_name="master_product_links")
    op.drop_index("ix_master_product_links_master", table_name="master_product_links")
    op.drop_table("master_product_links")
    op.drop_index("ix_master_products_user_active", table_name="master_products")
    op.drop_index("ix_master_products_user_id", table_name="master_products")
    op.drop_table("master_products")
