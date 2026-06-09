"""Diagnostics and soft cleanup for WB storage rows created as fake orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Text, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Order, OrderItem, WbDailyReportRow, WbReportFinanceComponent
from app.models.enums import Marketplace

STORAGE_FAKE_ORDER_REASON = "Ошибочный заказ из строки хранения WB"


@dataclass(slots=True)
class StorageFakeOrderCandidate:
    order_id: int
    marketplace_account_id: int
    order_external_id: str
    order_date: datetime
    evidence: str


@dataclass(slots=True)
class StorageFakeOrderCleanupResult:
    candidates: list[StorageFakeOrderCandidate]
    soft_deleted: int = 0
    components_unlinked: int = 0
    rows_unlinked: int = 0


class StorageOrderCleanupService:
    """Find and soft-delete orders that were accidentally created from WB storage rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_candidates(
        self,
        *,
        user_id: int | None = None,
        marketplace_account_id: int | None = None,
        limit: int = 100,
    ) -> list[StorageFakeOrderCandidate]:
        storage_rows = (
            select(WbDailyReportRow.linked_order_id.label("order_id"))
            .where(WbDailyReportRow.linked_order_id.is_not(None))
            .where(func.lower(func.coalesce(WbDailyReportRow.payment_reason, "")).like("%хран%"))
            .union_all(
                select(WbDailyReportRow.order_id.label("order_id"))
                .where(WbDailyReportRow.order_id.is_not(None))
                .where(
                    func.lower(func.coalesce(WbDailyReportRow.payment_reason, "")).like("%хран%")
                )
            )
            .subquery()
        )
        query = (
            select(
                Order.id,
                Order.marketplace_account_id,
                Order.order_external_id,
                Order.order_date,
                func.count(OrderItem.id).label("items_count"),
                func.coalesce(func.sum(OrderItem.quantity), 0).label("quantity"),
                func.coalesce(func.sum(OrderItem.discounted_price), 0).label("price"),
            )
            .outerjoin(OrderItem, OrderItem.order_id == Order.id)
            .where(Order.marketplace == Marketplace.WB)
            .where(Order.deleted_at.is_(None))
            .where(
                (Order.id.in_(select(storage_rows.c.order_id)))
                | cast(Order.raw_payload, Text).ilike("%Хранение%")
            )
            .group_by(Order.id)
            .order_by(Order.order_date.desc(), Order.id.desc())
            .limit(limit)
        )
        if user_id is not None:
            query = query.where(Order.user_id == user_id)
        if marketplace_account_id is not None:
            query = query.where(Order.marketplace_account_id == marketplace_account_id)

        candidates: list[StorageFakeOrderCandidate] = []
        for row in (await self.session.execute(query)).all():
            order_id, account_id, external_id, order_date, items_count, quantity, price = row
            if int(items_count or 0) > 0 and (int(quantity or 0) > 0 or price):
                continue
            candidates.append(
                StorageFakeOrderCandidate(
                    order_id=int(order_id),
                    marketplace_account_id=int(account_id),
                    order_external_id=str(external_id),
                    order_date=order_date,
                    evidence="строка WB с обоснованием 'Хранение' связана с заказом",
                )
            )
        return candidates

    async def soft_delete_candidates(
        self,
        *,
        user_id: int | None = None,
        marketplace_account_id: int | None = None,
        limit: int = 100,
    ) -> StorageFakeOrderCleanupResult:
        candidates = await self.find_candidates(
            user_id=user_id,
            marketplace_account_id=marketplace_account_id,
            limit=limit,
        )
        if not candidates:
            return StorageFakeOrderCleanupResult(candidates=[])

        now = datetime.now(UTC)
        order_ids = [item.order_id for item in candidates]
        await self.session.execute(
            update(Order)
            .where(Order.id.in_(order_ids))
            .values(deleted_at=now, deleted_reason=STORAGE_FAKE_ORDER_REASON)
        )
        rows_result = await self.session.execute(
            update(WbDailyReportRow)
            .where(
                (WbDailyReportRow.order_id.in_(order_ids))
                | (WbDailyReportRow.linked_order_id.in_(order_ids))
            )
            .where(func.lower(func.coalesce(WbDailyReportRow.payment_reason, "")).like("%хран%"))
            .values(
                operation_scope="period",
                order_required=False,
                product_required=False,
                order_id=None,
                linked_order_id=None,
                matched_order_id=None,
                product_id=None,
                linked_product_id=None,
                order_match_status="not_required",
                product_match_status="not_required",
                order_match_reason="Для строки хранения не требуется заказ",
                product_match_reason="Для строки хранения не требуется товар",
            )
        )
        components_result = await self.session.execute(
            update(WbReportFinanceComponent)
            .where(WbReportFinanceComponent.order_id.in_(order_ids))
            .where(WbReportFinanceComponent.finance_category == "storage")
            .values(
                operation_scope="period",
                order_id=None,
                product_id=None,
                is_order_fact=False,
                is_product_fact=False,
                is_global_fact=True,
            )
        )
        await self.session.flush()
        return StorageFakeOrderCleanupResult(
            candidates=candidates,
            soft_deleted=len(order_ids),
            rows_unlinked=int(rows_result.rowcount or 0),
            components_unlinked=int(components_result.rowcount or 0),
        )
