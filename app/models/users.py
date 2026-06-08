"""SQLAlchemy models for users."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

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
    UserStatus,
)

JsonType = JSON().with_variant(JSONB, "postgresql")

if TYPE_CHECKING:
    from app.models.audit import ApiKeyAuditLog, UserActivityLog
    from app.models.integrations import SyncStatus
    from app.models.marketplaces import MarketplaceAccount
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
