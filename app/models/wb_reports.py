"""SQLAlchemy models for wb reports."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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

class WbFinancialReport(TimestampMixin, Base):
    __tablename__ = "wb_financial_reports"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "period_type",
            "report_id",
            name="uq_wb_reports_account_period_report",
        ),
        Index("ix_wb_reports_period", "marketplace_account_id", "period_type", "date_from"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), index=True
    )
    report_id: Mapped[str] = mapped_column(String(128))
    period_type: Mapped[str] = mapped_column(String(16), index=True)
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    create_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str | None] = mapped_column(String(16))
    report_type: Mapped[str | None] = mapped_column(String(128))
    retail_amount_sum: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    for_pay_sum: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    delivery_service_sum: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)

class WbReportCheckState(TimestampMixin, Base):
    __tablename__ = "wb_report_check_states"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "period_type",
            name="uq_wb_report_check_account_period",
        ),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), index=True
    )
    period_type: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(64), default="UNKNOWN")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    reports_found: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)

class WbPromotion(TimestampMixin, Base):
    __tablename__ = "wb_promotions"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "wb_promotion_id",
            name="uq_wb_promotions_account_promo",
        ),
        Index("ix_wb_promotions_account_active", "marketplace_account_id", "is_active_today"),
        Index("ix_wb_promotions_dates", "start_datetime", "end_datetime"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), index=True
    )
    wb_promotion_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str | None] = mapped_column(String(512))
    promotion_type: Mapped[str | None] = mapped_column(String(64))
    start_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active_today: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

class WbPromotionNomenclature(TimestampMixin, Base):
    __tablename__ = "wb_promotion_nomenclatures"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "wb_promotion_id",
            "wb_nm_id",
            "in_action",
            name="uq_wb_promo_nomenclatures_account_promo_nm_action",
        ),
        Index("ix_wb_promo_nomenclatures_nm", "marketplace_account_id", "wb_nm_id"),
        Index("ix_wb_promo_nomenclatures_promo", "marketplace_account_id", "wb_promotion_id"),
        Index("ix_wb_promo_nomenclatures_synced", "marketplace_account_id", "synced_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), index=True
    )
    wb_promotion_id: Mapped[int] = mapped_column(BigInteger, index=True)
    wb_nm_id: Mapped[int] = mapped_column(BigInteger, index=True)
    in_action: Mapped[bool] = mapped_column(Boolean, default=False)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency_code: Mapped[str | None] = mapped_column(String(16))
    plan_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    current_discount: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    plan_discount: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

class WbAutoPromotionCondition(TimestampMixin, Base):
    __tablename__ = "wb_auto_promotion_conditions"
    __table_args__ = (
        sa.UniqueConstraint(
            "marketplace_account_id",
            "wb_promotion_id",
            "wb_nm_id",
            "source",
            name="uq_auto_promo_cond_acct_promo_nm_src",
        ),
        sa.UniqueConstraint(
            "marketplace_account_id",
            "wb_nm_id",
            "promotion_name",
            "source",
            name="uq_auto_promo_cond_acct_nm_pname_src",
        ),
        Index("ix_auto_promo_cond_account_nm", "marketplace_account_id", "wb_nm_id"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    wb_promotion_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    wb_nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    seller_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    promotion_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    required_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_auto_promo_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    wb_condition_discount_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    current_wb_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_full_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    candidate_discounted_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    condition_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    is_participating: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class WbAutoPromoFileImport(TimestampMixin, Base):
    __tablename__ = "wb_auto_promo_file_imports"
    __table_args__ = (Index("ix_wb_auto_promo_file_imports_user_created", "user_id", "created_at"),)

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    promotion_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="preview")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    rows: Mapped[list["WbAutoPromoFileImportRow"]] = relationship(
        back_populates="import_record",
        cascade="all, delete-orphan",
    )

class WbAutoPromoFileImportRow(TimestampMixin, Base):
    __tablename__ = "wb_auto_promo_file_import_rows"
    __table_args__ = (Index("ix_wb_auto_promo_file_rows_import_id", "import_id"),)

    id: Mapped[int_pk]
    import_id: Mapped[int] = mapped_column(
        ForeignKey("wb_auto_promo_file_imports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    wb_nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    seller_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    plan_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_full_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    current_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    wb_upload_discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    wb_status: Mapped[str | None] = mapped_column(String(512), nullable=True)
    already_participating: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    import_record: Mapped["WbAutoPromoFileImport"] = relationship(back_populates="rows")

class WbAutoPromoPriceRecommendation(TimestampMixin, Base):
    __tablename__ = "wb_auto_promo_price_recommendations"
    __table_args__ = (
        Index("ix_auto_promo_recs_acct_nm_status", "marketplace_account_id", "wb_nm_id", "status"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    wb_nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    wb_promotion_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    promotion_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mrc_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_wb_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    required_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    required_price_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recommended_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_full_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_auto_promo_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    wb_condition_discount_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    candidate_discounted_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    recommended_discounted_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    recommended_full_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    recommended_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    safe_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    safe_full_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    safe_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    condition_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    mrc_lower_bound: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    mrc_upper_bound: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="calculation")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class WbPriceChangeHistory(Base):
    __tablename__ = "wb_price_change_history"
    __table_args__ = (
        Index("ix_price_change_hist_nm", "wb_nm_id"),
        Index("ix_price_change_hist_account_created", "marketplace_account_id", "created_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    wb_nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    wb_upload_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    new_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    target_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    wb_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wb_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_discounted_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    mrc_lower_bound: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    mrc_upper_bound: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False, default="auto_promotion")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

class WbDailyReportImport(TimestampMixin, Base):
    """Metadata for a single WB daily realisation-report import attempt."""

    __tablename__ = "wb_daily_report_imports"
    __table_args__ = (
        Index("ix_wb_daily_report_imports_user", "user_id"),
        Index("ix_wb_daily_report_imports_account", "marketplace_account_id"),
        Index("ix_wb_daily_report_imports_created", "created_at"),
        Index("ix_wb_daily_report_imports_deleted", "deleted_at"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="file")
    report_type: Mapped[str] = mapped_column(String(16), nullable=False, default="daily")
    original_filename: Mapped[str | None] = mapped_column(String(512))
    report_number: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_pending_match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_ambiguous_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    delete_reason: Mapped[str | None] = mapped_column(Text)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    rows: Mapped[list["WbDailyReportRow"]] = relationship(
        back_populates="import_record",
        cascade="all, delete-orphan",
    )

class WbDailyReportRow(TimestampMixin, Base):
    """Single row of a WB daily realisation report (XLSX import)."""

    __tablename__ = "wb_daily_report_rows"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "report_type",
            "report_number",
            "row_hash",
            name="ux_wb_daily_report_row_dedupe",
        ),
        Index("ix_wb_daily_report_rows_user", "user_id"),
        Index("ix_wb_daily_report_rows_account", "marketplace_account_id"),
        Index("ix_wb_daily_report_rows_import", "import_id"),
        Index("ix_wb_daily_report_rows_type", "report_type"),
        Index("ix_wb_daily_report_rows_sale_dt", "sale_dt"),
        Index("ix_wb_daily_report_rows_order_dt", "order_dt"),
        Index("ix_wb_daily_report_rows_barcode", "barcode"),
        Index("ix_wb_daily_report_rows_supplier_article", "supplier_article"),
        Index("ix_wb_daily_report_rows_shk", "shk"),
        Index("ix_wb_daily_report_rows_payment_reason", "payment_reason"),
        Index("ix_wb_daily_report_rows_srid", "srid"),
        Index("ix_wb_daily_report_rows_status", "row_status"),
        Index("ix_wb_daily_report_rows_source_hash", "source_row_hash"),
        Index("ix_wb_daily_report_rows_stable_key", "stable_business_key"),
        Index("ix_wb_daily_report_rows_srid_raw", "srid_raw"),
        Index("ix_wb_daily_report_rows_srid_normalized", "srid_normalized"),
        Index("ix_wb_daily_report_rows_rid_normalized", "rid_normalized"),
        Index("ix_wb_daily_report_rows_basket_id", "basket_id"),
        Index("ix_wb_daily_report_rows_order_match_status", "order_match_status"),
        Index("ix_wb_daily_report_rows_operation_scope", "operation_scope"),
        Index("ix_wb_daily_report_rows_order_required", "order_required"),
        Index("ix_wb_daily_report_rows_product_required", "product_required"),
        Index("ix_wb_daily_report_rows_deleted", "deleted_at"),
        Index("ix_wb_daily_report_rows_order_id", "order_id"),
        Index("ix_wb_daily_report_rows_product_id", "product_id"),
    )

    id: Mapped[int_pk]
    import_id: Mapped[int] = mapped_column(
        ForeignKey("wb_daily_report_imports.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    report_number: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False, default="daily")
    report_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stable_business_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_row_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    previous_payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    changed_fields: Mapped[list[str] | None] = mapped_column(JsonType, nullable=True)
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sale_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    supplier_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    size: Mapped[str | None] = mapped_column(String(128), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shk: Mapped[str | None] = mapped_column(String(128), nullable=True)
    srid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    srid_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    srid_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rid_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linked_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    linked_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    doc_type_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payment_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retail_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    retail_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    for_pay: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    delivery_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    return_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    penalty: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    storage_fee: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    acceptance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    deduction: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission_correction_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    reimbursement_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    logistics_penalty_correction_type: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    basket_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sale_method: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_match_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    order_match_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    product_match_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    order_match_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    product_match_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_match_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    order_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    product_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    match_attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_match_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_match_error: Mapped[str | None] = mapped_column(Text)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    matched_order_id: Mapped[int | None] = mapped_column(Integer)
    finance_operation_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown"
    )
    finance_category: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    row_status: Mapped[str] = mapped_column(String(24), nullable=False, default="new")
    skip_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)

    import_record: Mapped[WbDailyReportImport] = relationship(back_populates="rows")

class WbReportFinanceComponent(TimestampMixin, Base):
    """Normalized financial component created from a WB report row."""

    __tablename__ = "wb_report_finance_components"
    __table_args__ = (
        Index("ix_wb_report_components_import", "report_import_id"),
        Index("ix_wb_report_components_row", "report_row_id"),
        Index("ix_wb_report_components_account", "marketplace_account_id"),
        Index("ix_wb_report_components_order", "order_id"),
        Index("ix_wb_report_components_product", "product_id"),
        Index("ix_wb_report_components_category", "finance_category"),
        Index("ix_wb_report_components_scope", "operation_scope"),
        Index("ix_wb_report_components_active", "is_active"),
        Index("ix_wb_report_components_deleted", "deleted_at"),
    )

    id: Mapped[int_pk]
    report_import_id: Mapped[int] = mapped_column(
        ForeignKey("wb_daily_report_imports.id", ondelete="CASCADE"), nullable=False
    )
    report_row_id: Mapped[int] = mapped_column(
        ForeignKey("wb_daily_report_rows.id", ondelete="CASCADE"), nullable=False
    )
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    operation_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    finance_category: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_column_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    normalized_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    sign_rule: Mapped[str] = mapped_column(String(64), nullable=False)
    is_order_fact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_product_fact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_global_fact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class WbDailyReportImportRowLog(TimestampMixin, Base):
    """Processing journal for one uploaded WB daily report row."""

    __tablename__ = "wb_daily_report_import_row_logs"
    __table_args__ = (
        Index("ix_wb_daily_report_row_logs_import", "import_id"),
        Index("ix_wb_daily_report_row_logs_source_hash", "source_hash"),
        Index("ix_wb_daily_report_row_logs_status", "status"),
    )

    id: Mapped[int_pk]
    import_id: Mapped[int] = mapped_column(
        ForeignKey("wb_daily_report_imports.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    skip_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
