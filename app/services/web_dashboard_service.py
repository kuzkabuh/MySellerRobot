"""version: 2.0.0
description: Web cabinet dashboard aggregation, filters, KPI, and chart data.
updated: 2026-05-15
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    Order,
    OrderItem,
    ProfitSnapshot,
    ReturnsEvent,
    SalesEvent,
    WbDailyReportRow,
)
from app.models.enums import CalculationType, Marketplace, SaleModel

ZERO = Decimal("0")


@dataclass(slots=True)
class DashboardFilters:
    period: str
    marketplace: Marketplace | None
    sale_model: SaleModel | None
    timezone: str
    local_date_from: date
    local_date_to: date
    date_from: datetime
    date_to: datetime
    previous_from: datetime
    previous_to: datetime


@dataclass(slots=True)
class KpiMetric:
    label: str
    value: Decimal | int
    suffix: str = ""
    change_percent: Decimal | None = None
    tone: str = "neutral"


@dataclass(slots=True)
class DailyPoint:
    label: str
    revenue: Decimal = ZERO
    estimated_profit: Decimal = ZERO
    orders: int = 0
    sales: int = 0
    returns: int = 0
    cancellations: int = 0
    wb_revenue: Decimal = ZERO
    ozon_revenue: Decimal = ZERO
    fbo_orders: int = 0
    fbs_orders: int = 0
    rfbs_orders: int = 0


@dataclass(slots=True)
class MarketplaceBreakdown:
    marketplace: Marketplace
    revenue: Decimal = ZERO
    orders: int = 0
    sales: int = 0
    estimated_profit: Decimal = ZERO


@dataclass(slots=True)
class DashboardEvent:
    event_date: datetime
    title: str
    subtitle: str
    marketplace: Marketplace
    amount: Decimal
    tone: str = "neutral"
    href: str | None = None


@dataclass(slots=True)
class DashboardData:
    filters: DashboardFilters
    metrics: list[KpiMetric]
    points: list[DailyPoint]
    marketplace_breakdown: list[MarketplaceBreakdown]
    actual_profit: Decimal
    recent_events: list[DashboardEvent] = field(default_factory=list)


@dataclass(slots=True)
class _OrderAggregate:
    revenue: Decimal = ZERO
    orders: int = 0
    estimated_profit: Decimal = ZERO
    margin_sum: Decimal = ZERO
    margin_count: int = 0
    loss_orders: int = 0
    cancellations: int = 0


@dataclass(slots=True)
class _SalesAggregate:
    sales: int = 0
    revenue: Decimal = ZERO
    estimated_profit: Decimal = ZERO


@dataclass(slots=True)
class _ReturnAggregate:
    returns: int = 0
    amount: Decimal = ZERO


@dataclass(slots=True)
class _WbDailyReportAggregate:
    payout: Decimal = ZERO
    sales_amount: Decimal = ZERO
    commission: Decimal = ZERO
    logistics: Decimal = ZERO
    penalties: Decimal = ZERO
    deductions: Decimal = ZERO


@dataclass(slots=True)
class _RawDashboardRows:
    order_rows: list[
        tuple[datetime, Marketplace, SaleModel, int, str | None, Decimal, Decimal | None]
    ]
    sales_rows: list[tuple[datetime, Marketplace, int, Decimal, Decimal | None]]
    return_rows: list[tuple[datetime, Marketplace, int, Decimal]]


class WebDashboardService:
    """Build the main web dashboard for a seller."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def dashboard(
        self,
        *,
        user_id: int,
        timezone: str,
        period: str = "today",
        marketplace: str | None = None,
        sale_model: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> DashboardData:
        filters = build_dashboard_filters(
            timezone=timezone,
            period=period,
            marketplace=marketplace,
            sale_model=sale_model,
            date_from=date_from,
            date_to=date_to,
        )
        current = await self._aggregate(user_id=user_id, filters=filters)
        previous_filters = DashboardFilters(
            period=filters.period,
            marketplace=filters.marketplace,
            sale_model=filters.sale_model,
            timezone=filters.timezone,
            local_date_from=filters.local_date_from,
            local_date_to=filters.local_date_to,
            date_from=filters.previous_from,
            date_to=filters.previous_to,
            previous_from=filters.previous_from,
            previous_to=filters.previous_to,
        )
        previous = await self._aggregate(user_id=user_id, filters=previous_filters)
        wb_current = await self._wb_daily_report_aggregate(user_id=user_id, filters=filters)
        wb_previous = await self._wb_daily_report_aggregate(
            user_id=user_id,
            filters=previous_filters,
        )
        raw_rows = await self._raw_rows(user_id=user_id, filters=filters)
        points = self._build_daily_points(filters, raw_rows)
        marketplace_breakdown = self._build_marketplace_breakdown(raw_rows)
        actual_profit = await self._actual_profit(user_id=user_id, filters=filters)
        return DashboardData(
            filters=filters,
            metrics=self._build_metrics(current, previous, actual_profit, wb_current, wb_previous),
            points=points,
            marketplace_breakdown=marketplace_breakdown,
            actual_profit=actual_profit,
            recent_events=self._build_recent_events(raw_rows),
        )

    async def _aggregate(
        self,
        *,
        user_id: int,
        filters: DashboardFilters,
    ) -> tuple[_OrderAggregate, _SalesAggregate, _ReturnAggregate]:
        order_result = await self.session.execute(self._order_query(user_id, filters))
        orders, revenue, profit, margin, loss_orders, cancellations = order_result.one()
        sales_result = await self.session.execute(self._sales_query(user_id, filters))
        sales, sales_revenue, sales_profit = sales_result.one()
        returns_result = await self.session.execute(self._returns_query(user_id, filters))
        returns, returns_amount = returns_result.one()
        return (
            _OrderAggregate(
                revenue=_decimal(revenue),
                orders=int(orders or 0),
                estimated_profit=_decimal(profit),
                margin_sum=_decimal(margin),
                margin_count=1 if margin is not None else 0,
                loss_orders=int(loss_orders or 0),
                cancellations=int(cancellations or 0),
            ),
            _SalesAggregate(
                sales=int(sales or 0),
                revenue=_decimal(sales_revenue),
                estimated_profit=_decimal(sales_profit),
            ),
            _ReturnAggregate(returns=int(returns or 0), amount=_decimal(returns_amount)),
        )

    def _order_query(self, user_id: int, filters: DashboardFilters):  # type: ignore[no-untyped-def]
        query = (
            select(
                func.count(func.distinct(Order.id)),
                func.coalesce(func.sum(OrderItem.discounted_price * OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.profit_estimated), 0),
                func.avg(OrderItem.margin_percent_estimated),
                func.count(func.distinct(Order.id)).filter(OrderItem.profit_estimated < 0),
                func.count(func.distinct(Order.id)).filter(
                    func.lower(func.coalesce(Order.normalized_status, Order.status, "")).in_(
                        ("cancelled", "canceled", "cancel")
                    )
                ),
            )
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(Order.user_id == user_id)
            .where(Order.order_date >= filters.date_from)
            .where(Order.order_date <= filters.date_to)
        )
        return _apply_order_filters(query, filters)

    def _sales_query(self, user_id: int, filters: DashboardFilters):  # type: ignore[no-untyped-def]
        query = (
            select(
                func.coalesce(func.sum(SalesEvent.quantity), 0),
                func.coalesce(func.sum(SalesEvent.amount), 0),
                func.coalesce(func.sum(SalesEvent.estimated_profit), 0),
            )
            .where(SalesEvent.user_id == user_id)
            .where(SalesEvent.event_date >= filters.date_from)
            .where(SalesEvent.event_date <= filters.date_to)
        )
        if filters.marketplace is not None:
            query = query.where(SalesEvent.marketplace == filters.marketplace)
        return query

    def _returns_query(self, user_id: int, filters: DashboardFilters):  # type: ignore[no-untyped-def]
        query = (
            select(
                func.coalesce(func.sum(ReturnsEvent.quantity), 0),
                func.coalesce(func.sum(ReturnsEvent.amount), 0),
            )
            .where(ReturnsEvent.user_id == user_id)
            .where(ReturnsEvent.event_date >= filters.date_from)
            .where(ReturnsEvent.event_date <= filters.date_to)
        )
        if filters.marketplace is not None:
            query = query.where(ReturnsEvent.marketplace == filters.marketplace)
        return query

    async def _wb_daily_report_aggregate(
        self,
        *,
        user_id: int,
        filters: DashboardFilters,
    ) -> _WbDailyReportAggregate:
        if filters.marketplace not in (None, Marketplace.WB):
            return _WbDailyReportAggregate()
        query = (
            select(
                func.coalesce(func.sum(WbDailyReportRow.for_pay), 0),
                func.coalesce(func.sum(WbDailyReportRow.retail_amount), 0),
                func.coalesce(func.sum(WbDailyReportRow.commission_rub), 0),
                func.coalesce(func.sum(WbDailyReportRow.delivery_rub), 0),
                func.coalesce(func.sum(WbDailyReportRow.penalty), 0),
                func.coalesce(func.sum(WbDailyReportRow.deduction), 0),
            )
            .where(WbDailyReportRow.user_id == user_id)
            .where(WbDailyReportRow.sale_dt >= filters.date_from)
            .where(WbDailyReportRow.sale_dt <= filters.date_to)
        )
        result = await self.session.execute(query)
        payout, sales_amount, commission, logistics, penalties, deductions = result.one()
        return _WbDailyReportAggregate(
            payout=_decimal(payout),
            sales_amount=_decimal(sales_amount),
            commission=_decimal(commission),
            logistics=_decimal(logistics),
            penalties=_decimal(penalties),
            deductions=_decimal(deductions),
        )

    async def _raw_rows(self, *, user_id: int, filters: DashboardFilters) -> _RawDashboardRows:
        order_query = (
            select(
                Order.marketplace,
                Order.sale_model,
                Order.id,
                Order.order_date,
                Order.normalized_status,
                func.coalesce(func.sum(OrderItem.discounted_price * OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.profit_estimated), 0),
            )
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(Order.user_id == user_id)
            .where(Order.order_date >= filters.date_from)
            .where(Order.order_date <= filters.date_to)
            .group_by(
                Order.marketplace,
                Order.sale_model,
                Order.id,
                Order.order_date,
                Order.normalized_status,
            )
        )
        order_query = _apply_order_filters(order_query, filters)
        sales_query = (
            select(
                SalesEvent.event_date,
                SalesEvent.marketplace,
                func.coalesce(func.sum(SalesEvent.quantity), 0),
                func.coalesce(func.sum(SalesEvent.amount), 0),
                func.coalesce(func.sum(SalesEvent.estimated_profit), 0),
            )
            .where(SalesEvent.user_id == user_id)
            .where(SalesEvent.event_date >= filters.date_from)
            .where(SalesEvent.event_date <= filters.date_to)
            .group_by(SalesEvent.event_date, SalesEvent.marketplace)
        )
        returns_query = (
            select(
                ReturnsEvent.event_date,
                ReturnsEvent.marketplace,
                func.coalesce(func.sum(ReturnsEvent.quantity), 0),
                func.coalesce(func.sum(ReturnsEvent.amount), 0),
            )
            .where(ReturnsEvent.user_id == user_id)
            .where(ReturnsEvent.event_date >= filters.date_from)
            .where(ReturnsEvent.event_date <= filters.date_to)
            .group_by(ReturnsEvent.event_date, ReturnsEvent.marketplace)
        )
        if filters.marketplace is not None:
            sales_query = sales_query.where(SalesEvent.marketplace == filters.marketplace)
            returns_query = returns_query.where(ReturnsEvent.marketplace == filters.marketplace)
        order_rows = await self.session.execute(order_query)
        sales_rows = await self.session.execute(sales_query)
        return_rows = await self.session.execute(returns_query)
        return _RawDashboardRows(
            order_rows=[
                (
                    order_date,
                    marketplace,
                    sale_model,
                    int(order_id),
                    status,
                    _decimal(revenue),
                    profit,
                )
                for (
                    marketplace,
                    sale_model,
                    order_id,
                    order_date,
                    status,
                    revenue,
                    profit,
                ) in order_rows
            ],
            sales_rows=[
                (row_date, marketplace, int(quantity or 0), _decimal(amount), profit)
                for row_date, marketplace, quantity, amount, profit in sales_rows
            ],
            return_rows=[
                (row_date, marketplace, int(quantity or 0), _decimal(amount))
                for row_date, marketplace, quantity, amount in return_rows
            ],
        )

    async def _actual_profit(self, *, user_id: int, filters: DashboardFilters) -> Decimal:
        query = (
            select(func.coalesce(func.sum(ProfitSnapshot.profit), 0))
            .join(OrderItem, OrderItem.id == ProfitSnapshot.order_item_id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.user_id == user_id)
            .where(ProfitSnapshot.calculation_type == CalculationType.ACTUAL)
            .where(ProfitSnapshot.calculated_at >= filters.date_from)
            .where(ProfitSnapshot.calculated_at <= filters.date_to)
        )
        query = _apply_order_filters(query, filters)
        result = await self.session.execute(query)
        return _decimal(result.scalar_one())

    def _build_daily_points(
        self,
        filters: DashboardFilters,
        rows: _RawDashboardRows,
    ) -> list[DailyPoint]:
        start = filters.local_date_from
        end = filters.local_date_to
        tz = _timezone(filters.timezone)
        points: dict[date, DailyPoint] = {}
        current = start
        while current <= end:
            points[current] = DailyPoint(label=current.strftime("%d.%m"))
            current += timedelta(days=1)
        for row_at, marketplace, sale_model, _order_id, status, revenue, profit in rows.order_rows:
            row_date = row_at.astimezone(tz).date()
            point = points.setdefault(row_date, DailyPoint(label=row_date.strftime("%d.%m")))
            point.orders += 1
            point.revenue += revenue
            point.estimated_profit += _decimal(profit)
            if is_cancelled_status(status):
                point.cancellations += 1
            if marketplace == Marketplace.WB:
                point.wb_revenue += revenue
            if marketplace == Marketplace.OZON:
                point.ozon_revenue += revenue
            if sale_model == SaleModel.FBO:
                point.fbo_orders += 1
            elif sale_model == SaleModel.RFBS:
                point.rfbs_orders += 1
            else:
                point.fbs_orders += 1
        for row_at, _marketplace, quantity, _amount, _profit in rows.sales_rows:
            row_date = row_at.astimezone(tz).date()
            point = points.setdefault(row_date, DailyPoint(label=row_date.strftime("%d.%m")))
            point.sales += quantity
        for row_at, _marketplace, quantity, _amount in rows.return_rows:
            row_date = row_at.astimezone(tz).date()
            point = points.setdefault(row_date, DailyPoint(label=row_date.strftime("%d.%m")))
            point.returns += quantity
        return [points[key] for key in sorted(points)]

    def _build_marketplace_breakdown(
        self,
        rows: _RawDashboardRows,
    ) -> list[MarketplaceBreakdown]:
        data = {
            Marketplace.WB: MarketplaceBreakdown(marketplace=Marketplace.WB),
            Marketplace.OZON: MarketplaceBreakdown(marketplace=Marketplace.OZON),
        }
        for (
            _row_date,
            marketplace,
            _sale_model,
            _order_id,
            _status,
            revenue,
            profit,
        ) in rows.order_rows:
            item = data[marketplace]
            item.orders += 1
            item.revenue += revenue
            item.estimated_profit += _decimal(profit)
        for _row_date, marketplace, quantity, _amount, _profit in rows.sales_rows:
            data[marketplace].sales += quantity
        return list(data.values())

    def _build_recent_events(self, rows: _RawDashboardRows) -> list[DashboardEvent]:
        events: list[DashboardEvent] = []
        for row_at, marketplace, sale_model, order_id, status, revenue, _profit in rows.order_rows:
            is_cancelled = is_cancelled_status(status)
            events.append(
                DashboardEvent(
                    event_date=row_at,
                    title="Отмена заказа" if is_cancelled else "Новый заказ",
                    subtitle=sale_model.value if sale_model else "Модель не указана",
                    marketplace=marketplace,
                    amount=revenue,
                    tone="bad" if is_cancelled else "action",
                    href=f"/web/orders/{order_id}",
                )
            )
        for row_at, marketplace, quantity, amount in rows.return_rows:
            events.append(
                DashboardEvent(
                    event_date=row_at,
                    title="Возврат",
                    subtitle=f"{quantity} шт.",
                    marketplace=marketplace,
                    amount=amount,
                    tone="warn",
                    href="/web/returns",
                )
            )
        return sorted(events, key=lambda event: event.event_date, reverse=True)[:8]

    def _build_metrics(
        self,
        current: tuple[_OrderAggregate, _SalesAggregate, _ReturnAggregate],
        previous: tuple[_OrderAggregate, _SalesAggregate, _ReturnAggregate],
        actual_profit: Decimal,
        wb_current: _WbDailyReportAggregate,
        wb_previous: _WbDailyReportAggregate,
    ) -> list[KpiMetric]:
        current_orders, current_sales, current_returns = current
        previous_orders, previous_sales, previous_returns = previous
        return [
            KpiMetric(
                label="Выручка",
                value=current_orders.revenue,
                suffix="₽",
                change_percent=percent_change(current_orders.revenue, previous_orders.revenue),
            ),
            KpiMetric(
                label="Заказы",
                value=current_orders.orders,
                change_percent=percent_change(
                    Decimal(current_orders.orders), Decimal(previous_orders.orders)
                ),
            ),
            KpiMetric(
                label="Продажи",
                value=current_sales.sales,
                change_percent=percent_change(
                    Decimal(current_sales.sales), Decimal(previous_sales.sales)
                ),
            ),
            KpiMetric(
                label="Плановая прибыль",
                value=current_orders.estimated_profit,
                suffix="₽",
                change_percent=percent_change(
                    current_orders.estimated_profit, previous_orders.estimated_profit
                ),
                tone="good" if current_orders.estimated_profit >= 0 else "bad",
            ),
            KpiMetric(
                label="К выплате",
                value=wb_current.payout,
                suffix="₽",
                change_percent=percent_change(wb_current.payout, wb_previous.payout),
            ),
            KpiMetric(label="Фактическая прибыль", value=actual_profit, suffix="₽"),
            KpiMetric(
                label="Возвраты",
                value=current_returns.returns,
                change_percent=percent_change(
                    Decimal(current_returns.returns), Decimal(previous_returns.returns)
                ),
                tone="bad" if current_returns.returns else "neutral",
            ),
            KpiMetric(
                label="Средняя маржа",
                value=current_orders.margin_sum,
                suffix="%",
                change_percent=percent_change(
                    current_orders.margin_sum, previous_orders.margin_sum
                ),
            ),
            KpiMetric(
                label="Убыточные заказы",
                value=current_orders.loss_orders,
                change_percent=percent_change(
                    Decimal(current_orders.loss_orders), Decimal(previous_orders.loss_orders)
                ),
                tone="bad" if current_orders.loss_orders else "neutral",
            ),
        ]


def build_dashboard_filters(
    *,
    timezone: str,
    period: str,
    marketplace: str | None,
    sale_model: str | None,
    date_from: str | None,
    date_to: str | None,
) -> DashboardFilters:
    tz = _timezone(timezone)
    today = datetime.now(tz=tz).date()
    allowed_periods = {
        "today",
        "yesterday",
        "7d",
        "30d",
        "current_month",
        "previous_month",
        "custom",
    }
    normalized_period = period if period in allowed_periods else "today"
    if normalized_period == "custom" and date_from and date_to:
        start_date = date.fromisoformat(date_from)
        end_date = date.fromisoformat(date_to)
    elif normalized_period == "yesterday":
        start_date = today - timedelta(days=1)
        end_date = start_date
    elif normalized_period == "7d":
        start_date = today - timedelta(days=6)
        end_date = today
    elif normalized_period == "30d":
        start_date = today - timedelta(days=29)
        end_date = today
    elif normalized_period == "current_month":
        start_date = today.replace(day=1)
        end_date = today
    elif normalized_period == "previous_month":
        current_month_start = today.replace(day=1)
        end_date = current_month_start - timedelta(days=1)
        start_date = end_date.replace(day=1)
    else:
        start_date = today
        end_date = today
        normalized_period = "today"
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    start = datetime.combine(start_date, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(end_date, time.max, tzinfo=tz).astimezone(UTC)
    days = (end_date - start_date).days + 1
    previous_end_date = start_date - timedelta(days=1)
    previous_start_date = previous_end_date - timedelta(days=days - 1)
    previous_from = datetime.combine(previous_start_date, time.min, tzinfo=tz).astimezone(UTC)
    previous_to = datetime.combine(previous_end_date, time.max, tzinfo=tz).astimezone(UTC)
    return DashboardFilters(
        period=normalized_period,
        marketplace=parse_marketplace(marketplace),
        sale_model=parse_sale_model(sale_model),
        timezone=timezone,
        local_date_from=start_date,
        local_date_to=end_date,
        date_from=start,
        date_to=end,
        previous_from=previous_from,
        previous_to=previous_to,
    )


def parse_marketplace(value: str | None) -> Marketplace | None:
    if not value:
        return None
    if value == "all":
        return None
    try:
        str_value = str(value).strip()
    except Exception:
        return None
    if not str_value or str_value == "all":
        return None
    try:
        return Marketplace(str_value)
    except ValueError:
        return None


def parse_sale_model(value: str | None) -> SaleModel | None:
    if not value:
        return None
    if value == "all":
        return None
    try:
        str_value = str(value).strip()
    except Exception:
        return None
    if not str_value or str_value == "all":
        return None
    for sale_model in SaleModel:
        if str_value.upper() == sale_model.name or str_value == sale_model.value:
            return sale_model
    return None


def percent_change(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        if current == 0:
            return ZERO
        return None
    return ((current - previous) / abs(previous) * Decimal("100")).quantize(Decimal("0.1"))


def is_cancelled_status(status: str | None) -> bool:
    return (status or "").lower() in {"cancelled", "canceled", "cancel"}


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Europe/Moscow")


def _apply_order_filters(query, filters: DashboardFilters):  # type: ignore[no-untyped-def]
    if filters.marketplace is not None:
        query = query.where(Order.marketplace == filters.marketplace)
    if filters.sale_model is not None:
        query = query.where(Order.sale_model == filters.sale_model)
    return query


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))
