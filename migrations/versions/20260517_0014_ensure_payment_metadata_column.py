"""Ensure payment metadata column exists on production databases.

Revision ID: 20260517_0014
Revises: 20260517_0013
Create Date: 2026-05-17
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

revision: str = "20260517_0014"
down_revision: str | None = "20260517_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_metadata JSON")
        return
    existing_columns = {column["name"] for column in inspect(bind).get_columns("payments")}
    if "payment_metadata" not in existing_columns:
        op.execute("ALTER TABLE payments ADD COLUMN payment_metadata JSON")


def downgrade() -> None:
    # The canonical 20260516_0011 migration already defines this column for fresh databases.
    # This corrective migration is intentionally non-destructive on downgrade so it does not
    # remove a column that belongs to the baseline subscription/payment schema.
    return
