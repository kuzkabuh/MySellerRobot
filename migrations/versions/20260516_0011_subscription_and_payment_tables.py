"""Add subscription and payment tables for monetization.

Revision ID: 20260516_0011
Revises: 20260516_0010
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260516_0011"
down_revision: str | None = "20260516_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create subscription_tiers table
    op.create_table(
        "subscription_tiers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_monthly", sa.Numeric(10, 2), nullable=False),
        sa.Column("price_yearly", sa.Numeric(10, 2), nullable=True),
        sa.Column("max_marketplace_accounts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_orders_per_month", sa.Integer(), nullable=True),
        sa.Column("max_products", sa.Integer(), nullable=True),
        sa.Column("feature_web_cabinet", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("feature_analytics", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("feature_plan_fact", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("feature_break_even", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("feature_stock_forecast", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("feature_alerts", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("feature_api_access", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("feature_priority_support", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_subscription_tiers_code", "subscription_tiers", ["code"])

    # Create user_subscriptions table
    op.create_table(
        "user_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tier_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "CANCELLED", "EXPIRED", "TRIAL", name="subscriptionstatus"),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_trial", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_provider", sa.String(32), nullable=True),
        sa.Column("payment_id", sa.String(128), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tier_id"], ["subscription_tiers.id"]),
        sa.UniqueConstraint("user_id", "tier_id", "started_at"),
    )
    op.create_index("ix_user_subscriptions_user_id", "user_subscriptions", ["user_id"])
    op.create_index("ix_user_subscriptions_status", "user_subscriptions", ["status"])
    op.create_index("ix_user_subscriptions_started_at", "user_subscriptions", ["started_at"])
    op.create_index("ix_user_subscriptions_expires_at", "user_subscriptions", ["expires_at"])

    # Create payments table
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_payment_id", sa.String(128), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="RUB"),
        sa.Column(
            "status",
            sa.Enum("PENDING", "SUCCEEDED", "CANCELLED", "FAILED", name="paymentstatus"),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("payment_method", sa.String(64), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["user_subscriptions.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("provider", "provider_payment_id"),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_provider", "payments", ["provider"])
    op.create_index("ix_payments_provider_payment_id", "payments", ["provider_payment_id"])
    op.create_index("ix_payments_status", "payments", ["status"])

    # Insert default tiers
    op.execute("""
        INSERT INTO subscription_tiers (
            code, name, description, price_monthly, price_yearly,
            max_marketplace_accounts, max_orders_per_month, max_products,
            feature_web_cabinet, feature_analytics, feature_plan_fact,
            feature_break_even, feature_stock_forecast, feature_alerts,
            feature_api_access, feature_priority_support,
            is_active, sort_order, created_at
        ) VALUES
        (
            'free', 'FREE', 'Бесплатный тариф для начинающих селлеров',
            0, 0,
            1, 100, NULL,
            true, false, false,
            false, false, false,
            false, false,
            true, 0, NOW()
        ),
        (
            'basic', 'BASIC', 'Базовый тариф для малого бизнеса',
            490, 4900,
            2, 1000, NULL,
            true, true, false,
            false, false, true,
            false, false,
            true, 1, NOW()
        ),
        (
            'pro', 'PRO', 'Профессиональный тариф для активных продавцов',
            1490, 14900,
            5, NULL, NULL,
            true, true, true,
            true, true, true,
            false, true,
            true, 2, NOW()
        ),
        (
            'enterprise', 'ENTERPRISE', 'Корпоративный тариф с индивидуальными условиями',
            0, 0,
            999, NULL, NULL,
            true, true, true,
            true, true, true,
            true, true,
            true, 3, NOW()
        )
    """)


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("user_subscriptions")
    op.drop_table("subscription_tiers")
    op.execute("DROP TYPE IF EXISTS subscriptionstatus")
    op.execute("DROP TYPE IF EXISTS paymentstatus")
