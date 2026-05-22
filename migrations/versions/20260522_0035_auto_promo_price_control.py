"""Add wb_auto_promo_price_recommendations and wb_auto_promotion_conditions tables.

Revision ID: 20260522_0035_auto_promo_price_control
Revises: 20260522_0034_mrc_pricing_settings
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_0035_auto_promo_price_control"
down_revision: str | None = "20260522_0034_mrc_pricing_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wb_auto_promotion_conditions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("wb_promotion_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("wb_nm_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("seller_article", sa.String(256), nullable=True),
        sa.Column("required_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("current_wb_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("source", sa.String(64), nullable=False, server_default=sa.text("'api'")),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_auto_promo_conditions_account_promo_nm",
        "wb_auto_promotion_conditions",
        ["marketplace_account_id", "wb_promotion_id", "wb_nm_id"],
    )

    op.create_table(
        "wb_auto_promo_price_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("wb_nm_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("wb_promotion_id", sa.BigInteger(), nullable=True),
        sa.Column("mrc_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("current_wb_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("required_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("recommended_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("min_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("mrc_lower_bound", sa.Numeric(12, 2), nullable=False),
        sa.Column("mrc_upper_bound", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(64), nullable=False, server_default=sa.text("'calculation'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_auto_promo_recs_account_status",
        "wb_auto_promo_price_recommendations",
        ["marketplace_account_id", "status"],
    )
    op.create_index(
        "ix_auto_promo_recs_product",
        "wb_auto_promo_price_recommendations",
        ["product_id"],
    )

    op.create_table(
        "wb_price_change_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("wb_nm_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("old_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("new_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False, server_default=sa.text("'auto_promotion'")),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_price_change_history_nm",
        "wb_price_change_history",
        ["wb_nm_id"],
    )


def downgrade() -> None:
    op.drop_table("wb_price_change_history")
    op.drop_table("wb_auto_promo_price_recommendations")
    op.drop_table("wb_auto_promotion_conditions")
