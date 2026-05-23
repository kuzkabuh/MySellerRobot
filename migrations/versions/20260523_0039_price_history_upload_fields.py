"""Add wb_upload_id, target_discounted_price, wb_price, wb_discount,
final_discounted_price, raw_payload, raw_response, updated_at to wb_price_change_history.

Revision ID: 20260523_0039_price_history_upload_fields
Revises: 20260523_0038_price_history_bounds
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa

revision = "20260523_0039_price_history_upload_fields"
down_revision = "20260523_0038_price_history_bounds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    col_names = {col["name"] for col in inspector.get_columns("wb_price_change_history")}

    if "wb_upload_id" not in col_names:
        op.add_column(
            "wb_price_change_history",
            sa.Column("wb_upload_id", sa.BigInteger(), nullable=True),
        )
    if "target_discounted_price" not in col_names:
        op.add_column(
            "wb_price_change_history",
            sa.Column("target_discounted_price", sa.Numeric(12, 2), nullable=True),
        )
    if "wb_price" not in col_names:
        op.add_column(
            "wb_price_change_history",
            sa.Column("wb_price", sa.Integer(), nullable=True),
        )
    if "wb_discount" not in col_names:
        op.add_column(
            "wb_price_change_history",
            sa.Column("wb_discount", sa.Integer(), nullable=True),
        )
    if "final_discounted_price" not in col_names:
        op.add_column(
            "wb_price_change_history",
            sa.Column("final_discounted_price", sa.Numeric(12, 2), nullable=True),
        )
    if "raw_payload" not in col_names:
        op.add_column(
            "wb_price_change_history",
            sa.Column("raw_payload", sa.JSON(), nullable=True),
        )
    if "raw_response" not in col_names:
        op.add_column(
            "wb_price_change_history",
            sa.Column("raw_response", sa.JSON(), nullable=True),
        )
    if "updated_at" not in col_names:
        op.add_column(
            "wb_price_change_history",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    col_names = {col["name"] for col in inspector.get_columns("wb_price_change_history")}

    for col in ("updated_at", "raw_response", "raw_payload", "final_discounted_price",
                "wb_discount", "wb_price", "target_discounted_price", "wb_upload_id"):
        if col in col_names:
            op.drop_column("wb_price_change_history", col)
