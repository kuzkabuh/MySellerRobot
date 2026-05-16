"""Add subscription lifecycle period and replacement status for v1.6.3.

Revision ID: 20260517_0013
Revises: 20260516_0012
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260517_0013"
down_revision: str | None = "20260516_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE subscriptionstatus ADD VALUE IF NOT EXISTS 'REPLACED'")

    op.add_column(
        "user_subscriptions",
        sa.Column("period", sa.String(length=16), nullable=False, server_default="monthly"),
    )


def downgrade() -> None:
    op.drop_column("user_subscriptions", "period")
    # PostgreSQL enum values cannot be removed safely without rebuilding the type.
