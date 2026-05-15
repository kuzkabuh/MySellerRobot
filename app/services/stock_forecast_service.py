"""version: 1.0.0
description: Stock forecast, out-of-stock risk, and lost revenue estimation service.
updated: 2026-05-15
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Order, OrderItem, Product, SalesEvent, StockSnapshot
from app.models.enums import Marketplace

MONEY = Decimal("0.01")
ZERO = Decimal("0")


@dataclass(slots=True)
class StockForecastRow:
    product_id: int | None
    title: str
    seller_article: str
    marketplace: Marketplace
    warehouse: str
    quantity: int
    average_daily_sales: Decimal
    days_until_stockout: Decimal | None
    lost_revenue_30d: Decimal
    status: str
    recommendation: str


class StockForecastService:
    """Forecast stockout dates and possible lost revenue from current stock and sales speed."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def forecast(self, *, user_id: int, horizon_days: int = 30) -> list[StockForecastRow]:
        latest = await self._latest_snapshots(user_id)
        rows: list[StockForecastRow] = []
        for snapshot in latest:
            title, seller_article = await self._product_title(snapshot)
            average_daily_sales = await self._average_daily_sales(
                user_id=user_id,
                product_id=snapshot.product_id,
                marketplace=snapshot.marketplace,
            )
            if average_daily_sales <= 0 and snapshot.average_daily_sales_7d is not None:
                average_daily_sales = Decimal(snapshot.average_daily_sales_7d)
            days = calculate_days_until_stockout(snapshot.quantity, average_daily_sales)
            average_price = await self._average_order_price(
                user_id=user_id,
                product_id=snapshot.product_id,
                marketplace=snapshot.marketplace,
            )
            lost_revenue = estimate_lost_revenue(
                days_until_stockout=days,
                horizon_days=horizon_days,
                average_daily_sales=average_daily_sales,
                average_price=average_price,
            )
            status, recommendation = classify_stock_risk(snapshot.quantity, days)
            rows.append(
                StockForecastRow(
                    product_id=snapshot.product_id,
                    title=title,
                    seller_article=seller_article,
                    marketplace=snapshot.marketplace,
                    warehouse=snapshot.warehouse or "Склад не указан",
                    quantity=snapshot.quantity,
                    average_daily_sales=average_daily_sales.quantize(Decimal("0.01")),
                    days_until_stockout=days,
                    lost_revenue_30d=lost_revenue,
                    status=status,
                    recommendation=recommendation,
                )
            )
        return sorted(
            rows,
            key=lambda row: (row.days_until_stockout is None, row.days_until_stockout or 999999),
        )

    async def _latest_snapshots(self, user_id: int) -> list[StockSnapshot]:
        result = await self.session.execute(
            select(StockSnapshot)
            .where(StockSnapshot.user_id == user_id)
            .order_by(
                StockSnapshot.product_id, StockSnapshot.warehouse, StockSnapshot.snapshot_at.desc()
            )
        )
        latest: dict[tuple[int | None, str, Marketplace], StockSnapshot] = {}
        for snapshot in result.scalars().all():
            key = (snapshot.product_id, snapshot.warehouse or "", snapshot.marketplace)
            latest.setdefault(key, snapshot)
        return list(latest.values())

    async def _product_title(self, snapshot: StockSnapshot) -> tuple[str, str]:
        if snapshot.product_id is None:
            return "Товар не сопоставлен", "н/д"
        product = await self.session.get(Product, snapshot.product_id)
        if product is None:
            return "Товар не найден", "н/д"
        return product.title or "Без названия", product.seller_article or "н/д"

    async def _average_daily_sales(
        self,
        *,
        user_id: int,
        product_id: int | None,
        marketplace: Marketplace,
    ) -> Decimal:
        if product_id is None:
            return ZERO
        since = datetime.now(tz=UTC) - timedelta(days=30)
        result = await self.session.execute(
            select(func.coalesce(func.sum(SalesEvent.quantity), 0))
            .where(SalesEvent.user_id == user_id)
            .where(SalesEvent.product_id == product_id)
            .where(SalesEvent.marketplace == marketplace)
            .where(SalesEvent.event_date >= since)
        )
        return Decimal(result.scalar_one() or 0) / Decimal("30")

    async def _average_order_price(
        self,
        *,
        user_id: int,
        product_id: int | None,
        marketplace: Marketplace,
    ) -> Decimal:
        if product_id is None:
            return ZERO
        since = datetime.now(tz=UTC) - timedelta(days=30)
        result = await self.session.execute(
            select(func.avg(OrderItem.discounted_price))
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.user_id == user_id)
            .where(Order.marketplace == marketplace)
            .where(OrderItem.product_id == product_id)
            .where(Order.order_date >= since)
        )
        return _money(result.scalar_one())


def calculate_days_until_stockout(quantity: int, average_daily_sales: Decimal) -> Decimal | None:
    if average_daily_sales <= 0:
        return None
    return (Decimal(quantity) / average_daily_sales).quantize(Decimal("0.1"))


def estimate_lost_revenue(
    *,
    days_until_stockout: Decimal | None,
    horizon_days: int,
    average_daily_sales: Decimal,
    average_price: Decimal,
) -> Decimal:
    if days_until_stockout is None or average_daily_sales <= 0 or average_price <= 0:
        return ZERO
    lost_days = Decimal(horizon_days) - days_until_stockout
    if lost_days <= 0:
        return ZERO
    return _money(lost_days * average_daily_sales * average_price)


def classify_stock_risk(quantity: int, days_until_stockout: Decimal | None) -> tuple[str, str]:
    if quantity <= 0:
        return "out_of_stock", "Товар закончился. Пополните склад как можно быстрее."
    if days_until_stockout is None:
        return "unknown", "Недостаточно продаж для прогноза. Следите за остатком вручную."
    if days_until_stockout <= 7:
        return "critical", "Критический риск out-of-stock в ближайшую неделю."
    if days_until_stockout <= 30:
        return "warning", "Запас закончится в течение 30 дней. Запланируйте пополнение."
    return "ok", "Запас выглядит достаточным на ближайший месяц."


def _money(value: Decimal | int | float | None) -> Decimal:
    return Decimal(value or 0).quantize(MONEY, rounding=ROUND_HALF_UP)
