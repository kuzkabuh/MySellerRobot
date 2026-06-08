"""Regression tests for WB daily report duplicate upload handling.

Verifies that re-importing the same report produces no IntegrityError,
correctly categorizes rows as unchanged/updated/new, and after a
failed flush the MissingGreenlet is avoided by using scalar values.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.domain import WbDailyReportRow
from app.services.wb_daily_report_import_service import (
    WbDailyReportImportService,
)
from app.services.wb_daily_report_parser import WbDailyReportParsed, WbDailyReportParsedRow


def _mock_row(
    *,
    row_number: int = 1,
    nm_id: int = 303906114,
    barcode: str = "2042291607481",
    supplier_article: str = "w4005",
    retail_amount: str = "1500.00",
) -> WbDailyReportParsedRow:
    raw = {
        "row_number": row_number,
        "nm_id": nm_id,
        "barcode": barcode,
        "supplier_article": supplier_article,
        "retail_amount": retail_amount,
        "for_pay": "1200.00",
        "commission_rub": "300.00",
        "delivery_rub": "50.00",
    }
    return WbDailyReportParsedRow(
        row_number=row_number,
        report_type="weekly",
        sale_dt=None,
        order_dt=None,
        nm_id=nm_id,
        supplier_article=supplier_article,
        product_name="Test",
        size=None,
        barcode=barcode,
        shk="SHK123",
        srid="SRID123",
        srid_normalized="srid123",
        rid_normalized="rid123",
        doc_type_name=None,
        payment_reason="Продажа",
        subject_name=None,
        brand_name=None,
        quantity=1,
        retail_price=None,
        retail_amount=None,
        for_pay=None,
        delivery_count=None,
        return_count=None,
        delivery_rub=None,
        penalty=None,
        storage_fee=None,
        acceptance=None,
        deduction=None,
        commission_rub=None,
        commission_correction_amount=None,
        reimbursement_amount=None,
        logistics_penalty_correction_type=None,
        basket_id=None,
        sale_method=None,
        finance_operation_type="sale",
        finance_category="revenue",
        order_required=True,
        raw=raw,
    )


def _as_scalars(rows: list) -> MagicMock:
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars_mock
    return result


@pytest.mark.asyncio
async def test_insert_batch_finds_existing_by_stable_key() -> None:
    """Given a row previously imported, _insert_batch should find it by stable_business_key
    and mark it as unchanged when the source hash matches."""
    parsed_row = _mock_row()
    source_hash = parsed_row.compute_source_row_hash()
    stable_key = parsed_row.compute_stable_business_key(
        marketplace_account_id=1,
        report_number="RPT001",
    )

    existing_db_row = WbDailyReportRow(
        id=100,
        stable_business_key=stable_key,
        row_hash=source_hash,
        source_row_hash=source_hash,
        marketplace_account_id=1,
        report_type="weekly",
        report_number="RPT001",
        deleted_at=None,
    )

    session = AsyncMock()
    session.execute.return_value = _as_scalars([existing_db_row])

    service = WbDailyReportImportService(session)
    account = MagicMock()
    account.id = 1

    result = await service._insert_batch(
        user_id=1,
        account=account,
        import_id=10,
        report_number="RPT001",
        report_type="weekly",
        report_period_start=None,
        report_period_end=None,
        batch=[parsed_row],
    )

    assert result["created"] == 0
    assert result["updated"] == 0
    assert result["unchanged"] == 1


@pytest.mark.asyncio
async def test_insert_batch_updates_changed_row() -> None:
    """When stable_key matches but source_hash differs, the row should be updated."""
    parsed_row = _mock_row(retail_amount="2000.00")
    old_hash = "old_hash_that_differs"
    stable_key = parsed_row.compute_stable_business_key(
        marketplace_account_id=1,
        report_number="RPT001",
    )

    existing_db_row = WbDailyReportRow(
        id=100,
        stable_business_key=stable_key,
        row_hash=old_hash,
        source_row_hash=old_hash,
        raw_json={},
        version=1,
        marketplace_account_id=1,
        report_type="weekly",
        report_number="RPT001",
        deleted_at=None,
    )

    session = AsyncMock()
    session.execute.return_value = _as_scalars([existing_db_row])

    service = WbDailyReportImportService(session)
    account = MagicMock()
    account.id = 1

    result = await service._insert_batch(
        user_id=1,
        account=account,
        import_id=10,
        report_number="RPT001",
        report_type="weekly",
        report_period_start=None,
        report_period_end=None,
        batch=[parsed_row],
    )

    assert result["created"] == 0
    assert result["updated"] == 1
    assert result["unchanged"] == 0


@pytest.mark.asyncio
async def test_insert_batch_creates_new_row_when_not_found() -> None:
    """When no existing row matches stable_key or hash, a new row is created."""
    parsed_row = _mock_row()

    session = AsyncMock()
    session.execute.return_value = _as_scalars([])

    service = WbDailyReportImportService(session)
    account = MagicMock()
    account.id = 1

    result = await service._insert_batch(
        user_id=1,
        account=account,
        import_id=10,
        report_number="RPT001",
        report_type="weekly",
        report_period_start=None,
        report_period_end=None,
        batch=[parsed_row],
    )

    assert result["created"] == 1
    assert result["updated"] == 0
    assert result["unchanged"] == 0


@pytest.mark.asyncio
async def test_insert_batch_finds_existing_by_row_hash_fallback() -> None:
    """For pre-migration rows without stable_business_key, fallback by row_hash."""
    parsed_row = _mock_row()
    source_hash = parsed_row.compute_source_row_hash()

    # Simulate that the row exists but with NULL stable_business_key (pre-0060 migration)
    existing_no_stable_key = WbDailyReportRow(
        id=100,
        stable_business_key=None,
        row_hash=source_hash,
        source_row_hash=source_hash,
        marketplace_account_id=1,
        report_type="weekly",
        report_number="RPT001",
        deleted_at=None,
    )

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _as_scalars([]),  # _product_links (barcodes/nms check, no results)
            _as_scalars([]),  # _order_links
            _as_scalars([]),  # stable_business_key batch query → empty
            _as_scalars([existing_no_stable_key]),  # row_hash fallback query → finds it
        ]
    )

    service = WbDailyReportImportService(session)
    account = MagicMock()
    account.id = 1

    result = await service._insert_batch(
        user_id=1,
        account=account,
        import_id=10,
        report_number="RPT001",
        report_type="weekly",
        report_period_start=None,
        report_period_end=None,
        batch=[parsed_row],
    )

    assert result["created"] == 0
    assert result["updated"] == 0
    assert result["unchanged"] == 1


@pytest.mark.asyncio
async def test_import_parsed_uses_scalar_values_after_integrity_error() -> None:
    """After an IntegrityError and rollback, import_parsed uses scalar values
    to avoid MissingGreenlet on expired ORM attributes."""
    parsed = WbDailyReportParsed(
        report_type="weekly",
        report_number="RPT001",
        report_date=None,
        report_period_start=None,
        report_period_end=None,
        skipped_rows=0,
        rows=[_mock_row()],
    )

    session = AsyncMock()
    # First flush creates the import_record, second raises (within _insert_batch)
    session.flush = AsyncMock(side_effect=[None, IntegrityError("mock", None, None)])
    session.execute.return_value = _as_scalars([])

    service = WbDailyReportImportService(session)
    account = MagicMock()
    account.id = 42

    with pytest.raises(IntegrityError):
        await service.import_parsed(
            user_id=1,
            marketplace_account=account,
            parsed=parsed,
            file_hash="abc123",
            original_filename="test.xlsx",
        )

    # Verify session.rollback was called
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_mixed_batch_correctly_categorizes_rows() -> None:
    """A batch with unchanged, updated, and new rows each get correct counters."""
    row_unchanged = _mock_row(row_number=1, nm_id=100, barcode="b1")
    row_updated = _mock_row(row_number=2, nm_id=200, barcode="b2", retail_amount="5000.00")
    row_new = _mock_row(row_number=3, nm_id=300, barcode="b3")

    hash_unchanged = row_unchanged.compute_source_row_hash()
    key_unchanged = row_unchanged.compute_stable_business_key(
        marketplace_account_id=1, report_number="RPT001",
    )
    key_updated = row_updated.compute_stable_business_key(
        marketplace_account_id=1, report_number="RPT001",
    )

    existing_unchanged = WbDailyReportRow(
        id=1, stable_business_key=key_unchanged, row_hash=hash_unchanged,
        source_row_hash=hash_unchanged, raw_json={}, version=1,
        marketplace_account_id=1, report_type="weekly", report_number="RPT001",
        deleted_at=None,
    )
    existing_updated = WbDailyReportRow(
        id=2, stable_business_key=key_updated, row_hash=hash_unchanged,
        source_row_hash=hash_unchanged, raw_json={}, version=1,
        marketplace_account_id=1, report_type="weekly", report_number="RPT001",
        deleted_at=None,
    )

    session = AsyncMock()
    session.execute.return_value = _as_scalars([existing_unchanged, existing_updated])

    service = WbDailyReportImportService(session)
    account = MagicMock()
    account.id = 1

    result = await service._insert_batch(
        user_id=1,
        account=account,
        import_id=10,
        report_number="RPT001",
        report_type="weekly",
        report_period_start=None,
        report_period_end=None,
        batch=[row_unchanged, row_updated, row_new],
    )

    # existing_unchanged: hash matches → unchanged
    # existing_updated: imported row hash differs from stored → updated
    # row_new: no existing match → created
    assert result["created"] == 1
    assert result["updated"] == 1
    assert result["unchanged"] == 1
