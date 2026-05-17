"""Add plan/fact target settings.

Revision ID: 20260517_0019
Revises: 20260517_0018
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260517_0019"
down_revision: str | None = "20260517_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_fact_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("marketplace", sa.String(length=16), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("revenue_plan", sa.Numeric(14, 2), nullable=True),
        sa.Column("profit_plan", sa.Numeric(14, 2), nullable=True),
        sa.Column("orders_plan", sa.Integer(), nullable=True),
        sa.Column("buyouts_plan", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("comment", sa.Text(), nullable=True),
    )
    op.create_index("ix_plan_fact_targets_user_id", "plan_fact_targets", ["user_id"])
    op.create_index(
        "ix_plan_fact_targets_user_period",
        "plan_fact_targets",
        ["user_id", "period_start", "period_end"],
    )
    op.create_index(
        "ix_plan_fact_targets_user_marketplace",
        "plan_fact_targets",
        ["user_id", "marketplace"],
    )


def downgrade() -> None:
    op.drop_index("ix_plan_fact_targets_user_marketplace", table_name="plan_fact_targets")
    op.drop_index("ix_plan_fact_targets_user_period", table_name="plan_fact_targets")
    op.drop_index("ix_plan_fact_targets_user_id", table_name="plan_fact_targets")
    op.drop_table("plan_fact_targets")
