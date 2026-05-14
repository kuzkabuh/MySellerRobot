"""version: 1.0.0
description: Extend sales events for buyout notifications.
updated: 2026-05-14

Revision ID: 20260514_0006
Revises: 20260514_0005
Create Date: 2026-05-14 21:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260514_0006"
down_revision: str | None = "20260514_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'SALE_COMPLETED'")
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'SALE_DIGEST'")

    sale_event_type = postgresql.ENUM(
        "BUYOUT",
        "SALE_COMPLETED",
        "DELIVERED_TO_CUSTOMER",
        name="saleeventtype",
    )
    sale_event_type.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "sales_events",
        sa.Column("related_order_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sales_events",
        sa.Column("related_order_item_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sales_events",
        sa.Column(
            "event_type",
            sale_event_type,
            nullable=False,
            server_default="SALE_COMPLETED",
        ),
    )
    op.add_column("sales_events", sa.Column("product_id", sa.Integer(), nullable=True))
    op.add_column("sales_events", sa.Column("seller_article", sa.String(length=255), nullable=True))
    op.add_column(
        "sales_events",
        sa.Column("marketplace_article", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "sales_events",
        sa.Column("expected_payout", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "sales_events",
        sa.Column("estimated_profit", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "sales_events",
        sa.Column("actual_profit", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "sales_events",
        sa.Column("notification_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_sales_events_related_order_id_orders",
        "sales_events",
        "orders",
        ["related_order_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sales_events_related_order_item_id_order_items",
        "sales_events",
        "order_items",
        ["related_order_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sales_events_product_id_products",
        "sales_events",
        "products",
        ["product_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sales_events_related_order_id", "sales_events", ["related_order_id"])
    op.create_index(
        "ix_sales_events_related_order_item_id",
        "sales_events",
        ["related_order_item_id"],
    )
    op.create_index("ix_sales_events_event_type", "sales_events", ["event_type"])
    op.create_index("ix_sales_events_seller_article", "sales_events", ["seller_article"])
    op.create_index(
        "ix_sales_events_marketplace_article",
        "sales_events",
        ["marketplace_article"],
    )


def downgrade() -> None:
    op.drop_index("ix_sales_events_marketplace_article", table_name="sales_events")
    op.drop_index("ix_sales_events_seller_article", table_name="sales_events")
    op.drop_index("ix_sales_events_event_type", table_name="sales_events")
    op.drop_index("ix_sales_events_related_order_item_id", table_name="sales_events")
    op.drop_index("ix_sales_events_related_order_id", table_name="sales_events")
    op.drop_constraint("fk_sales_events_product_id_products", "sales_events", type_="foreignkey")
    op.drop_constraint(
        "fk_sales_events_related_order_item_id_order_items",
        "sales_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_sales_events_related_order_id_orders",
        "sales_events",
        type_="foreignkey",
    )
    op.drop_column("sales_events", "notification_sent_at")
    op.drop_column("sales_events", "actual_profit")
    op.drop_column("sales_events", "estimated_profit")
    op.drop_column("sales_events", "expected_payout")
    op.drop_column("sales_events", "marketplace_article")
    op.drop_column("sales_events", "seller_article")
    op.drop_column("sales_events", "product_id")
    op.drop_column("sales_events", "event_type")
    op.drop_column("sales_events", "related_order_item_id")
    op.drop_column("sales_events", "related_order_id")
    postgresql.ENUM(name="saleeventtype").drop(op.get_bind(), checkfirst=True)
