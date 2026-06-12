"""version: 1.0.0
description: Полноценный модуль управления ценами.

Изменения:
- products: добавлены min_price, max_price
- ozon_current_prices: текущие цены Ozon (аналог wb_product_prices)
- price_change_log: единый журнал ручных изменений цен (WB + Ozon)

Revision ID: 20260613_0068
Revises: 20260613_0067
Create Date: 2026-06-13
"""

import sqlalchemy as sa
from alembic import op

revision = "20260613_0068"
down_revision = "20260613_0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── products: min_price, max_price ──────────────────────────────────────
    _add_column_if_not_exists(
        conn,
        "products",
        "min_price",
        sa.Column("min_price", sa.Numeric(12, 2), nullable=True),
    )
    _add_column_if_not_exists(
        conn,
        "products",
        "max_price",
        sa.Column("max_price", sa.Numeric(12, 2), nullable=True),
    )

    # ── ozon_current_prices ─────────────────────────────────────────────────
    if not _table_exists(conn, "ozon_current_prices"):
        op.create_table(
            "ozon_current_prices",
            sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
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
            sa.Column(
                "product_id",
                sa.Integer(),
                sa.ForeignKey("products.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("ozon_product_id", sa.String(128), nullable=True),
            sa.Column("offer_id", sa.String(255), nullable=False),
            sa.Column("price", sa.Numeric(12, 2), nullable=True),
            sa.Column("old_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("marketing_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("min_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("currency_code", sa.String(16), nullable=False, server_default="RUB"),
            sa.Column("raw_payload", sa.JSON(), nullable=True),
            sa.Column(
                "synced_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
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
            sa.UniqueConstraint(
                "marketplace_account_id",
                "offer_id",
                name="uq_ozon_current_prices_account_offer",
            ),
        )
        op.create_index("ix_ozon_current_prices_user", "ozon_current_prices", ["user_id"])
        op.create_index(
            "ix_ozon_current_prices_account", "ozon_current_prices", ["marketplace_account_id"]
        )
        op.create_index("ix_ozon_current_prices_offer", "ozon_current_prices", ["offer_id"])
        op.create_index(
            "ix_ozon_current_prices_product", "ozon_current_prices", ["product_id"]
        )

    # ── price_change_log ────────────────────────────────────────────────────
    if not _table_exists(conn, "price_change_log"):
        op.create_table(
            "price_change_log",
            sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
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
            sa.Column(
                "product_id",
                sa.Integer(),
                sa.ForeignKey("products.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("marketplace", sa.String(32), nullable=False),
            sa.Column("external_product_id", sa.String(128), nullable=False),
            sa.Column("seller_article", sa.String(255), nullable=True),
            sa.Column("old_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("new_price", sa.Numeric(12, 2), nullable=False),
            sa.Column("old_discount", sa.Integer(), nullable=True),
            sa.Column("new_discount", sa.Integer(), nullable=True),
            # WB-specific (полная цена до скидки + скидка)
            sa.Column("wb_price_sent", sa.Integer(), nullable=True),
            sa.Column("wb_discount_sent", sa.Integer(), nullable=True),
            sa.Column("wb_upload_id", sa.BigInteger(), nullable=True),
            # Метаданные
            sa.Column("source", sa.String(64), nullable=False, server_default="manual"),
            sa.Column("reason", sa.String(128), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("changed_by_user_id", sa.Integer(), nullable=True),
            sa.Column("changed_by_ip", sa.String(64), nullable=True),
            # Статус
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("raw_response", sa.JSON(), nullable=True),
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
        op.create_index("ix_price_change_log_user", "price_change_log", ["user_id"])
        op.create_index(
            "ix_price_change_log_account", "price_change_log", ["marketplace_account_id"]
        )
        op.create_index("ix_price_change_log_product", "price_change_log", ["product_id"])
        op.create_index(
            "ix_price_change_log_marketplace", "price_change_log", ["marketplace"]
        )
        op.create_index(
            "ix_price_change_log_created", "price_change_log", ["created_at"]
        )
        op.create_index(
            "ix_price_change_log_external_id",
            "price_change_log",
            ["marketplace_account_id", "external_product_id"],
        )


def downgrade() -> None:
    op.drop_table("price_change_log")
    op.drop_table("ozon_current_prices")
    op.drop_column("products", "max_price")
    op.drop_column("products", "min_price")


def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :tbl"
        ),
        {"tbl": table_name},
    )
    return result.scalar_one_or_none() is not None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col"
        ),
        {"table": table_name, "col": column_name},
    )
    return result.scalar_one_or_none() is not None


def _add_column_if_not_exists(conn, table_name: str, column_name: str, column: sa.Column) -> None:
    if not _column_exists(conn, table_name, column_name):
        op.add_column(table_name, column)
