"""web cabinet auth

version: 1.0.0
description: Add one-time login tokens and web sessions for Telegram-linked cabinet access.
updated: 2026-05-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260514_0004"
down_revision: str | None = "20260514_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "one_time_login_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
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
        sa.UniqueConstraint("token_hash", name="uq_one_time_login_tokens_token_hash"),
    )
    op.create_index(
        "ix_one_time_login_tokens_user_id",
        "one_time_login_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_one_time_login_tokens_user_expires",
        "one_time_login_tokens",
        ["user_id", "expires_at"],
    )
    op.create_index(
        "ix_one_time_login_tokens_expires_at",
        "one_time_login_tokens",
        ["expires_at"],
    )
    op.create_index(
        "ix_one_time_login_tokens_used_at",
        "one_time_login_tokens",
        ["used_at"],
    )

    op.create_table(
        "user_web_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("session_hash", name="uq_user_web_sessions_session_hash"),
    )
    op.create_index("ix_user_web_sessions_user_id", "user_web_sessions", ["user_id"])
    op.create_index(
        "ix_user_web_sessions_user_expires",
        "user_web_sessions",
        ["user_id", "expires_at"],
    )
    op.create_index("ix_user_web_sessions_expires_at", "user_web_sessions", ["expires_at"])
    op.create_index("ix_user_web_sessions_revoked_at", "user_web_sessions", ["revoked_at"])


def downgrade() -> None:
    op.drop_index("ix_user_web_sessions_revoked_at", table_name="user_web_sessions")
    op.drop_index("ix_user_web_sessions_expires_at", table_name="user_web_sessions")
    op.drop_index("ix_user_web_sessions_user_expires", table_name="user_web_sessions")
    op.drop_index("ix_user_web_sessions_user_id", table_name="user_web_sessions")
    op.drop_table("user_web_sessions")

    op.drop_index("ix_one_time_login_tokens_used_at", table_name="one_time_login_tokens")
    op.drop_index("ix_one_time_login_tokens_expires_at", table_name="one_time_login_tokens")
    op.drop_index("ix_one_time_login_tokens_user_expires", table_name="one_time_login_tokens")
    op.drop_index("ix_one_time_login_tokens_user_id", table_name="one_time_login_tokens")
    op.drop_table("one_time_login_tokens")
