"""SQLAlchemy models for orders."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, int_pk
from app.models.enums import (
    FboNotificationMode,
    Marketplace,
    SaleEventType,
    SaleModel,
    SourceEventType,
    UrgencyType,
)

JsonType = JSON().with_variant(JSONB, "postgresql")

if TYPE_CHECKING:
    from app.models.finance import ProfitSnapshot

class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "marketplace",
            "order_external_id",
            name="uq_orders_account_marketplace_external",
        ),
        Index("ix_orders_user_date", "user_id", "order_date"),
        Index("ix_orders_deadline_status", "deadline_at", "status"),
        Index("ix_orders_deleted", "deleted_at"),
        Index(
            "ix_orders_account_unnotified",
            "marketplace_account_id",
            "first_notified_at",
            "sale_model",
        ),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    order_external_id: Mapped[str] = mapped_column(String(255))
    posting_number: Mapped[str | None] = mapped_column(String(255), index=True)
    assembly_id: Mapped[str | None] = mapped_column(String(255), index=True)
    srid: Mapped[str | None] = mapped_column(String(255), index=True)
    order_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sale_model: Mapped[SaleModel | None] = mapped_column(
        Enum(SaleModel, values_callable=lambda e: [m.value for m in e])
    )
    fulfillment_type: Mapped[str | None] = mapped_column(String(64))
    urgency_type: Mapped[UrgencyType | None] = mapped_column(Enum(UrgencyType))
    source_event_type: Mapped[SourceEventType | None] = mapped_column(Enum(SourceEventType))
    status: Mapped[str] = mapped_column(String(128), index=True)
    raw_status: Mapped[str | None] = mapped_column(String(128), index=True)
    normalized_status: Mapped[str | None] = mapped_column(String(128), index=True)
    warehouse: Mapped[str | None] = mapped_column(String(255))
    warehouse_type: Mapped[str | None] = mapped_column(String(128))
    delivery_schema: Mapped[str | None] = mapped_column(String(128))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    processing_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    requires_seller_action: Mapped[bool] = mapped_column(Boolean, default=False)
    first_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deleted_reason: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")

class OrderItem(TimestampMixin, Base):
    __tablename__ = "order_items"
    __table_args__ = (Index("ix_order_items_articles", "seller_article", "marketplace_article"),)

    id: Mapped[int_pk]
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    seller_article: Mapped[str | None] = mapped_column(String(255))
    marketplace_article: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(1024))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    buyer_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    seller_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    discounted_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    payout_amount_estimated: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    seller_payout_estimated: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    commission_estimated: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    commission_source: Mapped[str | None] = mapped_column(String(64))
    commission_percent_planned: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    commission_amount_planned: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    commission_rate_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_commission_versions.id", ondelete="SET NULL")
    )
    commission_rate_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_commission_rates.id", ondelete="SET NULL")
    )
    commission_match_status: Mapped[str | None] = mapped_column(String(32))
    commission_calculation_confidence: Mapped[str | None] = mapped_column(String(32))
    ozon_commission_base_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    logistics_estimated: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    logistics_source: Mapped[str | None] = mapped_column(String(64))
    wb_logistics_amount_planned: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    wb_logistics_base_tariff: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    wb_logistics_warehouse_coefficient_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4)
    )
    wb_logistics_localization_index: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    wb_logistics_distribution_index_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    wb_logistics_distribution_surcharge_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2)
    )
    wb_logistics_tariff_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("wb_logistics_tariff_versions.id", ondelete="SET NULL")
    )
    wb_logistics_tariff_rate_id: Mapped[int | None] = mapped_column(
        ForeignKey("wb_logistics_tariff_rates.id", ondelete="SET NULL")
    )
    wb_logistics_source: Mapped[str | None] = mapped_column(String(64))
    wb_logistics_confidence: Mapped[str | None] = mapped_column(String(32))
    wb_reverse_logistics_amount_planned: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    other_marketplace_expenses_estimated: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    cost_price_used: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    package_cost_used: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    tax_amount_estimated: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    profit_estimated: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    margin_percent_estimated: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    economy_confidence: Mapped[str] = mapped_column(String(32), default="PRELIMINARY")

    order: Mapped[Order] = relationship(back_populates="items")
    snapshots: Mapped[list["ProfitSnapshot"]] = relationship(back_populates="order_item")

class SalesEvent(TimestampMixin, Base):
    __tablename__ = "sales_events"
    __table_args__ = (
        UniqueConstraint("marketplace_account_id", "marketplace", "external_event_id"),
        Index("ix_sales_events_date", "user_id", "event_date"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id"))
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace))
    related_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )
    related_order_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_items.id", ondelete="SET NULL"), index=True
    )
    external_event_id: Mapped[str] = mapped_column(String(255))
    order_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    event_type: Mapped[SaleEventType] = mapped_column(
        Enum(SaleEventType), default=SaleEventType.SALE_COMPLETED, index=True
    )
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    seller_article: Mapped[str | None] = mapped_column(String(255), index=True)
    marketplace_article: Mapped[str | None] = mapped_column(String(255), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    expected_payout: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    estimated_profit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    actual_profit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)

class ReturnsEvent(TimestampMixin, Base):
    __tablename__ = "returns_events"
    __table_args__ = (
        UniqueConstraint("marketplace_account_id", "marketplace", "external_event_id"),
        Index("ix_returns_events_date", "user_id", "event_date"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id"))
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace))
    external_event_id: Mapped[str] = mapped_column(String(255))
    order_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    reason: Mapped[str | None] = mapped_column(String(512))
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)

class FboDigestQueue(TimestampMixin, Base):
    __tablename__ = "fbo_digest_queue"
    __table_args__ = (
        UniqueConstraint("user_id", "order_id", name="uq_fbo_digest_user_order"),
        Index("ix_fbo_digest_user_sent", "user_id", "sent_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    estimated_profit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    mode: Mapped[FboNotificationMode] = mapped_column(
        Enum(FboNotificationMode),
        default=FboNotificationMode.DIGEST_30_MIN,
    )
