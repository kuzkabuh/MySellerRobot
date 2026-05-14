"""notification type order modes

version: 1.0.0
description: Add order model notification settings enum values used by FBO/FBS/rFBS polling.
updated: 2026-05-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260514_0005"
down_revision: str | None = "20260514_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for value in ["ORDER_FBS", "ORDER_RFBS", "ORDER_FBO", "FBO_DIGEST"]:
        op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL does not support dropping individual enum values safely.
    return None
