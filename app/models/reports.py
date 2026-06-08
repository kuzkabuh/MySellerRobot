"""SQLAlchemy models for reports."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    Date,
    DateTime,
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

JsonType = JSON().with_variant(JSONB, "postgresql")

class DailyReport(TimestampMixin, Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("user_id", "report_date"),)

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    message_text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class MrcImport(TimestampMixin, Base):
    __tablename__ = "mrc_imports"

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    original_file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="preview")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cleared_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rows: Mapped[list["MrcImportRow"]] = relationship(
        back_populates="import_record", cascade="all, delete-orphan"
    )

class MrcImportRow(TimestampMixin, Base):
    __tablename__ = "mrc_import_rows"
    __table_args__ = (Index("ix_mrc_import_rows_import_id", "import_id"),)

    id: Mapped[int_pk]
    import_id: Mapped[int] = mapped_column(
        ForeignKey("mrc_imports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wb_nm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seller_sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    old_mrc_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    new_mrc_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    import_record: Mapped["MrcImport"] = relationship(back_populates="rows")
