"""add last_wb_financial_detail_sync_at to marketplace_accounts

Revision ID: 0027
Revises: 20260520_0026_per_sync_timestamps
Create Date: 2026-05-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "20260520_0026_per_sync_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace_accounts",
        sa.Column("last_wb_financial_detail_sync_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("marketplace_accounts", "last_wb_financial_detail_sync_at")
