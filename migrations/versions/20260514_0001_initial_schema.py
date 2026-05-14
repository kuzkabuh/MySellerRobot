"""initial schema

version: 1.0.0
description: Initial production schema for Seller Profit Bot.
updated: 2026-05-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260514_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    user_status = _pg_enum("ACTIVE", "BLOCKED", name="userstatus")
    marketplace = _pg_enum("WB", "OZON", name="marketplace")
    account_status = _pg_enum("DRAFT", "ACTIVE", "ERROR", "DISABLED", name="accountstatus")
    sale_model = _pg_enum("FBS", "FBO", "rFBS", "DBS", "DBW", name="salemodel")
    calc_type = _pg_enum("ESTIMATED", "ACTUAL", name="calculationtype")
    notification_type = _pg_enum(
        "NEW_ORDER",
        "DAILY_REPORT",
        "FBS_CONTROL",
        "STOCK_ALERT",
        "PROFIT_ALERT",
        name="notificationtype",
    )
    alert_type = _pg_enum(
        "LOSS_ORDER",
        "LOW_MARGIN",
        "MISSING_COST",
        "LOW_STOCK",
        "STOCKOUT_FORECAST",
        "FBS_DEADLINE_RISK",
        "LOGISTICS_GROWTH",
        "BUYOUT_DROP",
        "ORDERS_DROP",
        name="alerttype",
    )
    sync_status = _pg_enum("PENDING", "RUNNING", "SUCCESS", "ERROR", name="syncjobstatus")
    for enum in [
        user_status,
        marketplace,
        account_status,
        sale_model,
        calc_type,
        notification_type,
        alert_type,
        sync_status,
    ]:
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(255)),
        sa.Column("first_name", sa.String(255)),
        sa.Column("status", user_status, nullable=False),
        sa.Column("tariff", sa.String(64), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False),
        sa.Column("subscription_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])

    op.create_table(
        "marketplace_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marketplace", marketplace, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("encrypted_client_id", sa.Text()),
        sa.Column("status", account_status, nullable=False),
        sa.Column("last_success_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notification_settings", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "marketplace", "name", name="uq_accounts_user_marketplace_name"),
    )
    op.create_index("ix_accounts_user_marketplace_active", "marketplace_accounts", ["user_id", "marketplace", "is_active"])

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marketplace", marketplace, nullable=False),
        sa.Column("external_product_id", sa.String(128), nullable=False),
        sa.Column("seller_article", sa.String(255)),
        sa.Column("marketplace_article", sa.String(255)),
        sa.Column("title", sa.String(1024)),
        sa.Column("brand", sa.String(255)),
        sa.Column("image_url", sa.Text()),
        sa.Column("category", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("marketplace_account_id", "marketplace", "external_product_id", name="uq_products_account_marketplace_external"),
    )
    op.create_index("ix_products_user_article", "products", ["user_id", "seller_article"])

    op.create_table(
        "product_cost_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cost_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("package_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("additional_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cost_history_product_period", "product_cost_history", ["product_id", "valid_from", "valid_to"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marketplace", marketplace, nullable=False),
        sa.Column("order_external_id", sa.String(255), nullable=False),
        sa.Column("posting_number", sa.String(255)),
        sa.Column("assembly_id", sa.String(255)),
        sa.Column("srid", sa.String(255)),
        sa.Column("order_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sale_model", sale_model),
        sa.Column("status", sa.String(128), nullable=False),
        sa.Column("warehouse", sa.String(255)),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("marketplace_account_id", "marketplace", "order_external_id", name="uq_orders_account_marketplace_external"),
    )
    op.create_index("ix_orders_user_date", "orders", ["user_id", "order_date"])
    op.create_index("ix_orders_deadline_status", "orders", ["deadline_at", "status"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("seller_article", sa.String(255)),
        sa.Column("marketplace_article", sa.String(255)),
        sa.Column("title", sa.String(1024)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("buyer_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("seller_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("discounted_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("payout_amount_estimated", sa.Numeric(12, 2)),
        sa.Column("commission_estimated", sa.Numeric(12, 2)),
        sa.Column("logistics_estimated", sa.Numeric(12, 2)),
        sa.Column("other_marketplace_expenses_estimated", sa.Numeric(12, 2)),
        sa.Column("cost_price_used", sa.Numeric(12, 2)),
        sa.Column("package_cost_used", sa.Numeric(12, 2)),
        sa.Column("tax_amount_estimated", sa.Numeric(12, 2)),
        sa.Column("profit_estimated", sa.Numeric(12, 2)),
        sa.Column("margin_percent_estimated", sa.Numeric(7, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_order_items_articles", "order_items", ["seller_article", "marketplace_article"])

    op.create_table(
        "profit_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_item_id", sa.Integer(), sa.ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("calculation_type", calc_type, nullable=False),
        sa.Column("gross_revenue", sa.Numeric(12, 2), nullable=False),
        sa.Column("marketplace_commission", sa.Numeric(12, 2), nullable=False),
        sa.Column("logistics_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("acquiring_cost", sa.Numeric(12, 2)),
        sa.Column("storage_cost", sa.Numeric(12, 2)),
        sa.Column("return_cost", sa.Numeric(12, 2)),
        sa.Column("other_marketplace_costs", sa.Numeric(12, 2), nullable=False),
        sa.Column("cost_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("package_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("additional_seller_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("profit", sa.Numeric(12, 2), nullable=False),
        sa.Column("margin_percent", sa.Numeric(7, 2), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculation_source", sa.String(255), nullable=False),
        sa.Column("raw_financial_data", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_profit_snapshots_item_type", "profit_snapshots", ["order_item_id", "calculation_type", "calculated_at"])

    _create_events_and_support_tables(marketplace, notification_type, alert_type, sync_status)


def _pg_enum(*values: str, name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


def _create_events_and_support_tables(
    marketplace: postgresql.ENUM,
    notification_type: postgresql.ENUM,
    alert_type: postgresql.ENUM,
    sync_status: postgresql.ENUM,
) -> None:
    op.create_table(
        "financial_report_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id"), nullable=False),
        sa.Column("marketplace", marketplace, nullable=False),
        sa.Column("external_row_id", sa.String(255), nullable=False),
        sa.Column("order_external_id", sa.String(255)),
        sa.Column("product_external_id", sa.String(255)),
        sa.Column("operation_type", sa.String(255), nullable=False),
        sa.Column("operation_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("marketplace_account_id", "marketplace", "external_row_id", name="uq_financial_rows_external"),
    )
    op.create_index("ix_financial_rows_period", "financial_report_rows", ["marketplace_account_id", "operation_date"])
    for table in ("sales_events", "returns_events"):
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id"), nullable=False),
            sa.Column("marketplace", marketplace, nullable=False),
            sa.Column("external_event_id", sa.String(255), nullable=False),
            sa.Column("order_external_id", sa.String(255)),
            sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("reason", sa.String(512)) if table == "returns_events" else sa.Column("raw_placeholder", sa.String(1)),
            sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("marketplace_account_id", "marketplace", "external_event_id"),
        )
        if table == "sales_events":
            op.drop_column("sales_events", "raw_placeholder")
        op.create_index(f"ix_{table}_date", table, ["user_id", "event_date"])

    op.create_table(
        "stock_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("marketplace", marketplace, nullable=False),
        sa.Column("warehouse", sa.String(255)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("average_daily_sales_7d", sa.Numeric(10, 2)),
        sa.Column("days_until_stockout", sa.Numeric(10, 2)),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_stock_snapshots_product_date", "stock_snapshots", ["product_id", "snapshot_at"])
    _create_alerts_reports_billing(marketplace, notification_type, alert_type, sync_status)


def _create_alerts_reports_billing(
    marketplace: postgresql.ENUM,
    notification_type: postgresql.ENUM,
    alert_type: postgresql.ENUM,
    sync_status: postgresql.ENUM,
) -> None:
    op.create_table(
        "notification_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id")),
        sa.Column("notification_type", notification_type, nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("quiet_from", sa.Time()),
        sa.Column("quiet_to", sa.Time()),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "marketplace_account_id", "notification_type"),
    )
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id")),
        sa.Column("alert_type", alert_type, nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("threshold", sa.Numeric(12, 2)),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "marketplace_account_id", "alert_type"),
    )
    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("alert_rules.id", ondelete="SET NULL")),
        sa.Column("alert_type", alert_type, nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("rule_id", "idempotency_key", name="uq_alert_events_rule_key"),
    )
    op.create_index("ix_alert_events_user_created", "alert_events", ["user_id", "created_at"])

    op.create_table("daily_reports", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("report_date", sa.Date(), nullable=False), sa.Column("payload", postgresql.JSONB(), nullable=False), sa.Column("message_text", sa.Text(), nullable=False), sa.Column("sent_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint("user_id", "report_date"))
    op.create_table("sync_jobs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id")), sa.Column("job_type", sa.String(128), nullable=False), sa.Column("status", sync_status, nullable=False), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("error_message", sa.Text()), sa.Column("retries", sa.Integer(), nullable=False), sa.Column("payload", postgresql.JSONB(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_sync_jobs_account_type", "sync_jobs", ["marketplace_account_id", "job_type"])
    op.create_table("api_request_logs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("marketplace_account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id")), sa.Column("marketplace", marketplace), sa.Column("method", sa.String(16), nullable=False), sa.Column("url", sa.Text(), nullable=False), sa.Column("status_code", sa.Integer()), sa.Column("duration_ms", sa.Integer()), sa.Column("error_message", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_api_logs_account_created", "api_request_logs", ["marketplace_account_id", "created_at"])
    op.create_table("subscription_plans", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(64), nullable=False, unique=True), sa.Column("title", sa.String(255), nullable=False), sa.Column("monthly_price", sa.Numeric(12, 2), nullable=False), sa.Column("marketplace_limit", sa.Integer(), nullable=False), sa.Column("sku_limit", sa.Integer(), nullable=False), sa.Column("features", postgresql.JSONB(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("subscriptions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("plan_id", sa.Integer(), sa.ForeignKey("subscription_plans.id"), nullable=False), sa.Column("status", sa.String(64), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True)), sa.Column("payment_provider", sa.String(128)), sa.Column("external_subscription_id", sa.String(255)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_subscriptions_user_status", "subscriptions", ["user_id", "status"])


def downgrade() -> None:
    for table in [
        "subscriptions",
        "subscription_plans",
        "api_request_logs",
        "sync_jobs",
        "daily_reports",
        "alert_events",
        "alert_rules",
        "notification_settings",
        "stock_snapshots",
        "returns_events",
        "sales_events",
        "financial_report_rows",
        "profit_snapshots",
        "order_items",
        "orders",
        "product_cost_history",
        "products",
        "marketplace_accounts",
        "users",
    ]:
        op.drop_table(table)
    for enum_name in [
        "syncjobstatus",
        "alerttype",
        "notificationtype",
        "calculationtype",
        "salemodel",
        "accountstatus",
        "marketplace",
        "userstatus",
    ]:
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
