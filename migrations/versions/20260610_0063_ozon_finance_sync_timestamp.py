"""Add last_ozon_finance_sync_at to marketplace_accounts for Sync Center.

Revision ID: 20260610_0063
Revises: 20260609_0062
Create Date: 2026-06-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260610_0063"
down_revision: str | None = "20260609_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "marketplace_accounts",
        sa.Column("last_ozon_finance_sync_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("marketplace_accounts", "last_ozon_finance_sync_at")
