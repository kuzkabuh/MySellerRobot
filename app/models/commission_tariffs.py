"""version: 1.0.0
description: Commission tariff models for WB and Ozon marketplace commissions.
updated: 2026-05-20
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, int_pk
from app.models.enums import Marketplace

JsonType = JSON().with_variant(JSONB, "postgresql")


class MarketplaceCommissionVersion(TimestampMixin, Base):
    """Versioned set of commission tariffs for a marketplace."""

    __tablename__ = "marketplace_commission_versions"
    __table_args__ = (
        Index("ix_commission_versions_marketplace_active", "marketplace", "is_active"),
        Index("ix_commission_versions_effective", "marketplace", "effective_from", "effective_to"),
    )

    id: Mapped[int_pk]
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    version_label: Mapped[str] = mapped_column(String(255))
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    effective_to: Mapped[date | None] = mapped_column(Date, index=True)
    source_type: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_file_name: Mapped[str | None] = mapped_column(String(255))
    source_file_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    imported_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    rates: Mapped[list["MarketplaceCommissionRate"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
    )
    import_logs: Mapped[list["MarketplaceCommissionImportLog"]] = relationship(
        back_populates="version",
    )


class MarketplaceCommissionRate(TimestampMixin, Base):
    """Normalized commission rate for a specific category/price range/sales model."""

    __tablename__ = "marketplace_commission_rates"
    __table_args__ = (
        Index(
            "ix_commission_rates_version_lookup",
            "version_id",
            "marketplace",
            "sales_model",
            "category_name",
            "price_from",
            "price_to",
        ),
    )

    id: Mapped[int_pk]
    version_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_commission_versions.id", ondelete="CASCADE"),
        index=True,
    )
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    category_name: Mapped[str] = mapped_column(String(512), index=True)
    product_type_name: Mapped[str | None] = mapped_column(String(512), index=True)
    subject_name: Mapped[str | None] = mapped_column(String(512))
    object_name: Mapped[str | None] = mapped_column(String(512))
    sales_model: Mapped[str] = mapped_column(String(32), index=True)
    price_from: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    price_to: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    price_to_inclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    commission_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType)

    version: Mapped[MarketplaceCommissionVersion] = relationship(back_populates="rates")


class MarketplaceTariffSourceCheck(TimestampMixin, Base):
    """Log of Ozon commission source page checks."""

    __tablename__ = "marketplace_tariff_source_checks"
    __table_args__ = (
        Index("ix_tariff_source_checks_marketplace_checked", "marketplace", "checked_at"),
    )

    id: Mapped[int_pk]
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    page_hash: Mapped[str | None] = mapped_column(String(64))
    current_detected_period_label: Mapped[str | None] = mapped_column(String(512))
    current_detected_file_url: Mapped[str | None] = mapped_column(Text)
    current_detected_file_name: Mapped[str | None] = mapped_column(String(255))
    has_changes: Mapped[bool] = mapped_column(Boolean, default=False)
    change_type: Mapped[str] = mapped_column(String(64), default="no_change")
    details: Mapped[dict[str, Any] | None] = mapped_column(JsonType)


class MarketplaceCommissionImportLog(TimestampMixin, Base):
    """Log of XLSX commission file imports."""

    __tablename__ = "marketplace_commission_import_logs"
    __table_args__ = (
        Index("ix_commission_import_logs_marketplace_created", "marketplace", "created_at"),
    )

    id: Mapped[int_pk]
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_commission_versions.id", ondelete="SET NULL"),
    )
    file_name: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_failed: Mapped[int] = mapped_column(Integer, default=0)
    validation_errors: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    error_message: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    version: Mapped[MarketplaceCommissionVersion | None] = relationship(
        back_populates="import_logs"
    )
