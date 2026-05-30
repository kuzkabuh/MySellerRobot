"""Add index for unnotified order recovery queries.

Revision ID: 20260520_0024
Revises: 20260520_0023
Create Date: 2026-05-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260520_0024"
down_revision: str | None = "20260520_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_orders_account_unnotified",
        "orders",
        ["marketplace_account_id", "first_notified_at", "sale_model"],
    )


def downgrade() -> None:
    op.drop_index("ix_orders_account_unnotified", table_name="orders")
