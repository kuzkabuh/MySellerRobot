"""version: 1.0.0
description: Добавление расширенных полей в subscription_tiers для admin billing dashboard.
date: 2026-06-12

Добавляет поля:
- is_featured      — рекомендуемый тариф (выделяется на витрине)
- badge_text       — метка тарифа: «Популярный», «Для старта» и т.п.
- trial_days       — продолжительность бесплатного пробного периода
- is_custom_price  — тариф индивидуальный / по запросу
- internal_note    — внутренняя заметка для администратора

Revision ID: 20260612_0066
Revises: 20260610_0065
Create Date: 2026-06-12
"""

import sqlalchemy as sa
from alembic import op

revision = "20260612_0066"
down_revision = "20260610_0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "is_featured",
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "badge_text",
        sa.Column("badge_text", sa.String(64), nullable=True),
    )
    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "trial_days",
        sa.Column("trial_days", sa.Integer(), nullable=True),
    )
    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "is_custom_price",
        sa.Column("is_custom_price", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    _add_column_if_not_exists(
        conn,
        "subscription_tiers",
        "internal_note",
        sa.Column("internal_note", sa.Text(), nullable=True),
    )

    # Помечаем PRO как рекомендуемый и добавляем метки
    conn.execute(sa.text("""
        UPDATE subscription_tiers SET is_featured = true, badge_text = 'Популярный'
        WHERE code = 'pro' AND is_featured = false
    """))
    conn.execute(sa.text("""
        UPDATE subscription_tiers SET badge_text = 'Для старта'
        WHERE code = 'basic' AND badge_text IS NULL
    """))
    conn.execute(sa.text("""
        UPDATE subscription_tiers SET badge_text = 'Для бизнеса'
        WHERE code = 'business' AND badge_text IS NULL
    """))
    conn.execute(sa.text("""
        UPDATE subscription_tiers SET is_custom_price = true
        WHERE code = 'enterprise' AND is_custom_price = false
    """))


def downgrade() -> None:
    op.drop_column("subscription_tiers", "internal_note")
    op.drop_column("subscription_tiers", "is_custom_price")
    op.drop_column("subscription_tiers", "trial_days")
    op.drop_column("subscription_tiers", "badge_text")
    op.drop_column("subscription_tiers", "is_featured")


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
