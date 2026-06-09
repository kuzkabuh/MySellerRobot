"""version: 1.0.0
description: Priority-based matching of WB financial report rows to orders.
updated: 2026-06-09
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import FinancialReportRow, Order, OrderItem
from app.models.enums import Marketplace
from app.repositories.orders import OrderRepository

logger = logging.getLogger(__name__)

MATCH_HIGH = "high"
MATCH_MEDIUM = "medium"
MATCH_LOW = "low"


@dataclass(slots=True)
class MatchResult:
    order_id: int | None = None
    order_item_id: int | None = None
    match_status: str = "unmatched"
    match_method: str = ""
    match_confidence: str = ""
    match_reason: str = ""
    candidates_count: int = 0


class WbOrderReportMatcher:
    """Match WB financial report rows to orders with priority-based strategies.

    Priority order:
    1. High: srid, orderUid, orderId, shkId, rrdId
    2. Medium: nmId + sku + date + amount, vendorCode + date + amount
    3. Low: vendorCode + date window (no auto-match)
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_repo = OrderRepository(session)

    async def match(
        self,
        row: FinancialReportRow,
        *,
        account_id: int,
        marketplace: Marketplace = Marketplace.WB,
    ) -> MatchResult:
        raw = row.raw_payload or {}

        # High-priority: exact identifiers
        for method, value in self._high_priority_keys(raw):
            candidates = await self._find_candidates(account_id, marketplace, method, value)
            if len(candidates) == 1:
                return MatchResult(
                    order_id=candidates[0],
                    match_status="matched",
                    match_method=method,
                    match_confidence=MATCH_HIGH,
                    match_reason=f"Точное совпадение по {method}: {value}",
                    candidates_count=1,
                )
            if len(candidates) > 1:
                return MatchResult(
                    match_status="ambiguous",
                    match_method=method,
                    match_confidence=MATCH_HIGH,
                    match_reason=f"Найдено {len(candidates)} кандидатов по {method}: {value}",
                    candidates_count=len(candidates),
                )

        # Medium-priority: composite keys
        for method, criteria in self._medium_priority_criteria(raw, row):
            candidates = await self._find_candidates_composite(
                account_id, marketplace, **criteria
            )
            if len(candidates) == 1:
                return MatchResult(
                    order_id=candidates[0],
                    match_status="matched",
                    match_method=method,
                    match_confidence=MATCH_MEDIUM,
                    match_reason=f"Совпадение по {method}",
                    candidates_count=1,
                )
            if len(candidates) > 1:
                return MatchResult(
                    match_status="ambiguous",
                    match_method=method,
                    match_confidence=MATCH_MEDIUM,
                    match_reason=f"Найдено {len(candidates)} кандидатов по {method}",
                    candidates_count=len(candidates),
                )

        # Low-priority: vendor/date window — never auto-match
        for method, criteria in self._low_priority_criteria(raw):
            candidates = await self._find_candidates_range(
                account_id, marketplace, **criteria
            )
            if candidates:
                return MatchResult(
                    match_status="manual_review",
                    match_method=method,
                    match_confidence=MATCH_LOW,
                    match_reason=(
                        f"Найдено {len(candidates)} кандидатов по {method}. "
                        "Требуется ручная проверка"
                    ),
                    candidates_count=len(candidates),
                )

        return MatchResult(
            match_status="unmatched",
            match_reason="Не найдено совпадений ни по одному критерию",
        )

    def _high_priority_keys(self, raw: dict[str, Any]) -> list[tuple[str, str]]:
        keys: list[tuple[str, str]] = []
        for field, label in (
            ("srid", "srid"),
            ("orderUid", "orderUid"),
            ("orderId", "orderId"),
            ("shkId", "shkId"),
        ):
            val = raw.get(field)
            if val is not None:
                keys.append((label, str(val)))
        return keys

    def _medium_priority_criteria(
        self,
        raw: dict[str, Any],
        row: FinancialReportRow,
    ) -> list[tuple[str, dict[str, Any]]]:
        criteria: list[tuple[str, dict[str, Any]]] = []
        nm_id = raw.get("nmId")
        vendor_code = raw.get("vendorCode")
        order_dt = raw.get("orderDt") or raw.get("saleDt")
        amount = float(row.amount) if row.amount else None

        if nm_id and order_dt and amount:
            criteria.append((
                "nmId+sku+date+amount",
                {
                    "nm_id": str(nm_id),
                    "sku": raw.get("sku", ""),
                    "date": order_dt,
                    "amount": amount,
                },
            ))

        if vendor_code and order_dt and amount:
            criteria.append((
                "vendorCode+date+amount",
                {
                    "vendor_code": vendor_code,
                    "date": order_dt,
                    "amount": amount,
                },
            ))

        return criteria

    def _low_priority_criteria(
        self,
        raw: dict[str, Any],
    ) -> list[tuple[str, dict[str, Any]]]:
        criteria: list[tuple[str, dict[str, Any]]] = []
        supplier_article = raw.get("vendorCode") or raw.get("supplierArticle")
        order_dt = raw.get("orderDt") or raw.get("saleDt")

        if supplier_article and order_dt:
            criteria.append((
                "vendorCode+dateWindow",
                {
                    "vendor_code": str(supplier_article),
                    "date": order_dt,
                },
            ))

        return criteria

    async def _find_candidates(
        self,
        account_id: int,
        marketplace: Marketplace,
        field: str,
        value: str,
    ) -> list[int]:
        field_map = {
            "srid": Order.srid,
            "orderId": Order.order_external_id,
            "orderUid": Order.order_external_id,
            "shkId": None,
        }
        col = field_map.get(field)
        if col is None:
            return []

        query = select(Order.id).where(
            Order.marketplace_account_id == account_id,
            Order.marketplace == marketplace,
            col == value,
            Order.deleted_at.is_(None),
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _find_candidates_composite(
        self,
        account_id: int,
        marketplace: Marketplace,
        **kwargs: Any,
    ) -> list[int]:
        conditions = [
            Order.marketplace_account_id == account_id,
            Order.marketplace == marketplace,
            Order.deleted_at.is_(None),
        ]

        nm_id = kwargs.get("nm_id")
        if nm_id:
            conditions.append(
                Order.items.any(
                    OrderItem.marketplace_article == nm_id
                )
            )

        val = kwargs.get("vendor_code")
        if val:
            conditions.append(
                Order.items.any(
                    OrderItem.seller_article == val
                )
            )

        date_val = kwargs.get("date")
        if date_val:
            try:
                dt = datetime.fromisoformat(str(date_val).replace("Z", "+00:00"))
                window = timedelta(hours=24)
                conditions.append(
                    Order.order_date.between(dt - window, dt + window)
                )
            except (ValueError, TypeError):
                pass

        amount = kwargs.get("amount")
        if amount is not None:
            threshold = Decimal(str(amount)) * Decimal("0.1")
            conditions.append(
                Order.items.any(
                    func.abs(OrderItem.discounted_price * OrderItem.quantity - Decimal(str(amount)))
                    < threshold
                )
            )

        query = select(Order.id).where(*conditions).limit(10)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _find_candidates_range(
        self,
        account_id: int,
        marketplace: Marketplace,
        **kwargs: Any,
    ) -> list[int]:
        conditions = [
            Order.marketplace_account_id == account_id,
            Order.marketplace == marketplace,
            Order.deleted_at.is_(None),
        ]

        val = kwargs.get("vendor_code")
        if val:
            conditions.append(
                Order.items.any(
                    OrderItem.seller_article.ilike(f"%{val}%")
                )
            )

        date_val = kwargs.get("date")
        if date_val:
            try:
                dt = datetime.fromisoformat(str(date_val).replace("Z", "+00:00"))
                window = timedelta(days=3)
                conditions.append(
                    Order.order_date.between(dt - window, dt + window)
                )
            except (ValueError, TypeError):
                pass

        query = select(Order.id).where(*conditions).limit(20)
        result = await self.session.execute(query)
        return list(result.scalars().all())
