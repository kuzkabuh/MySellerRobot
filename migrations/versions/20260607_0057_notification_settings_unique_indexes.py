"""Add partial unique indexes for notification settings.

Revision ID: 20260607_0057
Revises: 20260607_0056
Create Date: 2026-06-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260607_0057"
down_revision: str | None = "20260607_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM notification_settings ns
        USING notification_settings newer
        WHERE ns.user_id = newer.user_id
          AND ns.notification_type = newer.notification_type
          AND ns.marketplace_account_id IS NULL
          AND newer.marketplace_account_id IS NULL
          AND (
            newer.updated_at > ns.updated_at
            OR (newer.updated_at = ns.updated_at AND newer.id > ns.id)
          )
        """
    )
    op.execute(
        """
        DELETE FROM notification_settings ns
        USING notification_settings newer
        WHERE ns.user_id = newer.user_id
          AND ns.notification_type = newer.notification_type
          AND ns.marketplace_account_id = newer.marketplace_account_id
          AND ns.marketplace_account_id IS NOT NULL
          AND (
            newer.updated_at > ns.updated_at
            OR (newer.updated_at = ns.updated_at AND newer.id > ns.id)
          )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_settings_global
        ON notification_settings (user_id, notification_type)
        WHERE marketplace_account_id IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_settings_account
        ON notification_settings (user_id, marketplace_account_id, notification_type)
        WHERE marketplace_account_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_notification_settings_account")
    op.execute("DROP INDEX IF EXISTS uq_notification_settings_global")
