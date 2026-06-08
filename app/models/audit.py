"""SQLAlchemy models for audit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, int_pk

JsonType = JSON().with_variant(JSONB, "postgresql")

if TYPE_CHECKING:
    from app.models.marketplaces import MarketplaceAccount
    from app.models.users import User

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
