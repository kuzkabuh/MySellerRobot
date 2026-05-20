"""version: 1.0.0
description: WB logistics tariff models for box delivery tariffs.
updated: 2026-05-20
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, int_pk

JsonType = JSON().with_variant(JSONB, "postgresql")


class WbLogisticsTariffVersion(TimestampMixin, Base):
    """Versioned set of WB box delivery logistics tariffs."""

    __tablename__ = "wb_logistics_tariff_versions"
    __table_args__ = (
        Index("ix_wb_logistics_versions_active", "is_active"),
        Index("ix_wb_logistics_versions_tariff_date", "tariff_date"),
    )

    id: Mapped[int_pk]
    tariff_date: Mapped[date] = mapped_column(Date, index=True)
    version_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64), default="wb_api")
    rows_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    rates: Mapped[list["WbLogisticsTariffRate"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
    )


class WbLogisticsTariffRate(TimestampMixin, Base):
    """Normalized WB box delivery logistics tariff for a warehouse/sales model."""

    __tablename__ = "wb_logistics_tariff_rates"
    __table_args__ = (
        Index(
            "ix_wb_logistics_rates_lookup",
            "version_id",
            "warehouse_name",
            "sales_model",
        ),
    )

    id: Mapped[int_pk]
    version_id: Mapped[int] = mapped_column(
        ForeignKey("wb_logistics_tariff_versions.id", ondelete="CASCADE"),
        index=True,
    )
    warehouse_name: Mapped[str] = mapped_column(String(255), index=True)
    geo_name: Mapped[str | None] = mapped_column(String(255))
    sales_model: Mapped[str] = mapped_column(String(32), index=True)

    # FBO fields: boxDeliveryBase, boxDeliveryLiter, boxDeliveryCoefExpr
    fbo_base_tariff: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    fbo_liter_tariff: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    fbo_coefficient_expr: Mapped[str | None] = mapped_column(String(512))

    # FBS fields: boxDeliveryMarketplaceBase/Liter/CoefExpr
    fbs_base_tariff: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    fbs_liter_tariff: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    fbs_coefficient_expr: Mapped[str | None] = mapped_column(String(512))

    # Parsed coefficient as decimal for direct use (if expression is simple)
    logistics_coefficient_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))

    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType)

    version: Mapped[WbLogisticsTariffVersion] = relationship(back_populates="rates")
