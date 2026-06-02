"""add user company profiles

Revision ID: 20260602_0054
Revises: 20260602_0053
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260602_0054"
down_revision: str | None = "20260602_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_company_profiles",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("kpp", sa.String(length=9), nullable=True),
        sa.Column("ogrn", sa.String(length=15), nullable=True),
        sa.Column("name_full", sa.Text(), nullable=True),
        sa.Column("name_short", sa.Text(), nullable=True),
        sa.Column("company_type", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("okved", sa.String(length=32), nullable=True),
        sa.Column("okved_name", sa.Text(), nullable=True),
        sa.Column("director_name", sa.Text(), nullable=True),
        sa.Column("registration_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_company_profiles_user_id"),
    )
    op.create_index("ix_user_company_profiles_inn", "user_company_profiles", ["inn"])
    op.create_index("ix_user_company_profiles_ogrn", "user_company_profiles", ["ogrn"])
    op.create_index("ix_user_company_profiles_status", "user_company_profiles", ["status"])


def downgrade() -> None:
    op.drop_index("ix_user_company_profiles_status", table_name="user_company_profiles")
    op.drop_index("ix_user_company_profiles_ogrn", table_name="user_company_profiles")
    op.drop_index("ix_user_company_profiles_inn", table_name="user_company_profiles")
    op.drop_table("user_company_profiles")
