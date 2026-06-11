"""Wildberries daily financial detail report sync and reconciliation."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, MarketplaceApiError, RateLimitError
from app.core.security import TokenCipher
from app.integrations.wildberries.finance_client import WbFinanceApiClient
from app.models.domain import (
    FinancialReportRow,
    MarketplaceAccount,
    Order,
    OrderItem,
    ProfitSnapshot,
    SyncTaskRun,
)
from app.models.enums import CalculationType, Marketplace
from app.repositories.orders import OrderRepository
from app.schemas.profit import CostInput, ProfitInput, ProfitResult
from app.services.common.sync_status_service import SyncStatusService
from app.services.unit_economics.cost_service import CostService
from app.services.unit_economics.profit_calculator import ProfitCalculator
from app.services.wb.reports.operation_classifier import classify_financial_operation

logger = logging.getLogger(__name__)

DETAILED_REPORT_FIELDS = [
    "rrdId",
    "reportId",
    "nmId",
    "vendorCode",
    "sku",
    "orderId",
    "orderUid",
    "srid",
    "docTypeName",
    "sellerOperName",
    "quantity",
    "dateFrom",
    "dateTo",
    "createDate",
    "orderDt",
    "saleDt",
    "rrDate",
    "retailPrice",
    "retailAmount",
    "retailPriceWithDisc",
    "productDiscountForReport",
    "sellerPromo",
    "sellerPromoDiscount",
    "spp",
    "salePercent",
    "wibesDiscountPercent",
    "cashbackAmount",
    "cashbackDiscount",
    "loyaltyDiscount",
    "commissionPercent",
    "kvwBase",
    "kvw",
    "ppvzSalesCommission",
    "forPay",
    "ppvzReward",
    "vw",
    "vwNds",
    "additionalPayment",
    "acquiringFee",
    "acquiringPercent",
    "paymentProcessing",
    "acquiringBank",
    "deliveryAmount",
    "returnAmount",
    "deliveryService",
    "rebillLogisticCost",
    "rebillLogisticOrg",
    "deliveryMethod",
    "penalty",
    "paidStorage",
    "deduction",
    "paidAcceptance",
    "bonusTypeName",
    "officeName",
    "ppvzOfficeName",
    "ppvzOfficeId",
    "country",
    "isB2b",
    "trbxId",
    "articleSubstitution",
    "installmentCofinancingAmount",
    "agencyVat",
]


@dataclass(slots=True)
class SyncCounters:
    pages_fetched: int = 0
    total_rows_fetched: int = 0
    rows_upserted: int = 0
    rows_matched: int = 0
    rows_unmatched: int = 0
    orders_reconciled: int = 0
    snapshots_upserted: int = 0
    failed_rows: int = 0
    errors: list[str] = field(default_factory=list)


class WbDailyFinancialDetailService:
    """Fetch, store, reconcile, and calculate actual profit
    from WB daily financial detail reports."""

    def __init__(self, session: AsyncSession, cipher: TokenCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()
        self.calculator = ProfitCalculator()
        self.cost_service = CostService(session)
        self.order_repo = OrderRepository(session)
        self.sync_status = SyncStatusService(session)
        self._finance_client: WbFinanceApiClient | None = None

    def _get_finance_client(self, account: MarketplaceAccount) -> WbFinanceApiClient:
        if self._finance_client is None:
            api_key = self.cipher.decrypt(account.encrypted_api_key)
            self._finance_client = WbFinanceApiClient(api_key)
        return self._finance_client

    async def sync_account_for_date(
        self,
        account: MarketplaceAccount,
        report_date: date,
    ) -> SyncCounters:
        if account.marketplace != Marketplace.WB:
            return SyncCounters()

        # Prevent parallel runs for the same account+date
        task_name = f"wb_financial_detail_{account.id}"
        existing_run = await self._has_running_task(task_name)
        if existing_run:
            logger.warning(
                "wb_financial_detail_parallel_skip",
                extra={
                    "account_id": account.id,
                    "report_date": report_date.isoformat(),
                    "existing_run_id": existing_run.id,
                },
            )
            counters = SyncCounters()
            counters.errors.append(
                f"Sync already running (run #{existing_run.id}), skipped"
            )
            return counters

        sync_run = await self.sync_status.start(
            task_name=task_name,
            metadata={
                "account_id": account.id,
                "user_id": account.user_id,
                "report_date": report_date.isoformat(),
            },
        )

        settings = get_settings()
        client = self._get_finance_client(account)
        limit = settings.wb_report_detailed_limit
        date_str = report_date.isoformat()

        logger.info(
            "wb_daily_financial_detail_sync_started",
            extra={
                "account_id": account.id,
                "user_id": account.user_id,
                "report_date": date_str,
                "sync_run_id": sync_run.id,
            },
        )

        counters = SyncCounters()
        all_rows: list[dict[str, Any]] = []
        rrd_id = 0
        consecutive_empty = 0

        try:
            while True:
                payload = await client.get_sales_reports_detailed(
                    date_from=date_str,
                    date_to=date_str,
                    period="daily",
                    limit=limit,
                    rrd_id=rrd_id,
                    fields=DETAILED_REPORT_FIELDS,
                )
                counters.pages_fetched += 1

                if payload is None:
                    logger.info(
                        "wb_finance_api_204_no_more_data",
                        extra={
                            "account_id": account.id,
                            "report_date": date_str,
                            "rrd_id": rrd_id,
                        },
                    )
                    break

                page_rows = WbFinanceApiClient.extract_rows(payload)
                all_rows.extend(page_rows)
                counters.total_rows_fetched += len(page_rows)

                logger.info(
                    "wb_daily_financial_detail_page_fetched",
                    extra={
                        "account_id": account.id,
                        "report_date": date_str,
                        "page": counters.pages_fetched,
                        "rrd_id": rrd_id,
                        "fetched_rows": len(page_rows),
                    },
                )

                if not page_rows:
                    consecutive_empty += 1
                    if consecutive_empty >= 3:
                        break
                    rrd_id += 1
                    continue
                consecutive_empty = 0

                last_rrd_id = self._get_last_rrd_id(page_rows)
                if last_rrd_id is None or last_rrd_id == rrd_id:
                    rrd_id += 1
                    continue
                rrd_id = last_rrd_id

        except (AuthenticationError, RateLimitError, MarketplaceApiError) as exc:
            error_msg = f"API error: {exc}"
            counters.errors.append(error_msg)
            logger.error(
                "wb_daily_financial_detail_sync_failed",
                extra={
                    "account_id": account.id,
                    "report_date": date_str,
                    "pages_fetched": counters.pages_fetched,
                    "error": error_msg,
                },
            )
            await self.sync_status.mark_failed(
                sync_run,
                error=error_msg,
                records_processed=counters.total_rows_fetched,
                success_count=counters.rows_upserted,
                failed_count=counters.failed_rows,
            )
            return counters

        if not all_rows:
            logger.info(
                "wb_daily_financial_detail_sync_no_data",
                extra={
                    "account_id": account.id,
                    "report_date": date_str,
                },
            )
            account.last_wb_financial_detail_sync_at = datetime.now(tz=UTC)
            return counters

        await self._upsert_report_rows(account, all_rows, date_str, counters)
        await self._reconcile_and_calculate(account, all_rows, date_str, counters)

        account.last_wb_financial_detail_sync_at = datetime.now(tz=UTC)
        account.last_success_sync_at = datetime.now(tz=UTC)

        await self.sync_status.mark_success(
            sync_run,
            records_processed=counters.total_rows_fetched,
            success_count=counters.rows_upserted,
            failed_count=counters.failed_rows,
        )

        logger.info(
            "wb_daily_financial_detail_sync_completed",
            extra={
                "account_id": account.id,
                "user_id": account.user_id,
                "report_date": date_str,
                "sync_run_id": sync_run.id,
                "pages_fetched": counters.pages_fetched,
                "total_rows_fetched": counters.total_rows_fetched,
                "rows_upserted": counters.rows_upserted,
                "rows_matched": counters.rows_matched,
                "rows_unmatched": counters.rows_unmatched,
                "orders_reconciled": counters.orders_reconciled,
                "snapshots_upserted": counters.snapshots_upserted,
                "failed_rows": counters.failed_rows,
            },
        )

        return counters

    async def _has_running_task(self, task_name: str) -> SyncTaskRun | None:
        result = await self.session.execute(
            select(SyncTaskRun)
            .where(
                SyncTaskRun.task_name == task_name,
                SyncTaskRun.status == "started",
            )
            .order_by(SyncTaskRun.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _get_last_rrd_id(rows: list[dict[str, Any]]) -> int | None:
        for row in reversed(rows):
            rrd_id = row.get("rrdId")
            if rrd_id is not None:
                try:
                    return int(rrd_id)
                except (TypeError, ValueError):
                    continue
        return None

    async def _upsert_report_rows(
        self,
        account: MarketplaceAccount,
        rows: list[dict[str, Any]],
        report_date: str,
        counters: SyncCounters,
    ) -> None:
        for row in rows:
            try:
                await self._upsert_single_row(account, row, report_date)
                counters.rows_upserted += 1
            except Exception as exc:
                counters.failed_rows += 1
                counters.errors.append(f"Row upsert failed: {exc}")
                logger.warning(
                    "wb_financial_row_upsert_failed",
                    extra={
                        "account_id": account.id,
                        "report_date": report_date,
                        "error": str(exc)[:200],
                    },
                )

    async def _upsert_single_row(
        self,
        account: MarketplaceAccount,
        row: dict[str, Any],
        report_date: str,
    ) -> None:
        rrd_id = row.get("rrdId")
        if rrd_id is None:
            rrd_id = row.get("reportId")
        if rrd_id is None:
            # Build stable composite key from available identifiers
            parts = [
                report_date,
                str(row.get("nmId", "")),
                str(row.get("orderId", "")),
                str(row.get("srid", "")),
                str(row.get("orderUid", "")),
                str(row.get("docTypeName", "")),
            ]
            rrd_id = f"composite-{'-'.join(filter(None, parts))}"
            logger.warning(
                "wb_financial_row_missing_rrd_id",
                extra={
                    "account_id": account.id,
                    "report_date": report_date,
                    "composite_key": rrd_id,
                    "row_keys": list(row.keys())[:10],
                },
            )

        external_row_id = str(rrd_id)
        order_external_id = self._extract_order_external_id(row)
        product_external_id = str(row.get("nmId") or "") if row.get("nmId") is not None else None
        operation_type = self._determine_operation_type(row)
        operation_category = self._classify_operation_category(row, operation_type)
        operation_date = self._parse_operation_date(row, report_date)
        amount = self._determine_amount(row, operation_type)

        existing = await self.session.execute(
            select(FinancialReportRow).where(
                FinancialReportRow.marketplace_account_id == account.id,
                FinancialReportRow.marketplace == Marketplace.WB,
                FinancialReportRow.external_row_id == external_row_id,
            )
        )
        report_row = existing.scalar_one_or_none()

        if report_row is None:
            report_row = FinancialReportRow(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                marketplace=Marketplace.WB,
                external_row_id=external_row_id,
            )
            self.session.add(report_row)

        report_row.order_external_id = order_external_id
        report_row.product_external_id = product_external_id
        report_row.operation_type = operation_type
        report_row.operation_category = operation_category
        report_row.operation_date = operation_date
        report_row.amount = amount
        report_row.raw_payload = row
        await self.session.flush()

    @staticmethod
    def _classify_operation_category(
        row: dict[str, Any],
        operation_type: str,
    ) -> str:
        """Classify a financial row using the dedicated classifier, with fallback.

        Category names are mapped to be compatible with the
        reconciliation service (order_profit_reconciliation_service).
        """
        seller_oper = str(row.get("sellerOperName") or "") or None
        doc_type = str(row.get("docTypeName") or "") or None
        bonus_type = str(row.get("bonusTypeName") or "") or None

        op_type_name, category = classify_financial_operation(
            seller_oper_name=seller_oper,
            doc_type_name=doc_type,
            bonus_type_name=bonus_type,
        )

        # Map dedicated classifier categories to reconciliation-compatible names
        CATEGORY_MAP = {
            "revenue": "sale",
            "paid_acceptance": "acceptance",
        }
        mapped = CATEGORY_MAP.get(category, category)

        # If classifier returned a known category, use the mapped name
        if mapped != "other":
            return mapped

        # Fallback: keyword matching on raw fields
        type_lower = operation_type.lower()
        doc_type_lower = str(row.get("docTypeName") or "").lower()

        if any(kw in type_lower or kw in doc_type_lower
               for kw in ("продажа", "sale", "реализация")):
            return "sale"
        if any(kw in type_lower or kw in doc_type_lower for kw in ("возврат", "return")):
            return "return"
        if any(kw in type_lower or kw in doc_type_lower
               for kw in ("логист", "delivery", "logistic")):
            return "logistics"
        if any(kw in type_lower or kw in doc_type_lower
               for kw in ("комисс", "commission", "reward")):
            return "commission"
        if any(kw in type_lower or kw in doc_type_lower for kw in ("штраф", "penalty", "fine")):
            return "penalty"
        if any(kw in type_lower or kw in doc_type_lower for kw in ("хранен", "storage")):
            return "storage"
        if any(kw in type_lower or kw in doc_type_lower
               for kw in ("удержан", "deduction", "удержание")):
            return "deduction"
        if any(kw in type_lower or kw in doc_type_lower
               for kw in ("приемк", "приёмк", "acceptance")):
            return "acceptance"
        if any(kw in type_lower or kw in doc_type_lower
               for kw in ("доплат", "additional", "additionalPayment")):
            return "compensation"
        if any(kw in type_lower or kw in doc_type_lower
               for kw in ("эквайринг", "acquiring", "paymentProcessing")):
            return "acquiring"

        forPay = row.get("forPay")
        if forPay is not None:
            return "payout"

        return "other"

    @staticmethod
    def _extract_order_external_id(row: dict[str, Any]) -> str | None:
        order_id = row.get("orderId")
        if order_id is not None:
            return str(order_id)
        order_uid = row.get("orderUid")
        if order_uid:
            return str(order_uid)
        return None

    @staticmethod
    def _determine_operation_type(row: dict[str, Any]) -> str:
        """Get the best operation description from available fields.

        Priority: sellerOperName > docTypeName > bonusTypeName.
        This matches operation_classifier._best_name priority.
        """
        seller_oper = str(row.get("sellerOperName") or "").strip()
        if seller_oper:
            return seller_oper
        doc_type = str(row.get("docTypeName") or "").strip()
        if doc_type:
            return doc_type
        bonus_type = str(row.get("bonusTypeName") or "").strip()
        if bonus_type:
            return bonus_type
        return "unknown"

    @staticmethod
    def _parse_operation_date(row: dict[str, Any], report_date: str) -> datetime:
        for key in ("orderDt", "saleDt", "rrDate", "createDate"):
            value = row.get(key)
            if value:
                try:
                    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    continue

        try:
            d = date.fromisoformat(report_date)
            return datetime(d.year, d.month, d.day, tzinfo=UTC)
        except ValueError:
            return datetime.now(tz=UTC)

    @staticmethod
    def _determine_amount(row: dict[str, Any], operation_type: str) -> Decimal:
        type_lower = operation_type.lower()

        if any(kw in type_lower for kw in ("продажа", "sale", "реализация")):
            val = row.get("retailAmount") or row.get("forPay") or row.get("retailPriceWithDisc")
            if val is not None:
                return _safe_decimal(val)

        if any(kw in type_lower for kw in ("возврат", "return")):
            val = row.get("returnAmount") or row.get("retailAmount")
            if val is not None:
                return _safe_decimal(val)

        if any(kw in type_lower for kw in ("логист", "delivery", "logistic")):
            val = (
                row.get("deliveryAmount")
                or row.get("deliveryService")
                or row.get("rebillLogisticCost")
            )
            if val is not None:
                return _safe_decimal(val)

        if any(kw in type_lower for kw in ("штраф", "penalty", "fine")):
            val = row.get("penalty")
            if val is not None:
                return _safe_decimal(val)

        if any(kw in type_lower for kw in ("хранен", "storage")):
            val = row.get("paidStorage")
            if val is not None:
                return _safe_decimal(val)

        if any(kw in type_lower for kw in ("удержан", "deduction", "удержание")):
            val = row.get("deduction")
            if val is not None:
                return _safe_decimal(val)

        if any(kw in type_lower for kw in ("приемк", "приёмк", "acceptance")):
            val = row.get("paidAcceptance")
            if val is not None:
                return _safe_decimal(val)

        if any(kw in type_lower for kw in ("доплат", "additional", "additionalPayment")):
            val = row.get("additionalPayment")
            if val is not None:
                return _safe_decimal(val)

        if any(kw in type_lower for kw in ("комисс", "commission", "reward")):
            val = row.get("ppvzSalesCommission") or row.get("ppvzReward") or row.get("kvw")
            if val is not None:
                return _safe_decimal(val)

        if any(kw in type_lower for kw in ("эквайринг", "acquiring", "paymentProcessing")):
            val = row.get("acquiringFee") or row.get("paymentProcessing")
            if val is not None:
                return _safe_decimal(val)

        forPay = row.get("forPay")
        if forPay is not None:
            return _safe_decimal(forPay)

        return _safe_decimal(row.get("retailAmount", 0))

    async def _reconcile_and_calculate(
        self,
        account: MarketplaceAccount,
        rows: list[dict[str, Any]],
        report_date: str,
        counters: SyncCounters,
    ) -> None:
        order_cache: dict[str, Order] = {}
        order_rows_map: dict[int, list[dict[str, Any]]] = {}

        for row in rows:
            order = await self._find_matching_order(account, row, order_cache)
            if order is None:
                counters.rows_unmatched += 1
                logger.debug(
                    "wb_financial_row_unmatched",
                    extra={
                        "account_id": account.id,
                        "report_date": report_date,
                        "rrd_id": row.get("rrdId"),
                        "order_id": row.get("orderId"),
                        "srid": row.get("srid"),
                    },
                )
                continue

            counters.rows_matched += 1
            if order.id not in order_rows_map:
                order_rows_map[order.id] = []
            order_rows_map[order.id].append(row)

        for order_id, matched_rows in order_rows_map.items():
            try:
                order = await self.order_repo.get_with_items(order_id)
                if order is None or not order.items:
                    continue
                if order.assembly_id is None:
                    for row in matched_rows:
                        order_id_val = row.get("orderId")
                        if order_id_val is not None:
                            order.assembly_id = str(order_id_val)
                            break
                await self._calculate_actual_for_order(order, matched_rows, counters)
                counters.orders_reconciled += 1
            except Exception as exc:
                counters.failed_rows += 1
                counters.errors.append(f"Reconciliation failed for order {order_id}: {exc}")
                logger.exception(
                    "wb_order_reconciliation_failed",
                    extra={
                        "account_id": account.id,
                        "order_id": order_id,
                        "report_date": report_date,
                    },
                )

    async def _find_matching_order(
        self,
        account: MarketplaceAccount,
        row: dict[str, Any],
        cache: dict[str, Order],
    ) -> Order | None:
        order_id = row.get("orderId")
        if order_id is not None:
            order_external_id = str(order_id)
            if order_external_id in cache:
                return cache[order_external_id]
            order = await self.order_repo.get_by_external(
                account_id=account.id,
                marketplace=Marketplace.WB,
                order_external_id=order_external_id,
            )
            if order is not None:
                cache[order_external_id] = order
                logger.info(
                    "wb_financial_row_matched_by_order_id",
                    extra={
                        "account_id": account.id,
                        "order_id": order.id,
                        "order_external_id": order_external_id,
                        "rrd_id": row.get("rrdId"),
                    },
                )
                return order

        srid = row.get("srid")
        if srid:
            srid_str = str(srid)
            result = await self.session.execute(
                select(Order)
                .where(Order.marketplace_account_id == account.id)
                .where(Order.marketplace == Marketplace.WB)
                .where(Order.srid == srid_str)
            )
            order = result.scalar_one_or_none()
            if order is not None:
                cache[srid_str] = order
                logger.info(
                    "wb_financial_row_matched_by_srid",
                    extra={
                        "account_id": account.id,
                        "order_id": order.id,
                        "srid": srid_str,
                        "rrd_id": row.get("rrdId"),
                    },
                )
                return order

        return None

    async def _calculate_actual_for_order(
        self,
        order: Order,
        report_rows: list[dict[str, Any]],
        counters: SyncCounters,
    ) -> None:
        for item in order.items:
            aggregated = self._aggregate_report_rows(report_rows, item)
            cost = None
            if item.product_id:
                cost = await self.cost_service.get_actual_cost(item.product_id, order.order_date)

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
                            cost_price=cost.cost_price if cost else Decimal("0"),
                            package_cost=cost.package_cost if cost else Decimal("0"),
                            additional_cost=cost.additional_cost if cost else Decimal("0"),
                            tax_rate=cost.tax_rate if cost else Decimal("0"),
                        )
                        if cost
                        else None
                    ),
                    calculation_source="wb_daily_financial_detail",
                )
            )

            await self._upsert_actual_snapshot(item, result, counters)

    def _aggregate_report_rows(
        self,
        report_rows: list[dict[str, Any]],
        item: OrderItem,
    ) -> dict[str, Decimal]:
        gross_revenue = Decimal("0")
        expected_payout = Decimal("0")
        has_for_pay = False
        marketplace_commission = Decimal("0")
        logistics_cost = Decimal("0")
        acquiring_cost = Decimal("0")
        storage_cost = Decimal("0")
        return_cost = Decimal("0")
        other_marketplace_costs = Decimal("0")
        additional_payment = Decimal("0")
        deduct_costs = Decimal("0")

        for row in report_rows:
            op_type = self._determine_operation_type(row).lower()
            has_fp = row.get("forPay") is not None
            if has_fp:
                expected_payout += _safe_decimal(row.get("forPay"))
                has_for_pay = True

            if any(kw in op_type for kw in ("продажа", "sale", "реализация")):
                gross_revenue += _safe_decimal(row.get("retailAmount", 0))
                commission = _safe_decimal(row.get("ppvzSalesCommission", 0))
                if commission > 0:
                    marketplace_commission += commission
                elif row.get("ppvzReward"):
                    marketplace_commission += _safe_decimal(row["ppvzReward"])

                acq = _safe_decimal(row.get("acquiringFee", 0))
                if acq > 0:
                    acquiring_cost += acq
                acq2 = _safe_decimal(row.get("paymentProcessing", 0))
                if acq2 > 0:
                    acquiring_cost += acq2

                if not has_fp:
                    deduct_costs += commission + acq + acq2

            elif any(kw in op_type for kw in ("возврат", "return")):
                return_cost += _safe_decimal(row.get("returnAmount", 0))
                if row.get("retailAmount"):
                    gross_revenue -= _safe_decimal(row["retailAmount"])

            elif any(kw in op_type for kw in ("логист", "delivery", "logistic")):
                dlv = _safe_decimal(row.get("deliveryAmount", 0))
                dsv = _safe_decimal(row.get("deliveryService", 0))
                rlc = _safe_decimal(row.get("rebillLogisticCost", 0))
                logistics_cost += dlv + dsv + rlc
                if not has_fp:
                    deduct_costs += dlv + dsv + rlc

            elif any(kw in op_type for kw in ("комисс", "commission", "reward")):
                val = _safe_decimal(row.get("ppvzSalesCommission", 0))
                if val == 0:
                    val = _safe_decimal(row.get("ppvzReward", 0))
                if val == 0:
                    val = _safe_decimal(row.get("kvw", 0))
                marketplace_commission += val
                if not has_fp:
                    deduct_costs += val

            elif any(kw in op_type for kw in ("штраф", "penalty", "fine")):
                val = _safe_decimal(row.get("penalty", 0))
                other_marketplace_costs += val
                if not has_fp:
                    deduct_costs += val

            elif any(kw in op_type for kw in ("хранен", "storage")):
                val = _safe_decimal(row.get("paidStorage", 0))
                storage_cost += val
                if not has_fp:
                    deduct_costs += val

            elif any(kw in op_type for kw in ("удержан", "deduction", "удержание")):
                val = _safe_decimal(row.get("deduction", 0))
                other_marketplace_costs += val
                if not has_fp:
                    deduct_costs += val

            elif any(kw in op_type for kw in ("приемк", "приёмк", "acceptance")):
                val = _safe_decimal(row.get("paidAcceptance", 0))
                other_marketplace_costs += val
                if not has_fp:
                    deduct_costs += val

            elif any(kw in op_type for kw in ("доплат", "additional")):
                additional_payment += _safe_decimal(row.get("additionalPayment", 0))

            elif any(kw in op_type for kw in ("эквайринг", "acquiring")):
                acq3 = _safe_decimal(row.get("acquiringFee", 0))
                pp = _safe_decimal(row.get("paymentProcessing", 0))
                acquiring_cost += acq3 + pp
                if not has_fp:
                    deduct_costs += acq3 + pp

        if has_for_pay:
            expected_payout = expected_payout + additional_payment - deduct_costs
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
            expected_payout += additional_payment

        return {
            "gross_revenue": gross_revenue,
            "expected_payout": expected_payout,
            "marketplace_commission": marketplace_commission,
            "logistics_cost": logistics_cost,
            "acquiring_cost": acquiring_cost,
            "storage_cost": storage_cost,
            "return_cost": return_cost,
            "other_marketplace_costs": other_marketplace_costs,
            "compensation_amount": additional_payment,
            "paid_acceptance_amount": other_marketplace_costs,
        }

    async def _upsert_actual_snapshot(
        self,
        item: OrderItem,
        result: ProfitResult,
        counters: SyncCounters,
    ) -> None:
        existing = await self.session.execute(
            select(ProfitSnapshot)
            .where(ProfitSnapshot.order_item_id == item.id)
            .where(ProfitSnapshot.calculation_type == CalculationType.ACTUAL)
            .order_by(ProfitSnapshot.calculated_at.desc())
            .limit(1)
        )
        snapshot = existing.scalar_one_or_none()

        raw_financial_data = {
            "gross_revenue": str(result.gross_revenue),
            "expected_payout": str(result.expected_payout),
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
            "calculation_source": "wb_daily_financial_detail",
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
        snapshot.tax_amount = result.tax_amount
        snapshot.profit = result.profit
        snapshot.margin_percent = result.margin_percent
        snapshot.calculated_at = datetime.now(tz=UTC)
        snapshot.calculation_source = "wb_daily_financial_detail"
        snapshot.economy_confidence = "EXACT"
        snapshot.raw_financial_data = raw_financial_data

        counters.snapshots_upserted += 1

        logger.info(
            "wb_order_actual_profit_snapshot_upserted",
            extra={
                "order_item_id": item.id,
                "profit": str(result.profit),
                "margin_percent": str(result.margin_percent),
            },
        )


def _safe_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
