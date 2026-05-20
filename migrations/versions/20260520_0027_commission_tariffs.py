"""Add commission tariff tables for WB and Ozon marketplace commissions.

Revision ID: 20260520_0027_commission_tariffs
Revises: 20260520_0027_wb_financial_detail_sync
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_0027_commission_tariffs"
down_revision: str | None = "20260520_0027_wb_financial_detail_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "marketplace_commission_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "marketplace",
            sa.Enum("WB", "OZON", name="marketplace"),
            nullable=False,
            index=True,
        ),
        sa.Column("version_label", sa.String(255), nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False, index=True),
        sa.Column("effective_to", sa.Date, nullable=True, index=True),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("source_file_name", sa.String(255), nullable=True),
        sa.Column("source_file_sha256", sa.String(64), nullable=True, index=True),
        sa.Column(
            "imported_by_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, default=False, index=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, index=True),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_commission_versions_marketplace_active",
        "marketplace_commission_versions",
        ["marketplace", "is_active"],
    )
    op.create_index(
        "ix_commission_versions_effective",
        "marketplace_commission_versions",
        ["marketplace", "effective_from", "effective_to"],
    )

    op.create_table(
        "marketplace_commission_rates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "version_id",
            sa.Integer,
            sa.ForeignKey("marketplace_commission_versions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "marketplace",
            sa.Enum("WB", "OZON", name="marketplace"),
            nullable=False,
            index=True,
        ),
        sa.Column("category_name", sa.String(512), nullable=False, index=True),
        sa.Column("product_type_name", sa.String(512), nullable=True, index=True),
        sa.Column("subject_name", sa.String(512), nullable=True),
        sa.Column("object_name", sa.String(512), nullable=True),
        sa.Column("sales_model", sa.String(32), nullable=False, index=True),
        sa.Column("price_from", sa.Numeric(12, 2), nullable=False, default=0),
        sa.Column("price_to", sa.Numeric(12, 2), nullable=False, default=0),
        sa.Column("price_to_inclusive", sa.Boolean, nullable=False, default=False),
        sa.Column("commission_percent", sa.Numeric(7, 4), nullable=False),
        sa.Column("raw_payload", sa.JSON, nullable=True),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_commission_rates_version_lookup",
        "marketplace_commission_rates",
        ["version_id", "marketplace", "sales_model", "category_name", "price_from", "price_to"],
    )

    op.create_table(
        "marketplace_tariff_source_checks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "marketplace",
            sa.Enum("WB", "OZON", name="marketplace"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("page_hash", sa.String(64), nullable=True),
        sa.Column("current_detected_period_label", sa.String(512), nullable=True),
        sa.Column("current_detected_file_url", sa.Text, nullable=True),
        sa.Column("current_detected_file_name", sa.String(255), nullable=True),
        sa.Column("has_changes", sa.Boolean, nullable=False, default=False),
        sa.Column("change_type", sa.String(64), nullable=False, default="no_change"),
        sa.Column("details", sa.JSON, nullable=True),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_tariff_source_checks_marketplace_checked",
        "marketplace_tariff_source_checks",
        ["marketplace", "checked_at"],
    )

    op.create_table(
        "marketplace_commission_import_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "marketplace",
            sa.Enum("WB", "OZON", name="marketplace"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "version_id",
            sa.Integer,
            sa.ForeignKey("marketplace_commission_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False, index=True),
        sa.Column(
            "uploaded_by_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, default="uploaded"),
        sa.Column("rows_total", sa.Integer, nullable=False, default=0),
        sa.Column("rows_imported", sa.Integer, nullable=False, default=0),
        sa.Column("rows_failed", sa.Integer, nullable=False, default=0),
        sa.Column("validation_errors", sa.JSON, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_commission_import_logs_marketplace_created",
        "marketplace_commission_import_logs",
        ["marketplace", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("marketplace_commission_import_logs")
    op.drop_table("marketplace_tariff_source_checks")
    op.drop_table("marketplace_commission_rates")
    op.drop_table("marketplace_commission_versions")
