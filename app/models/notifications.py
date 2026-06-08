"""SQLAlchemy models for notifications."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import Any

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
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, int_pk
from app.models.enums import (
    AlertType,
    NotificationType,
)

JsonType = JSON().with_variant(JSONB, "postgresql")

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
