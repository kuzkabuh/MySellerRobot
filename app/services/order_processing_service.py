"""version: 1.0.0
description: Online order ingestion, idempotency, product matching, and estimated profit snapshots.
updated: 2026-05-14
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import (
    MarketplaceAccount,
    Order,
    OrderItem,
    ProductCostHistory,
    ProfitSnapshot,
)
from app.models.enums import CalculationType, Marketplace
from app.repositories.orders import OrderRepository
from app.repositories.products import ProductRepository
from app.schemas.orders import NormalizedOrder
from app.schemas.profit import CostInput, ProfitInput, ProfitResult
from app.services.cost_service import CostService
from app.services.message_formatter import MessageFormatter
from app.services.profit_calculator import ProfitCalculator


@dataclass(slots=True)
class NewOrderNotification:
    telegram_id: int
    order_id: int
    text: str


class OrderProcessingService:
    """Process marketplace orders and prepare Telegram notifications."""

    def __init__(
        self,
        session: AsyncSession,
        cipher: TokenCipher | None = None,
    ) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()
        self.orders = OrderRepository(session)
        self.products = ProductRepository(session)
        self.costs = CostService(session)
        self.calculator = ProfitCalculator()
        self.formatter = MessageFormatter()

    async def poll_account(self, account: MarketplaceAccount) -> list[NewOrderNotification]:
        normalized_orders = await self._fetch_orders(account)
        notifications: list[NewOrderNotification] = []
        for normalized in normalized_orders:
            if await self.orders.exists(account.id, normalized):
                continue
            order = await self.orders.create(account.user_id, account.id, normalized)
            await self._calculate_estimated_profit(account, order, normalized)
            first_item = normalized.items[0] if normalized.items else None
            if first_item and account.user:
                order_with_items = await self.orders.get_with_items(order.id)
                item = (
                    order_with_items.items[0]
                    if order_with_items and order_with_items.items
                    else None
                )
                profit = await self._latest_estimated_profit(item) if item else None
                if profit:
                    notifications.append(
                        NewOrderNotification(
                            telegram_id=account.user.telegram_id,
                            order_id=order.id,
                            text=self.formatter.new_order_card(
                                normalized,
                                first_item,
                                profit,
                                detailed=False,
                            ),
                        )
                    )
        await self.session.commit()
        return notifications

    async def _fetch_orders(self, account: MarketplaceAccount) -> list[NormalizedOrder]:
        if account.marketplace == Marketplace.WB:
            api_key = self.cipher.decrypt(account.encrypted_api_key)
            wb_client = WildberriesClient(api_key)
            return [
                wb_client.normalize_fbs_order(item) for item in await wb_client.get_new_fbs_orders()
            ]

        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client_id = self.cipher.decrypt(account.encrypted_client_id or "")
        ozon_client = OzonClient(client_id=client_id, api_key=api_key)
        now = datetime.now(tz=UTC)
        data = await ozon_client.get_fbs_postings(now - timedelta(minutes=30), now)
        postings = data.get("result", {}).get("postings", [])
        return [
            ozon_client.normalize_fbs_posting(item) for item in postings if isinstance(item, dict)
        ]

    async def _calculate_estimated_profit(
        self,
        account: MarketplaceAccount,
        order: Order,
        normalized: NormalizedOrder,
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
            cost = (
                await self.costs.get_actual_cost(product.id, order.order_date) if product else None
            )
            result = self._calculate_item_profit(item, cost)
            self._apply_profit_to_item(item, result)
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
                    calculation_source="online_estimated",
                    raw_financial_data=None,
                )
            )
        await self.session.flush()

    def _calculate_item_profit(
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
                marketplace_commission=item.commission_estimated or Decimal("0"),
                logistics_cost=item.logistics_estimated or Decimal("0"),
                other_marketplace_costs=(item.other_marketplace_expenses_estimated or Decimal("0")),
                cost=cost_input,
            )
        )

    @staticmethod
    def _apply_profit_to_item(item: OrderItem, result: ProfitResult) -> None:
        item.cost_price_used = result.cost_price
        item.package_cost_used = result.package_cost
        item.tax_amount_estimated = result.tax_amount
        item.profit_estimated = result.profit
        item.margin_percent_estimated = result.margin_percent

    async def _latest_estimated_profit(self, item: OrderItem | None) -> ProfitResult | None:
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
