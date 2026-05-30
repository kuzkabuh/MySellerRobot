"""add payment_email column to users table

Revision ID: 20260519_0021
Revises: 20260518_0020
Create Date: 2026-05-19

non-destructive: adds nullable column with no default
"""

from alembic import op

revision = "20260519_0021"
down_revision = "20260518_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS payment_email VARCHAR(255)")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS payment_email")
