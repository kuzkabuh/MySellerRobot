"""version: 1.0.0
description: Promo code models for discount management.
updated: 2026-05-31
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, int_pk

if TYPE_CHECKING:
    from app.models.domain import User
    from app.models.subscriptions import Payment, SubscriptionTier, UserSubscription


class PromoCode(TimestampMixin, Base):
    """Промокод для скидок и бонусных периодов."""

    __tablename__ = "promo_codes"

    id: Mapped[int_pk]
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)

    promo_type: Mapped[str] = mapped_column(String(32))
    discount_percent: Mapped[int | None] = mapped_column(Integer)
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    free_days: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="RUB")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    max_uses_total: Mapped[int | None] = mapped_column(Integer)
    max_uses_per_user: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)

    min_order_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    only_for_new_users: Mapped[bool] = mapped_column(Boolean, default=False)

    created_by_admin_id: Mapped[int | None] = mapped_column(Integer)

    tariffs: Mapped[list["PromoCodeTariff"]] = relationship(
        back_populates="promo_code", cascade="all, delete-orphan"
    )
    periods: Mapped[list["PromoCodePeriod"]] = relationship(
        back_populates="promo_code", cascade="all, delete-orphan"
    )
    usages: Mapped[list["PromoCodeUsage"]] = relationship(
        back_populates="promo_code", cascade="all, delete-orphan"
    )


class PromoCodeTariff(Base):
    """Связь промокода с тарифом."""

    __tablename__ = "promo_code_tariffs"
    __table_args__ = (UniqueConstraint("promo_code_id", "tariff_id"),)

    id: Mapped[int_pk]
    promo_code_id: Mapped[int] = mapped_column(
        ForeignKey("promo_codes.id", ondelete="CASCADE"), index=True
    )
    tariff_id: Mapped[int] = mapped_column(
        ForeignKey("subscription_tiers.id", ondelete="CASCADE"), index=True
    )

    promo_code: Mapped["PromoCode"] = relationship(back_populates="tariffs")
    tariff: Mapped["SubscriptionTier"] = relationship()


class PromoCodePeriod(Base):
    """Связь промокода с периодом подписки."""

    __tablename__ = "promo_code_periods"
    __table_args__ = (UniqueConstraint("promo_code_id", "period"),)

    id: Mapped[int_pk]
    promo_code_id: Mapped[int] = mapped_column(
        ForeignKey("promo_codes.id", ondelete="CASCADE"), index=True
    )
    period: Mapped[str] = mapped_column(String(16))

    promo_code: Mapped["PromoCode"] = relationship(back_populates="periods")


class PromoCodeUsage(Base):
    """История использования промокодов."""

    __tablename__ = "promo_code_usages"

    id: Mapped[int_pk]
    promo_code_id: Mapped[int] = mapped_column(
        ForeignKey("promo_codes.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_subscriptions.id", ondelete="SET NULL")
    )
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"), index=True
    )
    tariff_id: Mapped[int] = mapped_column(
        ForeignKey("subscription_tiers.id"), index=True
    )
    period: Mapped[str] = mapped_column(String(16))

    original_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    final_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    free_days_applied: Mapped[int | None] = mapped_column(Integer)

    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default="reserved", index=True)

    provider_payment_id: Mapped[str | None] = mapped_column(String(128))

    promo_code: Mapped["PromoCode"] = relationship(back_populates="usages")
    user: Mapped["User"] = relationship()
    subscription: Mapped["UserSubscription | None"] = relationship()
    payment: Mapped["Payment | None"] = relationship()
    tariff: Mapped["SubscriptionTier"] = relationship()
