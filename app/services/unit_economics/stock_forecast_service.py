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
    sale_model: str
    marketplace_label: str | None = None
    is_common_fbs: bool = False


class StockForecastService:
    """Forecast stockout dates and possible lost revenue from current stock and sales speed."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def forecast(self, *, user_id: int, horizon_days: int = 30) -> list[StockForecastRow]:
        latest = await self._latest_snapshots(user_id)
        product_ids = {s.product_id for s in latest if s.product_id is not None}
        products_map = await self._batch_products(product_ids)
        sales_map = await self._batch_daily_sales(user_id, latest)
        price_map = await self._batch_average_prices(user_id, latest)
        rows: list[StockForecastRow] = []
        for snapshot in latest:
            title, seller_article = self._product_title_from_map(snapshot, products_map)
            average_daily_sales = sales_map.get(snapshot.product_id, ZERO)
            if average_daily_sales <= 0 and snapshot.average_daily_sales_7d is not None:
                average_daily_sales = Decimal(snapshot.average_daily_sales_7d)
            days = calculate_days_until_stockout(snapshot.quantity, average_daily_sales)
            average_price = price_map.get(snapshot.product_id, ZERO)
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
                    sale_model=_stock_sale_model(snapshot),
                )
            )
        merged_rows = _merge_common_fbs(rows)
        return sorted(
            merged_rows,
            key=lambda row: (row.days_until_stockout is None, row.days_until_stockout or 999999),
        )

    async def _batch_products(self, product_ids: set[int]) -> dict[int, Product]:
        if not product_ids:
            return {}
        result = await self.session.execute(select(Product).where(Product.id.in_(product_ids)))
        return {p.id: p for p in result.scalars().all()}

    async def _batch_daily_sales(
        self,
        user_id: int,
        snapshots: list[StockSnapshot],
    ) -> dict[int | None, Decimal]:
        product_ids = [s.product_id for s in snapshots if s.product_id is not None]
        if not product_ids:
            return {}
        since = datetime.now(tz=UTC) - timedelta(days=30)
        result = await self.session.execute(
            select(
                SalesEvent.product_id,
                func.coalesce(func.sum(SalesEvent.quantity), 0),
            )
            .where(SalesEvent.user_id == user_id)
            .where(SalesEvent.product_id.in_(product_ids))
            .where(SalesEvent.event_date >= since)
            .group_by(SalesEvent.product_id)
        )
        return {pid: Decimal(total) / Decimal("30") for pid, total in result.all()}

    async def _batch_average_prices(
        self,
        user_id: int,
        snapshots: list[StockSnapshot],
    ) -> dict[int | None, Decimal]:
        product_ids = [s.product_id for s in snapshots if s.product_id is not None]
        if not product_ids:
            return {}
        since = datetime.now(tz=UTC) - timedelta(days=30)
        result = await self.session.execute(
            select(
                OrderItem.product_id,
                func.avg(OrderItem.discounted_price),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.user_id == user_id)
            .where(OrderItem.product_id.in_(product_ids))
            .where(Order.order_date >= since)
            .group_by(OrderItem.product_id)
        )
        return {pid: _money(avg) for pid, avg in result.all()}

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

    def _product_title_from_map(
        self, snapshot: StockSnapshot, products_map: dict[int, Product]
    ) -> tuple[str, str]:
        if snapshot.product_id is None:
            return "Товар не сопоставлен", "н/д"
        product = products_map.get(snapshot.product_id)
        if product is None:
            return "Товар не найден", "н/д"
        return product.title or "Без названия", product.seller_article or "н/д"


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


def stock_status_label(status: str) -> str:
    return {
        "out_of_stock": "Нет в наличии",
        "critical": "Критически низкий",
        "warning": "Низкий остаток",
        "unknown": "Недостаточно данных",
        "ok": "Норма",
    }.get(status, status)


def stock_status_tone(status: str) -> str:
    return {
        "out_of_stock": "bad",
        "critical": "bad",
        "warning": "warn",
        "unknown": "neutral",
        "ok": "good",
    }.get(status, "neutral")


def _stock_sale_model(snapshot: StockSnapshot) -> str:
    raw = snapshot.raw_payload or {}
    source = str(raw.get("stock_source") or "").upper()
    warehouse = (snapshot.warehouse or "").upper()
    if "FBS" in source or "FBS" in warehouse or "SELLER" in source:
        return "FBS"
    if "FBO" in source or "FBO" in warehouse:
        return "FBO"
    if snapshot.marketplace == Marketplace.OZON and "WAREHOUSE" in source:
        return "FBS"
    return "FBO"


def _merge_common_fbs(rows: list[StockForecastRow]) -> list[StockForecastRow]:
    fbs_groups: dict[str, list[StockForecastRow]] = {}
    others: list[StockForecastRow] = []
    for row in rows:
        if row.sale_model == "FBS" and row.seller_article != "н/д":
            fbs_groups.setdefault(row.seller_article.lower(), []).append(row)
        else:
            others.append(row)

    merged: list[StockForecastRow] = []
    for group in fbs_groups.values():
        marketplaces = {row.marketplace for row in group}
        if len(group) < 2 or len(marketplaces) < 2:
            merged.extend(group)
            continue
        first = group[0]
        quantity = max(row.quantity for row in group)
        average_daily_sales = sum((row.average_daily_sales for row in group), ZERO)
        days = calculate_days_until_stockout(quantity, average_daily_sales)
        status, recommendation = classify_stock_risk(quantity, days)
        merged.append(
            StockForecastRow(
                product_id=first.product_id,
                title=first.title,
                seller_article=first.seller_article,
                marketplace=first.marketplace,
                warehouse="Общий склад продавца",
                quantity=quantity,
                average_daily_sales=average_daily_sales.quantize(Decimal("0.01")),
                days_until_stockout=days,
                lost_revenue_30d=sum((row.lost_revenue_30d for row in group), ZERO),
                status=status,
                recommendation=f"Общий FBS-остаток для WB и Ozon. {recommendation}",
                sale_model="FBS",
                marketplace_label="WB + Ozon",
                is_common_fbs=True,
            )
        )
    return others + merged


def _money(value: Decimal | int | float | None) -> Decimal:
    return Decimal(value or 0).quantize(MONEY, rounding=ROUND_HALF_UP)
