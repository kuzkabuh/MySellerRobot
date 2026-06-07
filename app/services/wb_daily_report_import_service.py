"""version: 1.0.0
description: Service for importing parsed WB daily realisation reports into the database.
updated: 2026-06-07
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    MarketplaceAccount,
    WbDailyReportImport,
    WbDailyReportRow,
)
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

        import_record = WbDailyReportImport(
            user_id=user_id,
            marketplace_account_id=marketplace_account.id,
            source_type=source_type,
            original_filename=original_filename,
            report_number=parsed.report_number,
            report_date=parsed.report_date,
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
        import_record.rows_skipped = skipped
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
        user_id: int,
        marketplace_account_id: int | None = None,
        limit: int = 50,
    ) -> list[WbDailyReportImport]:
        stmt = (
            select(WbDailyReportImport)
            .where(WbDailyReportImport.user_id == user_id)
            .order_by(WbDailyReportImport.created_at.desc())
            .limit(limit)
        )
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

    async def _insert_batch(
        self,
        *,
        user_id: int,
        account: MarketplaceAccount,
        import_id: int,
        report_number: str,
        batch: list[WbDailyReportParsedRow],
    ) -> int:
        values: list[dict[str, object]] = []
        for row in batch:
            values.append(
                {
                    "import_id": import_id,
                    "user_id": user_id,
                    "marketplace_account_id": account.id,
                    "report_number": report_number,
                    "row_hash": row.compute_hash(),
                    "row_number": row.row_number,
                    "sale_dt": row.sale_dt,
                    "order_dt": row.order_dt,
                    "nm_id": row.nm_id,
                    "supplier_article": row.supplier_article,
                    "barcode": row.barcode,
                    "doc_type_name": row.doc_type_name,
                    "subject_name": row.subject_name,
                    "brand_name": row.brand_name,
                    "quantity": row.quantity,
                    "retail_price": row.retail_price,
                    "retail_amount": row.retail_amount,
                    "for_pay": row.for_pay,
                    "delivery_rub": row.delivery_rub,
                    "penalty": row.penalty,
                    "storage_fee": row.storage_fee,
                    "acceptance": row.acceptance,
                    "deduction": row.deduction,
                    "raw_json": row.raw,
                }
            )

        insert_stmt = pg_insert(WbDailyReportRow).values(values)
        insert_stmt = insert_stmt.on_conflict_do_nothing(
            index_elements=["marketplace_account_id", "report_number", "row_hash"]
        )
        result = await self.session.execute(insert_stmt)
        return result.rowcount or 0

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
        existing = await self.session.execute(
            select(WbDailyReportImport).where(
                WbDailyReportImport.user_id == user_id,
                WbDailyReportImport.marketplace_account_id == account.id,
                WbDailyReportImport.file_hash == file_hash,
            )
        )
        record = existing.scalar_one()
        record.rows_total = max(record.rows_total, len(parsed.rows))
        record.rows_skipped = record.rows_skipped + len(parsed.rows)
        record.updated_at = datetime.now(UTC)
        await self.session.commit()

        return WbDailyReportImportResult(
            import_id=record.id,
            report_number=record.report_number,
            rows_total=record.rows_total,
            rows_inserted=0,
            rows_skipped=len(parsed.rows),
            is_duplicate=True,
        )


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
