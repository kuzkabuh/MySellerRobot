"""Add server defaults for subscription and payment timestamps.

Revision ID: 20260517_0015
Revises: 20260517_0014
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260517_0015"
down_revision: str | None = "20260517_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("subscription_tiers", "user_subscriptions", "payments")


def upgrade() -> None:
    now_expr = "NOW()" if op.get_bind().dialect.name == "postgresql" else "CURRENT_TIMESTAMP"
    for table in TABLES:
        op.execute(
            sa.text(
                f"""
                UPDATE {table}
                SET created_at = COALESCE(created_at, {now_expr}),
                    updated_at = COALESCE(updated_at, created_at, {now_expr})
                WHERE created_at IS NULL OR updated_at IS NULL
                """
            )
        )
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
        op.alter_column(
            table,
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )


def downgrade() -> None:
    for table in TABLES:
        op.alter_column(
            table,
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
            server_default=None,
        )
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=None,
        )
