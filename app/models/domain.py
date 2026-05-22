"""version: 1.5.0
description: Main database models for sellers, marketplaces, prices, stocks, orders, and alerts.
updated: 2026-05-17
"""

from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, int_pk
from app.models.enums import (
    AccountStatus,
    AlertType,
    CalculationType,
    FboNotificationMode,
    Marketplace,
    NotificationType,
    SaleEventType,
    SaleModel,
    SourceEventType,
    SyncJobStatus,
    UrgencyType,
    UserStatus,
)

JsonType = JSON().with_variant(JSONB, "postgresql")

if TYPE_CHECKING:
    from app.models.subscriptions import UserSubscription


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int_pk]
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.ACTIVE)
    tariff: Mapped[str] = mapped_column(String(64), default="Free")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    low_margin_threshold_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("10.00")
    )
    language: Mapped[str] = mapped_column(String(16), default="ru")
    payment_email: Mapped[str | None] = mapped_column(String(255))
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    subscription_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    accounts: Mapped[list["MarketplaceAccount"]] = relationship(back_populates="user")
    subscriptions: Mapped[list["UserSubscription"]] = relationship(back_populates="user")
    web_login_tokens: Mapped[list["OneTimeLoginToken"]] = relationship(back_populates="user")
    web_sessions: Mapped[list["UserWebSession"]] = relationship(back_populates="user")


class MarketplaceAccount(TimestampMixin, Base):
    __tablename__ = "marketplace_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "marketplace", "name", name="uq_accounts_user_marketplace_name"
        ),
        Index("ix_accounts_user_marketplace_active", "user_id", "marketplace", "is_active"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    name: Mapped[str] = mapped_column(String(255))
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    encrypted_client_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AccountStatus] = mapped_column(Enum(AccountStatus), default=AccountStatus.DRAFT)
    last_success_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_order_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_orders_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sales_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_stocks_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_products_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_profile_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ozon_enrichment_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_wb_reports_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_wb_financial_detail_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    seller_external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    seller_name: Mapped[str | None] = mapped_column(String(255))
    seller_legal_name: Mapped[str | None] = mapped_column(String(255))
    seller_info_payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notification_settings: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)

    user: Mapped[User] = relationship(back_populates="accounts")


class OneTimeLoginToken(TimestampMixin, Base):
    __tablename__ = "one_time_login_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_one_time_login_tokens_token_hash"),
        Index("ix_one_time_login_tokens_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship(back_populates="web_login_tokens")


class UserWebSession(TimestampMixin, Base):
    __tablename__ = "user_web_sessions"
    __table_args__ = (
        UniqueConstraint("session_hash", name="uq_user_web_sessions_session_hash"),
        Index("ix_user_web_sessions_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="web_sessions")


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "marketplace",
            "external_product_id",
            name="uq_products_account_marketplace_external",
        ),
        Index("ix_products_user_article", "user_id", "seller_article"),
        Index("ix_products_wb_chrt", "marketplace_account_id", "chrt_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    external_product_id: Mapped[str] = mapped_column(String(128))
    seller_article: Mapped[str | None] = mapped_column(String(255), index=True)
    marketplace_article: Mapped[str | None] = mapped_column(String(255), index=True)
    chrt_id: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(1024))
    brand: Mapped[str | None] = mapped_column(String(255))
    image_url: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(255))
    marketplace_category_id: Mapped[str | None] = mapped_column(String(128))
    length_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    volume_liters: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    dimensions_source: Mapped[str | None] = mapped_column(String(64))
    marketplace_commission_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    marketplace_commission_source: Mapped[str | None] = mapped_column(String(128))
    commission_fbw: Mapped[Decimal | None] = mapped_column("commission_fbw", Numeric(7, 4))
    commission_fbs: Mapped[Decimal | None] = mapped_column("commission_fbs", Numeric(7, 4))
    commission_dbs: Mapped[Decimal | None] = mapped_column("commission_dbs", Numeric(7, 4))
    commission_edbs: Mapped[Decimal | None] = mapped_column("commission_edbs", Numeric(7, 4))
    commission_pickup: Mapped[Decimal | None] = mapped_column("commission_pickup", Numeric(7, 4))
    commission_booking: Mapped[Decimal | None] = mapped_column(
        "commission_booking", Numeric(7, 4)
    )
    mrc_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    costs: Mapped[list["ProductCostHistory"]] = relationship(back_populates="product")
    master_links: Mapped[list["MasterProductLink"]] = relationship(back_populates="product")


class MasterProduct(TimestampMixin, Base):
    __tablename__ = "master_products"
    __table_args__ = (
        UniqueConstraint("user_id", "canonical_sku", name="uq_master_products_user_sku"),
        Index("ix_master_products_user_active", "user_id", "is_active"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    canonical_sku: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str | None] = mapped_column(String(1024))
    brand: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(255))
    image_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    links: Mapped[list["MasterProductLink"]] = relationship(back_populates="master_product")


class MasterProductLink(TimestampMixin, Base):
    __tablename__ = "master_product_links"
    __table_args__ = (
        UniqueConstraint("product_id", name="uq_master_product_links_product"),
        UniqueConstraint(
            "master_product_id",
            "marketplace",
            "seller_article",
            name="uq_master_product_links_marketplace_article",
        ),
        Index("ix_master_product_links_master", "master_product_id", "marketplace"),
    )

    id: Mapped[int_pk]
    master_product_id: Mapped[int] = mapped_column(
        ForeignKey("master_products.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    seller_article: Mapped[str | None] = mapped_column(String(255), index=True)
    marketplace_article: Mapped[str | None] = mapped_column(String(255), index=True)
    match_method: Mapped[str] = mapped_column(String(64), default="AUTO_SKU")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("1.0000"))

    master_product: Mapped[MasterProduct] = relationship(back_populates="links")
    product: Mapped[Product] = relationship(back_populates="master_links")


class ProductCostHistory(TimestampMixin, Base):
    __tablename__ = "product_cost_history"
    __table_args__ = (
        Index("ix_cost_history_product_period", "product_id", "valid_from", "valid_to"),
    )

    id: Mapped[int_pk]
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    package_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    additional_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=0)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    comment: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship(back_populates="costs")


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
    wb_logistics_distribution_surcharge_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
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


class ProfitSnapshot(TimestampMixin, Base):
    __tablename__ = "profit_snapshots"
    __table_args__ = (
        Index(
            "ix_profit_snapshots_item_type", "order_item_id", "calculation_type", "calculated_at"
        ),
    )

    id: Mapped[int_pk]
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id", ondelete="CASCADE"),
        index=True,
    )
    calculation_type: Mapped[CalculationType] = mapped_column(Enum(CalculationType), index=True)
    gross_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    marketplace_commission: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    logistics_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    acquiring_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    storage_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    return_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    other_marketplace_costs: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    package_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    additional_seller_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    profit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    margin_percent: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=0)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    calculation_source: Mapped[str] = mapped_column(String(255))
    economy_confidence: Mapped[str] = mapped_column(String(32), default="PRELIMINARY")
    raw_financial_data: Mapped[dict[str, Any] | None] = mapped_column(JsonType)

    order_item: Mapped[OrderItem] = relationship(back_populates="snapshots")


class FinancialReportRow(TimestampMixin, Base):
    __tablename__ = "financial_report_rows"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "marketplace",
            "external_row_id",
            name="uq_financial_rows_external",
        ),
        Index("ix_financial_rows_period", "marketplace_account_id", "operation_date"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id"))
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    external_row_id: Mapped[str] = mapped_column(String(255))
    order_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    product_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    operation_type: Mapped[str] = mapped_column(String(255), index=True)
    operation_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    currency: Mapped[str] = mapped_column(String(16), default="RUB")
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


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


class StockSnapshot(TimestampMixin, Base):
    __tablename__ = "stock_snapshots"
    __table_args__ = (Index("ix_stock_snapshots_product_date", "product_id", "snapshot_at"),)

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace))
    warehouse: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    average_daily_sales_7d: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    days_until_stockout: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class MarketplaceWarehouse(TimestampMixin, Base):
    __tablename__ = "marketplace_warehouses"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "marketplace",
            "external_warehouse_id",
            name="uq_marketplace_warehouses_external",
        ),
        Index("ix_marketplace_warehouses_account", "marketplace_account_id", "marketplace"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id"))
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    external_warehouse_id: Mapped[str] = mapped_column(String(128))
    name: Mapped[str | None] = mapped_column(String(255))
    warehouse_type: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class OzonPriceSnapshot(TimestampMixin, Base):
    __tablename__ = "ozon_price_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "offer_id",
            "synced_at",
            name="uq_ozon_price_snapshots_offer_synced",
        ),
        Index("ix_ozon_price_snapshots_product_latest", "product_id", "synced_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    ozon_product_id: Mapped[str | None] = mapped_column(String(128), index=True)
    offer_id: Mapped[str] = mapped_column(String(255), index=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    marketing_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency_code: Mapped[str | None] = mapped_column(String(16))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class OzonPromo(TimestampMixin, Base):
    __tablename__ = "ozon_promos"
    __table_args__ = (
        UniqueConstraint("marketplace_account_id", "external_promo_id", name="uq_ozon_promos"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id"))
    external_promo_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    date_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(String(128))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class OzonPromoProduct(TimestampMixin, Base):
    __tablename__ = "ozon_promo_products"
    __table_args__ = (
        UniqueConstraint(
            "promo_id",
            "offer_id",
            name="uq_ozon_promo_products_offer",
        ),
    )

    id: Mapped[int_pk]
    promo_id: Mapped[int] = mapped_column(ForeignKey("ozon_promos.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    ozon_product_id: Mapped[str | None] = mapped_column(String(128), index=True)
    offer_id: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str | None] = mapped_column(String(128))
    action_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_action_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class AccountBalanceSnapshot(TimestampMixin, Base):
    __tablename__ = "account_balance_snapshots"
    __table_args__ = (Index("ix_account_balance_latest", "marketplace_account_id", "fetched_at"),)

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), index=True
    )
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    currency: Mapped[str] = mapped_column(String(16), default="RUB")
    current: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    for_withdraw: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    accrued: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    payments_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(64), default="OK")
    error_message: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class WbFinancialReport(TimestampMixin, Base):
    __tablename__ = "wb_financial_reports"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "period_type",
            "report_id",
            name="uq_wb_reports_account_period_report",
        ),
        Index("ix_wb_reports_period", "marketplace_account_id", "period_type", "date_from"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), index=True
    )
    report_id: Mapped[str] = mapped_column(String(128))
    period_type: Mapped[str] = mapped_column(String(16), index=True)
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    create_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str | None] = mapped_column(String(16))
    report_type: Mapped[str | None] = mapped_column(String(128))
    retail_amount_sum: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    for_pay_sum: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    delivery_service_sum: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class WbReportCheckState(TimestampMixin, Base):
    __tablename__ = "wb_report_check_states"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "period_type",
            name="uq_wb_report_check_account_period",
        ),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), index=True
    )
    period_type: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(64), default="UNKNOWN")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    reports_found: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class WbPromotion(TimestampMixin, Base):
    __tablename__ = "wb_promotions"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "wb_promotion_id",
            name="uq_wb_promotions_account_promo",
        ),
        Index("ix_wb_promotions_account_active", "marketplace_account_id", "is_active_today"),
        Index("ix_wb_promotions_dates", "start_datetime", "end_datetime"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), index=True
    )
    wb_promotion_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str | None] = mapped_column(String(512))
    promotion_type: Mapped[str | None] = mapped_column(String(64))
    start_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active_today: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class WbPromotionNomenclature(TimestampMixin, Base):
    __tablename__ = "wb_promotion_nomenclatures"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "wb_promotion_id",
            "wb_nm_id",
            "in_action",
            name="uq_wb_promo_nomenclatures_account_promo_nm_action",
        ),
        Index("ix_wb_promo_nomenclatures_nm", "marketplace_account_id", "wb_nm_id"),
        Index("ix_wb_promo_nomenclatures_promo", "marketplace_account_id", "wb_promotion_id"),
        Index("ix_wb_promo_nomenclatures_synced", "marketplace_account_id", "synced_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), index=True
    )
    wb_promotion_id: Mapped[int] = mapped_column(BigInteger, index=True)
    wb_nm_id: Mapped[int] = mapped_column(BigInteger, index=True)
    in_action: Mapped[bool] = mapped_column(Boolean, default=False)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency_code: Mapped[str | None] = mapped_column(String(16))
    plan_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    current_discount: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    plan_discount: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class PlanFactTarget(TimestampMixin, Base):
    __tablename__ = "plan_fact_targets"
    __table_args__ = (
        Index("ix_plan_fact_targets_user_period", "user_id", "period_start", "period_end"),
        Index("ix_plan_fact_targets_user_marketplace", "user_id", "marketplace"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace: Mapped[Marketplace | None] = mapped_column(Enum(Marketplace), nullable=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    revenue_plan: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    profit_plan: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    orders_plan: Mapped[int | None] = mapped_column(Integer)
    buyouts_plan: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    comment: Mapped[str | None] = mapped_column(Text)


class NotificationSetting(TimestampMixin, Base):
    __tablename__ = "notification_settings"
    __table_args__ = (UniqueConstraint("user_id", "marketplace_account_id", "notification_type"),)

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id")
    )
    notification_type: Mapped[NotificationType] = mapped_column(Enum(NotificationType))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_from: Mapped[time | None] = mapped_column(Time)
    quiet_to: Mapped[time | None] = mapped_column(Time)
    settings: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


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


class AlertRule(TimestampMixin, Base):
    __tablename__ = "alert_rules"
    __table_args__ = (UniqueConstraint("user_id", "marketplace_account_id", "alert_type"),)

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id")
    )
    alert_type: Mapped[AlertType] = mapped_column(Enum(AlertType), index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    threshold: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    settings: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class AlertEvent(TimestampMixin, Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint("rule_id", "idempotency_key", name="uq_alert_events_rule_key"),
        Index("ix_alert_events_user_created", "user_id", "created_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id", ondelete="SET NULL"))
    alert_type: Mapped[AlertType] = mapped_column(Enum(AlertType), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailyReport(TimestampMixin, Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("user_id", "report_date"),)

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    message_text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncJob(TimestampMixin, Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (Index("ix_sync_jobs_account_type", "marketplace_account_id", "job_type"),)

    id: Mapped[int_pk]
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    marketplace_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id")
    )
    marketplace: Mapped[Marketplace | None] = mapped_column(Enum(Marketplace), index=True)
    job_type: Mapped[str] = mapped_column(String(128), index=True)
    date_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    date_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[SyncJobStatus] = mapped_column(
        Enum(SyncJobStatus), default=SyncJobStatus.PENDING
    )
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    processed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    records_loaded: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    records_failed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    job_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonType, default=dict)


class ApiRequestLog(TimestampMixin, Base):
    __tablename__ = "api_request_logs"
    __table_args__ = (Index("ix_api_logs_account_created", "marketplace_account_id", "created_at"),)

    id: Mapped[int_pk]
    marketplace_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id")
    )
    marketplace: Mapped[Marketplace | None] = mapped_column(Enum(Marketplace))
    method: Mapped[str] = mapped_column(String(16))
    url: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)


class SubscriptionPlan(TimestampMixin, Base):
    __tablename__ = "subscription_plans"

    id: Mapped[int_pk]
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    marketplace_limit: Mapped[int] = mapped_column(Integer, default=1)
    sku_limit: Mapped[int] = mapped_column(Integer, default=100)
    features: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Subscription(TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_subscriptions_user_status", "user_id", "status"),)

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"))
    status: Mapped[str] = mapped_column(String(64), default="ACTIVE")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_provider: Mapped[str | None] = mapped_column(String(128))
    external_subscription_id: Mapped[str | None] = mapped_column(String(255))


class MrcImport(TimestampMixin, Base):
    __tablename__ = "mrc_imports"

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    original_file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="preview")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cleared_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rows: Mapped[list["MrcImportRow"]] = relationship(back_populates="import_record", cascade="all, delete-orphan")


class MrcImportRow(TimestampMixin, Base):
    __tablename__ = "mrc_import_rows"
    __table_args__ = (Index("ix_mrc_import_rows_import_id", "import_id"),)

    id: Mapped[int_pk]
    import_id: Mapped[int] = mapped_column(ForeignKey("mrc_imports.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wb_nm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seller_sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    old_mrc_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    new_mrc_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=sa.func.now())

    import_record: Mapped["MrcImport"] = relationship(back_populates="rows")


class MrcPricingSettings(TimestampMixin, Base):
    __tablename__ = "mrc_pricing_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "marketplace_account_id", name="uq_mrc_settings_user_account"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    marketplace_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    marketplace: Mapped[str] = mapped_column(String(16), nullable=False, default="wb")
    default_discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("75.00"))
    full_price_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("4.00"))
    allowed_action_price_deviation_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("10.00"))
    auto_promo_check_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_add_to_promotions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_price_for_auto_promotions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now())


class WbAutoPromotionCondition(TimestampMixin, Base):
    __tablename__ = "wb_auto_promotion_conditions"
    __table_args__ = (
        Index("ix_auto_promo_conditions_account_promo_nm", "marketplace_account_id", "wb_promotion_id", "wb_nm_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    wb_promotion_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    wb_nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    seller_article: Mapped[str | None] = mapped_column(String(256), nullable=True)
    required_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_wb_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="api")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WbAutoPromoPriceRecommendation(TimestampMixin, Base):
    __tablename__ = "wb_auto_promo_price_recommendations"
    __table_args__ = (
        Index("ix_auto_promo_recs_account_status", "marketplace_account_id", "status"),
        Index("ix_auto_promo_recs_product", "product_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    wb_nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    wb_promotion_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mrc_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_wb_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    required_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    recommended_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    mrc_lower_bound: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    mrc_upper_bound: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="calculation")


class WbPriceChangeHistory(Base):
    __tablename__ = "wb_price_change_history"
    __table_args__ = (
        Index("ix_price_change_history_nm", "wb_nm_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    wb_nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    new_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False, default="auto_promotion")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=sa.func.now())
