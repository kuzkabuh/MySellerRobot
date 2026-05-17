"""version: 1.2.0
description: Web cabinet order list, order detail, and PostgreSQL-safe SKU profit queries.
updated: 2026-05-17
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import Order, OrderItem, ProfitSnapshot, SalesEvent
from app.models.enums import CalculationType, EconomyConfidence, Marketplace, SaleModel
from app.services.marketplace_presentation import order_status_label
from app.services.web_dashboard_service import (
    build_dashboard_filters,
)

ZERO = Decimal("0")


@dataclass(slots=True)
class OrderWebFilters:
    period: str
    marketplace: Marketplace | None
    sale_model: SaleModel | None
    local_date_from: date
    local_date_to: date
    date_from: datetime
    date_to: datetime
    economy: str
    status: str
    sku: str
    sort: str
    direction: str


@dataclass(slots=True)
class OrderRow:
    order_id: int
    item_id: int
    order_date: datetime
    marketplace: Marketplace
    sale_model: SaleModel | None
    order_external_id: str
    posting_number: str | None
    title: str
    seller_article: str
    marketplace_article: str
    quantity: int
    revenue: Decimal
    estimated_profit: Decimal | None
    margin_percent: Decimal | None
    status: str
    source_event_type: str
    requires_action: bool
    missing_cost: bool
    economy_confidence: str


@dataclass(slots=True)
class OrderDetailItem:
    item: OrderItem
    estimated_snapshot: ProfitSnapshot | None
    actual_snapshot: ProfitSnapshot | None


@dataclass(slots=True)
class OrderDetail:
    order: Order
    items: list[OrderDetailItem]
    estimated_profit: Decimal
    actual_profit: Decimal | None
    deviation: Decimal | None


@dataclass(slots=True)
class ProfitSkuRow:
    title: str
    seller_article: str
    marketplace: Marketplace
    sale_model: SaleModel | None
    orders: int
    sales: int
    revenue: Decimal
    cost: Decimal
    marketplace_costs: Decimal
    estimated_profit: Decimal
    actual_profit: Decimal
    margin_percent: Decimal
    roi_percent: Decimal | None
    missing_cost_items: int
    preliminary_items: int


@dataclass(slots=True)
class ProfitSummary:
    estimated_profit: Decimal
    actual_profit: Decimal
    deviation: Decimal
    average_unit_profit: Decimal
    average_margin: Decimal
    roi_percent: Decimal | None


@dataclass(slots=True)
class ProfitPageData:
    filters: OrderWebFilters
    summary: ProfitSummary
    rows: list[ProfitSkuRow]


class WebOrdersProfitService:
    """Build web order and profit pages from normalized marketplace data."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_orders(
        self,
        *,
        user_id: int,
        timezone: str,
        period: str,
        marketplace: str | None,
        sale_model: str | None,
        date_from: str | None,
        date_to: str | None,
        economy: str = "all",
        status: str = "all",
        sku: str = "",
        sort: str = "date",
        direction: str = "desc",
        limit: int = 100,
    ) -> tuple[OrderWebFilters, list[OrderRow]]:
        filters = build_order_web_filters(
            timezone=timezone,
            period=period,
            marketplace=marketplace,
            sale_model=sale_model,
            date_from=date_from,
            date_to=date_to,
            economy=economy,
            status=status,
            sku=sku,
            sort=sort,
            direction=direction,
        )
        query = (
            select(
                Order.id,
                OrderItem.id,
                Order.order_date,
                Order.marketplace,
                Order.sale_model,
                Order.order_external_id,
                Order.posting_number,
                OrderItem.title,
                OrderItem.seller_article,
                OrderItem.marketplace_article,
                OrderItem.quantity,
                (OrderItem.discounted_price * OrderItem.quantity).label("revenue"),
                OrderItem.profit_estimated,
                OrderItem.margin_percent_estimated,
                Order.normalized_status,
                Order.status,
                Order.source_event_type,
                Order.requires_seller_action,
                OrderItem.cost_price_used,
                OrderItem.economy_confidence,
            )
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(Order.user_id == user_id)
            .where(Order.order_date >= filters.date_from)
            .where(Order.order_date <= filters.date_to)
            .limit(limit)
        )
        query = _apply_order_page_filters(query, filters)
        query = _apply_order_sort(query, filters)
        result = await self.session.execute(query)
        rows = []
        for row in result.all():
            (
                order_id,
                item_id,
                order_date,
                marketplace_value,
                sale_model_value,
                order_external_id,
                posting_number,
                title,
                seller_article,
                marketplace_article,
                quantity,
                revenue,
                estimated_profit,
                margin_percent,
                normalized_status,
                raw_status,
                source_event_type,
                requires_action,
                cost_price_used,
                economy_confidence,
            ) = row
            rows.append(
                OrderRow(
                    order_id=int(order_id),
                    item_id=int(item_id),
                    order_date=order_date,
                    marketplace=marketplace_value,
                    sale_model=sale_model_value,
                    order_external_id=str(order_external_id),
                    posting_number=posting_number,
                    title=title or "Без названия",
                    seller_article=seller_article or "н/д",
                    marketplace_article=marketplace_article or "н/д",
                    quantity=int(quantity or 0),
                    revenue=_decimal(revenue),
                    estimated_profit=(
                        _decimal(estimated_profit) if estimated_profit is not None else None
                    ),
                    margin_percent=(
                        _decimal(margin_percent) if margin_percent is not None else None
                    ),
                    status=normalized_status or raw_status or "н/д",
                    source_event_type=(
                        source_event_type.value if source_event_type is not None else "н/д"
                    ),
                    requires_action=bool(requires_action),
                    missing_cost=cost_price_used is None,
                    economy_confidence=str(
                        economy_confidence or EconomyConfidence.PRELIMINARY.value
                    ),
                )
            )
        return filters, rows

    async def order_detail(self, *, user_id: int, order_id: int) -> OrderDetail | None:
        result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.snapshots))
            .where(Order.user_id == user_id)
            .where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()
        if order is None:
            return None
        items = []
        estimated_total = ZERO
        actual_total = ZERO
        has_actual = False
        for item in order.items:
            estimated_snapshot = _latest_snapshot(item.snapshots, CalculationType.ESTIMATED)
            actual_snapshot = _latest_snapshot(item.snapshots, CalculationType.ACTUAL)
            if estimated_snapshot is not None:
                estimated_total += estimated_snapshot.profit
            elif item.profit_estimated is not None:
                estimated_total += item.profit_estimated
            if actual_snapshot is not None:
                actual_total += actual_snapshot.profit
                has_actual = True
            items.append(
                OrderDetailItem(
                    item=item,
                    estimated_snapshot=estimated_snapshot,
                    actual_snapshot=actual_snapshot,
                )
            )
        actual_profit = actual_total if has_actual else None
        deviation = actual_total - estimated_total if has_actual else None
        return OrderDetail(
            order=order,
            items=items,
            estimated_profit=estimated_total,
            actual_profit=actual_profit,
            deviation=deviation,
        )

    async def profit_by_sku(
        self,
        *,
        user_id: int,
        timezone: str,
        period: str,
        marketplace: str | None,
        sale_model: str | None,
        date_from: str | None,
        date_to: str | None,
        economy: str = "all",
        sku: str = "",
        sort: str = "profit",
        direction: str = "desc",
        limit: int = 100,
    ) -> ProfitPageData:
        filters = build_order_web_filters(
            timezone=timezone,
            period=period,
            marketplace=marketplace,
            sale_model=sale_model,
            date_from=date_from,
            date_to=date_to,
            economy=economy,
            status="all",
            sku=sku,
            sort=sort,
            direction=direction,
        )
        order_rows = await self._profit_order_rows(user_id, filters)
        sales_map = await self._sales_by_sku(user_id, filters)
        rows: list[ProfitSkuRow] = []
        for row in order_rows:
            (
                title,
                seller_article,
                marketplace_value,
                sale_model_value,
                orders,
                revenue,
                quantity,
                cost,
                marketplace_costs,
                estimated_profit,
                actual_profit,
                margin,
                missing_cost_items,
                preliminary_items,
            ) = row
            key = (marketplace_value, seller_article or "")
            sales = sales_map.get(key, 0)
            profit = _decimal(estimated_profit)
            total_cost = _decimal(cost)
            rows.append(
                ProfitSkuRow(
                    title=title or seller_article or "Без названия",
                    seller_article=seller_article or "н/д",
                    marketplace=marketplace_value,
                    sale_model=sale_model_value,
                    orders=int(orders or 0),
                    sales=sales,
                    revenue=_decimal(revenue),
                    cost=total_cost,
                    marketplace_costs=_decimal(marketplace_costs),
                    estimated_profit=profit,
                    actual_profit=_decimal(actual_profit),
                    margin_percent=_decimal(margin),
                    roi_percent=roi_percent(profit, total_cost),
                    missing_cost_items=int(missing_cost_items or 0),
                    preliminary_items=int(preliminary_items or 0),
                )
            )
        rows = _filter_profit_rows(rows, filters.economy)
        rows = _sort_profit_rows(rows, filters.sort, filters.direction)[:limit]
        return ProfitPageData(filters=filters, summary=_profit_summary(rows), rows=rows)

    async def _profit_order_rows(
        self,
        user_id: int,
        filters: OrderWebFilters,
    ) -> list[Any]:
        query = self._profit_order_query(user_id, filters)
        result = await self.session.execute(query)
        return list(result.all())

    @staticmethod
    def _profit_order_query(user_id: int, filters: OrderWebFilters) -> Select[Any]:
        title_expr = func.coalesce(
            OrderItem.title,
            OrderItem.seller_article,
            literal_column("'Без названия'"),
        )
        article_expr = func.coalesce(OrderItem.seller_article, literal_column("''"))
        query = (
            select(
                title_expr,
                article_expr,
                Order.marketplace,
                Order.sale_model,
                func.count(func.distinct(Order.id)),
                func.coalesce(func.sum(OrderItem.discounted_price * OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.quantity), 0),
                func.coalesce(
                    func.sum(
                        (
                            func.coalesce(OrderItem.cost_price_used, 0)
                            + func.coalesce(OrderItem.package_cost_used, 0)
                        )
                        * OrderItem.quantity
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        func.coalesce(OrderItem.commission_estimated, 0)
                        + func.coalesce(OrderItem.logistics_estimated, 0)
                        + func.coalesce(OrderItem.other_marketplace_expenses_estimated, 0)
                    ),
                    0,
                ),
                func.coalesce(func.sum(OrderItem.profit_estimated), 0),
                func.coalesce(
                    func.sum(ProfitSnapshot.profit).filter(
                        ProfitSnapshot.calculation_type == CalculationType.ACTUAL
                    ),
                    0,
                ),
                func.avg(OrderItem.margin_percent_estimated),
                func.count(OrderItem.id).filter(OrderItem.cost_price_used.is_(None)),
                func.count(OrderItem.id).filter(
                    OrderItem.economy_confidence == EconomyConfidence.PRELIMINARY.value
                ),
            )
            .join(OrderItem, OrderItem.order_id == Order.id)
            .outerjoin(ProfitSnapshot, ProfitSnapshot.order_item_id == OrderItem.id)
            .where(Order.user_id == user_id)
            .where(Order.order_date >= filters.date_from)
            .where(Order.order_date <= filters.date_to)
            .group_by(
                title_expr,
                article_expr,
                Order.marketplace,
                Order.sale_model,
            )
        )
        return _apply_order_page_filters(query, filters, include_economy=False)

    async def _sales_by_sku(
        self,
        user_id: int,
        filters: OrderWebFilters,
    ) -> dict[tuple[Marketplace, str], int]:
        article_expr = func.coalesce(SalesEvent.seller_article, literal_column("''"))
        query = (
            select(
                SalesEvent.marketplace,
                article_expr,
                func.coalesce(func.sum(SalesEvent.quantity), 0),
            )
            .where(SalesEvent.user_id == user_id)
            .where(SalesEvent.event_date >= filters.date_from)
            .where(SalesEvent.event_date <= filters.date_to)
            .group_by(SalesEvent.marketplace, article_expr)
        )
        if filters.marketplace is not None:
            query = query.where(SalesEvent.marketplace == filters.marketplace)
        result = await self.session.execute(query)
        return {
            (marketplace, seller_article): int(quantity or 0)
            for marketplace, seller_article, quantity in result.all()
        }


def build_order_web_filters(
    *,
    timezone: str,
    period: str,
    marketplace: str | None,
    sale_model: str | None,
    date_from: str | None,
    date_to: str | None,
    economy: str,
    status: str,
    sku: str,
    sort: str,
    direction: str,
) -> OrderWebFilters:
    base = build_dashboard_filters(
        timezone=timezone,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
    )
    return OrderWebFilters(
        period=base.period,
        marketplace=base.marketplace,
        sale_model=base.sale_model,
        local_date_from=base.local_date_from,
        local_date_to=base.local_date_to,
        date_from=base.date_from,
        date_to=base.date_to,
        economy=economy if economy in {"all", "profit", "loss", "missing_cost"} else "all",
        status=status if status in {"all", "active", "cancelled", "action_required"} else "all",
        sku=sku.strip(),
        sort=sort if sort in {"date", "profit", "revenue", "margin", "orders", "roi"} else "date",
        direction="asc" if direction == "asc" else "desc",
    )


def roi_percent(profit: Decimal, cost: Decimal) -> Decimal | None:
    if cost == 0:
        return None
    return (profit / cost * Decimal("100")).quantize(Decimal("0.1"))


def _apply_order_page_filters(
    query: Select[Any],
    filters: OrderWebFilters,
    *,
    include_economy: bool = True,
) -> Select[Any]:
    if filters.marketplace is not None:
        query = query.where(Order.marketplace == filters.marketplace)
    if filters.sale_model is not None:
        query = query.where(Order.sale_model == filters.sale_model)
    if filters.sku:
        pattern = f"%{filters.sku}%"
        query = query.where(
            (OrderItem.seller_article.ilike(pattern))
            | (OrderItem.marketplace_article.ilike(pattern))
            | (OrderItem.title.ilike(pattern))
        )
    if filters.status == "cancelled":
        query = query.where(
            func.lower(func.coalesce(Order.normalized_status, Order.status, "")).in_(
                ("cancelled", "canceled", "cancel")
            )
        )
    elif filters.status == "active":
        query = query.where(
            ~func.lower(func.coalesce(Order.normalized_status, Order.status, "")).in_(
                ("cancelled", "canceled", "cancel")
            )
        )
    elif filters.status == "action_required":
        query = query.where(Order.requires_seller_action.is_(True))
    if include_economy:
        if filters.economy == "loss":
            query = query.where(OrderItem.profit_estimated < 0)
        elif filters.economy == "profit":
            query = query.where(OrderItem.profit_estimated >= 0)
        elif filters.economy == "missing_cost":
            query = query.where(OrderItem.cost_price_used.is_(None))
    return query


def _apply_order_sort(query: Select[Any], filters: OrderWebFilters) -> Select[Any]:
    sort_map = {
        "date": Order.order_date,
        "profit": OrderItem.profit_estimated,
        "revenue": OrderItem.discounted_price * OrderItem.quantity,
        "margin": OrderItem.margin_percent_estimated,
    }
    expression = sort_map.get(filters.sort, Order.order_date)
    expression = expression.asc() if filters.direction == "asc" else expression.desc()
    return query.order_by(expression, Order.id.desc())


def _latest_snapshot(
    snapshots: list[ProfitSnapshot],
    calculation_type: CalculationType,
) -> ProfitSnapshot | None:
    filtered = [item for item in snapshots if item.calculation_type == calculation_type]
    if not filtered:
        return None
    return max(filtered, key=lambda item: item.calculated_at)


def _filter_profit_rows(rows: list[ProfitSkuRow], economy: str) -> list[ProfitSkuRow]:
    if economy == "loss":
        return [row for row in rows if row.estimated_profit < 0]
    if economy == "profit":
        return [row for row in rows if row.estimated_profit >= 0]
    if economy == "missing_cost":
        return [row for row in rows if row.missing_cost_items > 0]
    return rows


def _sort_profit_rows(
    rows: list[ProfitSkuRow],
    sort: str,
    direction: str,
) -> list[ProfitSkuRow]:
    reverse = direction != "asc"
    key_map = {
        "profit": lambda row: row.estimated_profit,
        "revenue": lambda row: row.revenue,
        "margin": lambda row: row.margin_percent,
        "orders": lambda row: Decimal(row.orders),
        "roi": lambda row: row.roi_percent or Decimal("-999999"),
    }
    key = key_map.get(sort, key_map["profit"])
    return sorted(rows, key=key, reverse=reverse)


def _profit_summary(rows: list[ProfitSkuRow]) -> ProfitSummary:
    estimated = sum((row.estimated_profit for row in rows), ZERO)
    actual = sum((row.actual_profit for row in rows), ZERO)
    revenue = sum((row.revenue for row in rows), ZERO)
    cost = sum((row.cost for row in rows), ZERO)
    quantity = sum((row.orders for row in rows), 0)
    return ProfitSummary(
        estimated_profit=estimated,
        actual_profit=actual,
        deviation=actual - estimated,
        average_unit_profit=estimated / Decimal(quantity) if quantity else ZERO,
        average_margin=(
            (estimated / revenue * Decimal("100")).quantize(Decimal("0.1")) if revenue else ZERO
        ),
        roi_percent=roi_percent(estimated, cost),
    )


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))


def localized_order_date(value: datetime, timezone: str) -> str:
    return value.astimezone(ZoneInfo(timezone)).strftime("%d.%m.%Y %H:%M")


def order_state_label(status: str | None, requires_action: bool) -> str:
    return order_status_label(status, requires_action)
