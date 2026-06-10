"""version: 1.2.0
description: Web cabinet account, subscription, costs, prices, sales, returns, and control data.
updated: 2026-06-08
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    AccountBalanceSnapshot,
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
    WbDailyReportImport,
    WbDailyReportRow,
    WbFinancialReport,
    WbReportCheckState,
    WbReportFinanceComponent,
)
from app.models.enums import Marketplace, SubscriptionStatus
from app.models.subscriptions import Payment, SubscriptionTier, UserSubscription
from app.services.common.data_quality_service import DataQualityReport, DataQualityService
from app.services.subscriptions.subscription_service import SubscriptionService
from app.services.common.web_dashboard_service import DashboardFilters, build_dashboard_filters
from app.utils.datetime import get_user_timezone, user_day_bounds_utc

ZERO = Decimal("0")


@dataclass(slots=True)
class SalesRow:
    event_date: datetime
    marketplace: Marketplace
    event_type: str
    sale_model: str | None
    seller_article: str
    marketplace_article: str
    product_name: str | None
    barcode: str | None
    nm_id: int | None
    quantity: int
    amount: Decimal
    expected_payout: Decimal | None
    estimated_profit: Decimal | None
    actual_profit: Decimal | None
    fact_status: str
    fact_status_label: str
    order_external_id: str | None
    order_id: int | None
    wb_report_number: str | None
    wb_report_type: str | None
    wb_report_import_id: int | None
    wb_components: dict[str, Decimal] | None


@dataclass(slots=True)
class SalesPageData:
    filters: DashboardFilters
    rows: list[SalesRow]
    total_quantity: int
    total_amount: Decimal
    total_profit: Decimal
    total_actual_profit: Decimal
    full_fact_count: int
    partial_fact_count: int
    pending_fact_count: int
    no_report_count: int


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
    latest_balance: AccountBalanceSnapshot | None = None
    latest_daily_report: WbFinancialReport | None = None
    latest_weekly_report: WbFinancialReport | None = None
    report_states: list[WbReportCheckState] | None = None


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


@dataclass(slots=True)
class SyncCenterAccountData:
    account: MarketplaceAccount
    products_count: int
    orders_30d: int
    balance: AccountBalanceSnapshot | None = None

    @property
    def sync_freshness_orders(self) -> str:
        return self._freshness(self.account.last_order_poll_at, 30)

    @property
    def sync_freshness_sales(self) -> str:
        return self._freshness(self.account.last_sales_sync_at, 60)

    @property
    def sync_freshness_stocks(self) -> str:
        return self._freshness(self.account.last_stocks_sync_at, 24 * 60)

    @property
    def sync_freshness_products(self) -> str:
        return self._freshness(self.account.last_products_sync_at, 48 * 60)

    @property
    def sync_freshness_profile(self) -> str:
        return self._freshness(self.account.last_profile_sync_at, 48 * 60)

    @property
    def sync_freshness_wb_reports(self) -> str:
        return self._freshness(self.account.last_wb_reports_sync_at, 24 * 60)

    @property
    def sync_freshness_ozon_finance(self) -> str:
        return self._freshness(self.account.last_ozon_finance_sync_at, 24 * 60)

    @property
    def total_syncs_today(self) -> int:
        count = 0
        for attr in ("last_order_poll_at", "last_sales_sync_at", "last_stocks_sync_at",
                     "last_products_sync_at", "last_profile_sync_at", "last_wb_reports_sync_at",
                     "last_ozon_finance_sync_at"):
            val = getattr(self.account, attr, None)
            if val and val.date() == datetime.now(val.tzinfo or UTC).date():
                count += 1
        return count

    @staticmethod
    def _freshness(dt: datetime | None, threshold_minutes: int) -> str:
        if dt is None:
            return "none"
        ago = (datetime.now(UTC) - dt).total_seconds() / 60
        if ago <= threshold_minutes:
            return "good"
        if ago <= threshold_minutes * 3:
            return "warn"
        return "bad"


@dataclass(slots=True)
class SyncCenterPageData:
    accounts: list[SyncCenterAccountData]
    total_accounts: int
    healthy_accounts: int
    error_accounts_count: int
    stale_accounts: int
    total_products: int
    total_orders_30d: int
    data_quality_score: int | None


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
        events = list(result.scalars().all())

        order_ids = [e.related_order_id for e in events if e.related_order_id]
        product_ids = [e.product_id for e in events if e.product_id]
        orders_map: dict[int, Order] = {}
        products_map: dict[int, Product] = {}

        if order_ids:
            orders_result = await self.session.execute(
                select(Order).where(Order.id.in_(order_ids))
            )
            orders_map = {o.id: o for o in orders_result.scalars().all()}

        if product_ids:
            products_result = await self.session.execute(
                select(Product).where(Product.id.in_(product_ids))
            )
            products_map = {p.id: p for p in products_result.scalars().all()}

        order_id_set = list(orders_map.keys())
        report_rows_map: dict[int, list[WbDailyReportRow]] = {}
        components_map: dict[int, list[WbReportFinanceComponent]] = {}

        if order_id_set:
            rows_result = await self.session.execute(
                select(WbDailyReportRow)
                .where(WbDailyReportRow.order_id.in_(order_id_set))
                .where(WbDailyReportRow.is_active.is_(True))
                .where(WbDailyReportRow.deleted_at.is_(None))
            )
            for rr in rows_result.scalars().all():
                oid = rr.order_id
                if oid is not None:
                    report_rows_map.setdefault(oid, []).append(rr)

            for oid, rrs in report_rows_map.items():
                rids = [r.id for r in rrs]
                comps_result = await self.session.execute(
                    select(WbReportFinanceComponent)
                    .where(WbReportFinanceComponent.report_row_id.in_(rids))
                    .where(WbReportFinanceComponent.is_active.is_(True))
                )
                for comp in comps_result.scalars().all():
                    components_map.setdefault(oid, []).append(comp)

        report_import_ids = set()
        for rr_list in report_rows_map.values():
            for rr in rr_list:
                if rr.import_id:
                    report_import_ids.add(rr.import_id)
        imports_map: dict[int, WbDailyReportImport] = {}
        if report_import_ids:
            imp_result = await self.session.execute(
                select(WbDailyReportImport).where(
                    WbDailyReportImport.id.in_(list(report_import_ids))
                ).where(WbDailyReportImport.deleted_at.is_(None))
            )
            imports_map = {imp.id: imp for imp in imp_result.scalars().all()}

        FINANCE_REVENUE = "Реализация товаров"
        FINANCE_WB_COMMISSION = "Вознаграждение WB"
        FINANCE_WB_COMMISSION_VAT = "НДС вознаграждения WB"
        FINANCE_LOGISTICS = "Логистика"
        FINANCE_STORAGE = "Хранение"
        FINANCE_DEDUCTION = "Удержания"
        FINANCE_PENALTY = "Штрафы"
        FINANCE_PAID_ACCEPTANCE = "Платная приемка"
        FINANCE_COMPENSATION = "Компенсации"
        FINANCE_PAYMENT_SERVICES = "Платежные услуги"
        FINANCE_LOYALTY = "Программа лояльности"

        FACT_CATEGORIES = {
            FINANCE_REVENUE,
            FINANCE_WB_COMMISSION,
            FINANCE_WB_COMMISSION_VAT,
            FINANCE_LOGISTICS,
            FINANCE_STORAGE,
            FINANCE_DEDUCTION,
            FINANCE_PENALTY,
            FINANCE_PAID_ACCEPTANCE,
            FINANCE_COMPENSATION,
            FINANCE_PAYMENT_SERVICES,
            FINANCE_LOYALTY,
        }

        rows: list[SalesRow] = []
        for event in events:
            order = orders_map.get(event.related_order_id) if event.related_order_id else None
            product = products_map.get(event.product_id) if event.product_id else None

            report_rows_for_order = report_rows_map.get(event.related_order_id, []) if event.related_order_id else []
            comps_for_order = components_map.get(event.related_order_id, []) if event.related_order_id else []

            wb_components: dict[str, Decimal] = {}
            for comp in comps_for_order:
                cat = comp.finance_category
                wb_components[cat] = wb_components.get(cat, ZERO) + comp.normalized_amount

            has_report = len(report_rows_for_order) > 0
            has_all_categories = all(cat in wb_components for cat in FACT_CATEGORIES)
            has_any_components = bool(wb_components)

            if not has_report:
                fact_status = "no_report"
                fact_status_label = "Отчёт не загружен"
            elif not has_any_components:
                fact_status = "pending_link"
                fact_status_label = "Ожидает привязки"
            elif has_all_categories:
                fact_status = "full"
                fact_status_label = "Факт полный"
            else:
                fact_status = "partial"
                fact_status_label = "Факт частичный"

            actual_fact_profit = None
            if has_any_components:
                revenue = wb_components.get(FINANCE_REVENUE, ZERO)
                wb_comm = wb_components.get(FINANCE_WB_COMMISSION, ZERO)
                wb_comm_vat = wb_components.get(FINANCE_WB_COMMISSION_VAT, ZERO)
                logistics = wb_components.get(FINANCE_LOGISTICS, ZERO)
                storage = wb_components.get(FINANCE_STORAGE, ZERO)
                deduction = wb_components.get(FINANCE_DEDUCTION, ZERO)
                penalty = wb_components.get(FINANCE_PENALTY, ZERO)
                paid_acc = wb_components.get(FINANCE_PAID_ACCEPTANCE, ZERO)
                compensation = wb_components.get(FINANCE_COMPENSATION, ZERO)
                payment_svc = wb_components.get(FINANCE_PAYMENT_SERVICES, ZERO)
                loyalty = wb_components.get(FINANCE_LOYALTY, ZERO)

                actual_fact_profit = (
                    revenue - wb_comm - wb_comm_vat - logistics - storage
                    - deduction - penalty - paid_acc - payment_svc - loyalty
                    + compensation
                )

            wb_report_number = None
            wb_report_type = None
            wb_report_import_id = None
            if report_rows_for_order:
                first_rr = report_rows_for_order[0]
                wb_report_number = first_rr.report_number
                wb_report_type = first_rr.report_type
                imp = imports_map.get(first_rr.import_id)
                if imp:
                    wb_report_import_id = imp.id

            barcode = product.barcode if product else None
            nm_id = None
            if product:
                if product.marketplace_article and product.marketplace_article.isdigit():
                    nm_id = int(product.marketplace_article)
                elif product.external_product_id and product.external_product_id.isdigit():
                    nm_id = int(product.external_product_id)
            if barcode is None and report_rows_for_order:
                barcode = report_rows_for_order[0].barcode

            sale_model_str = order.sale_model.value if order and order.sale_model else None

            rows.append(
                SalesRow(
                    event_date=event.event_date,
                    marketplace=event.marketplace,
                    event_type=event.event_type.value,
                    sale_model=sale_model_str,
                    seller_article=event.seller_article or "н/д",
                    marketplace_article=event.marketplace_article or "н/д",
                    product_name=product.title if product else None,
                    barcode=barcode,
                    nm_id=nm_id,
                    quantity=int(event.quantity or 0),
                    amount=_decimal(event.amount),
                    expected_payout=event.expected_payout,
                    estimated_profit=event.estimated_profit,
                    actual_profit=actual_fact_profit,
                    fact_status=fact_status,
                    fact_status_label=fact_status_label,
                    order_external_id=(
                        order.order_external_id if order else event.order_external_id
                    ),
                    order_id=event.related_order_id,
                    wb_report_number=wb_report_number,
                    wb_report_type=wb_report_type,
                    wb_report_import_id=wb_report_import_id,
                    wb_components=wb_components if wb_components else None,
                )
            )

        total_quantity = sum(row.quantity for row in rows)
        total_amount = sum((row.amount for row in rows), ZERO)
        total_plan_profit = sum((_decimal(row.estimated_profit) for row in rows), ZERO)
        total_actual_profit = sum((_decimal(row.actual_profit) for row in rows), ZERO)
        full_fact_count = sum(1 for r in rows if r.fact_status == "full")
        partial_fact_count = sum(1 for r in rows if r.fact_status == "partial")
        pending_fact_count = sum(1 for r in rows if r.fact_status == "pending_link")
        no_report_count = sum(1 for r in rows if r.fact_status == "no_report")

        return SalesPageData(
            filters=filters,
            rows=rows,
            total_quantity=total_quantity,
            total_amount=total_amount,
            total_profit=total_plan_profit,
            total_actual_profit=total_actual_profit,
            full_fact_count=full_fact_count,
            partial_fact_count=partial_fact_count,
            pending_fact_count=pending_fact_count,
            no_report_count=no_report_count,
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

    async def accounts_page(
        self, user_id: int, timezone: str = "Europe/Moscow"
    ) -> AccountsPageData:
        tier = await SubscriptionService(self.session).get_user_tier(user_id)
        result = await self.session.execute(
            select(MarketplaceAccount)
            .where(MarketplaceAccount.user_id == user_id)
            .order_by(MarketplaceAccount.is_active.desc(), MarketplaceAccount.marketplace)
        )
        rows = []
        for account in result.scalars().all():
            products = await self._count(Product.id, Product.marketplace_account_id == account.id)
            orders = await self._count_recent_orders(account.id, timezone)
            job_result = await self.session.execute(
                select(SyncJob)
                .where(SyncJob.marketplace_account_id == account.id)
                .order_by(SyncJob.created_at.desc())
                .limit(1)
            )
            job = job_result.scalar_one_or_none()
            balance_result = await self.session.execute(
                select(AccountBalanceSnapshot)
                .where(AccountBalanceSnapshot.marketplace_account_id == account.id)
                .order_by(AccountBalanceSnapshot.fetched_at.desc())
                .limit(1)
            )
            daily_report = await self._latest_wb_report(account.id, "daily")
            weekly_report = await self._latest_wb_report(account.id, "weekly")
            states_result = await self.session.execute(
                select(WbReportCheckState).where(
                    WbReportCheckState.marketplace_account_id == account.id
                )
            )
            rows.append(
                AccountRow(
                    account=account,
                    products_count=products,
                    orders_30d=orders,
                    latest_job_status=job.status.value if job else None,
                    latest_job_error=job.error_message if job else None,
                    latest_balance=balance_result.scalar_one_or_none(),
                    latest_daily_report=daily_report,
                    latest_weekly_report=weekly_report,
                    report_states=list(states_result.scalars().all()),
                )
            )
        return AccountsPageData(
            tier=tier,
            active_accounts=sum(1 for row in rows if row.account.is_active),
            rows=rows,
        )

    async def sync_center_page(
        self, user_id: int, timezone: str = "Europe/Moscow"
    ) -> SyncCenterPageData:
        result = await self.session.execute(
            select(MarketplaceAccount)
            .where(MarketplaceAccount.user_id == user_id)
            .order_by(MarketplaceAccount.is_active.desc(), MarketplaceAccount.marketplace)
        )
        accounts_raw = result.scalars().all()
        account_data_list: list[SyncCenterAccountData] = []
        total_products = 0
        total_orders = 0
        error_count = 0
        stale_count = 0
        for account in accounts_raw:
            products = await self._count(Product.id, Product.marketplace_account_id == account.id)
            orders = await self._count_recent_orders(account.id, timezone)
            balance_result = await self.session.execute(
                select(AccountBalanceSnapshot)
                .where(AccountBalanceSnapshot.marketplace_account_id == account.id)
                .order_by(AccountBalanceSnapshot.fetched_at.desc())
                .limit(1)
            )
            acc_data = SyncCenterAccountData(
                account=account,
                products_count=products,
                orders_30d=orders,
                balance=balance_result.scalar_one_or_none(),
            )
            account_data_list.append(acc_data)
            total_products += products
            total_orders += orders
            if account.status.value == "ERROR" or (
                account.last_error_message
                and not _is_resolved_greenlet_error(account.last_error_message)
            ):
                error_count += 1
            any_stale = any(
                getattr(acc_data, attr, "none") in ("bad", "none")
                for attr in (
                    "sync_freshness_orders", "sync_freshness_sales",
                    "sync_freshness_stocks", "sync_freshness_products",
                    "sync_freshness_profile",
                )
            )
            if any_stale:
                stale_count += 1
        dq_report = await DataQualityService(self.session).report(user_id=user_id)
        healthy = len(accounts_raw) - error_count
        return SyncCenterPageData(
            accounts=account_data_list,
            total_accounts=len(accounts_raw),
            healthy_accounts=healthy,
            error_accounts_count=error_count,
            stale_accounts=stale_count,
            total_products=total_products,
            total_orders_30d=total_orders,
            data_quality_score=dq_report.score,
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
        product_rows = result.all()
        product_ids = [p.id for p, _ in product_rows]

        costs_map = await self._batch_latest_costs(product_ids)
        stock_map = await self._batch_latest_stocks(product_ids)
        orders_map = await self._batch_order_counts(product_ids)

        rows = []
        for product, account_name in product_rows:
            cost = costs_map.get(product.id)
            rows.append(
                CostRow(
                    product=product,
                    account_name=str(account_name),
                    cost=cost,
                    stock_quantity=stock_map.get(product.id, 0),
                    orders_count=orders_map.get(product.id, 0),
                )
            )
        missing = sum(1 for row in rows if row.cost is None or row.cost.cost_price <= 0)
        return CostsPageData(
            rows=rows,
            missing_count=missing,
            configured_count=len(rows) - missing,
        )

    async def _batch_latest_costs(self, product_ids: list[int]) -> dict[int, ProductCostHistory]:
        if not product_ids:
            return {}
        subq = (
            select(
                ProductCostHistory.product_id,
                func.max(ProductCostHistory.valid_from).label("max_valid_from"),
            )
            .where(ProductCostHistory.product_id.in_(product_ids))
            .group_by(ProductCostHistory.product_id)
            .subquery()
        )
        result = await self.session.execute(
            select(ProductCostHistory).join(
                subq,
                (ProductCostHistory.product_id == subq.c.product_id)
                & (ProductCostHistory.valid_from == subq.c.max_valid_from),
            )
        )
        return {c.product_id: c for c in result.scalars().all()}

    async def _batch_latest_stocks(self, product_ids: list[int]) -> dict[int, int]:
        if not product_ids:
            return {}
        subq = (
            select(
                StockSnapshot.product_id,
                func.max(StockSnapshot.snapshot_at).label("max_snapshot_at"),
            )
            .where(StockSnapshot.product_id.in_(product_ids))
            .group_by(StockSnapshot.product_id)
            .subquery()
        )
        result = await self.session.execute(
            select(StockSnapshot.product_id, StockSnapshot.quantity).join(
                subq,
                (StockSnapshot.product_id == subq.c.product_id)
                & (StockSnapshot.snapshot_at == subq.c.max_snapshot_at),
            )
        )
        return {
            product_id: quantity for product_id, quantity in result.all() if product_id is not None
        }

    async def _batch_order_counts(self, product_ids: list[int]) -> dict[int, int]:
        if not product_ids:
            return {}
        result = await self.session.execute(
            select(OrderItem.product_id, func.count(OrderItem.id))
            .where(OrderItem.product_id.in_(product_ids))
            .group_by(OrderItem.product_id)
        )
        return {product_id: count for product_id, count in result.all() if product_id is not None}

    async def _latest_wb_report(
        self,
        account_id: int,
        period_type: str,
    ) -> WbFinancialReport | None:
        result = await self.session.execute(
            select(WbFinancialReport)
            .where(WbFinancialReport.marketplace_account_id == account_id)
            .where(WbFinancialReport.period_type == period_type)
            .order_by(WbFinancialReport.date_to.desc(), WbFinancialReport.fetched_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

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

    async def subscription_page(
        self, user_id: int, timezone: str = "Europe/Moscow"
    ) -> SubscriptionPageData:
        service = SubscriptionService(self.session)
        tier = await service.get_user_tier(user_id)
        active_subscription = await service.get_active_subscription(user_id)
        payments = await self.session.execute(
            select(Payment).where(Payment.user_id == user_id).order_by(Payment.created_at.desc())
        )
        now_local = datetime.now(tz=get_user_timezone(timezone))
        month_start = user_day_bounds_utc(now_local.date().replace(day=1), timezone)[0]
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
        accounts = [
            account
            for account in error_accounts.scalars().all()
            if not _is_resolved_greenlet_error(account.last_error_message)
        ]
        return ControlPageData(
            report=report,
            error_accounts=accounts,
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

    async def _count_recent_orders(self, account_id: int, timezone: str) -> int:
        since = user_day_bounds_utc(datetime.now(tz=get_user_timezone(timezone)).date(), timezone)[
            0
        ]
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
    return str(active_subscription.status.value)


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))


def _is_resolved_greenlet_error(message: str | None) -> bool:
    return bool(message and "greenlet_spawn has not been called" in message)
