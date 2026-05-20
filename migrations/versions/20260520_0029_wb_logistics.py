"""Add WB logistics tariff tables and order_items logistics tracking fields.

Revision ID: 20260520_0029_wb_logistics
Revises: 20260520_0028_ozon_commission
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

marketplace_enum = postgresql.ENUM("WB", "OZON", name="marketplace", create_type=False)

revision: str = "20260520_0029_wb_logistics"
down_revision: str | None = "20260520_0028_ozon_commission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wb_logistics_tariff_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tariff_date", sa.Date, nullable=False, index=True),
        sa.Column("version_hash", sa.String(64), nullable=True, index=True),
        sa.Column("source", sa.String(64), nullable=False, default="wb_api"),
        sa.Column("rows_count", sa.Integer, nullable=False, default=0),
        sa.Column("is_active", sa.Boolean, nullable=False, default=False, index=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_wb_logistics_versions_active",
        "wb_logistics_tariff_versions",
        ["is_active"],
    )
    op.create_index(
        "ix_wb_logistics_versions_tariff_date",
        "wb_logistics_tariff_versions",
        ["tariff_date"],
    )

    op.create_table(
        "wb_logistics_tariff_rates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "version_id",
            sa.Integer,
            sa.ForeignKey("wb_logistics_tariff_versions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("warehouse_name", sa.String(255), nullable=False, index=True),
        sa.Column("geo_name", sa.String(255), nullable=True),
        sa.Column("sales_model", sa.String(32), nullable=False, index=True),
        sa.Column("fbo_base_tariff", sa.Numeric(12, 4), nullable=True),
        sa.Column("fbo_liter_tariff", sa.Numeric(12, 4), nullable=True),
        sa.Column("fbo_coefficient_expr", sa.String(512), nullable=True),
        sa.Column("fbs_base_tariff", sa.Numeric(12, 4), nullable=True),
        sa.Column("fbs_liter_tariff", sa.Numeric(12, 4), nullable=True),
        sa.Column("fbs_coefficient_expr", sa.String(512), nullable=True),
        sa.Column("logistics_coefficient_percent", sa.Numeric(7, 4), nullable=True),
        sa.Column("raw_payload", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_wb_logistics_rates_lookup",
        "wb_logistics_tariff_rates",
        ["version_id", "warehouse_name", "sales_model"],
    )

    op.add_column(
        "order_items",
        sa.Column("wb_logistics_amount_planned", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("wb_logistics_base_tariff", sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("wb_logistics_warehouse_coefficient_percent", sa.Numeric(7, 4), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("wb_logistics_localization_index", sa.Numeric(7, 4), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("wb_logistics_distribution_index_percent", sa.Numeric(7, 4), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "wb_logistics_distribution_surcharge_amount",
            sa.Numeric(12, 2),
            nullable=True,
        ),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "wb_logistics_tariff_version_id",
            sa.Integer,
            sa.ForeignKey("wb_logistics_tariff_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "wb_logistics_tariff_rate_id",
            sa.Integer,
            sa.ForeignKey("wb_logistics_tariff_rates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "order_items",
        sa.Column("wb_logistics_source", sa.String(64), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("wb_logistics_confidence", sa.String(32), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("wb_reverse_logistics_amount_planned", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "wb_reverse_logistics_amount_planned")
    op.drop_column("order_items", "wb_logistics_confidence")
    op.drop_column("order_items", "wb_logistics_source")
    op.drop_column("order_items", "wb_logistics_tariff_rate_id")
    op.drop_column("order_items", "wb_logistics_tariff_version_id")
    op.drop_column("order_items", "wb_logistics_distribution_surcharge_amount")
    op.drop_column("order_items", "wb_logistics_distribution_index_percent")
    op.drop_column("order_items", "wb_logistics_localization_index")
    op.drop_column("order_items", "wb_logistics_warehouse_coefficient_percent")
    op.drop_column("order_items", "wb_logistics_base_tariff")
    op.drop_column("order_items", "wb_logistics_amount_planned")
    op.drop_table("wb_logistics_tariff_rates")
    op.drop_table("wb_logistics_tariff_versions")
