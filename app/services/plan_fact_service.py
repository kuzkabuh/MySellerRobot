"""version: 1.0.0
description: Plan/fact profit deviation aggregation for web and Telegram reports.
updated: 2026-05-15
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import Order, OrderItem, PlanFactTarget, ProfitSnapshot
from app.models.enums import CalculationType, Marketplace, SaleModel
from app.services.web_orders_profit_service import OrderWebFilters, build_order_web_filters

ZERO = Decimal("0")


@dataclass(slots=True)
class PlanFactRow:
    title: str
    seller_article: str
    marketplace: Marketplace
    sale_model: SaleModel | None
    orders: int
    estimated_profit: Decimal
    actual_profit: Decimal
    deviation: Decimal
    deviation_percent: Decimal | None
    pending_actual: int
    reason: str


@dataclass(slots=True)
class PlanFactSummary:
    estimated_profit: Decimal
    actual_profit: Decimal
    deviation: Decimal
    deviation_percent: Decimal | None
    orders: int
    pending_actual: int
    revenue: Decimal = ZERO
    buyouts: int = 0


@dataclass(slots=True)
class PlanFactPageData:
    filters: OrderWebFilters
    summary: PlanFactSummary
    rows: list[PlanFactRow]
    plan: PlanFactTarget | None = None


class PlanFactService:
    """Build plan/fact comparison from estimated and actual profit snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def compare(
        self,
        *,
        user_id: int,
        timezone: str,
        period: str,
        marketplace: str | None = "all",
        sale_model: str | None = "all",
        date_from: str | None = None,
        date_to: str | None = None,
        sku: str = "",
        sort: str = "deviation",
        direction: str = "asc",
        limit: int = 100,
    ) -> PlanFactPageData:
        filters = build_order_web_filters(
            timezone=timezone,
            period=period,
            marketplace=marketplace,
            sale_model=sale_model,
            date_from=date_from,
            date_to=date_to,
            economy="all",
            status="all",
            sku=sku,
            sort=sort if sort in {"deviation", "profit", "orders"} else "deviation",
            direction=direction,
        )
        orders = await self._orders(user_id, filters)
        buckets: dict[tuple[Marketplace, SaleModel | None, str], _PlanFactBucket] = {}
        for order in orders:
            for item in order.items:
                if not _matches_sku(item, filters.sku):
                    continue
                estimated_snapshot = _latest_snapshot(item.snapshots, CalculationType.ESTIMATED)
                actual_snapshot = _latest_snapshot(item.snapshots, CalculationType.ACTUAL)
                key = (order.marketplace, order.sale_model, item.seller_article or "н/д")
                bucket = buckets.setdefault(
                    key,
                    _PlanFactBucket(
                        title=item.title or item.seller_article or "Без названия",
                        seller_article=item.seller_article or "н/д",
                        marketplace=order.marketplace,
                        sale_model=order.sale_model,
                    ),
                )
                bucket.add(item, estimated_snapshot, actual_snapshot)
        rows = [_bucket_to_row(bucket) for bucket in buckets.values()]
        rows = _sort_rows(rows, filters.sort, filters.direction)[:limit]
        return PlanFactPageData(
            filters=filters,
            summary=_summary(rows),
            rows=rows,
            plan=await self._matching_plan(user_id, filters),
        )

    async def save_plan(
        self,
        *,
        user_id: int,
        period_start: date,
        period_end: date,
        marketplace: Marketplace | None,
        revenue_plan: Decimal | None,
        profit_plan: Decimal | None,
        orders_plan: int | None,
        buyouts_plan: int | None,
        target_id: int | None = None,
    ) -> PlanFactTarget:
        if period_end < period_start:
            period_start, period_end = period_end, period_start
        target: PlanFactTarget | None = None
        if target_id:
            result = await self.session.execute(
                select(PlanFactTarget)
                .where(PlanFactTarget.id == target_id)
                .where(PlanFactTarget.user_id == user_id)
            )
            target = result.scalar_one_or_none()
        if target is None:
            target = PlanFactTarget(user_id=user_id)
            self.session.add(target)
        target.period_start = period_start
        target.period_end = period_end
        target.marketplace = marketplace
        target.revenue_plan = revenue_plan
        target.profit_plan = profit_plan
        target.orders_plan = orders_plan
        target.buyouts_plan = buyouts_plan
        target.is_active = True
        await self.session.flush()
        return target

    async def delete_plan(self, *, user_id: int, target_id: int) -> None:
        result = await self.session.execute(
            select(PlanFactTarget)
            .where(PlanFactTarget.id == target_id)
            .where(PlanFactTarget.user_id == user_id)
        )
        target = result.scalar_one_or_none()
        if target is not None:
            target.is_active = False
            await self.session.flush()

    async def _orders(self, user_id: int, filters: OrderWebFilters) -> list[Order]:
        query = (
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.snapshots))
            .where(Order.user_id == user_id)
            .where(Order.order_date >= filters.date_from)
            .where(Order.order_date <= filters.date_to)
            .order_by(Order.order_date.desc())
        )
        if filters.marketplace is not None:
            query = query.where(Order.marketplace == filters.marketplace)
        if filters.sale_model is not None:
            query = query.where(Order.sale_model == filters.sale_model)
        result = await self.session.execute(query)
        return list(result.scalars().unique().all())

    async def _matching_plan(
        self,
        user_id: int,
        filters: OrderWebFilters,
    ) -> PlanFactTarget | None:
        query = (
            select(PlanFactTarget)
            .where(PlanFactTarget.user_id == user_id)
            .where(PlanFactTarget.is_active.is_(True))
            .where(PlanFactTarget.period_start <= filters.local_date_to)
            .where(PlanFactTarget.period_end >= filters.local_date_from)
            .order_by(PlanFactTarget.period_start.desc(), PlanFactTarget.updated_at.desc())
            .limit(1)
        )
        if filters.marketplace is None:
            query = query.where(PlanFactTarget.marketplace.is_(None))
        else:
            query = query.where(PlanFactTarget.marketplace == filters.marketplace)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()


@dataclass(slots=True)
class _PlanFactBucket:
    title: str
    seller_article: str
    marketplace: Marketplace
    sale_model: SaleModel | None
    orders: int = 0
    estimated_profit: Decimal = ZERO
    actual_profit: Decimal = ZERO
    estimated_revenue: Decimal = ZERO
    actual_revenue: Decimal = ZERO
    estimated_marketplace_costs: Decimal = ZERO
    actual_marketplace_costs: Decimal = ZERO
    pending_actual: int = 0

    def add(
        self,
        item: OrderItem,
        estimated_snapshot: ProfitSnapshot | None,
        actual_snapshot: ProfitSnapshot | None,
    ) -> None:
        self.orders += 1
        estimated_profit = (
            estimated_snapshot.profit
            if estimated_snapshot is not None
            else item.profit_estimated or ZERO
        )
        self.estimated_profit += estimated_profit
        self.estimated_revenue += (
            estimated_snapshot.gross_revenue
            if estimated_snapshot is not None
            else item.discounted_price * item.quantity
        )
        self.estimated_marketplace_costs += _snapshot_marketplace_costs(
            estimated_snapshot,
            item.commission_estimated,
            item.logistics_estimated,
            item.other_marketplace_expenses_estimated,
        )
        if actual_snapshot is None:
            self.pending_actual += 1
            return
        self.actual_profit += actual_snapshot.profit
        self.actual_revenue += actual_snapshot.gross_revenue
        self.actual_marketplace_costs += _snapshot_marketplace_costs(actual_snapshot)


def classify_deviation(
    *,
    estimated_profit: Decimal,
    actual_profit: Decimal,
    pending_actual: int,
    estimated_revenue: Decimal,
    actual_revenue: Decimal,
    estimated_marketplace_costs: Decimal,
    actual_marketplace_costs: Decimal,
) -> str:
    """Return a compact Russian explanation for the main plan/fact deviation."""

    if pending_actual:
        return "факт ещё не получен"
    deviation = actual_profit - estimated_profit
    if abs(deviation) < Decimal("1"):
        return "план совпал с фактом"
    if deviation > 0:
        return "факт лучше плана"
    if actual_marketplace_costs > estimated_marketplace_costs:
        return "расходы маркетплейса выше плана"
    if actual_revenue < estimated_revenue:
        return "выручка ниже плана"
    return "факт ниже плана"


def _bucket_to_row(bucket: _PlanFactBucket) -> PlanFactRow:
    deviation = bucket.actual_profit - bucket.estimated_profit
    return PlanFactRow(
        title=bucket.title,
        seller_article=bucket.seller_article,
        marketplace=bucket.marketplace,
        sale_model=bucket.sale_model,
        orders=bucket.orders,
        estimated_profit=bucket.estimated_profit,
        actual_profit=bucket.actual_profit,
        deviation=deviation,
        deviation_percent=_percent(deviation, bucket.estimated_profit),
        pending_actual=bucket.pending_actual,
        reason=classify_deviation(
            estimated_profit=bucket.estimated_profit,
            actual_profit=bucket.actual_profit,
            pending_actual=bucket.pending_actual,
            estimated_revenue=bucket.estimated_revenue,
            actual_revenue=bucket.actual_revenue,
            estimated_marketplace_costs=bucket.estimated_marketplace_costs,
            actual_marketplace_costs=bucket.actual_marketplace_costs,
        ),
    )


def _summary(rows: list[PlanFactRow]) -> PlanFactSummary:
    estimated = sum((row.estimated_profit for row in rows), ZERO)
    actual = sum((row.actual_profit for row in rows), ZERO)
    deviation = actual - estimated
    orders = sum(row.orders for row in rows)
    pending_actual = sum(row.pending_actual for row in rows)
    return PlanFactSummary(
        estimated_profit=estimated,
        actual_profit=actual,
        deviation=deviation,
        deviation_percent=_percent(deviation, estimated),
        orders=orders,
        pending_actual=pending_actual,
        revenue=estimated,
        buyouts=max(0, orders - pending_actual),
    )


def _sort_rows(rows: list[PlanFactRow], sort: str, direction: str) -> list[PlanFactRow]:
    reverse = direction != "asc"
    key_map = {
        "deviation": lambda row: row.deviation,
        "profit": lambda row: row.estimated_profit,
        "orders": lambda row: Decimal(row.orders),
    }
    return sorted(rows, key=key_map.get(sort, key_map["deviation"]), reverse=reverse)


def _latest_snapshot(
    snapshots: list[ProfitSnapshot],
    calculation_type: CalculationType,
) -> ProfitSnapshot | None:
    candidates = [item for item in snapshots if item.calculation_type == calculation_type]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.calculated_at)


def _snapshot_marketplace_costs(
    snapshot: ProfitSnapshot | None,
    commission: Decimal | None = None,
    logistics: Decimal | None = None,
    other: Decimal | None = None,
) -> Decimal:
    if snapshot is None:
        return (commission or ZERO) + (logistics or ZERO) + (other or ZERO)
    return (
        snapshot.marketplace_commission
        + snapshot.logistics_cost
        + (snapshot.acquiring_cost or ZERO)
        + (snapshot.storage_cost or ZERO)
        + (snapshot.return_cost or ZERO)
        + snapshot.other_marketplace_costs
    )


def _matches_sku(item: OrderItem, sku: str) -> bool:
    if not sku:
        return True
    needle = sku.lower()
    return any(
        needle in str(value or "").lower()
        for value in (item.seller_article, item.marketplace_article, item.title)
    )


def _percent(value: Decimal, base: Decimal) -> Decimal | None:
    if base == 0:
        return None
    return (value / abs(base) * Decimal("100")).quantize(Decimal("0.1"))
