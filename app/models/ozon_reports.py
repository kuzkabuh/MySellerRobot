"""SQLAlchemy models for ozon reports."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, int_pk

JsonType = JSON().with_variant(JSONB, "postgresql")

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
