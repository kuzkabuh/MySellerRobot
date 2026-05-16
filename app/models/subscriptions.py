"""version: 1.0.0
description: Subscription and payment models for monetization.
updated: 2026-05-16
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, int_pk
from app.models.enums import PaymentStatus, SubscriptionStatus

if TYPE_CHECKING:
    from app.models.domain import User


class SubscriptionTier(TimestampMixin, Base):
    """Тарифный план подписки."""

    __tablename__ = "subscription_tiers"

    id: Mapped[int_pk]
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    price_monthly: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    price_yearly: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    # Лимиты
    max_marketplace_accounts: Mapped[int] = mapped_column(Integer, default=1)
    max_orders_per_month: Mapped[int | None] = mapped_column(Integer)
    max_products: Mapped[int | None] = mapped_column(Integer)

    # Доступ к функциям
    feature_web_cabinet: Mapped[bool] = mapped_column(Boolean, default=True)
    feature_analytics: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_plan_fact: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_break_even: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_stock_forecast: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_alerts: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_api_access: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_priority_support: Mapped[bool] = mapped_column(Boolean, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    subscriptions: Mapped[list["UserSubscription"]] = relationship(back_populates="tier")


class UserSubscription(TimestampMixin, Base):
    """Подписка пользователя."""

    __tablename__ = "user_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "tier_id", "started_at"),)

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tier_id: Mapped[int] = mapped_column(ForeignKey("subscription_tiers.id"))

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE, index=True
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Trial период
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Платежная информация
    payment_provider: Mapped[str | None] = mapped_column(String(32))
    payment_id: Mapped[str | None] = mapped_column(String(128))
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="subscriptions")
    tier: Mapped["SubscriptionTier"] = relationship(back_populates="subscriptions")
    payments: Mapped[list["Payment"]] = relationship(back_populates="subscription")


class Payment(TimestampMixin, Base):
    """История платежей."""

    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("provider", "provider_payment_id"),)

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_subscriptions.id", ondelete="SET NULL")
    )

    provider: Mapped[str] = mapped_column(String(32), index=True)
    provider_payment_id: Mapped[str] = mapped_column(String(128), index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")

    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), default=PaymentStatus.PENDING, index=True
    )

    payment_method: Mapped[str | None] = mapped_column(String(64))

    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    payment_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Relationships
    user: Mapped["User"] = relationship()
    subscription: Mapped["UserSubscription | None"] = relationship(back_populates="payments")
