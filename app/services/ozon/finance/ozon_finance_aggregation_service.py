"""version: 1.0.0
description: Creates FinancialReportRow entries from Ozon posting financial_data,
    enabling actual profit snapshots via OrderProfitReconciliationService.
    Hooks into OrderProcessingService for new orders and run as periodic
    reconcile_ozon_finance worker task for existing orders.
updated: 2026-06-10
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import FinancialReportRow, MarketplaceAccount, Order, OrderItem
from app.models.enums import Marketplace, ReconciliationStatus
from app.services.unit_economics.order_profit_reconciliation_service import (
    OrderProfitReconciliationService,
)

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


class OzonFinanceAggregationService:
    """Convert Ozon posting financial data into FinancialReportRow entries.

    Ozon postings carry actual financial data (commission, payout, services)
    at posting time. This service creates FinancialReportRow entries from that
    data so the standard reconciliation pipeline can produce ACTUAL profit
    snapshots (not just ESTIMATED ones).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.reconciliation = OrderProfitReconciliationService(session)

    async def aggregate_order_finance(
        self,
        order: Order,
    ) -> int:
        """Create FinancialReportRow entries for an Ozon order from its item financial data.

        Returns the number of rows created.
        """
        if order.marketplace != Marketplace.OZON:
            return 0

        posting_number = order.order_external_id
        if not posting_number:
            return 0

        items_result = await self.session.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
        items = list(items_result.scalars().all())
        if not items:
            return 0

        rows_created = 0
        for item in items:
            rows_created += await self._create_financial_rows(order, item, posting_number)

        if rows_created > 0:
            await self.session.flush()

        return rows_created

    async def _create_financial_rows(
        self,
        order: Order,
        item: OrderItem,
        posting_number: str,
    ) -> int:
        """Create FinancialReportRow entries for a single OrderItem."""
        sku = item.marketplace_article or str(item.id)
        product_external_id = sku
        account_id = order.marketplace_account_id
        user_id = order.user_id
        operation_date = order.order_date or datetime.now(tz=UTC)

        # Build a human-readable raw_payload from item fields
        raw_payload: dict[str, Any] = {
            "posting_number": posting_number,
            "sku": sku,
            "seller_article": item.seller_article,
            "title": item.title,
            "quantity": item.quantity,
            "buyer_price": str(item.buyer_price),
            "payout_amount_estimated": str(item.payout_amount_estimated or ZERO),
            "seller_payout_estimated": str(item.seller_payout_estimated or ZERO),
            "commission_estimated": str(item.commission_estimated or ZERO),
            "logistics_estimated": str(item.logistics_estimated or ZERO),
            "other_marketplace_expenses_estimated": str(
                item.other_marketplace_expenses_estimated or ZERO
            ),
            "ozon_commission_base_price": str(item.ozon_commission_base_price or ZERO),
        }

        # Build financial rows — one per component
        rows_config = self._build_rows_config(item, raw_payload)
        created = 0
        for cfg in rows_config:
            row = await self._upsert_row(
                user_id=user_id,
                account_id=account_id,
                posting_number=posting_number,
                product_external_id=product_external_id,
                operation_date=operation_date,
                raw_payload=raw_payload,
                external_id_suffix=cfg["suffix"],
                operation_type=cfg["type"],
                operation_category=cfg["category"],
                amount=cfg["amount"],
            )
            if row is not None:
                created += 1

        # Also store a "sale" row for gross revenue
        gross_revenue = Decimal(str(item.buyer_price)) * Decimal(str(item.quantity))
        if gross_revenue > ZERO:
            sale_row = await self._upsert_row(
                user_id=user_id,
                account_id=account_id,
                posting_number=posting_number,
                product_external_id=product_external_id,
                operation_date=operation_date,
                raw_payload=raw_payload,
                external_id_suffix="sale",
                operation_type="Продажа",
                operation_category="sale",
                amount=gross_revenue,
            )
            if sale_row is not None:
                created += 1

        return created

    @staticmethod
    def _build_rows_config(
        item: OrderItem,
        raw_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build configs for each financial component row."""
        configs: list[dict[str, Any]] = []

        payout = item.payout_amount_estimated or ZERO
        if payout > ZERO:
            configs.append({
                "suffix": "payout",
                "type": "Выплата",
                "category": "payout",
                "amount": payout,
            })

        commission = item.commission_estimated
        if commission is not None and commission > ZERO:
            configs.append({
                "suffix": "commission",
                "type": "Комиссия МП",
                "category": "commission",
                "amount": commission,
            })

        logistics = item.logistics_estimated
        if logistics is not None and logistics > ZERO:
            configs.append({
                "suffix": "logistics",
                "type": "Логистика",
                "category": "logistics",
                "amount": logistics,
            })

        other_expenses = item.other_marketplace_expenses_estimated
        if other_expenses is not None and other_expenses > ZERO:
            configs.append({
                "suffix": "other_expenses",
                "type": "Прочие расходы МП",
                "category": "other_marketplace_costs",
                "amount": other_expenses,
            })

        return configs

    async def _upsert_row(
        self,
        user_id: int,
        account_id: int,
        posting_number: str,
        product_external_id: str,
        operation_date: datetime,
        raw_payload: dict[str, Any],
        external_id_suffix: str,
        operation_type: str,
        operation_category: str,
        amount: Decimal,
    ) -> FinancialReportRow | None:
        external_row_id = f"ozon-{posting_number}-{product_external_id}-{external_id_suffix}"

        existing = await self.session.execute(
            select(FinancialReportRow).where(
                FinancialReportRow.marketplace_account_id == account_id,
                FinancialReportRow.marketplace == Marketplace.OZON,
                FinancialReportRow.external_row_id == external_row_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return None

        row = FinancialReportRow(
            user_id=user_id,
            marketplace_account_id=account_id,
            marketplace=Marketplace.OZON,
            external_row_id=external_row_id,
            order_external_id=posting_number,
            product_external_id=product_external_id,
            operation_type=operation_type,
            operation_category=operation_category,
            operation_date=operation_date,
            amount=amount,
            currency="RUB",
            raw_payload=raw_payload,
        )
        self.session.add(row)
        return row

    async def reconcile_ozon_order(
        self,
        order: Order,
    ) -> ReconciliationStatus | None:
        """Run full reconciliation for an Ozon order, producing an ACTUAL profit snapshot."""
        if order.marketplace != Marketplace.OZON:
            return None

        order_with_items = await self.session.execute(
            select(Order).where(Order.id == order.id)
        )
        order_obj = order_with_items.scalar_one_or_none()
        if order_obj is None:
            return None

        from app.repositories.orders import OrderRepository

        repo = OrderRepository(self.session)
        full_order = await repo.get_with_items(order.id)
        if full_order is None:
            return None

        result = await self.reconciliation.reconcile_order(full_order)
        return result.reconciliation_status
