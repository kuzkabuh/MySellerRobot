"""Add MRC price to products and WB promotions tables.

Revision ID: 20260521_0031_wb_mrc_and_promotions
Revises: 20260520_0030_ozon_balance
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260521_0031_wb_mrc_and_promotions"
down_revision: str | None = "20260520_0030_ozon_balance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add mrc_price to products
    op.add_column(
        "products",
        sa.Column("mrc_price", sa.Numeric(12, 2), nullable=True),
    )

    # Create wb_promotions table
    op.create_table(
        "wb_promotions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("wb_promotion_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("name", sa.String(512), nullable=True),
        sa.Column("promotion_type", sa.String(64), nullable=True),
        sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active_today", sa.Boolean(), nullable=False, server_default=sa.text("false"), index=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("marketplace_account_id", "wb_promotion_id", name="uq_wb_promotions_account_promo"),
        sa.Index("ix_wb_promotions_account_active", "marketplace_account_id", "is_active_today"),
        sa.Index("ix_wb_promotions_dates", "start_datetime", "end_datetime"),
    )

    # Create wb_promotion_nomenclatures table
    op.create_table(
        "wb_promotion_nomenclatures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("wb_promotion_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("wb_nm_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("in_action", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("current_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency_code", sa.String(16), nullable=True),
        sa.Column("plan_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("current_discount", sa.Numeric(7, 4), nullable=True),
        sa.Column("plan_discount", sa.Numeric(7, 4), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "marketplace_account_id", "wb_promotion_id", "wb_nm_id", "in_action",
            name="uq_wb_promo_nomenclatures_account_promo_nm_action",
        ),
        sa.Index("ix_wb_promo_nomenclatures_nm", "marketplace_account_id", "wb_nm_id"),
        sa.Index("ix_wb_promo_nomenclatures_promo", "marketplace_account_id", "wb_promotion_id"),
        sa.Index("ix_wb_promo_nomenclatures_synced", "marketplace_account_id", "synced_at"),
    )


def downgrade() -> None:
    op.drop_table("wb_promotion_nomenclatures")
    op.drop_table("wb_promotions")
    op.drop_column("products", "mrc_price")
