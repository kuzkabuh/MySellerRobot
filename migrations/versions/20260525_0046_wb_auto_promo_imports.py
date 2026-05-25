"""Ensure WB auto-promo import tables exist.

Revision ID: 20260525_0046_wb_auto_promo_imports
Revises: 20260525_0045_ensure_auto_promo_columns
Create Date: 2026-05-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection
from sqlalchemy.engine.reflection import Inspector

revision = "20260525_0046_wb_auto_promo_imports"
down_revision = "20260525_0045_ensure_auto_promo_columns"
branch_labels = None
depends_on = None


IMPORT_TABLE = "wb_auto_promo_file_imports"
ROW_TABLE = "wb_auto_promo_file_import_rows"


def _table_names(inspector: Inspector) -> set[str]:
    return set(inspector.get_table_names())


def _column_names(inspector: Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector: Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _create_index_if_missing(
    inspector: Inspector,
    name: str,
    table_name: str,
    columns: list[str],
) -> None:
    if name not in _index_names(inspector, table_name):
        op.create_index(name, table_name, columns)


def _ensure_import_table(inspector: Inspector) -> None:
    if IMPORT_TABLE not in _table_names(inspector):
        op.create_table(
            IMPORT_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
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
            sa.Column("original_file_name", sa.String(512), nullable=True),
            sa.Column("promotion_name", sa.String(512), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="preview"),
            sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("warning_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_text", sa.Text(), nullable=True),
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
        )
        return

    columns = _column_names(inspector, IMPORT_TABLE)
    additions = [
        ("user_id", sa.Integer(), False, None),
        ("marketplace_account_id", sa.Integer(), False, None),
        ("original_file_name", sa.String(512), True, None),
        ("promotion_name", sa.String(512), True, None),
        ("status", sa.String(32), False, "preview"),
        ("total_rows", sa.Integer(), False, "0"),
        ("valid_rows", sa.Integer(), False, "0"),
        ("error_rows", sa.Integer(), False, "0"),
        ("warning_rows", sa.Integer(), False, "0"),
        ("applied_at", sa.DateTime(timezone=True), True, None),
        ("error_text", sa.Text(), True, None),
        ("created_at", sa.DateTime(timezone=True), False, sa.func.now()),
        ("updated_at", sa.DateTime(timezone=True), False, sa.func.now()),
    ]
    for name, column_type, nullable, server_default in additions:
        if name not in columns:
            op.add_column(
                IMPORT_TABLE,
                sa.Column(name, column_type, nullable=nullable, server_default=server_default),
            )


def _ensure_row_table(inspector: Inspector) -> None:
    if ROW_TABLE in _table_names(inspector):
        return

    op.create_table(
        ROW_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "import_id",
            sa.Integer(),
            sa.ForeignKey(f"{IMPORT_TABLE}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("wb_nm_id", sa.BigInteger(), nullable=True),
        sa.Column("seller_article", sa.String(255), nullable=True),
        sa.Column("title", sa.String(1024), nullable=True),
        sa.Column("plan_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("current_full_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("current_discount_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("current_discounted_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("wb_upload_discount_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("wb_status", sa.String(512), nullable=True),
        sa.Column("already_participating", sa.Boolean(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def _ensure_indexes(conn: Connection) -> None:
    inspector = sa.inspect(conn)
    if IMPORT_TABLE in _table_names(inspector):
        _create_index_if_missing(
            inspector, "ix_wb_auto_promo_file_imports_user_id", IMPORT_TABLE, ["user_id"]
        )
        _create_index_if_missing(
            inspector,
            "ix_wb_auto_promo_file_imports_marketplace_account_id",
            IMPORT_TABLE,
            ["marketplace_account_id"],
        )
        _create_index_if_missing(
            inspector, "ix_wb_auto_promo_file_imports_status", IMPORT_TABLE, ["status"]
        )
        _create_index_if_missing(
            inspector, "ix_wb_auto_promo_file_imports_created_at", IMPORT_TABLE, ["created_at"]
        )
        _create_index_if_missing(
            inspector,
            "ix_wb_auto_promo_file_imports_user_created",
            IMPORT_TABLE,
            ["user_id", "created_at"],
        )

    inspector = sa.inspect(conn)
    if ROW_TABLE in _table_names(inspector):
        _create_index_if_missing(
            inspector, "ix_wb_auto_promo_file_rows_import_id", ROW_TABLE, ["import_id"]
        )
        _create_index_if_missing(
            inspector, "ix_wb_auto_promo_file_import_rows_wb_nm_id", ROW_TABLE, ["wb_nm_id"]
        )


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    _ensure_import_table(inspector)
    inspector = sa.inspect(conn)
    _ensure_row_table(inspector)
    _ensure_indexes(conn)


def downgrade() -> None:
    # Deliberately no-op: this migration repairs production schema drift and must
    # not remove import history if a rollback is attempted.
    return None
