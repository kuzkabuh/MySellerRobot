"""version: 1.3.0
description: Web cabinet order list, order detail, and SKU profit queries with reconciliation status, commission/logistics breakdown, actual margin.
updated: 2026-06-09
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, exists, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import (
    FinancialReportRow,
    Order,
    OrderItem,
    ProfitSnapshot,
    SalesEvent,
    WbDailyReportRow,
    WbReportFinanceComponent,
)
from app.models.enums import (
    CalculationType,
    EconomyConfidence,
    Marketplace,
    ReconciliationStatus,
    SaleModel,
    SourceEventType,
)
from app.services.common.marketplace_presentation import order_status_label
from app.services.common.web_dashboard_service import (
    build_dashboard_filters,
)
from app.utils.datetime import format_datetime_for_user

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
    srid: str | None
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
    reconciliation_status: ReconciliationStatus


@dataclass(slots=True)
class OrderDetailItem:
    item: OrderItem
    estimated_snapshot: ProfitSnapshot | None
    actual_snapshot: ProfitSnapshot | None


@dataclass(slots=True)
class WbFactArticleState:
    key: str
    label: str
    amount: Decimal | None
    state: str


@dataclass(slots=True)
class WbOrderFact:
    status: ReconciliationStatus
    article_states: list[WbFactArticleState]
    linked_rows: list[WbDailyReportRow]
    unlinked_product_rows: list[WbDailyReportRow]


@dataclass(slots=True)
class OzonFactArticle:
    key: str
    label: str
    amount: Decimal | None


@dataclass(slots=True)
class OzonOrderFact:
    status: ReconciliationStatus
    articles: list[OzonFactArticle]
    rows: list[FinancialReportRow]


@dataclass(slots=True)
class OrderDetail:
    order: Order
    items: list[OrderDetailItem]
    estimated_profit: Decimal
    actual_profit: Decimal | None
    deviation: Decimal | None
    reconciliation_status: ReconciliationStatus
    wb_fact: WbOrderFact | None = None
    ozon_fact: OzonOrderFact | None = None
    is_financial_only: bool = False
    has_missing_cost_price: bool = False
    economy_confidence: str = "PRELIMINARY"


@dataclass(slots=True)
class ProfitSkuRow:
    title: str
    seller_article: str
    marketplace: Marketplace
    sale_model: SaleModel | None
    orders: int
    sales: int
    revenue: Decimal
    estimated_revenue: Decimal
    actual_revenue: Decimal
    payout: Decimal
    cost: Decimal
    marketplace_costs: Decimal
    estimated_profit: Decimal
    actual_profit: Decimal
    margin_percent: Decimal
    missing_cost_items: int
    preliminary_items: int
    actual_snapshot_items: int
    roi_percent: Decimal | None = None
    actual_margin: Decimal | None = None
    avg_commission: Decimal = ZERO
    avg_logistics: Decimal = ZERO
    reconciliation_status: ReconciliationStatus = ReconciliationStatus.PRELIMINARY


@dataclass(slots=True)
class ProfitSummary:
    estimated_profit: Decimal
    actual_profit: Decimal
    deviation: Decimal
    average_unit_profit: Decimal
    average_margin: Decimal
    roi_percent: Decimal | None


@dataclass(slots=True)
class OrderPageResult:
    filters: OrderWebFilters
    rows: list[OrderRow]
    total_count: int
    page: int
    per_page: int
    total_pages: int


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
        page: int = 1,
        per_page: int = 50,
    ) -> OrderPageResult:
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
        base_query = (
            select(
                Order.id,
                OrderItem.id,
                Order.order_date,
                Order.marketplace,
                Order.sale_model,
                Order.order_external_id,
                Order.posting_number,
                Order.srid,
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
                _order_has_wb_fact_row().label("has_wb_fact"),
                _order_has_wb_missing_fact_state().label("has_wb_missing_fact"),
                _order_has_wb_match_problem().label("has_wb_match_problem"),
            )
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(Order.user_id == user_id)
            .where(Order.deleted_at.is_(None))
            .where(Order.order_date >= filters.date_from)
            .where(Order.order_date <= filters.date_to)
        )
        base_query = _apply_order_page_filters(base_query, filters)

        count_query = (
            select(func.count(func.distinct(Order.id)))
            .select_from(Order)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(Order.user_id == user_id)
            .where(Order.deleted_at.is_(None))
            .where(Order.order_date >= filters.date_from)
            .where(Order.order_date <= filters.date_to)
        )
        count_query = _apply_order_page_filters(count_query, filters, count_distinct=True)
        count_result = await self.session.execute(count_query)
        total_count = int(count_result.scalar() or 0)

        per_page = max(1, min(per_page, 200))
        page = max(1, page)
        total_pages = max(1, (total_count + per_page - 1) // per_page)
        offset = (page - 1) * per_page

        query = (
            base_query.order_by(*_apply_order_sort_query(base_query, filters))
            .limit(per_page)
            .offset(offset)
        )
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
                srid,
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
                has_wb_fact,
                has_wb_missing_fact,
                has_wb_match_problem,
            ) = row
            missing_cost = cost_price_used is None
            rows.append(
                OrderRow(
                    order_id=int(order_id),
                    item_id=int(item_id),
                    order_date=order_date,
                    marketplace=marketplace_value,
                    sale_model=sale_model_value,
                    order_external_id=str(order_external_id),
                    posting_number=posting_number,
                    srid=str(srid) if srid else None,
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
                    missing_cost=missing_cost,
                    economy_confidence=str(
                        economy_confidence or EconomyConfidence.PRELIMINARY.value
                    ),
                    reconciliation_status=_reconciliation_status(
                        marketplace=marketplace_value,
                        missing_cost=missing_cost,
                        has_wb_fact=bool(has_wb_fact),
                        has_wb_missing_fact=bool(has_wb_missing_fact),
                        has_wb_match_problem=bool(has_wb_match_problem),
                    ),
                )
            )
        return OrderPageResult(
            filters=filters,
            rows=rows,
            total_count=total_count,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        )

    async def order_detail(self, *, user_id: int, order_id: int) -> OrderDetail | None:
        result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.snapshots))
            .where(Order.user_id == user_id)
            .where(Order.id == order_id)
            .where(Order.deleted_at.is_(None))
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
        wb_fact = await self._wb_order_fact(order) if order.marketplace == Marketplace.WB else None
        ozon_fact = await self._ozon_order_fact(order) if order.marketplace == Marketplace.OZON else None
        missing_cost = any(item.cost_price_used is None for item in order.items)
        reconciliation_status = (
            ReconciliationStatus.MANUAL_REVIEW
            if missing_cost
            else wb_fact.status
            if wb_fact is not None
            else ozon_fact.status
            if ozon_fact is not None
            else ReconciliationStatus.PRELIMINARY
        )
        is_financial_only = (
            order.marketplace == Marketplace.WB
            and order.source_event_type == SourceEventType.REPORT_ORDER
            and order.srid is not None
            and _is_short_srid(order.srid)
        )
        order_confidence = "PRELIMINARY"
        conf_priority = {"EXACT": 0, "ESTIMATED": 1, "PRELIMINARY": 2}
        for item in order.items:
            ic = str(item.economy_confidence or "PRELIMINARY")
            if conf_priority.get(ic, 2) > conf_priority.get(order_confidence, 2):
                order_confidence = ic
        order_confidence = order_confidence or "PRELIMINARY"

        return OrderDetail(
            order=order,
            items=items,
            estimated_profit=estimated_total,
            actual_profit=actual_profit,
            deviation=deviation,
            reconciliation_status=reconciliation_status,
            wb_fact=wb_fact,
            ozon_fact=ozon_fact,
            is_financial_only=is_financial_only,
            has_missing_cost_price=missing_cost,
            economy_confidence=order_confidence,
        )

    async def _wb_order_fact(self, order: Order) -> WbOrderFact:
        linked_rows = await self._wb_rows_linked_to_order(order)
        unlinked_rows = await self._wb_rows_unlinked_for_order_products(order)
        has_report_near_order = bool(linked_rows or unlinked_rows)
        if not has_report_near_order:
            has_report_near_order = await self._has_wb_report_rows_near_order(order)
        article_states = _wb_fact_article_states(
            linked_rows=linked_rows,
            unlinked_rows=unlinked_rows,
            has_report_near_order=has_report_near_order,
        )
        if any(
            row.order_match_status in {"ambiguous", "ambiguous_order_match", "error"}
            for row in linked_rows + unlinked_rows
        ):
            status = ReconciliationStatus.FACT_AMBIGUOUS
        elif linked_rows and all(state.state == "present" for state in article_states):
            status = ReconciliationStatus.FACT_MATCHED
        elif linked_rows:
            status = ReconciliationStatus.FACT_PARTIAL
        elif unlinked_rows:
            status = ReconciliationStatus.FACT_UNMATCHED
        elif has_report_near_order:
            status = ReconciliationStatus.FACT_UNMATCHED
        else:
            status = ReconciliationStatus.PRELIMINARY
        return WbOrderFact(
            status=status,
            article_states=article_states,
            linked_rows=linked_rows,
            unlinked_product_rows=unlinked_rows,
        )

    async def _ozon_order_fact(self, order: Order) -> OzonOrderFact | None:
        if not order.order_external_id:
            return None
        result = await self.session.execute(
            select(FinancialReportRow)
            .where(
                FinancialReportRow.marketplace_account_id == order.marketplace_account_id,
                FinancialReportRow.marketplace == Marketplace.OZON,
                FinancialReportRow.order_external_id == order.order_external_id,
            )
            .order_by(FinancialReportRow.operation_category, FinancialReportRow.operation_date)
        )
        rows = list(result.scalars().all())
        if not rows:
            return None

        articles: list[OzonFactArticle] = []
        seen_categories: set[str] = set()
        for row in rows:
            cat = (row.operation_category or "other").lower()
            if cat not in seen_categories:
                seen_categories.add(cat)
                label = _ozon_category_label(cat)
                articles.append(OzonFactArticle(key=cat, label=label, amount=row.amount))
            else:
                existing = next((a for a in articles if a.key == cat), None)
                if existing is not None and row.amount is not None:
                    existing.amount = (existing.amount or ZERO) + row.amount

        has_actual = any(
            s.calculation_type == CalculationType.ACTUAL
            for item in getattr(order, "items", [])
            for s in getattr(item, "snapshots", [])
        )
        if has_actual:
            status = ReconciliationStatus.FACT_MATCHED
        elif rows:
            status = ReconciliationStatus.FACT_PARTIAL
        else:
            status = ReconciliationStatus.PRELIMINARY

        return OzonOrderFact(status=status, articles=articles, rows=rows)

    async def _wb_rows_linked_to_order(self, order: Order) -> list[WbDailyReportRow]:
        result = await self.session.execute(
            select(WbDailyReportRow)
            .where(WbDailyReportRow.user_id == order.user_id)
            .where(WbDailyReportRow.marketplace_account_id == order.marketplace_account_id)
            .where(WbDailyReportRow.linked_order_id == order.id)
            .where(WbDailyReportRow.is_active.is_(True))
            .where(WbDailyReportRow.deleted_at.is_(None))
            .order_by(WbDailyReportRow.sale_dt.desc().nullslast(), WbDailyReportRow.id.desc())
            .limit(200)
        )
        return list(result.scalars().all())

    async def _wb_rows_unlinked_for_order_products(self, order: Order) -> list[WbDailyReportRow]:
        product_ids = {item.product_id for item in order.items if item.product_id is not None}
        if not product_ids:
            return []
        date_from = order.order_date - timedelta(days=14)
        date_to = order.order_date + timedelta(days=14)
        result = await self.session.execute(
            select(WbDailyReportRow)
            .where(WbDailyReportRow.user_id == order.user_id)
            .where(WbDailyReportRow.marketplace_account_id == order.marketplace_account_id)
            .where(WbDailyReportRow.linked_product_id.in_(product_ids))
            .where(WbDailyReportRow.linked_order_id.is_(None))
            .where(WbDailyReportRow.sale_dt >= date_from)
            .where(WbDailyReportRow.sale_dt <= date_to)
            .where(WbDailyReportRow.is_active.is_(True))
            .where(WbDailyReportRow.deleted_at.is_(None))
            .order_by(WbDailyReportRow.sale_dt.desc().nullslast(), WbDailyReportRow.id.desc())
            .limit(200)
        )
        return list(result.scalars().all())

    async def _has_wb_report_rows_near_order(self, order: Order) -> bool:
        date_from = order.order_date - timedelta(days=14)
        date_to = order.order_date + timedelta(days=14)
        result = await self.session.execute(
            select(WbDailyReportRow.id)
            .where(WbDailyReportRow.user_id == order.user_id)
            .where(WbDailyReportRow.marketplace_account_id == order.marketplace_account_id)
            .where(WbDailyReportRow.sale_dt >= date_from)
            .where(WbDailyReportRow.sale_dt <= date_to)
            .where(WbDailyReportRow.is_active.is_(True))
            .where(WbDailyReportRow.deleted_at.is_(None))
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

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
        status: str = "all",
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
            status=status,
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
                avg_commission,
                avg_logistics,
                missing_cost_items,
                preliminary_items,
                actual_snapshot_items,
            ) = row
            key = (marketplace_value, seller_article or "")
            sales = sales_map.get(key, 0)
            profit = _decimal(estimated_profit)
            total_cost = _decimal(cost)
            actual_profit_val = _decimal(actual_profit)
            missing = int(missing_cost_items or 0)
            has_actual = int(actual_snapshot_items or 0)
            has_preliminary = int(preliminary_items or 0)
            if missing > 0:
                reconcil_status = ReconciliationStatus.MANUAL_REVIEW
            elif has_actual > 0 and has_preliminary == 0:
                reconcil_status = ReconciliationStatus.FACT_MATCHED
            elif has_actual > 0:
                reconcil_status = ReconciliationStatus.FACT_PARTIAL
            else:
                reconcil_status = ReconciliationStatus.PRELIMINARY
            rows.append(
                ProfitSkuRow(
                    title=title or seller_article or "Без названия",
                    seller_article=seller_article or "н/д",
                    marketplace=marketplace_value,
                    sale_model=sale_model_value,
                    orders=int(orders or 0),
                    sales=sales,
                    revenue=_decimal(revenue),
                    estimated_revenue=_decimal(revenue),
                    actual_revenue=ZERO,
                    payout=ZERO,
                    cost=total_cost,
                    marketplace_costs=_decimal(marketplace_costs),
                    estimated_profit=profit,
                    actual_profit=actual_profit_val,
                    margin_percent=_decimal(margin),
                    actual_margin=None,
                    avg_commission=_decimal(avg_commission),
                    avg_logistics=_decimal(avg_logistics),
                    roi_percent=roi_percent(profit, total_cost),
                    missing_cost_items=missing,
                    preliminary_items=has_preliminary,
                    actual_snapshot_items=has_actual,
                    reconciliation_status=reconcil_status,
                )
            )
        rows = _filter_profit_rows(rows, filters.economy)
        rows = await self._merge_wb_daily_report_rows(user_id, filters, rows)
        for r in rows:
            if r.actual_revenue and r.actual_revenue > ZERO and r.actual_profit is not None:
                r.actual_margin = (
                    (r.actual_profit / r.actual_revenue * Decimal("100")).quantize(Decimal("0.1"))
                )
        rows = _sort_profit_rows(rows, filters.sort, filters.direction)[:limit]
        return ProfitPageData(filters=filters, summary=_profit_summary(rows), rows=rows)

    async def _merge_wb_daily_report_rows(
        self,
        user_id: int,
        filters: OrderWebFilters,
        rows: list[ProfitSkuRow],
    ) -> list[ProfitSkuRow]:
        if filters.marketplace not in (None, Marketplace.WB):
            return rows
        article_expr = func.coalesce(WbDailyReportRow.supplier_article, literal_column("''"))
        operation_text = func.lower(
            func.concat(
                func.coalesce(WbDailyReportRow.doc_type_name, ""),
                " ",
                func.coalesce(WbDailyReportRow.payment_reason, ""),
            )
        )
        sales_case = operation_text.not_like("%возврат%")
        rows_query = (
            select(
                article_expr.label("seller_article"),
                func.coalesce(func.sum(WbDailyReportRow.quantity).filter(sales_case), 0),
            )
            .where(WbDailyReportRow.user_id == user_id)
            .where(WbDailyReportRow.sale_dt >= filters.date_from)
            .where(WbDailyReportRow.sale_dt <= filters.date_to)
            .where(WbDailyReportRow.is_active.is_(True))
            .where(WbDailyReportRow.deleted_at.is_(None))
            .where(WbDailyReportRow.operation_scope.in_(("order", "product")))
            .group_by(article_expr)
        )
        if filters.sku:
            rows_query = rows_query.where(
                WbDailyReportRow.supplier_article.ilike(f"%{filters.sku}%")
            )
        rows_result = await self.session.execute(rows_query)
        sales_by_article = {
            str(seller_article or ""): int(sales or 0)
            for seller_article, sales in rows_result.all()
        }

        component_article_expr = func.coalesce(
            WbDailyReportRow.supplier_article,
            literal_column("''"),
        )
        query = (
            select(
                component_article_expr.label("seller_article"),
                func.coalesce(
                    func.sum(WbReportFinanceComponent.normalized_amount).filter(
                        WbReportFinanceComponent.finance_category.in_(("sale", "return"))
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(WbReportFinanceComponent.normalized_amount).filter(
                        WbReportFinanceComponent.finance_category == "payout"
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(WbReportFinanceComponent.normalized_amount).filter(
                        WbReportFinanceComponent.finance_category.in_(
                            (
                                "commission",
                                "logistics",
                                "storage",
                                "penalty",
                                "deduction",
                                "acceptance",
                            )
                        )
                    ),
                    0,
                ),
            )
            .join(
                WbDailyReportRow,
                WbDailyReportRow.id == WbReportFinanceComponent.report_row_id,
            )
            .where(WbDailyReportRow.user_id == user_id)
            .where(WbDailyReportRow.sale_dt >= filters.date_from)
            .where(WbDailyReportRow.sale_dt <= filters.date_to)
            .where(WbDailyReportRow.is_active.is_(True))
            .where(WbDailyReportRow.deleted_at.is_(None))
            .where(WbReportFinanceComponent.is_active.is_(True))
            .where(WbReportFinanceComponent.deleted_at.is_(None))
            .where(WbReportFinanceComponent.operation_scope.in_(("order", "product")))
            .group_by(component_article_expr)
        )
        if filters.sku:
            query = query.where(WbDailyReportRow.supplier_article.ilike(f"%{filters.sku}%"))
        result = await self.session.execute(query)
        by_key = {(row.marketplace, row.seller_article): row for row in rows}
        for (
            seller_article,
            revenue,
            payout,
            marketplace_costs,
        ) in result.all():
            article = str(seller_article or "")
            actual_profit = _decimal(payout)
            key = (Marketplace.WB, article)
            existing = by_key.get(key)
            if existing is not None:
                existing.sales += sales_by_article.get(article, 0)
                existing.actual_revenue += _decimal(revenue)
                existing.payout += _decimal(payout)
                existing.marketplace_costs += _decimal(marketplace_costs)
                if existing.actual_snapshot_items == 0:
                    existing.actual_profit += actual_profit - existing.cost
                if (
                    existing.reconciliation_status == ReconciliationStatus.PRELIMINARY
                    and sales_by_article.get(article, 0)
                ):
                    existing.reconciliation_status = ReconciliationStatus.FACT_MATCHED
                continue
            wb_payout = _decimal(payout)
            wb_revenue = _decimal(revenue)
            wb_costs = _decimal(marketplace_costs)
            wb_profit = wb_payout
            rows.append(
                ProfitSkuRow(
                    title=article or "WB daily report",
                    seller_article=article or "н/д",
                    marketplace=Marketplace.WB,
                    sale_model=None,
                    orders=0,
                    sales=sales_by_article.get(article, 0),
                    revenue=ZERO,
                    estimated_revenue=ZERO,
                    actual_revenue=wb_revenue,
                    payout=wb_payout,
                    cost=ZERO,
                    marketplace_costs=wb_costs,
                    estimated_profit=ZERO,
                    actual_profit=wb_profit,
                    margin_percent=ZERO,
                    actual_margin=None,
                    avg_commission=ZERO,
                    avg_logistics=ZERO,
                    roi_percent=None,
                    missing_cost_items=0,
                    preliminary_items=0,
                    actual_snapshot_items=0,
                    reconciliation_status=ReconciliationStatus.FACT_MATCHED,
                )
            )
        return rows

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
        latest_actual = (
            select(
                ProfitSnapshot.order_item_id.label("order_item_id"),
                ProfitSnapshot.profit.label("profit"),
                func.row_number()
                .over(
                    partition_by=ProfitSnapshot.order_item_id,
                    order_by=(ProfitSnapshot.calculated_at.desc(), ProfitSnapshot.id.desc()),
                )
                .label("rn"),
            )
            .where(ProfitSnapshot.calculation_type == CalculationType.ACTUAL)
            .subquery()
        )
        query = (
            select(
                title_expr.label("title"),
                article_expr.label("seller_article"),
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
                        + func.coalesce(OrderItem.tax_amount_estimated, 0)
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
                func.coalesce(func.sum(latest_actual.c.profit), 0),
                func.avg(OrderItem.margin_percent_estimated),
                func.avg(OrderItem.commission_estimated),
                func.avg(OrderItem.logistics_estimated),
                func.count(OrderItem.id).filter(OrderItem.cost_price_used.is_(None)),
                func.count(OrderItem.id).filter(
                    OrderItem.economy_confidence == EconomyConfidence.PRELIMINARY.value
                ),
                func.count(latest_actual.c.profit),
            )
            .join(OrderItem, OrderItem.order_id == Order.id)
            .outerjoin(
                latest_actual,
                (latest_actual.c.order_item_id == OrderItem.id) & (latest_actual.c.rn == 1),
            )
            .where(Order.user_id == user_id)
            .where(Order.deleted_at.is_(None))
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
                article_expr.label("seller_article"),
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
        economy=economy if economy in {"all", "profit", "loss", "missing_cost", "no_finance"} else "all",
        status=(
            status
            if status
            in {
                "all",
                "active",
                "cancelled",
                "action_required",
                "fact_missing",
                "fact_partial",
                "fact_complete",
                "match_problem",
            }
            else "all"
        ),
        sku=sku.strip(),
        sort=sort if sort in {
            "date", "profit", "actual_profit", "revenue", "margin", "orders", "sales", "roi"
        } else "date",
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
    count_distinct: bool = False,
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
    elif filters.status == "fact_missing":
        query = query.where(~_order_has_wb_fact_row())
    elif filters.status == "fact_partial":
        query = query.where(_order_has_wb_fact_row())
        query = query.where(_order_has_wb_missing_fact_state())
    elif filters.status == "fact_complete":
        query = query.where(_order_has_wb_fact_row())
        query = query.where(~_order_has_wb_missing_fact_state())
    elif filters.status == "match_problem":
        query = query.where(_order_has_wb_match_problem())
    if include_economy:
        if filters.economy == "loss":
            query = query.where(OrderItem.profit_estimated < 0)
        elif filters.economy == "profit":
            query = query.where(OrderItem.profit_estimated >= 0)
        elif filters.economy == "missing_cost":
            query = query.where(OrderItem.cost_price_used.is_(None))
    return query


def _order_has_wb_fact_row() -> Any:
    return exists(
        select(WbDailyReportRow.id).where(
            WbDailyReportRow.linked_order_id == Order.id,
            WbDailyReportRow.operation_scope == "order",
            WbDailyReportRow.deleted_at.is_(None),
            WbDailyReportRow.is_active.is_(True),
        )
    )


def _order_has_wb_missing_fact_state() -> Any:
    return exists(
        select(WbDailyReportRow.id).where(
            WbDailyReportRow.linked_order_id == Order.id,
            WbDailyReportRow.operation_scope == "order",
            WbDailyReportRow.deleted_at.is_(None),
            WbDailyReportRow.is_active.is_(True),
            WbDailyReportRow.order_match_status.in_(("order_pending_match", "pending", "partial")),
        )
    )


def _order_has_wb_match_problem() -> Any:
    return exists(
        select(WbDailyReportRow.id).where(
            WbDailyReportRow.marketplace_account_id == Order.marketplace_account_id,
            WbDailyReportRow.operation_scope == "order",
            WbDailyReportRow.deleted_at.is_(None),
            WbDailyReportRow.is_active.is_(True),
            WbDailyReportRow.order_match_status.in_(
                ("ambiguous", "ambiguous_order_match", "error")
            ),
        )
    )


def _reconciliation_status(
    *,
    marketplace: Marketplace,
    missing_cost: bool,
    has_wb_fact: bool,
    has_wb_missing_fact: bool,
    has_wb_match_problem: bool,
) -> ReconciliationStatus:
    if missing_cost:
        return ReconciliationStatus.MANUAL_REVIEW
    if marketplace != Marketplace.WB:
        return ReconciliationStatus.PRELIMINARY
    if has_wb_match_problem:
        return ReconciliationStatus.FACT_AMBIGUOUS
    if has_wb_fact and has_wb_missing_fact:
        return ReconciliationStatus.FACT_PARTIAL
    if has_wb_fact:
        return ReconciliationStatus.FACT_MATCHED
    return ReconciliationStatus.PRELIMINARY


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


def _apply_order_sort_query(query: Select[Any], filters: OrderWebFilters) -> Any:
    """Return sort expression for use in .order_by() chaining."""
    sort_map = {
        "date": Order.order_date,
        "profit": OrderItem.profit_estimated,
        "revenue": OrderItem.discounted_price * OrderItem.quantity,
        "margin": OrderItem.margin_percent_estimated,
    }
    expression = sort_map.get(filters.sort, Order.order_date)
    if filters.direction == "asc":
        return expression.asc(), Order.id.desc()
    return expression.desc(), Order.id.desc()


def _latest_snapshot(
    snapshots: list[ProfitSnapshot],
    calculation_type: CalculationType,
) -> ProfitSnapshot | None:
    filtered = [item for item in snapshots if item.calculation_type == calculation_type]
    if not filtered:
        return None
    return max(filtered, key=lambda item: (item.calculated_at, item.id or 0))


def _ozon_category_label(cat: str) -> str:
    labels = {
        "sale": "Продажа",
        "payout": "Выплата",
        "commission": "Комиссия Ozon",
        "logistics": "Логистика",
        "other_marketplace_costs": "Прочие расходы МП",
        "return": "Возвраты",
        "storage": "Хранение",
        "penalty": "Штрафы",
        "deduction": "Удержания",
        "acceptance": "Приёмка",
        "compensation": "Компенсации",
    }
    return labels.get(cat, cat)


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
        "actual_profit": lambda row: row.actual_profit or Decimal("-999999"),
        "revenue": lambda row: row.revenue,
        "margin": lambda row: row.margin_percent,
        "orders": lambda row: Decimal(row.orders),
        "sales": lambda row: Decimal(row.sales),
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


WB_FACT_ARTICLES: tuple[tuple[str, str, str], ...] = (
    ("sale", "Продажа", "retail_amount"),
    ("commission", "Комиссия WB", "commission_rub"),
    ("logistics", "Логистика", "delivery_rub"),
    ("storage", "Хранение", "storage_fee"),
    ("penalty", "Штрафы", "penalty"),
    ("deduction", "Удержания", "deduction"),
    ("acceptance", "Платная приемка FBS", "acceptance"),
    ("compensation", "Компенсации", "reimbursement_amount"),
    ("returns", "Возвраты", "return_count"),
    ("payout", "К перечислению", "for_pay"),
)


def _wb_fact_article_states(
    *,
    linked_rows: list[WbDailyReportRow],
    unlinked_rows: list[WbDailyReportRow],
    has_report_near_order: bool,
) -> list[WbFactArticleState]:
    states: list[WbFactArticleState] = []
    for key, label, attr in WB_FACT_ARTICLES:
        amount = _sum_wb_attr(linked_rows, attr)
        if amount is not None:
            state = "present"
        elif _sum_wb_attr(unlinked_rows, attr) is not None:
            state = "unlinked"
        elif has_report_near_order:
            state = "missing"
        else:
            state = "report_not_loaded"
        states.append(WbFactArticleState(key=key, label=label, amount=amount, state=state))
    return states


def _sum_wb_attr(rows: list[WbDailyReportRow], attr: str) -> Decimal | None:
    values: list[Decimal] = []
    for row in rows:
        if attr == "return_count":
            return_count = getattr(row, "return_count", None)
            if return_count is not None and int(return_count or 0) > 0:
                values.append(_decimal(getattr(row, "retail_amount", None)))
            continue
        value = getattr(row, attr, None)
        if value is not None:
            values.append(_decimal(value))
    if not values:
        return None
    return sum(values, ZERO)


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))


def localized_order_date(value: datetime, timezone: str) -> str:
    return format_datetime_for_user(value, timezone)


def order_state_label(status: str | None, requires_action: bool) -> str:
    return order_status_label(status, requires_action)


def _is_short_srid(srid: str | None) -> bool:
    """Check if srid looks like a short code rather than a real order ID.

    Real WB srids are typically longer strings or contain hyphens.
    Short all-numeric codes are likely financial report references.
    """
    if not srid:
        return False
    text = str(srid).strip()
    if len(text) < 8:
        return True
    if text.isdigit() and len(text) < 12:
        return True
    return False
