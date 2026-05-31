"""add stability and admin visibility tables

Revision ID: 20260531_0050
Revises: 20260531_0049
Create Date: 2026-05-31
"""

import sqlalchemy as sa
from alembic import op

revision = "20260531_0050"
down_revision = "20260531_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("subscription_applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "wb_auto_promo_price_recommendations",
        sa.Column("required_price_source", sa.String(64), nullable=True),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=True),
        sa.Column("entity_id", sa.String(128), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_user_created", "audit_logs", ["user_id", "created_at"])
    op.create_index("ix_audit_logs_action_created", "audit_logs", ["action", "created_at"])
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])

    op.create_table(
        "sync_task_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="started"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("records_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("triggered_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
    )
    op.create_index("ix_sync_task_runs_task_started", "sync_task_runs", ["task_name", "started_at"])
    op.create_index("ix_sync_task_runs_status_started", "sync_task_runs", ["status", "started_at"])
    op.create_index("ix_sync_task_runs_triggered_by_user_id", "sync_task_runs", ["triggered_by_user_id"])

    op.create_table(
        "notification_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("notification_type", sa.String(64), nullable=False, server_default="generic"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permanent_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notification_events_user_status", "notification_events", ["user_id", "status"])
    op.create_index("ix_notification_events_status_created", "notification_events", ["status", "created_at"])
    op.create_index("ix_notification_events_telegram_id", "notification_events", ["telegram_id"])


def downgrade() -> None:
    op.drop_table("notification_events")
    op.drop_table("sync_task_runs")
    op.drop_table("audit_logs")
    op.drop_column("wb_auto_promo_price_recommendations", "required_price_source")
    op.drop_column("payments", "subscription_applied_at")
