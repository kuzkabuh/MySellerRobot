"""version: 1.0.0
description: Financial report row import and actual profit recalculation skeleton.
updated: 2026-05-14
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import FinancialReportRow, OrderItem, ProfitSnapshot
from app.models.enums import CalculationType, Marketplace


class FinanceService:
    """Store normalized financial rows without binding business logic to one API method."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_financial_row(
        self,
        *,
        user_id: int,
        account_id: int,
        marketplace: Marketplace,
        external_row_id: str,
        operation_type: str,
        operation_date: datetime,
        amount: Decimal,
        order_external_id: str | None,
        product_external_id: str | None,
        raw_payload: dict[str, Any],
    ) -> bool:
        exists = await self.session.execute(
            select(FinancialReportRow.id).where(
                FinancialReportRow.marketplace_account_id == account_id,
                FinancialReportRow.marketplace == marketplace,
                FinancialReportRow.external_row_id == external_row_id,
            )
        )
        if exists.scalar_one_or_none() is not None:
            return False
        self.session.add(
            FinancialReportRow(
                user_id=user_id,
                marketplace_account_id=account_id,
                marketplace=marketplace,
                external_row_id=external_row_id,
                order_external_id=order_external_id,
                product_external_id=product_external_id,
                operation_type=operation_type,
                operation_date=operation_date,
                amount=amount,
                currency="RUB",
                raw_payload=raw_payload,
            )
        )
        await self.session.flush()
        return True

    async def create_actual_snapshot_from_item(
        self,
        item: OrderItem,
        actual_marketplace_costs: Decimal,
        source: str,
    ) -> ProfitSnapshot:
        gross = item.discounted_price * Decimal(item.quantity)
        cost = item.cost_price_used or Decimal("0")
        package = item.package_cost_used or Decimal("0")
        tax = item.tax_amount_estimated or Decimal("0")
        profit = gross - actual_marketplace_costs - cost - package - tax
        margin = (
            Decimal("0")
            if gross == 0
            else (profit / gross * Decimal("100")).quantize(Decimal("0.01"))
        )
        snapshot = ProfitSnapshot(
            order_item_id=item.id,
            calculation_type=CalculationType.ACTUAL,
            gross_revenue=gross,
            marketplace_commission=Decimal("0"),
            logistics_cost=Decimal("0"),
            acquiring_cost=None,
            storage_cost=None,
            return_cost=None,
            other_marketplace_costs=actual_marketplace_costs,
            cost_price=cost,
            package_cost=package,
            additional_seller_cost=Decimal("0"),
            tax_amount=tax,
            profit=profit,
            margin_percent=margin,
            calculated_at=datetime.now(tz=UTC),
            calculation_source=source,
            raw_financial_data=None,
        )
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot
