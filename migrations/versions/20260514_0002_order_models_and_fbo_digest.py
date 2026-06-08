"""order models and fbo digest

version: 1.0.0
description: Extend orders for FBO/FBS/rFBS semantics and add FBO digest queue.
updated: 2026-05-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260514_0002"
down_revision: str | None = "20260514_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    urgency_type = postgresql.ENUM(
        "ACTION_REQUIRED",
        "INFORMATIONAL",
        name="urgencytype",
        create_type=False,
    )
    source_event_type = postgresql.ENUM(
        "LIVE_ORDER",
        "STATISTICS_ORDER",
        "REPORT_ORDER",
        "POSTING_EVENT",
        name="sourceeventtype",
        create_type=False,
    )
    fbo_notification_mode = postgresql.ENUM(
        "INSTANT",
        "DIGEST_30_MIN",
        "DAILY_ONLY",
        name="fbonotificationmode",
        create_type=False,
    )
    for enum in [urgency_type, source_event_type, fbo_notification_mode]:
        enum.create(op.get_bind(), checkfirst=True)

    op.add_column("orders", sa.Column("fulfillment_type", sa.String(length=64), nullable=True))
    op.add_column("orders", sa.Column("urgency_type", urgency_type, nullable=True))
    op.add_column("orders", sa.Column("source_event_type", source_event_type, nullable=True))
    op.add_column("orders", sa.Column("raw_status", sa.String(length=128), nullable=True))
    op.add_column("orders", sa.Column("normalized_status", sa.String(length=128), nullable=True))
    op.add_column("orders", sa.Column("warehouse_type", sa.String(length=128), nullable=True))
    op.add_column("orders", sa.Column("delivery_schema", sa.String(length=128), nullable=True))
    op.add_column(
        "orders",
        sa.Column("processing_deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "requires_seller_action", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "orders", sa.Column("first_notified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "orders", sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_orders_processing_deadline", "orders", ["processing_deadline_at"])
    op.create_index("ix_orders_normalized_status", "orders", ["normalized_status"])

    op.execute("""
        UPDATE orders
        SET
            fulfillment_type = COALESCE(sale_model::text, 'FBS'),
            urgency_type = CASE
                WHEN sale_model::text IN (
                    'FBS', 'rFBS', 'DBS', 'DBW'
                ) THEN 'ACTION_REQUIRED'::urgencytype
                ELSE 'INFORMATIONAL'::urgencytype
            END,
            source_event_type = 'LIVE_ORDER'::sourceeventtype,
            raw_status = status,
            normalized_status = status,
            processing_deadline_at = deadline_at,
            requires_seller_action = CASE
                WHEN sale_model::text IN ('FBS', 'rFBS', 'DBS', 'DBW') THEN true
                ELSE false
            END
        """)

    op.create_table(
        "fbo_digest_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "marketplace",
            postgresql.ENUM("WB", "OZON", name="marketplace", create_type=False),
            nullable=False,
        ),
        sa.Column("revenue", sa.Numeric(12, 2), nullable=False),
        sa.Column("estimated_profit", sa.Numeric(12, 2), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mode", fbo_notification_mode, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "order_id", name="uq_fbo_digest_user_order"),
    )
    op.create_index("ix_fbo_digest_user_sent", "fbo_digest_queue", ["user_id", "sent_at"])


def downgrade() -> None:
    op.drop_index("ix_fbo_digest_user_sent", table_name="fbo_digest_queue")
    op.drop_table("fbo_digest_queue")
    op.drop_index("ix_orders_normalized_status", table_name="orders")
    op.drop_index("ix_orders_processing_deadline", table_name="orders")
    for column in [
        "last_notified_at",
        "first_notified_at",
        "requires_seller_action",
        "processing_deadline_at",
        "delivery_schema",
        "warehouse_type",
        "normalized_status",
        "raw_status",
        "source_event_type",
        "urgency_type",
        "fulfillment_type",
    ]:
        op.drop_column("orders", column)
    for enum_name in ["fbonotificationmode", "sourceeventtype", "urgencytype"]:
        postgresql.ENUM(name=enum_name).drop(op.get_bind(), checkfirst=True)
