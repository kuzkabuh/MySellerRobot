"""extend support tickets and add ticket events

Revision ID: 20260602_0052
Revises: 20260601_0051
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_0052"
down_revision: str | None = "20260601_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("support_tickets", sa.Column("telegram_id", sa.BigInteger(), nullable=True))
    op.add_column("support_tickets", sa.Column("username", sa.String(255), nullable=True))
    op.add_column("support_tickets", sa.Column("full_name", sa.String(512), nullable=True))
    op.add_column("support_tickets", sa.Column("admin_comment", sa.Text(), nullable=True))
    op.add_column("support_tickets", sa.Column("assigned_admin_id", sa.Integer(), nullable=True))
    op.add_column(
        "support_tickets",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute("""
        UPDATE support_tickets AS st
        SET telegram_id = u.telegram_id,
            username = u.username,
            full_name = trim(coalesce(u.first_name, '') || ' ' || coalesce(u.last_name, ''))
        FROM users AS u
        WHERE st.user_id = u.id
          AND st.telegram_id IS NULL
        """)
    op.execute("UPDATE support_tickets SET full_name = NULL WHERE full_name = ''")
    op.execute("UPDATE support_tickets SET status = 'new' WHERE status = 'open'")
    op.execute("UPDATE support_tickets SET status = 'answered' WHERE status = 'responded'")
    op.execute("""
        UPDATE support_tickets
        SET resolved_at = closed_at
        WHERE status = 'closed' AND resolved_at IS NULL
        """)
    op.alter_column(
        "support_tickets",
        "status",
        existing_type=sa.String(32),
        server_default="new",
    )

    op.create_index("ix_support_tickets_priority", "support_tickets", ["priority"])
    op.create_index("ix_support_tickets_telegram_id", "support_tickets", ["telegram_id"])
    op.create_index("ix_support_tickets_created_at", "support_tickets", ["created_at"])
    op.create_index(
        "ix_support_tickets_assigned_admin_id",
        "support_tickets",
        ["assigned_admin_id"],
    )

    op.create_table(
        "user_support_ticket_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "ticket_id",
            sa.Integer(),
            sa.ForeignKey("support_tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_support_ticket_events_ticket_id",
        "user_support_ticket_events",
        ["ticket_id"],
    )
    op.create_index(
        "ix_support_ticket_events_created_at",
        "user_support_ticket_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_support_ticket_events_created_at", table_name="user_support_ticket_events")
    op.drop_index("ix_support_ticket_events_ticket_id", table_name="user_support_ticket_events")
    op.drop_table("user_support_ticket_events")

    op.execute("UPDATE support_tickets SET status = 'open' WHERE status IN ('new', 'in_progress')")
    op.execute("UPDATE support_tickets SET status = 'responded' WHERE status = 'answered'")
    op.alter_column(
        "support_tickets",
        "status",
        existing_type=sa.String(32),
        server_default="open",
    )

    op.drop_index("ix_support_tickets_assigned_admin_id", table_name="support_tickets")
    op.drop_index("ix_support_tickets_created_at", table_name="support_tickets")
    op.drop_index("ix_support_tickets_telegram_id", table_name="support_tickets")
    op.drop_index("ix_support_tickets_priority", table_name="support_tickets")
    op.drop_column("support_tickets", "resolved_at")
    op.drop_column("support_tickets", "assigned_admin_id")
    op.drop_column("support_tickets", "admin_comment")
    op.drop_column("support_tickets", "full_name")
    op.drop_column("support_tickets", "username")
    op.drop_column("support_tickets", "telegram_id")
