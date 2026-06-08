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
    last_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    company_name: Mapped[str | None] = mapped_column(String(255))
    inn: Mapped[str | None] = mapped_column(String(32))
    ogrn: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.ACTIVE)
    role: Mapped[str] = mapped_column(String(32), default="user")
    tariff: Mapped[str] = mapped_column(String(64), default="Free")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    low_margin_threshold_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("10.00")
    )
    language: Mapped[str] = mapped_column(String(16), default="ru")
    payment_email: Mapped[str | None] = mapped_column(String(255))
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    subscription_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_ip: Mapped[str | None] = mapped_column(String(64))
    last_login_user_agent: Mapped[str | None] = mapped_column(String(512))
    web_login: Mapped[str | None] = mapped_column(String(64))
    web_password_hash: Mapped[str | None] = mapped_column(String(255))
    web_password_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    web_password_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_password_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    accounts: Mapped[list["MarketplaceAccount"]] = relationship(back_populates="user")
    subscriptions: Mapped[list["UserSubscription"]] = relationship(back_populates="user")
    web_login_tokens: Mapped[list["OneTimeLoginToken"]] = relationship(back_populates="user")
    web_sessions: Mapped[list["UserWebSession"]] = relationship(back_populates="user")
    activity_logs: Mapped[list["UserActivityLog"]] = relationship(back_populates="user")
    api_key_logs: Mapped[list["ApiKeyAuditLog"]] = relationship(back_populates="user")
    sync_statuses: Mapped[list["SyncStatus"]] = relationship(back_populates="user")
    support_tickets: Mapped[list["SupportTicket"]] = relationship(back_populates="user")
    support_ticket_events: Mapped[list["SupportTicketEvent"]] = relationship(back_populates="actor")
    company_profile: Mapped["UserCompanyProfile | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )


class UserCompanyProfile(TimestampMixin, Base):
    __tablename__ = "user_company_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_company_profiles_user_id"),
        Index("ix_user_company_profiles_inn", "inn"),
        Index("ix_user_company_profiles_ogrn", "ogrn"),
        Index("ix_user_company_profiles_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    inn: Mapped[str] = mapped_column(String(12))
    kpp: Mapped[str | None] = mapped_column(String(9))
    ogrn: Mapped[str | None] = mapped_column(String(15))
    name_full: Mapped[str | None] = mapped_column(Text)
    name_short: Mapped[str | None] = mapped_column(Text)
    company_type: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(Text)
    okved: Mapped[str | None] = mapped_column(String(32))
    okved_name: Mapped[str | None] = mapped_column(Text)
    director_name: Mapped[str | None] = mapped_column(Text)
    registration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(32))
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JsonType)

    user: Mapped[User] = relationship(back_populates="company_profile")


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
    last_wb_reports_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    api_key_status: Mapped[str] = mapped_column(String(32), default="unchecked")
    api_key_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    api_key_check_result: Mapped[dict[str, Any] | None] = mapped_column(JsonType)

    user: Mapped[User] = relationship(back_populates="accounts")
    api_key_logs: Mapped[list["ApiKeyAuditLog"]] = relationship(back_populates="account")


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
        Index("ix_products_barcode", "marketplace_account_id", "barcode"),
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
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    commission_booking: Mapped[Decimal | None] = mapped_column("commission_booking", Numeric(7, 4))
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
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rows: Mapped[list["MrcImportRow"]] = relationship(
        back_populates="import_record", cascade="all, delete-orphan"
    )


class MrcImportRow(TimestampMixin, Base):
    __tablename__ = "mrc_import_rows"
    __table_args__ = (Index("ix_mrc_import_rows_import_id", "import_id"),)

    id: Mapped[int_pk]
    import_id: Mapped[int] = mapped_column(
        ForeignKey("mrc_imports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wb_nm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seller_sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    old_mrc_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    new_mrc_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    import_record: Mapped["MrcImport"] = relationship(back_populates="rows")


class MrcPricingSettings(TimestampMixin, Base):
    __tablename__ = "mrc_pricing_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "marketplace_account_id", name="uq_mrc_settings_user_account"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    marketplace: Mapped[str] = mapped_column(String(16), nullable=False, default="wb")
    default_discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("75.00")
    )
    full_price_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("4.00")
    )
    allowed_action_price_deviation_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("10.00")
    )
    auto_promo_check_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_add_to_promotions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_price_for_auto_promotions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class WbAutoPromotionCondition(TimestampMixin, Base):
    __tablename__ = "wb_auto_promotion_conditions"
    __table_args__ = (
        sa.UniqueConstraint(
            "marketplace_account_id",
            "wb_promotion_id",
            "wb_nm_id",
            "source",
            name="uq_auto_promo_cond_acct_promo_nm_src",
        ),
        sa.UniqueConstraint(
            "marketplace_account_id",
            "wb_nm_id",
            "promotion_name",
            "source",
            name="uq_auto_promo_cond_acct_nm_pname_src",
        ),
        Index("ix_auto_promo_cond_account_nm", "marketplace_account_id", "wb_nm_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    wb_promotion_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    wb_nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    seller_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    promotion_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    required_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_auto_promo_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    wb_condition_discount_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    current_wb_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_full_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    candidate_discounted_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    condition_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    is_participating: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WbAutoPromoFileImport(TimestampMixin, Base):
    __tablename__ = "wb_auto_promo_file_imports"
    __table_args__ = (Index("ix_wb_auto_promo_file_imports_user_created", "user_id", "created_at"),)

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    promotion_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="preview")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    rows: Mapped[list["WbAutoPromoFileImportRow"]] = relationship(
        back_populates="import_record",
        cascade="all, delete-orphan",
    )


class WbAutoPromoFileImportRow(TimestampMixin, Base):
    __tablename__ = "wb_auto_promo_file_import_rows"
    __table_args__ = (Index("ix_wb_auto_promo_file_rows_import_id", "import_id"),)

    id: Mapped[int_pk]
    import_id: Mapped[int] = mapped_column(
        ForeignKey("wb_auto_promo_file_imports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    wb_nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    seller_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    plan_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_full_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    current_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    wb_upload_discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    wb_status: Mapped[str | None] = mapped_column(String(512), nullable=True)
    already_participating: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    import_record: Mapped["WbAutoPromoFileImport"] = relationship(back_populates="rows")


class WbAutoPromoPriceRecommendation(TimestampMixin, Base):
    __tablename__ = "wb_auto_promo_price_recommendations"
    __table_args__ = (
        Index("ix_auto_promo_recs_acct_nm_status", "marketplace_account_id", "wb_nm_id", "status"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    wb_nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    wb_promotion_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    promotion_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mrc_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_wb_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    required_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    required_price_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recommended_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_full_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_auto_promo_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    wb_condition_discount_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    candidate_discounted_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    recommended_discounted_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    recommended_full_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    recommended_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    safe_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    safe_full_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    safe_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    condition_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    mrc_lower_bound: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    mrc_upper_bound: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="calculation")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WbPriceChangeHistory(Base):
    __tablename__ = "wb_price_change_history"
    __table_args__ = (
        Index("ix_price_change_hist_nm", "wb_nm_id"),
        Index("ix_price_change_hist_account_created", "marketplace_account_id", "created_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    wb_nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    wb_upload_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    new_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    target_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    wb_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wb_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    mrc_lower_bound: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    mrc_upper_bound: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False, default="auto_promotion")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class WbProductPrice(Base):
    __tablename__ = "wb_product_prices"
    __table_args__ = (
        sa.UniqueConstraint(
            "marketplace_account_id",
            "wb_nm_id",
            name="uq_wb_product_prices_account_nm",
        ),
        Index("ix_wb_product_prices_account", "marketplace_account_id"),
        Index("ix_wb_product_prices_nm", "wb_nm_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    wb_nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    discount: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    club_discount: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    club_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(16), nullable=False, default="RUB")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_audit_logs_action_created", "action", "created_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)


class SyncTaskRun(Base):
    __tablename__ = "sync_task_runs"
    __table_args__ = (
        Index("ix_sync_task_runs_task_started", "task_name", "started_at"),
        Index("ix_sync_task_runs_status_started", "status", "started_at"),
    )

    id: Mapped[int_pk]
    task_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="started", index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    run_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JsonType, nullable=True)


class NotificationEvent(TimestampMixin, Base):
    __tablename__ = "notification_events"
    __table_args__ = (
        Index("ix_notification_events_user_status", "user_id", "status"),
        Index("ix_notification_events_status_created", "status", "created_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False, default="generic")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    permanent_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ApiKeyAuditLog(TimestampMixin, Base):
    __tablename__ = "api_key_audit_logs"
    __table_args__ = (
        Index("ix_api_key_audit_logs_user_id", "user_id"),
        Index("ix_api_key_audit_logs_account_id", "account_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), index=True
    )
    marketplace: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    old_key_mask: Mapped[str | None] = mapped_column(String(64))
    new_key_mask: Mapped[str | None] = mapped_column(String(64))
    check_result: Mapped[str | None] = mapped_column(String(32))
    check_details: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    ip_address: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="api_key_logs")
    account: Mapped[MarketplaceAccount] = relationship(back_populates="api_key_logs")


class UserActivityLog(TimestampMixin, Base):
    __tablename__ = "user_activity_logs"
    __table_args__ = (
        Index("ix_user_activity_logs_user_id", "user_id"),
        Index("ix_user_activity_logs_created_at", "created_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship(back_populates="activity_logs")


class SyncStatus(TimestampMixin, Base):
    __tablename__ = "sync_statuses"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "account_id", "sync_type", name="uq_sync_statuses_user_account_type"
        ),
        Index("ix_sync_statuses_user_id", "user_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=True
    )
    sync_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    items_processed: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Numeric(10, 2))

    user: Mapped[User] = relationship(back_populates="sync_statuses")


class SupportTicket(TimestampMixin, Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        Index("ix_support_tickets_user_id", "user_id"),
        Index("ix_support_tickets_status", "status"),
        Index("ix_support_tickets_priority", "priority"),
        Index("ix_support_tickets_telegram_id", "telegram_id"),
        Index("ix_support_tickets_created_at", "created_at"),
        Index("ix_support_tickets_assigned_admin_id", "assigned_admin_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(512))
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    category: Mapped[str | None] = mapped_column(String(64))
    admin_comment: Mapped[str | None] = mapped_column(Text)
    assigned_admin_id: Mapped[int | None] = mapped_column(Integer)
    admin_response: Mapped[str | None] = mapped_column(Text)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_by: Mapped[int | None] = mapped_column(Integer)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="support_tickets")
    events: Mapped[list["SupportTicketEvent"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
    )


class SupportTicketEvent(Base):
    __tablename__ = "user_support_ticket_events"
    __table_args__ = (
        Index("ix_support_ticket_events_ticket_id", "ticket_id"),
        Index("ix_support_ticket_events_created_at", "created_at"),
    )

    id: Mapped[int_pk]
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    ticket: Mapped[SupportTicket] = relationship(back_populates="events")
    actor: Mapped[User | None] = relationship(back_populates="support_ticket_events")


class WbDailyReportImport(TimestampMixin, Base):
    """Metadata for a single WB daily realisation-report import attempt."""

    __tablename__ = "wb_daily_report_imports"
    __table_args__ = (
        Index("ix_wb_daily_report_imports_user", "user_id"),
        Index("ix_wb_daily_report_imports_account", "marketplace_account_id"),
        Index("ix_wb_daily_report_imports_created", "created_at"),
        Index("ix_wb_daily_report_imports_deleted", "deleted_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="file")
    report_type: Mapped[str] = mapped_column(String(16), nullable=False, default="daily")
    original_filename: Mapped[str | None] = mapped_column(String(512))
    report_number: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_pending_match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_ambiguous_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    delete_reason: Mapped[str | None] = mapped_column(Text)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    rows: Mapped[list["WbDailyReportRow"]] = relationship(
        back_populates="import_record",
        cascade="all, delete-orphan",
    )


class WbDailyReportRow(TimestampMixin, Base):
    """Single row of a WB daily realisation report (XLSX import)."""

    __tablename__ = "wb_daily_report_rows"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "report_type",
            "report_number",
            "row_hash",
            name="ux_wb_daily_report_row_dedupe",
        ),
        Index("ix_wb_daily_report_rows_user", "user_id"),
        Index("ix_wb_daily_report_rows_account", "marketplace_account_id"),
        Index("ix_wb_daily_report_rows_import", "import_id"),
        Index("ix_wb_daily_report_rows_type", "report_type"),
        Index("ix_wb_daily_report_rows_sale_dt", "sale_dt"),
        Index("ix_wb_daily_report_rows_order_dt", "order_dt"),
        Index("ix_wb_daily_report_rows_barcode", "barcode"),
        Index("ix_wb_daily_report_rows_supplier_article", "supplier_article"),
        Index("ix_wb_daily_report_rows_shk", "shk"),
        Index("ix_wb_daily_report_rows_payment_reason", "payment_reason"),
        Index("ix_wb_daily_report_rows_srid", "srid"),
        Index("ix_wb_daily_report_rows_status", "row_status"),
        Index("ix_wb_daily_report_rows_source_hash", "source_row_hash"),
        Index("ix_wb_daily_report_rows_stable_key", "stable_business_key"),
        Index("ix_wb_daily_report_rows_srid_raw", "srid_raw"),
        Index("ix_wb_daily_report_rows_srid_normalized", "srid_normalized"),
        Index("ix_wb_daily_report_rows_rid_normalized", "rid_normalized"),
        Index("ix_wb_daily_report_rows_basket_id", "basket_id"),
        Index("ix_wb_daily_report_rows_order_match_status", "order_match_status"),
        Index("ix_wb_daily_report_rows_operation_scope", "operation_scope"),
        Index("ix_wb_daily_report_rows_order_required", "order_required"),
        Index("ix_wb_daily_report_rows_product_required", "product_required"),
        Index("ix_wb_daily_report_rows_deleted", "deleted_at"),
        Index("ix_wb_daily_report_rows_order_id", "order_id"),
        Index("ix_wb_daily_report_rows_product_id", "product_id"),
    )

    id: Mapped[int_pk]
    import_id: Mapped[int] = mapped_column(
        ForeignKey("wb_daily_report_imports.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    report_number: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False, default="daily")
    report_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stable_business_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_row_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    previous_payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    changed_fields: Mapped[list[str] | None] = mapped_column(JsonType, nullable=True)
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sale_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    supplier_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    size: Mapped[str | None] = mapped_column(String(128), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shk: Mapped[str | None] = mapped_column(String(128), nullable=True)
    srid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    srid_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    srid_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rid_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linked_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    linked_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    doc_type_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payment_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retail_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    retail_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    for_pay: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    delivery_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    return_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    penalty: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    storage_fee: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    acceptance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    deduction: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission_correction_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    reimbursement_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    logistics_penalty_correction_type: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    basket_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sale_method: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_match_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    order_match_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    product_match_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    order_match_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    product_match_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_match_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    order_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    product_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    match_attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_match_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_match_error: Mapped[str | None] = mapped_column(Text)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    matched_order_id: Mapped[int | None] = mapped_column(Integer)
    finance_operation_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown"
    )
    finance_category: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    row_status: Mapped[str] = mapped_column(String(24), nullable=False, default="new")
    skip_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)

    import_record: Mapped[WbDailyReportImport] = relationship(back_populates="rows")


class WbReportFinanceComponent(TimestampMixin, Base):
    """Normalized financial component created from a WB report row."""

    __tablename__ = "wb_report_finance_components"
    __table_args__ = (
        Index("ix_wb_report_components_import", "report_import_id"),
        Index("ix_wb_report_components_row", "report_row_id"),
        Index("ix_wb_report_components_account", "marketplace_account_id"),
        Index("ix_wb_report_components_order", "order_id"),
        Index("ix_wb_report_components_product", "product_id"),
        Index("ix_wb_report_components_category", "finance_category"),
        Index("ix_wb_report_components_scope", "operation_scope"),
        Index("ix_wb_report_components_active", "is_active"),
        Index("ix_wb_report_components_deleted", "deleted_at"),
    )

    id: Mapped[int_pk]
    report_import_id: Mapped[int] = mapped_column(
        ForeignKey("wb_daily_report_imports.id", ondelete="CASCADE"), nullable=False
    )
    report_row_id: Mapped[int] = mapped_column(
        ForeignKey("wb_daily_report_rows.id", ondelete="CASCADE"), nullable=False
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    operation_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    finance_category: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_column_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    normalized_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    sign_rule: Mapped[str] = mapped_column(String(64), nullable=False)
    is_order_fact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_product_fact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_global_fact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WbDailyReportImportRowLog(TimestampMixin, Base):
    """Processing journal for one uploaded WB daily report row."""

    __tablename__ = "wb_daily_report_import_row_logs"
    __table_args__ = (
        Index("ix_wb_daily_report_row_logs_import", "import_id"),
        Index("ix_wb_daily_report_row_logs_source_hash", "source_hash"),
        Index("ix_wb_daily_report_row_logs_status", "status"),
    )

    id: Mapped[int_pk]
    import_id: Mapped[int] = mapped_column(
        ForeignKey("wb_daily_report_imports.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    skip_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
