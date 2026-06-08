"""extend subscription_tiers for admin tariff management

Revision ID: 20260531_0048
Revises: 20260531_0047
Create Date: 2026-05-31
"""

import sqlalchemy as sa
from alembic import op

revision = "20260531_0048"
down_revision = "20260531_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "price_3_months",
        sa.Column("price_3_months", sa.Numeric(10, 2), nullable=True),
    )
    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "price_6_months",
        sa.Column("price_6_months", sa.Numeric(10, 2), nullable=True),
    )
    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "currency",
        sa.Column("currency", sa.String(3), nullable=False, server_default="RUB"),
    )
    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "max_users",
        sa.Column("max_users", sa.Integer(), nullable=True),
    )
    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "sync_interval_minutes",
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="180"),
    )
    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "analytics_depth_days",
        sa.Column("analytics_depth_days", sa.Integer(), nullable=False, server_default="30"),
    )
    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "feature_auto_promotions",
        sa.Column(
            "feature_auto_promotions",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "feature_telegram_notifications",
        sa.Column(
            "feature_telegram_notifications",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "is_public",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    existing_codes = {
        row[0] for row in conn.execute(sa.text("SELECT code FROM subscription_tiers")).fetchall()
    }

    if "business" not in existing_codes:
        conn.execute(sa.text("""
                INSERT INTO subscription_tiers
                    (code, name, description, price_monthly, price_3_months, price_6_months,
                     price_yearly, currency, max_marketplace_accounts, max_orders_per_month,
                     max_products, max_users, sync_interval_minutes, analytics_depth_days,
                     feature_web_cabinet, feature_analytics, feature_plan_fact,
                     feature_break_even, feature_stock_forecast, feature_alerts,
                     feature_api_access, feature_priority_support, feature_mrc_pricing,
                     feature_auto_promotions, feature_telegram_notifications,
                     is_active, is_public, sort_order, created_at, updated_at)
                VALUES
                    ('business', 'BUSINESS',
                     'Максимальные возможности для растущих команд и агентств.',
                     4990, 13490, 24990, 49900, 'RUB',
                     10, NULL, NULL, 5, 60, 365,
                     true, true, true, true, true, true,
                     true, true, true, true, true,
                     true, true, 25,
                     now(), now())
                """))

    conn.execute(sa.text("""
            UPDATE subscription_tiers
            SET feature_telegram_notifications = true
            WHERE feature_telegram_notifications IS NULL
               OR feature_telegram_notifications = false
               AND code IN ('basic', 'pro', 'enterprise', 'business')
            """))

    conn.execute(sa.text("""
            UPDATE subscription_tiers
            SET feature_auto_promotions = true
            WHERE code IN ('pro', 'business', 'enterprise')
            """))

    conn.execute(sa.text("""
            UPDATE subscription_tiers
            SET is_public = true
            WHERE is_public IS NULL
            """))

    conn.execute(sa.text("""
            UPDATE subscription_tiers
            SET sync_interval_minutes = CASE code
                WHEN 'free' THEN 180
                WHEN 'basic' THEN 120
                WHEN 'pro' THEN 60
                WHEN 'business' THEN 30
                WHEN 'enterprise' THEN 15
                ELSE 180
            END
            WHERE sync_interval_minutes IS NULL OR sync_interval_minutes = 180
            """))

    conn.execute(sa.text("""
            UPDATE subscription_tiers
            SET analytics_depth_days = CASE code
                WHEN 'free' THEN 30
                WHEN 'basic' THEN 60
                WHEN 'pro' THEN 180
                WHEN 'business' THEN 365
                WHEN 'enterprise' THEN 730
                ELSE 30
            END
            WHERE analytics_depth_days IS NULL OR analytics_depth_days = 30
            """))


def downgrade() -> None:
    op.drop_column("subscription_tiers", "is_public")
    op.drop_column("subscription_tiers", "feature_telegram_notifications")
    op.drop_column("subscription_tiers", "feature_auto_promotions")
    op.drop_column("subscription_tiers", "analytics_depth_days")
    op.drop_column("subscription_tiers", "sync_interval_minutes")
    op.drop_column("subscription_tiers", "max_users")
    op.drop_column("subscription_tiers", "currency")
    op.drop_column("subscription_tiers", "price_6_months")
    op.drop_column("subscription_tiers", "price_3_months")


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col"
        ),
        {"table": table_name, "col": column_name},
    )
    return result.scalar_one_or_none() is not None


def _add_column_if_not_exists(conn, table_name: str, column_name: str, column: sa.Column) -> None:
    if not _column_exists(conn, table_name, column_name):
        op.add_column(table_name, column)
