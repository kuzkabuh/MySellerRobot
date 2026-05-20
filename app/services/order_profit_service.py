"""version: 1.6.0
description: Shared tariff-aware estimated order profit calculation with confidence tracking.
updated: 2026-05-20
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    MarketplaceAccount,
    Order,
    OrderItem,
    Product,
    ProductCostHistory,
    ProfitSnapshot,
)
from app.models.enums import CalculationType, Marketplace
from app.repositories.orders import OrderRepository
from app.repositories.products import ProductRepository
from app.schemas.orders import NormalizedOrder
from app.schemas.profit import CostInput, ProfitInput, ProfitResult
from app.services.commission_tariffs.commission_resolver_service import CommissionResolverService
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
        tariff_resolver = CommissionResolverService(self.session)

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

            commission_rate = await self._resolve_commission_rate(
                tariff_resolver=tariff_resolver,
                order=order,
                product=product,
                item=item,
            )

            estimates = estimate_marketplace_expenses(
                order_with_items,
                item,
                product_commission_rate=commission_rate,
                commission_fbw=product.commission_fbw if product else None,
                commission_fbs=product.commission_fbs if product else None,
                commission_dbs=product.commission_dbs if product else None,
                commission_edbs=product.commission_edbs if product else None,
                commission_pickup=product.commission_pickup if product else None,
                commission_booking=product.commission_booking if product else None,
            )
            if item.commission_estimated is None and estimates.commission_is_known:
                item.commission_estimated = estimates.commission
                item.commission_source = estimates.commission_source.value
            elif item.commission_source is None:
                item.commission_source = estimates.commission_source.value
            if item.logistics_estimated is None or item.logistics_estimated == Decimal("0"):
                item.logistics_estimated = estimates.logistics
                item.logistics_source = estimates.logistics_source.value
            elif item.logistics_source is None:
                item.logistics_source = estimates.logistics_source.value
            item.economy_confidence = estimates.confidence.value
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
                    economy_confidence=estimates.confidence.value,
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

    async def _resolve_commission_rate(
        self,
        *,
        tariff_resolver: CommissionResolverService,
        order: Order,
        product: Product | None,
        item: OrderItem,
    ) -> Decimal | None:
        """Resolve commission rate: product fields first, then tariff DB fallback."""
        if product:
            sale_model = order.sale_model
            if sale_model:
                model_field_map = {
                    "FBO": product.commission_fbw,
                    "FBS": product.commission_fbs,
                    "rFBS": product.commission_fbs,
                    "DBS": product.commission_dbs,
                    "DBW": product.commission_dbs,
                }
                rate = model_field_map.get(sale_model.value)
                if rate is not None:
                    return rate
            if product.marketplace_commission_rate is not None:
                return product.marketplace_commission_rate

        if order.marketplace == Marketplace.OZON:
            price = item.discounted_price or item.seller_price or item.buyer_price
            result = await tariff_resolver.get_commission_rate(
                marketplace="OZON",
                order_date=order.order_date.date() if hasattr(order.order_date, "date") else order.order_date,
                sales_model=order.sale_model.value.lower() if order.sale_model else "fbs",
                category_name=product.category if product else None,
                product_type_name=None,
                product_price=price,
            )
            if result.match_status == "exact" and result.commission_percent is not None:
                return result.commission_percent / Decimal("100")

        if order.marketplace == Marketplace.WB:
            result = await tariff_resolver.get_commission_rate(
                marketplace="WB",
                order_date=order.order_date.date() if hasattr(order.order_date, "date") else order.order_date,
                sales_model=order.sale_model.value.lower() if order.sale_model else "fbo",
                category_name=product.category if product else None,
                subject_name=None,
            )
            if result.match_status == "exact" and result.commission_percent is not None:
                return result.commission_percent / Decimal("100")

        return None

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
