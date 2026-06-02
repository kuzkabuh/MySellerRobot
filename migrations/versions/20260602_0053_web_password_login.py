"""add web password login fields

Revision ID: 20260602_0053
Revises: 20260602_0052
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_0053"
down_revision: str | None = "20260602_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(32), nullable=False, server_default="user"),
    )
    op.add_column("users", sa.Column("web_login", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("web_password_hash", sa.String(255), nullable=True))
    op.add_column(
        "users",
        sa.Column("web_password_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("web_password_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_password_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_users_web_login",
        "users",
        ["web_login"],
        unique=True,
        postgresql_where=sa.text("web_login IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_users_web_login", table_name="users")
    op.drop_column("users", "last_password_login_at")
    op.drop_column("users", "web_password_updated_at")
    op.drop_column("users", "web_password_enabled")
    op.drop_column("users", "web_password_hash")
    op.drop_column("users", "web_login")
    op.drop_column("users", "role")
