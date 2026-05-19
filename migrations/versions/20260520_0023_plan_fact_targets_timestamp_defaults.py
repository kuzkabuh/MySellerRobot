"""Add server defaults for plan_fact_targets timestamps.

Revision ID: 20260520_0023
Revises: 20260519_0022
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_0023"
down_revision: str | None = "20260519_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    now_expr = "NOW()" if op.get_bind().dialect.name == "postgresql" else "CURRENT_TIMESTAMP"
    op.execute(
        sa.text(
            f"""
            UPDATE plan_fact_targets
            SET created_at = COALESCE(created_at, {now_expr}),
                updated_at = COALESCE(updated_at, created_at, {now_expr})
            WHERE created_at IS NULL OR updated_at IS NULL
            """
        )
    )
    op.alter_column(
        "plan_fact_targets",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    op.alter_column(
        "plan_fact_targets",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def downgrade() -> None:
    op.alter_column(
        "plan_fact_targets",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=None,
    )
    op.alter_column(
        "plan_fact_targets",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=None,
    )
