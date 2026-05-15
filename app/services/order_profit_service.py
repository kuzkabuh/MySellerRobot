"""version: 1.3.0
description: Shared estimated order profit calculation for online polling and history backfill.
updated: 2026-05-15
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    MarketplaceAccount,
    Order,
    OrderItem,
    ProductCostHistory,
    ProfitSnapshot,
)
from app.models.enums import CalculationType
from app.repositories.orders import OrderRepository
from app.repositories.products import ProductRepository
from app.schemas.orders import NormalizedOrder
from app.schemas.profit import CostInput, ProfitInput, ProfitResult
from app.services.cost_service import CostService
from app.services.marketplace_estimates import estimate_marketplace_expenses
from app.services.profit_calculator import ProfitCalculator


class OrderProfitService:
    """Calculate and persist estimated profit for order items."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.orders = OrderRepository(session)
        self.products = ProductRepository(session)
        self.costs = CostService(session)
        self.calculator = ProfitCalculator()

    async def calculate_estimated_profit(
        self,
        account: MarketplaceAccount,
        order: Order,
        normalized: NormalizedOrder,
        *,
        calculation_source: str = "online_estimated",
    ) -> None:
        order_with_items = await self.orders.get_with_items(order.id)
        if order_with_items is None:
            return
        normalized_by_index = list(normalized.items)
        for index, item in enumerate(order_with_items.items):
            source = normalized_by_index[index] if index < len(normalized_by_index) else None
            product = await self.products.find_for_order_item(
                account_id=account.id,
                marketplace=account.marketplace,
                seller_article=item.seller_article,
                marketplace_article=item.marketplace_article,
                external_product_id=source.external_product_id if source else None,
            )
            if product:
                item.product_id = product.id
                if not item.title and product.title:
                    item.title = product.title
            cost = (
                await self.costs.get_actual_cost(product.id, order.order_date) if product else None
            )
            estimates = estimate_marketplace_expenses(order_with_items, item)
            if item.commission_estimated is None:
                item.commission_estimated = estimates.commission
            if item.logistics_estimated is None or item.logistics_estimated == Decimal("0"):
                item.logistics_estimated = estimates.logistics
            result = self.calculate_item_profit(item, cost)
            self.apply_profit_to_item(item, result)
            self.session.add(
                ProfitSnapshot(
                    order_item_id=item.id,
                    calculation_type=CalculationType.ESTIMATED,
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
                    tax_amount=result.tax_amount,
                    profit=result.profit,
                    margin_percent=result.margin_percent,
                    calculated_at=datetime.now(tz=UTC),
                    calculation_source=calculation_source,
                    raw_financial_data=None,
                )
            )
        await self.session.flush()

    def calculate_item_profit(
        self,
        item: OrderItem,
        cost: ProductCostHistory | None,
    ) -> ProfitResult:
        gross_revenue = item.discounted_price or item.seller_price or item.buyer_price
        cost_input = None
        if cost:
            cost_input = CostInput(
                cost_price=cost.cost_price,
                package_cost=cost.package_cost,
                additional_cost=cost.additional_cost,
                tax_rate=cost.tax_rate,
            )
        return self.calculator.calculate(
            ProfitInput(
                gross_revenue=gross_revenue * Decimal(item.quantity),
                expected_payout=item.payout_amount_estimated,
                marketplace_commission=item.commission_estimated,
                logistics_cost=item.logistics_estimated or Decimal("0"),
                other_marketplace_costs=(item.other_marketplace_expenses_estimated or Decimal("0")),
                cost=cost_input,
            )
        )

    @staticmethod
    def apply_profit_to_item(item: OrderItem, result: ProfitResult) -> None:
        item.cost_price_used = result.cost_price
        item.package_cost_used = result.package_cost
        item.tax_amount_estimated = result.tax_amount
        item.profit_estimated = result.profit
        item.margin_percent_estimated = result.margin_percent

    @staticmethod
    def latest_estimated_result(item: OrderItem | None) -> ProfitResult | None:
        if item is None:
            return None
        return ProfitResult(
            gross_revenue=item.discounted_price * Decimal(item.quantity),
            marketplace_commission=item.commission_estimated or Decimal("0"),
            logistics_cost=item.logistics_estimated or Decimal("0"),
            acquiring_cost=Decimal("0"),
            storage_cost=Decimal("0"),
            return_cost=Decimal("0"),
            other_marketplace_costs=item.other_marketplace_expenses_estimated or Decimal("0"),
            cost_price=item.cost_price_used or Decimal("0"),
            package_cost=item.package_cost_used or Decimal("0"),
            additional_seller_cost=Decimal("0"),
            tax_amount=item.tax_amount_estimated or Decimal("0"),
            profit=item.profit_estimated or Decimal("0"),
            margin_percent=item.margin_percent_estimated or Decimal("0"),
            missing_cost=item.cost_price_used in {None, Decimal("0")},
        )
