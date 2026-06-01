"""user profile expansion and audit tables

Revision ID: 0051_user_profile
Revises: 0050_stability_admin_visibility
Create Date: 2026-06-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0051_user_profile"
down_revision: Union[str, None] = "0050_stability_admin_visibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_name", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("company_name", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("inn", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("ogrn", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_login_ip", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("last_login_user_agent", sa.String(512), nullable=True))

    op.add_column(
        "marketplace_accounts",
        sa.Column("api_key_status", sa.String(32), server_default="unchecked"),
    )
    op.add_column(
        "marketplace_accounts",
        sa.Column("api_key_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "marketplace_accounts",
        sa.Column("api_key_check_result", JSONB(), nullable=True),
    )

    op.create_table(
        "api_key_audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marketplace", sa.String(16), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("old_key_mask", sa.String(64), nullable=True),
        sa.Column("new_key_mask", sa.String(64), nullable=True),
        sa.Column("check_result", sa.String(32), nullable=True),
        sa.Column("check_details", JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_key_audit_logs_user_id", "api_key_audit_logs", ["user_id"])
    op.create_index("ix_api_key_audit_logs_account_id", "api_key_audit_logs", ["account_id"])

    op.create_table(
        "user_activity_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_activity_logs_user_id", "user_activity_logs", ["user_id"])
    op.create_index("ix_user_activity_logs_created_at", "user_activity_logs", ["created_at"])

    op.create_table(
        "sync_statuses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("sync_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("items_processed", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "account_id", "sync_type", name="uq_sync_statuses_user_account_type"),
    )
    op.create_index("ix_sync_statuses_user_id", "sync_statuses", ["user_id"])

    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("admin_response", sa.Text(), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_by", sa.Integer(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_support_tickets_user_id", "support_tickets", ["user_id"])
    op.create_index("ix_support_tickets_status", "support_tickets", ["status"])


def downgrade() -> None:
    op.drop_table("support_tickets")
    op.drop_table("sync_statuses")
    op.drop_table("user_activity_logs")
    op.drop_table("api_key_audit_logs")

    op.drop_column("marketplace_accounts", "api_key_check_result")
    op.drop_column("marketplace_accounts", "api_key_checked_at")
    op.drop_column("marketplace_accounts", "api_key_status")

    op.drop_column("users", "last_login_user_agent")
    op.drop_column("users", "last_login_ip")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "last_activity_at")
    op.drop_column("users", "ogrn")
    op.drop_column("users", "inn")
    op.drop_column("users", "company_name")
    op.drop_column("users", "email")
    op.drop_column("users", "phone")
    op.drop_column("users", "last_name")
