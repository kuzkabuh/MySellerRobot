"""add fetch_method to tariff source checks

Revision ID: 20260531_0047
Revises: 20260525_0046_wb_auto_promo_imports
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa

revision = "20260531_0047"
down_revision = "20260525_0046_wb_auto_promo_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace_tariff_source_checks",
        sa.Column("fetch_method", sa.String(32), nullable=True, server_default="http"),
    )


def downgrade() -> None:
    op.drop_column("marketplace_tariff_source_checks", "fetch_method")
