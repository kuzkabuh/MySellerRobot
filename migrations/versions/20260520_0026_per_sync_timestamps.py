"""add per-sync-type timestamps to marketplace_accounts

Revision ID: 20260520_0026
Revises: 20260520_0025
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa

revision = "20260520_0026"
down_revision = "20260520_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace_accounts",
        sa.Column("last_orders_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "marketplace_accounts",
        sa.Column("last_sales_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "marketplace_accounts",
        sa.Column("last_stocks_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "marketplace_accounts",
        sa.Column("last_products_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "marketplace_accounts",
        sa.Column("last_profile_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "marketplace_accounts",
        sa.Column("last_ozon_enrichment_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "marketplace_accounts",
        sa.Column("last_wb_reports_sync_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("marketplace_accounts", "last_wb_reports_sync_at")
    op.drop_column("marketplace_accounts", "last_ozon_enrichment_sync_at")
    op.drop_column("marketplace_accounts", "last_profile_sync_at")
    op.drop_column("marketplace_accounts", "last_products_sync_at")
    op.drop_column("marketplace_accounts", "last_stocks_sync_at")
    op.drop_column("marketplace_accounts", "last_sales_sync_at")
    op.drop_column("marketplace_accounts", "last_orders_sync_at")
