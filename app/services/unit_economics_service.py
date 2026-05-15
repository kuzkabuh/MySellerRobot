"""version: 1.0.0
description: Break-even price and price simulation service for product unit economics.
updated: 2026-05-15
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Order, OrderItem, Product
from app.models.enums import Marketplace

MONEY = Decimal("0.01")
PERCENT = Decimal("100")
ZERO = Decimal("0")


@dataclass(slots=True)
class BreakEvenRow:
    product_id: int | None
    title: str
    seller_article: str
    marketplace: Marketplace
    current_price: Decimal
    cost_price: Decimal
    commission_rate: Decimal
    logistics_cost: Decimal
    tax_rate: Decimal
    break_even_price: Decimal
    target_margin_price: Decimal
    simulated_price: Decimal
    simulated_profit: Decimal
    simulated_margin_percent: Decimal
    recommendation: str


class UnitEconomicsService:
    """Build break-even and price simulation data from existing order economics."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def rows(
        self,
        *,
        user_id: int,
        target_margin_percent: Decimal = Decimal("20"),
        price_delta_percent: Decimal = Decimal("0"),
        limit: int = 80,
    ) -> list[BreakEvenRow]:
        result = await self.session.execute(
            select(
                OrderItem.product_id,
                func.coalesce(Product.title, OrderItem.title, "Без названия"),
                func.coalesce(OrderItem.seller_article, Product.seller_article, "н/д"),
                Order.marketplace,
                func.avg(OrderItem.discounted_price),
                func.avg(func.coalesce(OrderItem.cost_price_used, 0)),
                func.avg(func.coalesce(OrderItem.commission_estimated, 0)),
                func.avg(func.coalesce(OrderItem.logistics_estimated, 0)),
                func.avg(func.coalesce(OrderItem.tax_amount_estimated, 0)),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .outerjoin(Product, Product.id == OrderItem.product_id)
            .where(Order.user_id == user_id)
            .group_by(
                OrderItem.product_id,
                Product.title,
                OrderItem.title,
                OrderItem.seller_article,
                Product.seller_article,
                Order.marketplace,
            )
            .order_by(func.max(Order.order_date).desc())
            .limit(limit)
        )
        rows: list[BreakEvenRow] = []
        for row in result.all():
            (
                product_id,
                title,
                seller_article,
                marketplace,
                current_price,
                cost_price,
                commission_amount,
                logistics_cost,
                tax_amount,
            ) = row
            rows.append(
                self.calculate_row(
                    product_id=product_id,
                    title=str(title),
                    seller_article=str(seller_article),
                    marketplace=marketplace,
                    current_price=_money(current_price),
                    cost_price=_money(cost_price),
                    commission_amount=_money(commission_amount),
                    logistics_cost=_money(logistics_cost),
                    tax_amount=_money(tax_amount),
                    target_margin_percent=target_margin_percent,
                    price_delta_percent=price_delta_percent,
                )
            )
        return rows

    def calculate_row(
        self,
        *,
        product_id: int | None,
        title: str,
        seller_article: str,
        marketplace: Marketplace,
        current_price: Decimal,
        cost_price: Decimal,
        commission_amount: Decimal,
        logistics_cost: Decimal,
        tax_amount: Decimal,
        target_margin_percent: Decimal,
        price_delta_percent: Decimal,
    ) -> BreakEvenRow:
        commission_rate = _safe_rate(commission_amount, current_price)
        tax_rate = _safe_rate(tax_amount, current_price)
        target_margin_rate = target_margin_percent / PERCENT
        variable_rate = commission_rate + tax_rate
        fixed_cost = cost_price + logistics_cost
        break_even_price = _price_for_margin(fixed_cost, variable_rate, ZERO)
        target_margin_price = _price_for_margin(fixed_cost, variable_rate, target_margin_rate)
        simulated_price = _money(current_price * (Decimal("1") + price_delta_percent / PERCENT))
        simulated_profit = _money(
            simulated_price - (simulated_price * variable_rate) - logistics_cost - cost_price
        )
        simulated_margin = (
            (simulated_profit / simulated_price * PERCENT).quantize(Decimal("0.1"))
            if simulated_price > 0
            else ZERO
        )
        recommendation = _recommendation(current_price, break_even_price, target_margin_price)
        return BreakEvenRow(
            product_id=product_id,
            title=title,
            seller_article=seller_article,
            marketplace=marketplace,
            current_price=current_price,
            cost_price=cost_price,
            commission_rate=(commission_rate * PERCENT).quantize(Decimal("0.1")),
            logistics_cost=logistics_cost,
            tax_rate=(tax_rate * PERCENT).quantize(Decimal("0.1")),
            break_even_price=break_even_price,
            target_margin_price=target_margin_price,
            simulated_price=simulated_price,
            simulated_profit=simulated_profit,
            simulated_margin_percent=simulated_margin,
            recommendation=recommendation,
        )


def _price_for_margin(
    fixed_cost: Decimal,
    variable_rate: Decimal,
    target_margin_rate: Decimal,
) -> Decimal:
    denominator = Decimal("1") - variable_rate - target_margin_rate
    if denominator <= Decimal("0.01"):
        return ZERO
    return _money(fixed_cost / denominator)


def _safe_rate(amount: Decimal, price: Decimal) -> Decimal:
    if price <= 0:
        return ZERO
    return amount / price


def _recommendation(
    current_price: Decimal,
    break_even_price: Decimal,
    target_margin_price: Decimal,
) -> str:
    if break_even_price == 0:
        return "Недостаточно данных для рекомендации"
    if current_price < break_even_price:
        return "Цена ниже безубыточной"
    if target_margin_price and current_price < target_margin_price:
        return "Цена покрывает расходы, но ниже цели по марже"
    return "Цена соответствует целевой экономике"


def _money(value: Decimal | int | float | None) -> Decimal:
    return Decimal(value or 0).quantize(MONEY, rounding=ROUND_HALF_UP)
