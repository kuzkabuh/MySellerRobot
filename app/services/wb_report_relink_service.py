"""Relink unbound WB report rows to orders after order backfills."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Text, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    Order,
    OrderItem,
    WbDailyReportImport,
    WbDailyReportRow,
    WbReportFinanceComponent,
)
from app.models.enums import Marketplace


@dataclass(slots=True)
class WbReportRelinkResult:
    scanned: int = 0
    matched: int = 0
    pending: int = 0
    ambiguous: int = 0
    errors: int = 0


class WbReportRelinkService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def relink_pending_rows(
        self,
        *,
        marketplace_account_id: int | None = None,
        import_id: int | None = None,
        limit: int = 1000,
    ) -> WbReportRelinkResult:
        query = (
            select(WbDailyReportRow)
            .join(WbDailyReportImport, WbDailyReportImport.id == WbDailyReportRow.import_id)
            .where(
                WbDailyReportRow.order_required.is_(True),
                WbDailyReportRow.order_id.is_(None),
                WbDailyReportRow.linked_order_id.is_(None),
                WbDailyReportRow.deleted_at.is_(None),
                WbDailyReportRow.is_active.is_(True),
                WbDailyReportImport.deleted_at.is_(None),
                WbDailyReportRow.order_match_status.in_(
                    (
                        "not_found",
                        "pending",
                        "order_pending_match",
                        "ambiguous",
                        "ambiguous_order_match",
                        "order_not_found",
                    )
                ),
            )
            .order_by(WbDailyReportRow.last_match_attempt_at.asc().nullsfirst())
            .limit(limit)
        )
        if marketplace_account_id is not None:
            query = query.where(WbDailyReportRow.marketplace_account_id == marketplace_account_id)
        if import_id is not None:
            query = query.where(WbDailyReportRow.import_id == import_id)

        rows = list((await self.session.execute(query)).scalars().all())
        result = WbReportRelinkResult(scanned=len(rows))
        now = datetime.now(UTC)
        for row in rows:
            row.match_attempts_count = (row.match_attempts_count or 0) + 1
            row.last_match_attempt_at = now
            row.last_match_error = None
            try:
                order_id, method, status, reason = await self._find_order(row)
            except Exception as exc:
                row.last_match_error = str(exc)[:1000]
                row.order_match_status = "error"
                result.errors += 1
                continue
            row.order_match_status = status
            row.order_match_method = method
            row.order_match_reason = reason
            row.skip_reason = reason
            if order_id is None:
                if status.startswith("ambiguous"):
                    result.ambiguous += 1
                else:
                    result.pending += 1
                continue
            row.order_id = order_id
            row.linked_order_id = order_id
            row.matched_order_id = order_id
            row.matched_at = now
            row.row_status = "new"
            row.skip_reason = None
            await self._activate_components_for_match(row)
            result.matched += 1
        await self.session.flush()
        return result

    async def _find_order(
        self, row: WbDailyReportRow
    ) -> tuple[int | None, str | None, str, str | None]:
        for method, value in (
            ("srid", row.srid_raw or row.srid),
            ("srid_normalized", row.srid_normalized),
            ("rid", row.rid_normalized),
            ("basket_id", row.basket_id),
            ("shk", row.shk),
        ):
            if not value:
                continue
            ids = await self._candidate_ids(row, method, str(value))
            if len(ids) == 1:
                return ids[0], method, "matched", None
            if len(ids) > 1:
                reason = f"Найдено несколько заказов по {method}"
                return None, method, "ambiguous_order_match", reason

        for method in ("barcode_nm_date", "barcode_article_date"):
            ids = await self._candidate_ids(row, method, "")
            if len(ids) == 1:
                return ids[0], method, "matched", None
            if len(ids) > 1:
                reason = f"Найдено несколько заказов по {method}"
                return None, method, "ambiguous_order_match", reason
        return None, None, "order_pending_match", "Заказ пока не найден"

    async def _candidate_ids(self, row: WbDailyReportRow, method: str, value: str) -> list[int]:
        base = select(Order.id).where(
            Order.marketplace_account_id == row.marketplace_account_id,
            Order.marketplace == Marketplace.WB,
        )
        if method == "srid":
            stmt = base.where(Order.srid == value)
        elif method == "srid_normalized":
            stmt = base.where(func.lower(func.trim(Order.srid)) == value)
        elif method == "rid":
            stmt = base.where(func.lower(func.trim(Order.srid)).like(f"%{value}%"))
        elif method == "basket_id":
            stmt = base.where(cast(Order.raw_payload, Text).ilike(f"%{value}%"))
        elif method == "shk":
            stmt = base.where((Order.order_external_id == value) | (Order.posting_number == value))
        else:
            if not row.order_dt or not row.barcode:
                return []
            date_from = row.order_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            date_to = date_from + timedelta(days=1)
            stmt = (
                base.join(OrderItem, OrderItem.order_id == Order.id)
                .where(Order.order_date >= date_from, Order.order_date < date_to)
                .where(cast(Order.raw_payload, Text).ilike(f"%{row.barcode}%"))
            )
            if method == "barcode_nm_date" and row.nm_id is not None:
                stmt = stmt.where(OrderItem.marketplace_article == str(row.nm_id))
            elif method == "barcode_article_date" and row.supplier_article:
                stmt = stmt.where(OrderItem.seller_article == row.supplier_article)
            else:
                return []
        return sorted({int(item) for item in (await self.session.execute(stmt.limit(3))).scalars()})

    async def _activate_components_for_match(self, row: WbDailyReportRow) -> None:
        await self.session.execute(
            update(WbReportFinanceComponent)
            .where(WbReportFinanceComponent.report_row_id == row.id)
            .values(
                order_id=row.order_id,
                is_order_fact=True,
                is_active=row.is_active,
                deleted_at=row.deleted_at,
            )
        )


def normalize_report_srid(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    return re.sub(r"\s+", "", text)
