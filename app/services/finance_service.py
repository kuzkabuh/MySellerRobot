"""version: 1.1.0
description: Financial report row import and actual profit recalculation service.
updated: 2026-05-15
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import FinancialReportRow, OrderItem, ProfitSnapshot
from app.models.enums import CalculationType, Marketplace
from app.schemas.profit import CostInput, ProfitInput
from app.services.profit_calculator import ProfitCalculator


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
        commission = item.commission_estimated or Decimal("0")
        other_costs = actual_marketplace_costs - commission
        if other_costs < 0:
            other_costs = Decimal("0")
        result = ProfitCalculator().calculate(
            ProfitInput(
                gross_revenue=gross,
                marketplace_commission=commission,
                other_marketplace_costs=other_costs,
                cost=CostInput(
                    cost_price=item.cost_price_used or Decimal("0"),
                    package_cost=item.package_cost_used or Decimal("0"),
                    tax_rate=Decimal("0"),
                ),
                tax_base=Decimal("0"),
            )
        )
        tax = item.tax_amount_estimated or Decimal("0")
        profit = result.profit - tax
        margin = (
            Decimal("0")
            if result.gross_revenue == 0
            else (profit / result.gross_revenue * Decimal("100")).quantize(Decimal("0.01"))
        )
        snapshot = ProfitSnapshot(
            order_item_id=item.id,
            calculation_type=CalculationType.ACTUAL,
            gross_revenue=result.gross_revenue,
            marketplace_commission=result.marketplace_commission,
            logistics_cost=result.logistics_cost,
            acquiring_cost=result.acquiring_cost,
            storage_cost=result.storage_cost,
            return_cost=result.return_cost,
            other_marketplace_costs=result.other_marketplace_costs,
            cost_price=result.cost_price,
            package_cost=result.package_cost,
            additional_seller_cost=result.additional_seller_cost,
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
