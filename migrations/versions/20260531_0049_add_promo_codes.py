"""add promo codes system

Revision ID: 20260531_0049
Revises: 20260531_0048
Create Date: 2026-05-31
"""

import sqlalchemy as sa
from alembic import op

revision = "20260531_0049"
down_revision = "20260531_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("promo_type", sa.String(32), nullable=False),
        sa.Column("discount_percent", sa.Integer(), nullable=True),
        sa.Column("discount_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("free_days", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="RUB"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_uses_total", sa.Integer(), nullable=True),
        sa.Column("max_uses_per_user", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_order_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "only_for_new_users",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_by_admin_id", sa.Integer(), nullable=True),
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
        ),
    )

    op.create_table(
        "promo_code_tariffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "promo_code_id",
            sa.Integer(),
            sa.ForeignKey("promo_codes.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "tariff_id",
            sa.Integer(),
            sa.ForeignKey("subscription_tiers.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.UniqueConstraint("promo_code_id", "tariff_id"),
    )

    op.create_table(
        "promo_code_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "promo_code_id",
            sa.Integer(),
            sa.ForeignKey("promo_codes.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("period", sa.String(16), nullable=False),
        sa.UniqueConstraint("promo_code_id", "period"),
    )

    op.create_table(
        "promo_code_usages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "promo_code_id",
            sa.Integer(),
            sa.ForeignKey("promo_codes.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            sa.Integer(),
            sa.ForeignKey("user_subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "payment_id",
            sa.Integer(),
            sa.ForeignKey("payments.id", ondelete="SET NULL"),
            index=True,
            nullable=True,
        ),
        sa.Column(
            "tariff_id",
            sa.Integer(),
            sa.ForeignKey("subscription_tiers.id"),
            index=True,
            nullable=False,
        ),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("original_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("final_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("free_days_applied", sa.Integer(), nullable=True),
        sa.Column(
            "used_at",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="reserved",
            index=True,
        ),
        sa.Column("provider_payment_id", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("promo_code_usages")
    op.drop_table("promo_code_periods")
    op.drop_table("promo_code_tariffs")
    op.drop_table("promo_codes")
