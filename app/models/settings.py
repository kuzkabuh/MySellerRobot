"""SQLAlchemy models for settings."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, int_pk


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
