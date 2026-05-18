"""order lifecycle notification markers

Revision ID: 20260518_0020
Revises: 20260517_0019
Create Date: 2026-05-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260518_0020"
down_revision: str | None = "20260517_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for value in ["ORDER_CANCELLED", "RETURN_CREATED"]:
        op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'")
    op.add_column(
        "orders",
        sa.Column("cancellation_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "returns_events",
        sa.Column("notification_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE orders
        SET cancellation_notified_at = now()
        WHERE lower(coalesce(normalized_status, status)) IN ('cancelled', 'canceled', 'cancel')
        """
    )
    op.execute("UPDATE returns_events SET notification_sent_at = now()")


def downgrade() -> None:
    op.drop_column("returns_events", "notification_sent_at")
    op.drop_column("orders", "cancellation_notified_at")
