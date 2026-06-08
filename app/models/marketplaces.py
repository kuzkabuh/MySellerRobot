"""SQLAlchemy models for marketplaces."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, int_pk
from app.models.enums import (
    AccountStatus,
    Marketplace,
)

JsonType = JSON().with_variant(JSONB, "postgresql")

if TYPE_CHECKING:
    from app.models.audit import ApiKeyAuditLog
    from app.models.users import User

class MarketplaceAccount(TimestampMixin, Base):
    __tablename__ = "marketplace_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "marketplace", "name", name="uq_accounts_user_marketplace_name"
        ),
        Index("ix_accounts_user_marketplace_active", "user_id", "marketplace", "is_active"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    name: Mapped[str] = mapped_column(String(255))
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    encrypted_client_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AccountStatus] = mapped_column(Enum(AccountStatus), default=AccountStatus.DRAFT)
    last_success_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_order_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_orders_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sales_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_stocks_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_products_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_profile_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ozon_enrichment_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_wb_reports_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_wb_financial_detail_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    seller_external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    seller_name: Mapped[str | None] = mapped_column(String(255))
    seller_legal_name: Mapped[str | None] = mapped_column(String(255))
    seller_info_payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notification_settings: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    api_key_status: Mapped[str] = mapped_column(String(32), default="unchecked")
    api_key_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    api_key_check_result: Mapped[dict[str, Any] | None] = mapped_column(JsonType)

    user: Mapped[User] = relationship(back_populates="accounts")
    api_key_logs: Mapped[list["ApiKeyAuditLog"]] = relationship(back_populates="account")

class MarketplaceWarehouse(TimestampMixin, Base):
    __tablename__ = "marketplace_warehouses"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "marketplace",
            "external_warehouse_id",
            name="uq_marketplace_warehouses_external",
        ),
        Index("ix_marketplace_warehouses_account", "marketplace_account_id", "marketplace"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id"))
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    external_warehouse_id: Mapped[str] = mapped_column(String(128))
    name: Mapped[str | None] = mapped_column(String(255))
    warehouse_type: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
