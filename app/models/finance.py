"""SQLAlchemy models for finance."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
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
    CalculationType,
    Marketplace,
)

JsonType = JSON().with_variant(JSONB, "postgresql")

if TYPE_CHECKING:
    from app.models.orders import OrderItem

class ProfitSnapshot(TimestampMixin, Base):
    __tablename__ = "profit_snapshots"
    __table_args__ = (
        Index(
            "ix_profit_snapshots_item_type", "order_item_id", "calculation_type", "calculated_at"
        ),
    )

    id: Mapped[int_pk]
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id", ondelete="CASCADE"),
        index=True,
    )
    calculation_type: Mapped[CalculationType] = mapped_column(Enum(CalculationType), index=True)
    gross_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    marketplace_commission: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    logistics_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    acquiring_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    storage_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    return_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    other_marketplace_costs: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    package_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    additional_seller_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    profit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    margin_percent: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=0)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    calculation_source: Mapped[str] = mapped_column(String(255))
    economy_confidence: Mapped[str] = mapped_column(String(32), default="PRELIMINARY")
    raw_financial_data: Mapped[dict[str, Any] | None] = mapped_column(JsonType)

    order_item: Mapped[OrderItem] = relationship(back_populates="snapshots")

class FinancialReportRow(TimestampMixin, Base):
    __tablename__ = "financial_report_rows"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_account_id",
            "marketplace",
            "external_row_id",
            name="uq_financial_rows_external",
        ),
        Index("ix_financial_rows_period", "marketplace_account_id", "operation_date"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(ForeignKey("marketplace_accounts.id"))
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    external_row_id: Mapped[str] = mapped_column(String(255))
    order_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    product_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    operation_type: Mapped[str] = mapped_column(String(255), index=True)
    operation_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    currency: Mapped[str] = mapped_column(String(16), default="RUB")
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)

class AccountBalanceSnapshot(TimestampMixin, Base):
    __tablename__ = "account_balance_snapshots"
    __table_args__ = (Index("ix_account_balance_latest", "marketplace_account_id", "fetched_at"),)

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_account_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_accounts.id", ondelete="CASCADE"), index=True
    )
    marketplace: Mapped[Marketplace] = mapped_column(Enum(Marketplace), index=True)
    currency: Mapped[str] = mapped_column(String(16), default="RUB")
    current: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    for_withdraw: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    accrued: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    payments_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(64), default="OK")
    error_message: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)

class PlanFactTarget(TimestampMixin, Base):
    __tablename__ = "plan_fact_targets"
    __table_args__ = (
        Index("ix_plan_fact_targets_user_period", "user_id", "period_start", "period_end"),
        Index("ix_plan_fact_targets_user_marketplace", "user_id", "marketplace"),
    )

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace: Mapped[Marketplace | None] = mapped_column(Enum(Marketplace), nullable=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    revenue_plan: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    profit_plan: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    orders_plan: Mapped[int | None] = mapped_column(Integer)
    buyouts_plan: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    comment: Mapped[str | None] = mapped_column(Text)
