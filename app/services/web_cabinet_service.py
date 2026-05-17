"""version: 1.1.0
description: Web cabinet account, subscription, costs, prices, sales, returns, and control data.
updated: 2026-05-17
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    AlertEvent,
    MarketplaceAccount,
    Order,
    OrderItem,
    OzonPriceSnapshot,
    Product,
    ProductCostHistory,
    ReturnsEvent,
    SalesEvent,
    StockSnapshot,
    SyncJob,
)
from app.models.enums import Marketplace, SubscriptionStatus
from app.models.subscriptions import Payment, SubscriptionTier, UserSubscription
from app.services.data_quality_service import DataQualityReport, DataQualityService
from app.services.subscription_service import SubscriptionService
from app.services.web_dashboard_service import DashboardFilters, build_dashboard_filters

ZERO = Decimal("0")


@dataclass(slots=True)
class SalesRow:
    event_date: datetime
    marketplace: Marketplace
    event_type: str
    seller_article: str
    marketplace_article: str
    quantity: int
    amount: Decimal
    expected_payout: Decimal | None
    estimated_profit: Decimal | None
    actual_profit: Decimal | None
    order_external_id: str | None


@dataclass(slots=True)
class SalesPageData:
    filters: DashboardFilters
    rows: list[SalesRow]
    total_quantity: int
    total_amount: Decimal
    total_profit: Decimal


@dataclass(slots=True)
class ReturnRow:
    event_date: datetime
    marketplace: Marketplace
    order_external_id: str | None
    quantity: int
    amount: Decimal
    reason: str


@dataclass(slots=True)
class ReturnsPageData:
    filters: DashboardFilters
    rows: list[ReturnRow]
    total_quantity: int
    total_amount: Decimal


@dataclass(slots=True)
class AccountRow:
    account: MarketplaceAccount
    products_count: int
    orders_30d: int
    latest_job_status: str | None
    latest_job_error: str | None


@dataclass(slots=True)
class AccountsPageData:
    tier: SubscriptionTier
    active_accounts: int
    rows: list[AccountRow]


@dataclass(slots=True)
class CostRow:
    product: Product
    account_name: str
    cost: ProductCostHistory | None
    stock_quantity: int
    orders_count: int


@dataclass(slots=True)
class CostsPageData:
    rows: list[CostRow]
    missing_count: int
    configured_count: int


@dataclass(slots=True)
class ProductCostDetail:
    product: Product
    account_name: str
    history: list[ProductCostHistory]
    latest_ozon_price: OzonPriceSnapshot | None = None


@dataclass(slots=True)
class SubscriptionPageData:
    tier: SubscriptionTier
    active_subscription: UserSubscription | None
    payments: list[Payment]
    used_accounts: int
    used_orders_month: int
    used_products: int


@dataclass(slots=True)
class ControlPageData:
    report: DataQualityReport
    error_accounts: list[MarketplaceAccount]
    open_alerts: list[AlertEvent]
    preliminary_orders: int
    missing_cost_products: int
    low_stock_products: int


class WebCabinetService:
    """Collect read models for server-rendered web cabinet pages."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def sales_page(
        self,
        *,
        user_id: int,
        timezone: str,
        period: str,
        marketplace: str | None,
        sku: str,
        date_from: str | None,
        date_to: str | None,
    ) -> SalesPageData:
        filters = build_dashboard_filters(
            timezone=timezone,
            period=period,
            marketplace=marketplace,
            sale_model="all",
            date_from=date_from,
            date_to=date_to,
        )
        query = (
            select(SalesEvent)
            .where(SalesEvent.user_id == user_id)
            .where(SalesEvent.event_date >= filters.date_from)
            .where(SalesEvent.event_date <= filters.date_to)
            .order_by(SalesEvent.event_date.desc())
            .limit(100)
        )
        if filters.marketplace is not None:
            query = query.where(SalesEvent.marketplace == filters.marketplace)
        if sku.strip():
            pattern = f"%{sku.strip()}%"
            query = query.where(
                (SalesEvent.seller_article.ilike(pattern))
                | (SalesEvent.marketplace_article.ilike(pattern))
            )
        result = await self.session.execute(query)
        rows = [
            SalesRow(
                event_date=event.event_date,
                marketplace=event.marketplace,
                event_type=event.event_type.value,
                seller_article=event.seller_article or "н/д",
                marketplace_article=event.marketplace_article or "н/д",
                quantity=int(event.quantity or 0),
                amount=_decimal(event.amount),
                expected_payout=event.expected_payout,
                estimated_profit=event.estimated_profit,
                actual_profit=event.actual_profit,
                order_external_id=event.order_external_id,
            )
            for event in result.scalars().all()
        ]
        return SalesPageData(
            filters=filters,
            rows=rows,
            total_quantity=sum(row.quantity for row in rows),
            total_amount=sum((row.amount for row in rows), ZERO),
            total_profit=sum((_decimal(row.estimated_profit) for row in rows), ZERO),
        )

    async def returns_page(
        self,
        *,
        user_id: int,
        timezone: str,
        period: str,
        marketplace: str | None,
        sku: str,
        date_from: str | None,
        date_to: str | None,
    ) -> ReturnsPageData:
        filters = build_dashboard_filters(
            timezone=timezone,
            period=period,
            marketplace=marketplace,
            sale_model="all",
            date_from=date_from,
            date_to=date_to,
        )
        query = (
            select(ReturnsEvent)
            .where(ReturnsEvent.user_id == user_id)
            .where(ReturnsEvent.event_date >= filters.date_from)
            .where(ReturnsEvent.event_date <= filters.date_to)
            .order_by(ReturnsEvent.event_date.desc())
            .limit(100)
        )
        if filters.marketplace is not None:
            query = query.where(ReturnsEvent.marketplace == filters.marketplace)
        if sku.strip():
            pattern = f"%{sku.strip()}%"
            query = query.where(ReturnsEvent.order_external_id.ilike(pattern))
        result = await self.session.execute(query)
        rows = [
            ReturnRow(
                event_date=event.event_date,
                marketplace=event.marketplace,
                order_external_id=event.order_external_id,
                quantity=int(event.quantity or 0),
                amount=_decimal(event.amount),
                reason=event.reason or "Причина не передана маркетплейсом",
            )
            for event in result.scalars().all()
        ]
        return ReturnsPageData(
            filters=filters,
            rows=rows,
            total_quantity=sum(row.quantity for row in rows),
            total_amount=sum((row.amount for row in rows), ZERO),
        )

    async def accounts_page(self, user_id: int) -> AccountsPageData:
        tier = await SubscriptionService(self.session).get_user_tier(user_id)
        result = await self.session.execute(
            select(MarketplaceAccount)
            .where(MarketplaceAccount.user_id == user_id)
            .order_by(MarketplaceAccount.is_active.desc(), MarketplaceAccount.marketplace)
        )
        rows = []
        for account in result.scalars().all():
            products = await self._count(Product.id, Product.marketplace_account_id == account.id)
            orders = await self._count_recent_orders(account.id)
            job_result = await self.session.execute(
                select(SyncJob)
                .where(SyncJob.marketplace_account_id == account.id)
                .order_by(SyncJob.created_at.desc())
                .limit(1)
            )
            job = job_result.scalar_one_or_none()
            rows.append(
                AccountRow(
                    account=account,
                    products_count=products,
                    orders_30d=orders,
                    latest_job_status=job.status.value if job else None,
                    latest_job_error=job.error_message if job else None,
                )
            )
        return AccountsPageData(
            tier=tier,
            active_accounts=sum(1 for row in rows if row.account.is_active),
            rows=rows,
        )

    async def costs_page(self, user_id: int) -> CostsPageData:
        result = await self.session.execute(
            select(Product, MarketplaceAccount.name)
            .join(MarketplaceAccount, MarketplaceAccount.id == Product.marketplace_account_id)
            .where(Product.user_id == user_id)
            .where(Product.is_active.is_(True))
            .order_by(Product.marketplace, Product.seller_article)
            .limit(200)
        )
        rows = []
        for product, account_name in result.all():
            cost = await self._latest_cost(product.id)
            rows.append(
                CostRow(
                    product=product,
                    account_name=str(account_name),
                    cost=cost,
                    stock_quantity=await self._latest_stock(product.id),
                    orders_count=await self._count(
                        OrderItem.id,
                        OrderItem.product_id == product.id,
                    ),
                )
            )
        missing = sum(1 for row in rows if row.cost is None or row.cost.cost_price <= 0)
        return CostsPageData(
            rows=rows,
            missing_count=missing,
            configured_count=len(rows) - missing,
        )

    async def product_cost_detail(
        self,
        *,
        user_id: int,
        product_id: int,
    ) -> ProductCostDetail | None:
        result = await self.session.execute(
            select(Product, MarketplaceAccount.name)
            .join(MarketplaceAccount, MarketplaceAccount.id == Product.marketplace_account_id)
            .where(Product.user_id == user_id)
            .where(Product.id == product_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        product, account_name = row
        history = await self.session.execute(
            select(ProductCostHistory)
            .where(ProductCostHistory.product_id == product.id)
            .order_by(ProductCostHistory.valid_from.desc())
        )
        latest_price = None
        if product.marketplace == Marketplace.OZON:
            price_result = await self.session.execute(
                select(OzonPriceSnapshot)
                .where(OzonPriceSnapshot.product_id == product.id)
                .order_by(OzonPriceSnapshot.synced_at.desc())
                .limit(1)
            )
            latest_price = price_result.scalar_one_or_none()
        return ProductCostDetail(
            product=product,
            account_name=str(account_name),
            history=list(history.scalars().all()),
            latest_ozon_price=latest_price,
        )

    async def subscription_page(self, user_id: int) -> SubscriptionPageData:
        service = SubscriptionService(self.session)
        tier = await service.get_user_tier(user_id)
        active_subscription = await service.get_active_subscription(user_id)
        payments = await self.session.execute(
            select(Payment).where(Payment.user_id == user_id).order_by(Payment.created_at.desc())
        )
        month_start = datetime.now(tz=UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return SubscriptionPageData(
            tier=tier,
            active_subscription=active_subscription,
            payments=list(payments.scalars().all())[:20],
            used_accounts=await self._count(
                MarketplaceAccount.id,
                MarketplaceAccount.user_id == user_id,
                MarketplaceAccount.is_active.is_(True),
            ),
            used_orders_month=await self._count(
                Order.id,
                Order.user_id == user_id,
                Order.order_date >= month_start,
            ),
            used_products=await self._count(Product.id, Product.user_id == user_id),
        )

    async def control_page(self, user_id: int) -> ControlPageData:
        report = await DataQualityService(self.session).report(user_id=user_id)
        error_accounts = await self.session.execute(
            select(MarketplaceAccount)
            .where(MarketplaceAccount.user_id == user_id)
            .where(MarketplaceAccount.last_error_message.is_not(None))
            .order_by(MarketplaceAccount.last_error_at.desc())
            .limit(10)
        )
        alerts = await self.session.execute(
            select(AlertEvent)
            .where(AlertEvent.user_id == user_id)
            .where(AlertEvent.resolved_at.is_(None))
            .order_by(AlertEvent.created_at.desc())
            .limit(10)
        )
        return ControlPageData(
            report=report,
            error_accounts=list(error_accounts.scalars().all()),
            open_alerts=list(alerts.scalars().all()),
            preliminary_orders=await self._count(
                OrderItem.id,
                OrderItem.economy_confidence == "PRELIMINARY",
                OrderItem.order_id.in_(select(Order.id).where(Order.user_id == user_id)),
            ),
            missing_cost_products=await self._missing_cost_products(user_id),
            low_stock_products=await self._low_stock_products(user_id),
        )

    async def _count(self, column, *conditions) -> int:  # type: ignore[no-untyped-def]
        query = select(func.count(column))
        for condition in conditions:
            query = query.where(condition)
        result = await self.session.execute(query)
        return int(result.scalar_one() or 0)

    async def _count_recent_orders(self, account_id: int) -> int:
        since = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self.session.execute(
            select(func.count(Order.id))
            .where(Order.marketplace_account_id == account_id)
            .where(Order.order_date >= since)
        )
        return int(result.scalar_one() or 0)

    async def _latest_cost(self, product_id: int) -> ProductCostHistory | None:
        result = await self.session.execute(
            select(ProductCostHistory)
            .where(ProductCostHistory.product_id == product_id)
            .order_by(ProductCostHistory.valid_from.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _latest_stock(self, product_id: int) -> int:
        result = await self.session.execute(
            select(StockSnapshot.quantity)
            .where(StockSnapshot.product_id == product_id)
            .order_by(StockSnapshot.snapshot_at.desc())
            .limit(1)
        )
        return int(result.scalar_one_or_none() or 0)

    async def _missing_cost_products(self, user_id: int) -> int:
        products = await self.session.execute(
            select(Product.id).where(Product.user_id == user_id).where(Product.is_active.is_(True))
        )
        count = 0
        for product_id in products.scalars().all():
            cost = await self._latest_cost(product_id)
            if cost is None or cost.cost_price <= 0:
                count += 1
        return count

    async def _low_stock_products(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count(StockSnapshot.id))
            .where(StockSnapshot.user_id == user_id)
            .where(StockSnapshot.quantity <= 3)
        )
        return int(result.scalar_one() or 0)


def subscription_status(active_subscription: UserSubscription | None) -> str:
    if active_subscription is None:
        return "FREE"
    if active_subscription.is_trial or active_subscription.status == SubscriptionStatus.TRIAL:
        return "TRIAL"
    return active_subscription.status.value


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))
