"""SQLAlchemy models for products."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    BigInteger,
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
    Marketplace,
)

JsonType = JSON().with_variant(JSONB, "postgresql")

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
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
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

    @property
    def purchase_price(self) -> Decimal:
        """Semantic alias for the product purchase price."""
        return self.cost_price or Decimal("0")

    @property
    def extra_costs(self) -> Decimal:
        """Semantic alias for additional per-item costs."""
        return self.additional_cost or Decimal("0")

    @property
    def fixed_costs(self) -> Decimal:
        """Semantic alias for fixed per-item costs."""
        return self.package_cost or Decimal("0")

    @property
    def full_cost(self) -> Decimal:
        return self.purchase_price + self.extra_costs + self.fixed_costs

class BreakEvenExpenseSetting(TimestampMixin, Base):
    __tablename__ = "break_even_expense_settings"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "scope",
            "category",
            "product_id",
            name="uq_break_even_expense_scope",
        ),
        Index("ix_break_even_expense_user_scope", "user_id", "scope"),
        Index("ix_break_even_expense_product", "product_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(32), default="global")
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=True
    )
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0.0600"))
    acquiring_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0.0150"))
    advertising_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0.0500"))
    packaging_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    storage_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    other_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))

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


class OzonCurrentPrice(Base):
    """Current Ozon prices — upserted on every sync, one row per offer_id per account."""

    __tablename__ = "ozon_current_prices"
    __table_args__ = (
        sa.UniqueConstraint(
            "marketplace_account_id",
            "offer_id",
            name="uq_ozon_current_prices_account_offer",
        ),
        Index("ix_ozon_current_prices_account", "marketplace_account_id"),
        Index("ix_ozon_current_prices_offer", "offer_id"),
        Index("ix_ozon_current_prices_product", "product_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    ozon_product_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    offer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    marketing_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
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


class PriceChangeLog(Base):
    """Unified price change log for manual edits on WB and Ozon."""

    __tablename__ = "price_change_log"
    __table_args__ = (
        Index("ix_price_change_log_account", "marketplace_account_id"),
        Index("ix_price_change_log_product", "product_id"),
        Index("ix_price_change_log_marketplace", "marketplace"),
        Index("ix_price_change_log_created", "created_at"),
        Index(
            "ix_price_change_log_external_id",
            "marketplace_account_id",
            "external_product_id",
        ),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    marketplace: Mapped[str] = mapped_column(String(32), nullable=False)
    external_product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    seller_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    new_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    old_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wb_price_sent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wb_discount_sent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wb_upload_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changed_by_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
