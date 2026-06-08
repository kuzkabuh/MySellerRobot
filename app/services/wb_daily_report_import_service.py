"""version: 1.0.0
description: Service for importing parsed WB daily realisation reports into the database.
updated: 2026-06-07
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    MarketplaceAccount,
    Order,
    Product,
    WbDailyReportImport,
    WbDailyReportImportRowLog,
    WbDailyReportRow,
)
from app.models.enums import Marketplace
from app.services.wb_daily_report_parser import (
    WbDailyReportParsed,
    WbDailyReportParsedRow,
)

logger = logging.getLogger(__name__)

DEDUP_DUPLICATE = "duplicate"


@dataclass(slots=True)
class WbDailyReportImportResult:
    import_id: int
    report_number: str
    rows_total: int
    rows_inserted: int
    rows_skipped: int
    is_duplicate: bool


@dataclass(slots=True)
class WbDailyReportRowFilters:
    operation_type: str = ""
    nm_id: int | None = None
    supplier_article: str = ""
    barcode: str = ""
    srid: str = ""
    status: str = ""
    date_from: str = ""
    date_to: str = ""
    amount_from: Decimal | None = None
    amount_to: Decimal | None = None
    linked_order: str = ""
    linked_product: str = ""
    search: str = ""


@dataclass(slots=True)
class WbDailyReportImportSummary:
    sales_amount: Decimal
    returns_amount: Decimal
    payout_amount: Decimal
    commission_amount: Decimal
    logistics_amount: Decimal
    storage_amount: Decimal
    deductions_amount: Decimal
    penalties_amount: Decimal
    acceptance_amount: Decimal
    orders_count: int
    sales_count: int
    returns_count: int
    unique_nm_ids: int
    unique_articles: int
    recognized_rows: int
    unrecognized_rows: int
    linked_products: int
    unlinked_products: int
    linked_orders: int
    unlinked_orders: int
    duplicate_rows: int
    skip_reasons: list[tuple[str, int]]


@dataclass(slots=True)
class WbDailyReportRowsPage:
    rows: list[WbDailyReportRow]
    total_count: int
    page: int
    per_page: int
    total_pages: int


@dataclass(slots=True)
class _LinkedEntity:
    id: int | None
    status: str
    method: str | None = None
    reason: str | None = None


class WbDailyReportImportService:
    """Persist parsed WB daily reports with idempotency and deduplication."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def import_parsed(
        self,
        *,
        user_id: int,
        marketplace_account: MarketplaceAccount,
        parsed: WbDailyReportParsed,
        file_hash: str,
        original_filename: str | None,
        source_type: str = "file",
    ) -> WbDailyReportImportResult:
        existing = await self.session.execute(
            select(WbDailyReportImport).where(
                WbDailyReportImport.user_id == user_id,
                WbDailyReportImport.marketplace_account_id == marketplace_account.id,
                WbDailyReportImport.file_hash == file_hash,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return await self._record_duplicate(
                user_id=user_id,
                account=marketplace_account,
                parsed=parsed,
                file_hash=file_hash,
                original_filename=original_filename,
                source_type=source_type,
            )

        logger.info(
            "wb_daily_report_import_started",
            extra={
                "user_id": user_id,
                "account_id": marketplace_account.id,
                "report_number": parsed.report_number,
                "report_type": parsed.report_type,
                "rows_total": len(parsed.rows),
                "source_filename": original_filename,
            },
        )
        import_record = WbDailyReportImport(
            user_id=user_id,
            marketplace_account_id=marketplace_account.id,
            source_type=source_type,
            report_type=parsed.report_type,
            original_filename=original_filename,
            report_number=parsed.report_number,
            report_date=parsed.report_date,
            report_period_start=parsed.report_period_start,
            report_period_end=parsed.report_period_end,
            file_hash=file_hash,
            rows_total=len(parsed.rows),
            rows_inserted=0,
            rows_skipped=parsed.skipped_rows,
            status="pending",
        )
        self.session.add(import_record)
        await self.session.flush()

        inserted = 0
        skipped = parsed.skipped_rows

        try:
            for batch in _chunked(parsed.rows, size=500):
                if not batch:
                    continue
                batch_inserted = await self._insert_batch(
                    user_id=user_id,
                    account=marketplace_account,
                    import_id=import_record.id,
                    report_number=parsed.report_number,
                    report_type=parsed.report_type,
                    report_period_start=parsed.report_period_start,
                    report_period_end=parsed.report_period_end,
                    batch=batch,
                )
                inserted += batch_inserted
        except IntegrityError:
            await self.session.rollback()
            logger.exception(
                "wb_daily_report_import_failed",
                extra={
                    "user_id": user_id,
                    "account_id": marketplace_account.id,
                    "report_number": parsed.report_number,
                },
            )
            raise

        import_record.rows_inserted = inserted
        import_record.rows_skipped = skipped + max(0, len(parsed.rows) - inserted)
        import_record.rows_total = len(parsed.rows)
        if inserted == 0 and len(parsed.rows) > 0:
            import_record.status = "partial"
            import_record.error_message = "Все строки оказались дубликатами ранее загруженных"
        elif inserted == 0 and len(parsed.rows) == 0:
            import_record.status = "empty"
        else:
            import_record.status = "success"

        await self.session.commit()
        await self.session.refresh(import_record)
        logger.info(
            "wb_daily_report_import_completed",
            extra={
                "import_id": import_record.id,
                "user_id": user_id,
                "account_id": marketplace_account.id,
                "rows_total": import_record.rows_total,
                "rows_inserted": import_record.rows_inserted,
                "rows_skipped": import_record.rows_skipped,
                "status": import_record.status,
            },
        )

        return WbDailyReportImportResult(
            import_id=import_record.id,
            report_number=import_record.report_number,
            rows_total=import_record.rows_total,
            rows_inserted=import_record.rows_inserted,
            rows_skipped=import_record.rows_skipped,
            is_duplicate=False,
        )

    async def list_imports(
        self,
        *,
        user_id: int | None,
        marketplace_account_id: int | None = None,
        limit: int = 50,
    ) -> list[WbDailyReportImport]:
        stmt = (
            select(WbDailyReportImport)
            .order_by(WbDailyReportImport.created_at.desc())
            .limit(limit)
        )
        if user_id is not None:
            stmt = stmt.where(WbDailyReportImport.user_id == user_id)
        if marketplace_account_id is not None:
            stmt = stmt.where(
                WbDailyReportImport.marketplace_account_id == marketplace_account_id
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_import(self, *, import_id: int, user_id: int) -> WbDailyReportImport | None:
        result = await self.session.execute(
            select(WbDailyReportImport).where(
                WbDailyReportImport.id == import_id,
                WbDailyReportImport.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def import_summary(self, *, import_id: int) -> WbDailyReportImportSummary:
        row_status = func.coalesce(WbDailyReportRow.row_status, "new")
        operation_text = func.lower(
            func.concat(
                func.coalesce(WbDailyReportRow.doc_type_name, ""),
                " ",
                func.coalesce(WbDailyReportRow.payment_reason, ""),
            )
        )
        sales_case = operation_text.not_like("%возврат%")
        returns_case = operation_text.like("%возврат%")
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(WbDailyReportRow.retail_amount).filter(sales_case), 0),
                func.coalesce(func.sum(WbDailyReportRow.retail_amount).filter(returns_case), 0),
                func.coalesce(func.sum(WbDailyReportRow.for_pay), 0),
                func.coalesce(func.sum(WbDailyReportRow.commission_rub), 0),
                func.coalesce(func.sum(WbDailyReportRow.delivery_rub), 0),
                func.coalesce(func.sum(WbDailyReportRow.storage_fee), 0),
                func.coalesce(func.sum(WbDailyReportRow.deduction), 0),
                func.coalesce(func.sum(WbDailyReportRow.penalty), 0),
                func.coalesce(func.sum(WbDailyReportRow.acceptance), 0),
                func.count(func.distinct(WbDailyReportRow.shk)).filter(
                    WbDailyReportRow.shk.is_not(None)
                ),
                func.coalesce(func.sum(WbDailyReportRow.quantity).filter(sales_case), 0),
                func.coalesce(func.sum(WbDailyReportRow.quantity).filter(returns_case), 0),
                func.count(func.distinct(WbDailyReportRow.nm_id)).filter(
                    WbDailyReportRow.nm_id.is_not(None)
                ),
                func.count(func.distinct(WbDailyReportRow.supplier_article)).filter(
                    WbDailyReportRow.supplier_article.is_not(None)
                ),
                func.count(WbDailyReportRow.id).filter(row_status.in_(("new", "partial"))),
                func.count(WbDailyReportRow.id).filter(row_status.in_(("error", "skipped"))),
                func.count(WbDailyReportRow.id).filter(WbDailyReportRow.linked_product_id.is_not(None)),
                func.count(WbDailyReportRow.id).filter(WbDailyReportRow.linked_product_id.is_(None)),
                func.count(WbDailyReportRow.id).filter(WbDailyReportRow.linked_order_id.is_not(None)),
                func.count(WbDailyReportRow.id).filter(WbDailyReportRow.linked_order_id.is_(None)),
            ).where(WbDailyReportRow.import_id == import_id)
        )
        values = result.one()
        duplicate_result = await self.session.execute(
            select(func.count(WbDailyReportImportRowLog.id)).where(
                WbDailyReportImportRowLog.import_id == import_id,
                WbDailyReportImportRowLog.status == "duplicate",
            )
        )
        reason_expr = func.coalesce(
            WbDailyReportImportRowLog.skip_reason,
            "Без причины",
        ).label("reason")
        reasons_subquery = (
            select(
                WbDailyReportImportRowLog.id.label("row_log_id"),
                reason_expr,
            )
            .where(WbDailyReportImportRowLog.import_id == import_id)
            .where(WbDailyReportImportRowLog.status != "new")
            .subquery()
        )
        reasons_count = func.count(reasons_subquery.c.row_log_id)
        reasons_result = await self.session.execute(
            select(
                reasons_subquery.c.reason,
                reasons_count,
            )
            .group_by(reasons_subquery.c.reason)
            .order_by(reasons_count.desc())
        )
        return WbDailyReportImportSummary(
            sales_amount=_decimal(values[0]),
            returns_amount=_decimal(values[1]),
            payout_amount=_decimal(values[2]),
            commission_amount=_decimal(values[3]),
            logistics_amount=_decimal(values[4]),
            storage_amount=_decimal(values[5]),
            deductions_amount=_decimal(values[6]),
            penalties_amount=_decimal(values[7]),
            acceptance_amount=_decimal(values[8]),
            orders_count=int(values[9] or 0),
            sales_count=int(values[10] or 0),
            returns_count=int(values[11] or 0),
            unique_nm_ids=int(values[12] or 0),
            unique_articles=int(values[13] or 0),
            recognized_rows=int(values[14] or 0),
            unrecognized_rows=int(values[15] or 0),
            linked_products=int(values[16] or 0),
            unlinked_products=int(values[17] or 0),
            linked_orders=int(values[18] or 0),
            unlinked_orders=int(values[19] or 0),
            duplicate_rows=int(duplicate_result.scalar_one() or 0),
            skip_reasons=[(str(reason), int(count or 0)) for reason, count in reasons_result.all()],
        )

    async def list_rows(
        self,
        *,
        import_id: int,
        filters: WbDailyReportRowFilters,
        page: int,
        per_page: int,
    ) -> WbDailyReportRowsPage:
        query = select(WbDailyReportRow).where(WbDailyReportRow.import_id == import_id)
        query = _apply_row_filters(query, filters)
        count_result = await self.session.execute(
            select(func.count()).select_from(query.subquery())
        )
        total_count = int(count_result.scalar_one() or 0)
        page = max(1, page)
        per_page = max(10, min(per_page, 100))
        total_pages = max(1, (total_count + per_page - 1) // per_page)
        result = await self.session.execute(
            query.order_by(WbDailyReportRow.sale_dt.desc().nullslast(), WbDailyReportRow.id.desc())
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return WbDailyReportRowsPage(
            rows=list(result.scalars().all()),
            total_count=total_count,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        )

    async def _insert_batch(
        self,
        *,
        user_id: int,
        account: MarketplaceAccount,
        import_id: int,
        report_number: str,
        report_type: str,
        report_period_start: object,
        report_period_end: object,
        batch: list[WbDailyReportParsedRow],
    ) -> int:
        hashes = [row.compute_hash() for row in batch]
        existing_hashes = await self._existing_hashes(
            account_id=account.id,
            report_number=report_number,
            report_type=report_type,
            hashes=hashes,
        )
        product_map = await self._product_links(user_id=user_id, account_id=account.id, rows=batch)
        order_map = await self._order_links(user_id=user_id, account_id=account.id, rows=batch)
        values: list[dict[str, object]] = []
        logs: list[WbDailyReportImportRowLog] = []
        for row in batch:
            row_hash = row.compute_hash()
            product_link = _resolve_product_link(row, product_map)
            order_link = _resolve_order_link(row, order_map)
            if row_hash in existing_hashes:
                logs.append(
                    WbDailyReportImportRowLog(
                        import_id=import_id,
                        row_number=row.row_number,
                        source_hash=row_hash,
                        status=DEDUP_DUPLICATE,
                        skip_reason=(
                            "Дубль: строка с таким ключом уже есть в этом отчёте WB"
                        ),
                        normalized_payload=row.raw,
                    )
                )
                continue
            logs.append(
                WbDailyReportImportRowLog(
                    import_id=import_id,
                    row_number=row.row_number,
                    source_hash=row_hash,
                    status="new",
                    normalized_payload=row.raw,
                )
            )
            values.append(
                {
                    "import_id": import_id,
                    "user_id": user_id,
                    "marketplace_account_id": account.id,
                    "report_number": report_number,
                    "report_type": report_type,
                    "report_period_start": report_period_start,
                    "report_period_end": report_period_end,
                    "row_hash": row_hash,
                    "row_number": row.row_number,
                    "sale_dt": row.sale_dt,
                    "order_dt": row.order_dt,
                    "nm_id": row.nm_id,
                    "supplier_article": row.supplier_article,
                    "product_name": row.product_name,
                    "size": row.size,
                    "barcode": row.barcode,
                    "shk": row.shk,
                    "srid": row.srid,
                    "linked_order_id": order_link.id,
                    "linked_product_id": product_link.id,
                    "doc_type_name": row.doc_type_name,
                    "payment_reason": row.payment_reason,
                    "subject_name": row.subject_name,
                    "brand_name": row.brand_name,
                    "quantity": row.quantity,
                    "retail_price": row.retail_price,
                    "retail_amount": row.retail_amount,
                    "for_pay": row.for_pay,
                    "delivery_count": row.delivery_count,
                    "return_count": row.return_count,
                    "delivery_rub": row.delivery_rub,
                    "penalty": row.penalty,
                    "storage_fee": row.storage_fee,
                    "acceptance": row.acceptance,
                    "deduction": row.deduction,
                    "commission_rub": row.commission_rub,
                    "commission_correction_amount": row.commission_correction_amount,
                    "reimbursement_amount": row.reimbursement_amount,
                    "logistics_penalty_correction_type": row.logistics_penalty_correction_type,
                    "basket_id": row.basket_id,
                    "sale_method": row.sale_method,
                    "product_match_status": product_link.status,
                    "order_match_status": order_link.status,
                    "product_match_method": product_link.method,
                    "order_match_method": order_link.method,
                    "finance_operation_type": row.finance_operation_type,
                    "finance_category": row.finance_category,
                    "row_status": _row_status(product_link, order_link),
                    "skip_reason": _row_reason(product_link, order_link),
                    "raw_json": row.raw,
                }
            )

        self.session.add_all(logs)
        if not values:
            return 0
        insert_stmt = pg_insert(WbDailyReportRow).values(values)
        insert_stmt = insert_stmt.on_conflict_do_nothing(
            index_elements=["marketplace_account_id", "report_type", "report_number", "row_hash"]
        )
        result = await self.session.execute(insert_stmt)
        return result.rowcount or 0

    async def _existing_hashes(
        self,
        *,
        account_id: int,
        report_number: str,
        report_type: str,
        hashes: list[str],
    ) -> set[str]:
        if not hashes:
            return set()
        result = await self.session.execute(
            select(WbDailyReportRow.row_hash).where(
                WbDailyReportRow.marketplace_account_id == account_id,
                WbDailyReportRow.report_type == report_type,
                WbDailyReportRow.report_number == report_number,
                WbDailyReportRow.row_hash.in_(hashes),
            )
        )
        return {str(value) for value in result.scalars().all()}

    async def _product_links(
        self,
        *,
        user_id: int,
        account_id: int,
        rows: list[WbDailyReportParsedRow],
    ) -> dict[tuple[str, str], list[int]]:
        barcodes = {row.barcode for row in rows if row.barcode}
        nm_ids = {str(row.nm_id) for row in rows if row.nm_id is not None}
        articles = {row.supplier_article for row in rows if row.supplier_article}
        if not barcodes and not nm_ids and not articles:
            return {}
        result = await self.session.execute(
            select(
                Product.id,
                Product.barcode,
                Product.external_product_id,
                Product.marketplace_article,
                Product.seller_article,
            ).where(
                Product.user_id == user_id,
                Product.marketplace_account_id == account_id,
                Product.marketplace == Marketplace.WB,
            )
        )
        mapping: dict[tuple[str, str], list[int]] = {}
        for product_id, barcode, external_id, marketplace_article, seller_article in result.all():
            for key, value in (
                ("barcode", barcode),
                ("nm_id", external_id),
                ("nm_id", marketplace_article),
                ("supplier_article", seller_article),
            ):
                if value is None:
                    continue
                text = str(value).strip()
                if not text:
                    continue
                if key == "barcode" and text not in barcodes:
                    continue
                if key == "nm_id" and text not in nm_ids:
                    continue
                if key == "supplier_article" and text not in articles:
                    continue
                mapping.setdefault((key, text), []).append(int(product_id))
        return mapping

    async def _order_links(
        self,
        *,
        user_id: int,
        account_id: int,
        rows: list[WbDailyReportParsedRow],
    ) -> dict[tuple[str, str], list[int]]:
        srids = {row.srid for row in rows if row.srid}
        shks = {row.shk for row in rows if row.shk}
        if not srids and not shks:
            return {}
        result = await self.session.execute(
            select(Order.srid, Order.order_external_id, Order.posting_number, Order.id).where(
                Order.user_id == user_id,
                Order.marketplace_account_id == account_id,
                Order.marketplace == Marketplace.WB,
            )
        )
        mapping: dict[tuple[str, str], list[int]] = {}
        for srid, order_external_id, posting_number, order_id in result.all():
            for key, value in (
                ("srid", srid),
                ("shk", order_external_id),
                ("shk", posting_number),
            ):
                if value is None:
                    continue
                text = str(value).strip()
                if not text:
                    continue
                if key == "srid" and text not in srids:
                    continue
                if key == "shk" and text not in shks:
                    continue
                mapping.setdefault((key, text), []).append(int(order_id))
        return mapping

    async def _record_duplicate(
        self,
        *,
        user_id: int,
        account: MarketplaceAccount,
        parsed: WbDailyReportParsed,
        file_hash: str,
        original_filename: str | None,
        source_type: str,
    ) -> WbDailyReportImportResult:
        record = WbDailyReportImport(
            user_id=user_id,
            marketplace_account_id=account.id,
            source_type=source_type,
            report_type=parsed.report_type,
            original_filename=original_filename,
            report_number=parsed.report_number,
            report_date=parsed.report_date,
            report_period_start=parsed.report_period_start,
            report_period_end=parsed.report_period_end,
            file_hash=file_hash,
            rows_total=len(parsed.rows),
            rows_inserted=0,
            rows_skipped=len(parsed.rows),
            status="duplicate",
            error_message="Этот файл уже загружался ранее. Новые строки не создавались.",
        )
        self.session.add(record)
        await self.session.flush()
        self.session.add_all(
            WbDailyReportImportRowLog(
                import_id=record.id,
                row_number=row.row_number,
                source_hash=row.compute_hash(),
                status=DEDUP_DUPLICATE,
                skip_reason="Дубль: файл с таким хешем уже загружался",
                normalized_payload=row.raw,
            )
            for row in parsed.rows
        )
        record.updated_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(record)
        logger.info(
            "wb_daily_report_duplicate_file",
            extra={
                "import_id": record.id,
                "user_id": user_id,
                "account_id": account.id,
                "rows_skipped": len(parsed.rows),
            },
        )

        return WbDailyReportImportResult(
            import_id=record.id,
            report_number=record.report_number,
            rows_total=record.rows_total,
            rows_inserted=0,
            rows_skipped=len(parsed.rows),
            is_duplicate=True,
        )


def _resolve_product_link(
    row: WbDailyReportParsedRow,
    mapping: dict[tuple[str, str], list[int]],
) -> _LinkedEntity:
    for method, value in (
        ("barcode", row.barcode),
        ("nm_id", str(row.nm_id) if row.nm_id is not None else None),
        ("supplier_article", row.supplier_article),
    ):
        if not value:
            continue
        ids = sorted(set(mapping.get((method, value), [])))
        if len(ids) == 1:
            return _LinkedEntity(id=ids[0], status="matched", method=method)
        if len(ids) > 1:
            return _LinkedEntity(
                id=None,
                status="ambiguous_match",
                method=method,
                reason=f"Неоднозначное сопоставление товара по {method}",
            )
    return _LinkedEntity(
        id=None,
        status="product_not_found",
        reason="Товар не найден по barcode, nm_id и артикулу продавца",
    )


def _resolve_order_link(
    row: WbDailyReportParsedRow,
    mapping: dict[tuple[str, str], list[int]],
) -> _LinkedEntity:
    for method, value in (("srid", row.srid), ("shk", row.shk)):
        if not value:
            continue
        ids = sorted(set(mapping.get((method, value), [])))
        if len(ids) == 1:
            return _LinkedEntity(id=ids[0], status="matched", method=method)
        if len(ids) > 1:
            return _LinkedEntity(
                id=None,
                status="ambiguous_match",
                method=method,
                reason=f"Неоднозначное сопоставление заказа по {method}",
            )
    return _LinkedEntity(
        id=None,
        status="order_not_found",
        reason="Заказ не найден по Srid или ШК",
    )


def _row_status(product_link: _LinkedEntity, order_link: _LinkedEntity) -> str:
    if "ambiguous_match" in {product_link.status, order_link.status}:
        return "skipped"
    if product_link.id is None:
        return "skipped"
    if order_link.id is None:
        return "partial"
    return "new"


def _row_reason(product_link: _LinkedEntity, order_link: _LinkedEntity) -> str | None:
    if product_link.id is not None and order_link.id is None:
        product_method = {
            "barcode": "barcode",
            "nm_id": "nm_id",
            "supplier_article": "артикулу поставщика",
        }.get(product_link.method or "", product_link.method or "товару")
        return (
            f"Товар найден по {product_method}; "
            "заказ не найден по Srid или ШК, строка учтена по товару"
        )
    reasons = [reason for reason in (product_link.reason, order_link.reason) if reason]
    return "; ".join(reasons) if reasons else None


def _chunked(
    items: Iterable[WbDailyReportParsedRow],
    *,
    size: int,
) -> Iterable[list[WbDailyReportParsedRow]]:
    batch: list[WbDailyReportParsedRow] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _apply_row_filters(query: Any, filters: WbDailyReportRowFilters) -> Any:
    if filters.operation_type:
        query = query.where(WbDailyReportRow.payment_reason == filters.operation_type)
    if filters.nm_id is not None:
        query = query.where(WbDailyReportRow.nm_id == filters.nm_id)
    if filters.supplier_article:
        query = query.where(
            WbDailyReportRow.supplier_article.ilike(f"%{filters.supplier_article}%")
        )
    if filters.barcode:
        query = query.where(WbDailyReportRow.barcode.ilike(f"%{filters.barcode}%"))
    if filters.srid:
        query = query.where(WbDailyReportRow.srid.ilike(f"%{filters.srid}%"))
    if filters.status:
        query = query.where(WbDailyReportRow.row_status == filters.status)
    if filters.date_from:
        query = query.where(func.date(WbDailyReportRow.sale_dt) >= filters.date_from)
    if filters.date_to:
        query = query.where(func.date(WbDailyReportRow.sale_dt) <= filters.date_to)
    if filters.amount_from is not None:
        query = query.where(WbDailyReportRow.for_pay >= filters.amount_from)
    if filters.amount_to is not None:
        query = query.where(WbDailyReportRow.for_pay <= filters.amount_to)
    if filters.linked_order == "yes":
        query = query.where(WbDailyReportRow.linked_order_id.is_not(None))
    elif filters.linked_order == "no":
        query = query.where(WbDailyReportRow.linked_order_id.is_(None))
    if filters.linked_product == "yes":
        query = query.where(WbDailyReportRow.linked_product_id.is_not(None))
    elif filters.linked_product == "no":
        query = query.where(WbDailyReportRow.linked_product_id.is_(None))
    if filters.search:
        pattern = f"%{filters.search}%"
        query = query.where(
            WbDailyReportRow.supplier_article.ilike(pattern)
            | WbDailyReportRow.barcode.ilike(pattern)
            | WbDailyReportRow.shk.ilike(pattern)
            | WbDailyReportRow.srid.ilike(pattern)
            | WbDailyReportRow.doc_type_name.ilike(pattern)
            | WbDailyReportRow.payment_reason.ilike(pattern)
        )
    return query


def _decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
