"""Add feature_mrc_pricing to subscription_tiers.

Revision ID: 20260521_0032_mrc_feature_flag
Revises: 20260521_0031_wb_mrc_and_promotions
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260521_0032_mrc_feature_flag"
down_revision: str | None = "20260521_0031_wb_mrc_and_promotions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscription_tiers",
        sa.Column(
            "feature_mrc_pricing", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    op.drop_column("subscription_tiers", "feature_mrc_pricing")
