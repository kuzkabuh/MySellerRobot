"""Add Ozon enrichment tables and marketplace seller metadata.

Revision ID: 20260517_0017
Revises: 20260517_0016
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260517_0017"
down_revision: str | None = "20260517_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB, "postgresql")


def created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def updated_at_column() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade() -> None:
    op.add_column(
        "marketplace_accounts",
        sa.Column("last_order_poll_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "marketplace_accounts",
        sa.Column("seller_external_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "marketplace_accounts",
        sa.Column("seller_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "marketplace_accounts",
        sa.Column("seller_legal_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "marketplace_accounts",
        sa.Column("seller_info_payload", json_type, nullable=True),
    )
    op.create_index(
        "ix_marketplace_accounts_seller_external_id",
        "marketplace_accounts",
        ["seller_external_id"],
    )

    op.create_table(
        "marketplace_warehouses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id")),
        sa.Column("marketplace", sa.String(length=16), nullable=False),
        sa.Column("external_warehouse_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("warehouse_type", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", json_type, nullable=False, server_default="{}"),
        created_at_column(),
        updated_at_column(),
        sa.UniqueConstraint(
            "marketplace_account_id",
            "marketplace",
            "external_warehouse_id",
            name="uq_marketplace_warehouses_external",
        ),
    )
    op.create_index(
        "ix_marketplace_warehouses_account",
        "marketplace_warehouses",
        ["marketplace_account_id", "marketplace"],
    )

    op.create_table(
        "ozon_price_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id")),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("ozon_product_id", sa.String(length=128), nullable=True),
        sa.Column("offer_id", sa.String(length=255), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("old_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("marketing_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("min_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency_code", sa.String(length=16), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", json_type, nullable=False, server_default="{}"),
        created_at_column(),
        updated_at_column(),
        sa.UniqueConstraint(
            "marketplace_account_id",
            "offer_id",
            "synced_at",
            name="uq_ozon_price_snapshots_offer_synced",
        ),
    )
    op.create_index(
        "ix_ozon_price_snapshots_product_latest",
        "ozon_price_snapshots",
        ["product_id", "synced_at"],
    )

    op.create_table(
        "ozon_promos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id")),
        sa.Column("external_promo_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("date_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=128), nullable=True),
        sa.Column("raw_payload", json_type, nullable=False, server_default="{}"),
        created_at_column(),
        updated_at_column(),
        sa.UniqueConstraint(
            "marketplace_account_id",
            "external_promo_id",
            name="uq_ozon_promos",
        ),
    )

    op.create_table(
        "ozon_promo_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("promo_id", sa.Integer(), sa.ForeignKey("ozon_promos.id", ondelete="CASCADE")),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id")),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("ozon_product_id", sa.String(length=128), nullable=True),
        sa.Column("offer_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=128), nullable=True),
        sa.Column("action_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("max_action_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("raw_payload", json_type, nullable=False, server_default="{}"),
        created_at_column(),
        updated_at_column(),
        sa.UniqueConstraint("promo_id", "offer_id", name="uq_ozon_promo_products_offer"),
    )


def downgrade() -> None:
    op.drop_table("ozon_promo_products")
    op.drop_table("ozon_promos")
    op.drop_index("ix_ozon_price_snapshots_product_latest", table_name="ozon_price_snapshots")
    op.drop_table("ozon_price_snapshots")
    op.drop_index("ix_marketplace_warehouses_account", table_name="marketplace_warehouses")
    op.drop_table("marketplace_warehouses")
    op.drop_index("ix_marketplace_accounts_seller_external_id", table_name="marketplace_accounts")
    op.drop_column("marketplace_accounts", "seller_info_payload")
    op.drop_column("marketplace_accounts", "seller_legal_name")
    op.drop_column("marketplace_accounts", "seller_name")
    op.drop_column("marketplace_accounts", "seller_external_id")
    op.drop_column("marketplace_accounts", "last_order_poll_at")
