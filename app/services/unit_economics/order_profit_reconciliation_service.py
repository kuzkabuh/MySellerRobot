"""version: 1.2.0
description: Centralised order profit reconciliation: match financial rows to orders
    and create/update actual ProfitSnapshot records. Idempotent by design.
updated: 2026-06-09
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    FinancialReportRow,
    MarketplaceAccount,
    Order,
    OrderItem,
    ProfitSnapshot,
    WbDailyReportRow,
)
from app.models.enums import CalculationType, ReconciliationStatus
from app.repositories.orders import OrderRepository
from app.schemas.profit import CostInput, ProfitInput
from app.services.unit_economics.cost_service import CostService
from app.services.unit_economics.profit_calculator import ProfitCalculator

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


@dataclass(slots=True)
class OrderReconciliationResult:
    order_id: int
    order_external_id: str
    reconciliation_status: ReconciliationStatus
    rows_matched: int
    rows_unmatched: int
    snapshot_created: bool
    snapshot_updated: bool
    profit: Decimal | None
    messages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BatchReconciliationResult:
    total_orders: int = 0
    matched: int = 0
    partial: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    manual_review: int = 0
    missing_cost: int = 0
    snapshots_created: int = 0
    snapshots_updated: int = 0
    errors: int = 0
    results: list[OrderReconciliationResult] = field(default_factory=list)


class OrderProfitReconciliationService:
    """Match financial data to orders and produce actual profit snapshots.

    Works idempotently: re-running the same reconciliation will update
    existing snapshots instead of creating duplicates.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.calculator = ProfitCalculator()
        self.cost_service = CostService(session)
        self.order_repo = OrderRepository(session)

    async def reconcile_order(
        self,
        order: Order,
    ) -> OrderReconciliationResult:
        """Reconcile a single order against available financial data.

        Steps:
        1. Find financial rows linked to this order.
        2. Aggregate revenue, costs, and payout amounts.
        3. Find cost price data.
        4. Calculate actual profit using forPay as primary source.
        5. Create or update ProfitSnapshot(ACTUAL).
        6. Determine reconciliation status.
        """
        messages: list[str] = []
        financial_rows = await self._find_financial_rows(order)
        report_rows = await self._find_linked_report_rows(order)

        all_rows = financial_rows + report_rows

        if not all_rows:
            # Check if order has any estimated snapshot → PRELIMINARY
            has_estimated = any(
                s.calculation_type == CalculationType.ESTIMATED
                for item in getattr(order, "items", [])
                for s in getattr(item, "snapshots", [])
            )
            if has_estimated:
                return OrderReconciliationResult(
                    order_id=order.id,
                    order_external_id=order.order_external_id,
                    reconciliation_status=ReconciliationStatus.PRELIMINARY,
                    rows_matched=0,
                    rows_unmatched=0,
                    snapshot_created=False,
                    snapshot_updated=False,
                    profit=None,
                    messages=["Нет финансового отчёта, только предварительная оценка"],
                )

            return OrderReconciliationResult(
                order_id=order.id,
                order_external_id=order.order_external_id,
                reconciliation_status=ReconciliationStatus.MISSING_REPORT,
                rows_matched=0,
                rows_unmatched=0,
                snapshot_created=False,
                snapshot_updated=False,
                profit=None,
                messages=["Нет финансовых строк, связанных с заказом — отчёт не загружен"],
            )

        ambiguous_statuses = {"ambiguous", "ambiguous_order_match", "error"}
        has_ambiguous = any(
            getattr(r, "order_match_status", None) in ambiguous_statuses
            for r in all_rows
        )
        if has_ambiguous:
            return OrderReconciliationResult(
                order_id=order.id,
                order_external_id=order.order_external_id,
                reconciliation_status=ReconciliationStatus.FACT_AMBIGUOUS,
                rows_matched=0,
                rows_unmatched=len(all_rows),
                snapshot_created=False,
                snapshot_updated=False,
                profit=None,
                messages=["Есть неоднозначные совпадения по заказу"],
            )

        for item in order.items:
            await self._reconcile_item(
                order=order,
                item=item,
                financial_rows=financial_rows,
                report_rows=report_rows,
                messages=messages,
            )

        # Check if any row has manual_review indicator
        has_manual_review = any(
            getattr(r, "order_match_status", None) in {"manual_review", "low_confidence"}
            or getattr(r, "match_confidence", 1.0) < 0.5
            for r in all_rows
        )

        has_missing_cost = any(
            item.cost_price_used is None or item.cost_price_used == ZERO
            for item in order.items
        )
        all_items_have_actual = all(
            self._has_actual_snapshot(item) for item in order.items
        )
        some_items_have_actual = any(
            self._has_actual_snapshot(item) for item in order.items
        )

        if has_manual_review:
            status = ReconciliationStatus.MANUAL_REVIEW
        elif has_missing_cost:
            status = ReconciliationStatus.MISSING_COST
        elif all_items_have_actual:
            status = ReconciliationStatus.FACT_MATCHED
        elif some_items_have_actual:
            status = ReconciliationStatus.FACT_PARTIAL
        else:
            status = ReconciliationStatus.FACT_UNMATCHED

        # Calculate total order profit
        total_profit = await self._total_order_profit(order)

        return OrderReconciliationResult(
            order_id=order.id,
            order_external_id=order.order_external_id,
            reconciliation_status=status,
            rows_matched=len(all_rows),
            rows_unmatched=0,
            snapshot_created=False,
            snapshot_updated=True,
            profit=total_profit,
            messages=messages,
        )

    async def _reconcile_item(
        self,
        order: Order,
        item: OrderItem,
        financial_rows: list[FinancialReportRow],
        report_rows: list[WbDailyReportRow],
        messages: list[str],
    ) -> None:
        aggregated = self._aggregate_financial_rows(
            item=item,
            financial_rows=financial_rows,
            report_rows=report_rows,
        )

        cost = None
        if item.product_id:
            cost = await self.cost_service.get_actual_cost(item.product_id, order.order_date)
        if cost is None and item.cost_price_used is not None:
            cost = _make_cost_from_item(item)
        if cost is None:
            cost = _make_cost_from_item(item)

        result = self.calculator.calculate(
            ProfitInput(
                gross_revenue=aggregated["gross_revenue"],
                expected_payout=aggregated["expected_payout"],
                marketplace_commission=aggregated["marketplace_commission"],
                logistics_cost=aggregated["logistics_cost"],
                acquiring_cost=aggregated["acquiring_cost"],
                storage_cost=aggregated["storage_cost"],
                return_cost=aggregated["return_cost"],
                other_marketplace_costs=aggregated["other_marketplace_costs"],
                cost=(
                    CostInput(
                        cost_price=cost.cost_price if cost else ZERO,
                        package_cost=cost.package_cost if cost else ZERO,
                        additional_cost=cost.additional_cost if cost else ZERO,
                        tax_rate=cost.tax_rate if cost else ZERO,
                    )
                    if cost
                    else None
                ),
                calculation_source="order_profit_reconciliation",
            )
        )

        await self._upsert_actual_snapshot(item, result)

        if aggregated.get("warnings"):
            messages.extend(aggregated["warnings"])

    def _aggregate_financial_rows(
        self,
        item: OrderItem,
        financial_rows: list[FinancialReportRow],
        report_rows: list[WbDailyReportRow],
    ) -> dict[str, Any]:
        gross_revenue = ZERO
        expected_payout = ZERO
        has_for_pay = False
        marketplace_commission = ZERO
        logistics_cost = ZERO
        acquiring_cost = ZERO
        storage_cost = ZERO
        return_cost = ZERO
        other_marketplace_costs = ZERO
        compensation = ZERO
        deduct_costs = ZERO
        warnings: list[str] = []

        # Aggregate from FinancialReportRow (API source)
        for row in financial_rows:
            op_type = (row.operation_type or "").lower()
            op_cat = (row.operation_category or "").lower()
            amt = row.amount or ZERO

            # Use category-based aggregation when available
            if op_cat == "sale" or "продажа" in op_type or "sale" in op_type:
                gross_revenue += abs(amt)
            elif op_cat == "return" or "возврат" in op_type or "return" in op_type:
                return_cost += abs(amt)
                if amt < 0:
                    gross_revenue += amt
            elif op_cat == "payout":
                expected_payout += amt
                has_for_pay = True
            elif op_cat in ("commission",) or "комисс" in op_type:
                marketplace_commission += abs(amt)
                deduct_costs += abs(amt)
            elif op_cat in ("logistics",) or "логист" in op_type or "delivery" in op_type:
                logistics_cost += abs(amt)
                deduct_costs += abs(amt)
            elif op_cat in ("acquiring",) or "эквайринг" in op_type:
                acquiring_cost += abs(amt)
                deduct_costs += abs(amt)
            elif op_cat in ("storage",) or "хранен" in op_type:
                storage_cost += abs(amt)
                deduct_costs += abs(amt)
            elif op_cat in ("penalty",) or "штраф" in op_type:
                other_marketplace_costs += abs(amt)
                deduct_costs += abs(amt)
            elif op_cat in ("deduction",) or "удержан" in op_type:
                other_marketplace_costs += abs(amt)
                deduct_costs += abs(amt)
            elif op_cat in ("acceptance",) or "приемк" in op_type or "приёмк" in op_type:
                other_marketplace_costs += abs(amt)
                deduct_costs += abs(amt)
            elif op_cat in ("compensation",) or "доплат" in op_type:
                compensation += abs(amt)
            elif op_cat in ("additional_payment",):
                compensation += abs(amt)
            elif row.raw_payload and isinstance(row.raw_payload, dict):
                fp = row.raw_payload.get("forPay")
                if fp is not None:
                    expected_payout += abs(_safe_decimal(fp))
                    has_for_pay = True

        # Fallback: if raw_payload has forPay, use it
        if not has_for_pay:
            for row in financial_rows:
                if row.raw_payload and isinstance(row.raw_payload, dict):
                    fp = row.raw_payload.get("forPay")
                    if fp is not None:
                        expected_payout += _safe_decimal(fp)
                        has_for_pay = True

        # Aggregate from WbDailyReportRow (file source)
        for row in report_rows:
            op_type = (row.doc_type_name or "").lower() + " " + (row.payment_reason or "").lower()
            has_fp = row.for_pay is not None and row.for_pay != ZERO

            if has_fp:
                expected_payout += row.for_pay
                has_for_pay = True

            if any(kw in op_type for kw in ("продажа", "sale", "реализация")):
                gross_revenue += row.retail_amount or ZERO
                comm = row.commission_rub or ZERO
                if comm > ZERO:
                    marketplace_commission += comm
                acq = ZERO
                if row.retail_amount and row.for_pay:
                    retail = row.retail_amount or ZERO
                    payout = row.for_pay or ZERO
                    delivery = row.delivery_rub or ZERO
                    acq = retail - payout - comm - delivery
                    if acq > ZERO:
                        acquiring_cost += acq
            elif any(kw in op_type for kw in ("возврат", "return")):
                return_cost += row.retail_amount or ZERO
                if row.retail_amount and row.retail_amount > ZERO:
                    gross_revenue -= row.retail_amount
            elif any(kw in op_type for kw in ("логист", "delivery")):
                logistics_cost += row.delivery_rub or ZERO
                if not has_fp:
                    deduct_costs += row.delivery_rub or ZERO
            elif any(kw in op_type for kw in ("комисс", "commission")):
                marketplace_commission += row.commission_rub or ZERO
                if not has_fp:
                    deduct_costs += row.commission_rub or ZERO
            elif any(kw in op_type for kw in ("штраф", "penalty")):
                other_marketplace_costs += row.penalty or ZERO
                if not has_fp:
                    deduct_costs += row.penalty or ZERO
            elif any(kw in op_type for kw in ("хранен", "storage")):
                storage_cost += row.storage_fee or ZERO
                if not has_fp:
                    deduct_costs += row.storage_fee or ZERO
            elif any(kw in op_type for kw in ("удержан", "deduction")):
                other_marketplace_costs += row.deduction or ZERO
                if not has_fp:
                    deduct_costs += row.deduction or ZERO
            elif any(kw in op_type for kw in ("приемк", "приёмк", "acceptance")):
                other_marketplace_costs += row.acceptance or ZERO
                if not has_fp:
                    deduct_costs += row.acceptance or ZERO

        if has_for_pay:
            expected_payout = expected_payout + compensation - deduct_costs
        else:
            total_expenses = (
                marketplace_commission
                + logistics_cost
                + acquiring_cost
                + storage_cost
                + return_cost
                + other_marketplace_costs
            )
            expected_payout = gross_revenue - total_expenses
            warnings.append(
                "forPay не найден, выплата рассчитана как выручка минус расходы МП"
            )
            expected_payout += compensation

        return {
            "gross_revenue": gross_revenue,
            "expected_payout": expected_payout,
            "marketplace_commission": marketplace_commission,
            "logistics_cost": logistics_cost,
            "acquiring_cost": acquiring_cost,
            "storage_cost": storage_cost,
            "return_cost": return_cost,
            "other_marketplace_costs": other_marketplace_costs,
            "warnings": warnings,
        }

    async def _upsert_actual_snapshot(
        self,
        item: OrderItem,
        result: Any,
    ) -> ProfitSnapshot:
        existing = await self.session.execute(
            select(ProfitSnapshot)
            .where(ProfitSnapshot.order_item_id == item.id)
            .where(ProfitSnapshot.calculation_type == CalculationType.ACTUAL)
            .order_by(ProfitSnapshot.calculated_at.desc())
            .limit(1)
        )
        snapshot = existing.scalar_one_or_none()

        raw_data = {
            "gross_revenue": str(result.gross_revenue),
            "expected_payout": str(result.expected_payout) if result.expected_payout else "0",
            "marketplace_commission": str(result.marketplace_commission),
            "logistics_cost": str(result.logistics_cost),
            "acquiring_cost": str(result.acquiring_cost),
            "storage_cost": str(result.storage_cost),
            "return_cost": str(result.return_cost),
            "other_marketplace_costs": str(result.other_marketplace_costs),
            "cost_price": str(result.cost_price),
            "package_cost": str(result.package_cost),
            "tax_amount": str(result.tax_amount),
            "profit": str(result.profit),
            "margin_percent": str(result.margin_percent),
        }

        if snapshot is None:
            snapshot = ProfitSnapshot(
                order_item_id=item.id,
                calculation_type=CalculationType.ACTUAL,
            )
            self.session.add(snapshot)

        snapshot.gross_revenue = result.gross_revenue
        snapshot.marketplace_commission = result.marketplace_commission
        snapshot.logistics_cost = result.logistics_cost
        snapshot.acquiring_cost = result.acquiring_cost
        snapshot.storage_cost = result.storage_cost
        snapshot.return_cost = result.return_cost
        snapshot.other_marketplace_costs = result.other_marketplace_costs
        snapshot.cost_price = result.cost_price
        snapshot.package_cost = result.package_cost
        snapshot.additional_seller_cost = result.additional_seller_cost
        snapshot.tax_amount = result.tax_amount
        snapshot.profit = result.profit
        snapshot.margin_percent = result.margin_percent
        snapshot.calculated_at = datetime.now(tz=UTC)
        snapshot.calculation_source = "order_profit_reconciliation"
        snapshot.economy_confidence = "EXACT"
        snapshot.raw_financial_data = raw_data

        await self.session.flush()
        return snapshot

    async def _find_financial_rows(
        self,
        order: Order,
    ) -> list[FinancialReportRow]:
        if not order.order_external_id:
            return []
        result = await self.session.execute(
            select(FinancialReportRow)
            .where(
                FinancialReportRow.marketplace_account_id == order.marketplace_account_id,
                FinancialReportRow.marketplace == order.marketplace,
                FinancialReportRow.order_external_id == order.order_external_id,
            )
            .limit(500)
        )
        return list(result.scalars().all())

    async def _find_linked_report_rows(
        self,
        order: Order,
    ) -> list[WbDailyReportRow]:
        result = await self.session.execute(
            select(WbDailyReportRow)
            .where(
                WbDailyReportRow.marketplace_account_id == order.marketplace_account_id,
                WbDailyReportRow.linked_order_id == order.id,
                WbDailyReportRow.is_active.is_(True),
                WbDailyReportRow.deleted_at.is_(None),
            )
            .limit(500)
        )
        return list(result.scalars().all())

    def _has_actual_snapshot(self, item: OrderItem) -> bool:
        return any(
            s.calculation_type == CalculationType.ACTUAL
            for s in getattr(item, "snapshots", [])
        )

    async def _total_order_profit(self, order: Order) -> Decimal | None:
        total = ZERO
        has_any = False
        result = await self.session.execute(
            select(ProfitSnapshot)
            .where(
                ProfitSnapshot.order_item_id.in_(
                    select(OrderItem.id).where(OrderItem.order_id == order.id)
                ),
                ProfitSnapshot.calculation_type == CalculationType.ACTUAL,
            )
        )
        snapshots = result.scalars().all()
        for snap in snapshots:
            total += snap.profit
            has_any = True
        return total if has_any else None

    async def reconcile_pending_orders(
        self,
        account: MarketplaceAccount,
        *,
        limit: int = 100,
        days_back: int = 30,
    ) -> BatchReconciliationResult:
        """Reconcile all orders in a date range that don't have actual snapshots.

        Idempotent: re-running the same account with the same parameters
        will update existing snapshots instead of creating duplicates.
        """
        from datetime import timedelta

        cutoff = datetime.now(tz=UTC) - timedelta(days=days_back)
        result = await self.session.execute(
            select(Order)
            .where(
                Order.marketplace_account_id == account.id,
                Order.marketplace == account.marketplace,
                Order.order_date >= cutoff,
                Order.deleted_at.is_(None),
            )
            .order_by(Order.order_date.desc())
            .limit(limit)
        )
        orders = list(result.scalars().all())
        batch = BatchReconciliationResult()
        for order in orders:
            try:
                order_with_items = await self.order_repo.get_with_items(order.id)
                if order_with_items is None:
                    continue
                rec_result = await self.reconcile_order(order_with_items)
                batch.results.append(rec_result)
                batch.total_orders += 1
                if rec_result.reconciliation_status == ReconciliationStatus.FACT_MATCHED:
                    batch.matched += 1
                elif rec_result.reconciliation_status == ReconciliationStatus.FACT_PARTIAL:
                    batch.partial += 1
                elif rec_result.reconciliation_status == ReconciliationStatus.FACT_UNMATCHED:
                    batch.unmatched += 1
                elif rec_result.reconciliation_status == ReconciliationStatus.FACT_AMBIGUOUS:
                    batch.ambiguous += 1
                elif rec_result.reconciliation_status == ReconciliationStatus.MANUAL_REVIEW:
                    batch.manual_review += 1
                elif rec_result.reconciliation_status == ReconciliationStatus.MISSING_COST:
                    batch.missing_cost += 1
                if rec_result.snapshot_created:
                    batch.snapshots_created += 1
                if rec_result.snapshot_updated:
                    batch.snapshots_updated += 1
            except Exception as exc:
                batch.errors += 1
                logger.exception(
                    "reconciliation_failed",
                    extra={"order_id": order.id, "error": str(exc)},
                )
        return batch


def _safe_decimal(value: Any) -> Decimal:
    if value is None:
        return ZERO
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return ZERO


def _make_cost_from_item(item: OrderItem) -> Any:
    """Create a cost-like object from OrderItem fields."""
    from types import SimpleNamespace
    return SimpleNamespace(
        cost_price=item.cost_price_used or ZERO,
        package_cost=item.package_cost_used or ZERO,
        additional_cost=ZERO,
        tax_rate=ZERO,
    )
