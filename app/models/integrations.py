"""SQLAlchemy models for integrations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
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
    Marketplace,
    SyncJobStatus,
)

JsonType = JSON().with_variant(JSONB, "postgresql")

if TYPE_CHECKING:
    from app.models.marketplaces import MarketplaceAccount
    from app.models.users import User

class SyncJob(TimestampMixin, Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (Index("ix_sync_jobs_account_type", "marketplace_account_id", "job_type"),)

    id: Mapped[int_pk]
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    marketplace_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id")
    )
    marketplace: Mapped[Marketplace | None] = mapped_column(Enum(Marketplace), index=True)
    job_type: Mapped[str] = mapped_column(String(128), index=True)
    date_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    date_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[SyncJobStatus] = mapped_column(
        Enum(SyncJobStatus), default=SyncJobStatus.PENDING
    )
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    processed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    records_loaded: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    records_failed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    job_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JsonType, default=dict)

class ApiRequestLog(TimestampMixin, Base):
    __tablename__ = "api_request_logs"
    __table_args__ = (Index("ix_api_logs_account_created", "marketplace_account_id", "created_at"),)

    id: Mapped[int_pk]
    marketplace_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id")
    )
    marketplace: Mapped[Marketplace | None] = mapped_column(Enum(Marketplace))
    method: Mapped[str] = mapped_column(String(16))
    url: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)

class SyncTaskRun(Base):
    __tablename__ = "sync_task_runs"
    __table_args__ = (
        Index("ix_sync_task_runs_task_started", "task_name", "started_at"),
        Index("ix_sync_task_runs_status_started", "status", "started_at"),
    )

    id: Mapped[int_pk]
    task_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="started", index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    run_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JsonType, nullable=True)

class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        Index("ix_sync_runs_account_started", "marketplace_account_id", "started_at"),
        Index("ix_sync_runs_status_started", "status", "started_at"),
        Index("ix_sync_runs_user_triggered", "user_id", "started_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    marketplace_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    marketplace: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    sync_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trigger_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(sa.Numeric(10, 2), nullable=True)
    records_loaded: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    records_created: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    records_skipped: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    details_json: Mapped[dict[str, Any] | None] = mapped_column("details", JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True
    )

    account: Mapped["MarketplaceAccount | None"] = relationship(
        backref="sync_runs", foreign_keys=[marketplace_account_id]
    )
    user: Mapped["User | None"] = relationship(
        backref="sync_runs_triggered", foreign_keys=[user_id]
    )


class SyncStatus(TimestampMixin, Base):
    __tablename__ = "sync_statuses"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "account_id", "sync_type", name="uq_sync_statuses_user_account_type"
        ),
        Index("ix_sync_statuses_user_id", "user_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=True
    )
    sync_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    items_processed: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Numeric(10, 2))

    user: Mapped[User] = relationship(back_populates="sync_statuses")
