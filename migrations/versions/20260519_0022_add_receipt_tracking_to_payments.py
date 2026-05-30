"""add receipt and notification tracking to payments table

Revision ID: 20260519_0022
Revises: 20260519_0021
Create Date: 2026-05-19

non-destructive: adds nullable columns with no default
"""
# ruff: noqa: E501

from alembic import op

revision = "20260519_0022"
down_revision = "20260519_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS success_notification_sent_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS receipt_id VARCHAR(128)")
    op.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS receipt_status VARCHAR(32)")


def downgrade() -> None:
    op.execute("ALTER TABLE payments DROP COLUMN IF EXISTS success_notification_sent_at")
    op.execute("ALTER TABLE payments DROP COLUMN IF EXISTS receipt_id")
    op.execute("ALTER TABLE payments DROP COLUMN IF EXISTS receipt_status")
