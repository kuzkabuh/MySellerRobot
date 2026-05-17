"""Add WB balance snapshots and financial report metadata.

Revision ID: 20260517_0018
Revises: 20260517_0017
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260517_0018"
down_revision: str | None = "20260517_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB, "postgresql")


def timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "account_balance_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "marketplace_account_id",
            sa.Integer(),
            sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("marketplace", sa.String(length=16), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="RUB"),
        sa.Column("current", sa.Numeric(14, 2), nullable=True),
        sa.Column("for_withdraw", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="OK"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", json_type, nullable=False, server_default="{}"),
        *timestamps(),
    )
    op.create_index(
        "ix_account_balance_latest",
        "account_balance_snapshots",
        ["marketplace_account_id", "fetched_at"],
    )

    op.create_table(
        "wb_financial_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "marketplace_account_id",
            sa.Integer(),
            sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_id", sa.String(length=128), nullable=False),
        sa.Column("period_type", sa.String(length=16), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("create_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("report_type", sa.String(length=128), nullable=True),
        sa.Column("retail_amount_sum", sa.Numeric(14, 2), nullable=True),
        sa.Column("for_pay_sum", sa.Numeric(14, 2), nullable=True),
        sa.Column("delivery_service_sum", sa.Numeric(14, 2), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", json_type, nullable=False, server_default="{}"),
        *timestamps(),
        sa.UniqueConstraint(
            "marketplace_account_id",
            "period_type",
            "report_id",
            name="uq_wb_reports_account_period_report",
        ),
    )
    op.create_index(
        "ix_wb_reports_period",
        "wb_financial_reports",
        ["marketplace_account_id", "period_type", "date_from"],
    )

    op.create_table(
        "wb_report_check_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "marketplace_account_id",
            sa.Integer(),
            sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="UNKNOWN"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("reports_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", json_type, nullable=False, server_default="{}"),
        *timestamps(),
        sa.UniqueConstraint(
            "marketplace_account_id",
            "period_type",
            name="uq_wb_report_check_account_period",
        ),
    )


def downgrade() -> None:
    op.drop_table("wb_report_check_states")
    op.drop_index("ix_wb_reports_period", table_name="wb_financial_reports")
    op.drop_table("wb_financial_reports")
    op.drop_index("ix_account_balance_latest", table_name="account_balance_snapshots")
    op.drop_table("account_balance_snapshots")
