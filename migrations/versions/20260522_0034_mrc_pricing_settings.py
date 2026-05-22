"""Add mrc_pricing_settings table for user-configurable MRC coefficients.

Revision ID: 20260522_0034_mrc_pricing_settings
Revises: 20260522_0001_fix_mrc_imports_updated_at
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_0034_mrc_pricing_settings"
down_revision: str | None = "20260522_0001_fix_mrc_imports_updated_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mrc_pricing_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("marketplace", sa.String(16), nullable=False, server_default=sa.text("'wb'")),
        sa.Column("default_discount_percent", sa.Numeric(5, 2), nullable=False, server_default=sa.text("'75.00'")),
        sa.Column("full_price_multiplier", sa.Numeric(5, 2), nullable=False, server_default=sa.text("'4.00'")),
        sa.Column("allowed_action_price_deviation_percent", sa.Numeric(5, 2), nullable=False, server_default=sa.text("'10.00'")),
        sa.Column("auto_promo_check_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auto_add_to_promotions", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auto_price_for_auto_promotions", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "marketplace_account_id", name="uq_mrc_settings_user_account"),
    )


def downgrade() -> None:
    op.drop_table("mrc_pricing_settings")
