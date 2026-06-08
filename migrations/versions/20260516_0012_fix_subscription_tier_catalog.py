"""Fix subscription tier catalog defaults for v1.6.2.

Revision ID: 20260516_0012
Revises: 20260516_0011
Create Date: 2026-05-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260516_0012"
down_revision: str | None = "20260516_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE subscription_tiers
        SET max_products = NULL
        WHERE code IN ('free', 'basic', 'pro')
        """)
    op.execute("""
        UPDATE subscription_tiers
        SET is_active = true
        WHERE code = 'enterprise'
        """)


def downgrade() -> None:
    op.execute("""
        UPDATE subscription_tiers
        SET max_products = CASE code
            WHEN 'free' THEN 100
            WHEN 'basic' THEN 1000
            WHEN 'pro' THEN 10000
            ELSE max_products
        END
        WHERE code IN ('free', 'basic', 'pro')
        """)
    op.execute("""
        UPDATE subscription_tiers
        SET is_active = false
        WHERE code = 'enterprise'
        """)
