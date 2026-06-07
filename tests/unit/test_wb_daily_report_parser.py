"""version: 1.0.0
description: Unit tests for WB daily realisation report XLSX parser.
updated: 2026-06-07
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.services.wb_daily_report_parser import (
    COLUMN_ALIASES,
    WbDailyReportParsed,
    compute_file_hash,
    iter_wb_daily_report_rows,
    parse_wb_daily_report_file,
    parse_wb_daily_report_upload,
)


def _build_xlsx_bytes(
    rows: list[list[object]],
    *,
    dimension: str = "A1",
    inject_dimension_a1: bool = False,
) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    for row in rows:
        worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    payload = buffer.getvalue()
    if inject_dimension_a1:
        payload = _corrupt_dimension_ref(payload)
    return payload


def _corrupt_dimension_ref(payload: bytes) -> bytes:
    """Patch the worksheet XML to set <dimension ref="A1"/> while data is larger."""
    import re

    source = io.BytesIO(payload)
    target = io.BytesIO()
    with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(target, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(
                    rb'<dimension[^/]*ref="[^"]+"',
                    b'<dimension ref="A1"',
                    data,
                    count=1,
                )
            zout.writestr(item, data)
    return target.getvalue()


SAMPLE_HEADERS = [
    "№",
    "Номер поставки",
    "Предмет",
    "Код номенклатуры",
    "Бренд",
    "Артикул поставщика",
    "Название",
    "Размер",
    "Баркод",
    "Тип документа",
    "Дата заказа покупателем",
    "Дата продажи",
    "Кол-во",
    "Цена розничная",
    "Вайлдберриз реализовал Товар (Пр)",
    "Цена розничная с учетом согласованной скидки",
    "Стоимость логистики",
    "Стоимость хранения",
    "Штраф",
]

SAMPLE_ROW_1 = [
    1,
    "433534920260606_4335349",
    "Полотенце",
    123456789,
    "BrandX",
    "ART-001",
    "Полотенце Fresh",
    "M",
    "4600000000001",
    "Продажа",
    "2026-06-05 12:30:00",
    "2026-06-06 09:00:00",
    1,
    1500.0,
    1200.5,
    1350.0,
    50.0,
    10.0,
    0.0,
]

SAMPLE_ROW_2 = [
    2,
    "433534920260606_4335349",
    "Полотенце",
    123456789,
    "BrandX",
    "ART-002",
    "Полотенце Soft",
    "L",
    "4600000000002",
    "Возврат",
    "2026-06-05 14:00:00",
    "2026-06-06 18:00:00",
    -1,
    1500.0,
    -1200.5,
    1350.0,
    0.0,
    0.0,
    100.0,
]


def test_parses_basic_report() -> None:
    payload = _build_xlsx_bytes([SAMPLE_HEADERS, SAMPLE_ROW_1, SAMPLE_ROW_2])
    parsed = iter_wb_daily_report_rows(payload)

    assert isinstance(parsed, WbDailyReportParsed)
    assert parsed.report_number == "433534920260606_4335349"
    assert parsed.report_date is not None
    assert parsed.report_date.isoformat() == "2026-06-06"
    assert len(parsed.rows) == 2
    assert parsed.skipped_rows == 0

    first = parsed.rows[0]
    assert first.nm_id == 123456789
    assert first.supplier_article == "ART-001"
    assert first.barcode == "4600000000001"
    assert first.doc_type_name == "Продажа"
    assert first.quantity == 1
    assert first.retail_price == Decimal("1500.00")
    assert first.for_pay == Decimal("1200.5")
    assert first.delivery_rub == Decimal("50.00")
    assert first.sale_dt is not None
    assert isinstance(first.sale_dt, datetime)


def test_handles_corrupt_dimension_a1() -> None:
    """openpyxl may report dimension=A1 while data is much larger.

    The parser must use ``worksheet.reset_dimensions()`` to recover the real extent.
    """
    payload = _build_xlsx_bytes(
        [SAMPLE_HEADERS, SAMPLE_ROW_1, SAMPLE_ROW_2],
        inject_dimension_a1=True,
    )
    parsed = iter_wb_daily_report_rows(payload)
    assert len(parsed.rows) == 2
    assert parsed.report_number == "433534920260606_4335349"


def test_rejects_empty_workbook() -> None:
    payload = _build_xlsx_bytes([])
    with pytest.raises(ValueError):
        iter_wb_daily_report_rows(payload)


def test_raises_without_report_number() -> None:
    headers = ["№", "Код номенклатуры", "Дата продажи"]
    rows = [headers, [1, 12345, "2026-06-06 10:00:00"]]
    payload = _build_xlsx_bytes(rows)
    with pytest.raises(ValueError, match="Не удалось определить номер отчёта"):
        iter_wb_daily_report_rows(payload)


def test_handles_alternate_column_order() -> None:
    headers = [
        "Номер отчёта",
        "Артикул поставщика",
        "Код номенклатуры",
        "Дата продажи",
        "Кол-во",
        "Цена розничная",
        "Вайлдберриз реализовал Товар (Пр)",
    ]
    row = ["990000120260606_990", "ART-009", 555, "2026-06-06 09:00:00", 2, 999.0, 800.0]
    payload = _build_xlsx_bytes([headers, row])
    parsed = iter_wb_daily_report_rows(payload)
    assert parsed.report_number == "990000120260606_990"
    assert parsed.rows[0].supplier_article == "ART-009"
    assert parsed.rows[0].nm_id == 555
    assert parsed.rows[0].quantity == 2
    assert parsed.rows[0].for_pay == Decimal("800.00")


def test_comma_decimal_normalization() -> None:
    row = list(SAMPLE_ROW_1)
    row[13] = "1 500,50"
    row[14] = "1 200,50"
    row[15] = "1 350,00"
    row[16] = "50,00"
    row[17] = "10,00"
    payload = _build_xlsx_bytes([SAMPLE_HEADERS, row])
    parsed = iter_wb_daily_report_rows(payload)
    assert parsed.rows[0].retail_price == Decimal("1500.50")
    assert parsed.rows[0].for_pay == Decimal("1200.50")


def test_handles_zip_with_xlsx_inside() -> None:
    xlsx_bytes = _build_xlsx_bytes([SAMPLE_HEADERS, SAMPLE_ROW_1])
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.xlsx", xlsx_bytes)
    archive_bytes = archive_buffer.getvalue()

    parsed = parse_wb_daily_report_file(_path_with_bytes(archive_bytes))
    assert parsed.report_number == "433534920260606_4335349"
    assert len(parsed.rows) == 1


def test_parse_file_handles_plain_xlsx_path() -> None:
    xlsx_bytes = _build_xlsx_bytes([SAMPLE_HEADERS, SAMPLE_ROW_1])

    parsed = parse_wb_daily_report_file(_path_with_bytes(xlsx_bytes, suffix=".xlsx"))

    assert parsed.report_number == "433534920260606_4335349"
    assert len(parsed.rows) == 1


def test_parse_upload_uses_filename_report_number_when_column_is_zero() -> None:
    row = list(SAMPLE_ROW_1)
    row[1] = 0
    payload = _build_xlsx_bytes([SAMPLE_HEADERS, row])

    parsed = parse_wb_daily_report_upload(
        payload,
        filename="Ежедневный детализированный отчет №433534920260606_4335349.xlsx",
    )

    assert parsed.report_number == "433534920260606_4335349"
    assert len(parsed.rows) == 1


def test_zip_without_xlsx_raises() -> None:
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("readme.txt", "no xlsx here")
    archive_bytes = archive_buffer.getvalue()

    with pytest.raises(ValueError, match="не найден XLSX-файл"):
        parse_wb_daily_report_file(_path_with_bytes(archive_bytes))


def test_known_columns_have_aliases() -> None:
    expected = {
        "report_number",
        "nm_id",
        "supplier_article",
        "barcode",
        "doc_type_name",
        "sale_dt",
        "order_dt",
        "quantity",
        "retail_price",
        "for_pay",
        "delivery_rub",
        "penalty",
        "storage_fee",
        "retail_amount",
    }
    assert expected.issubset(set(COLUMN_ALIASES.values()))


def test_compute_file_hash_is_stable() -> None:
    payload = b"hello world"
    assert compute_file_hash(payload) == compute_file_hash(payload)


def test_row_hash_dedupes_identical_rows() -> None:
    payload = _build_xlsx_bytes([SAMPLE_HEADERS, SAMPLE_ROW_1])
    parsed = iter_wb_daily_report_rows(payload)
    h1 = parsed.rows[0].compute_hash()

    payload_again = _build_xlsx_bytes([SAMPLE_HEADERS, SAMPLE_ROW_1])
    parsed_again = iter_wb_daily_report_rows(payload_again)
    h2 = parsed_again.rows[0].compute_hash()

    assert h1 == h2
    assert len(h1) == 64


def test_row_hash_differs_for_different_amount() -> None:
    payload = _build_xlsx_bytes([SAMPLE_HEADERS, SAMPLE_ROW_1])
    parsed = iter_wb_daily_report_rows(payload)
    h1 = parsed.rows[0].compute_hash()

    modified_row = list(SAMPLE_ROW_1)
    modified_row[14] = 9999.99
    payload2 = _build_xlsx_bytes([SAMPLE_HEADERS, modified_row])
    parsed2 = iter_wb_daily_report_rows(payload2)
    h2 = parsed2.rows[0].compute_hash()

    assert h1 != h2


def _path_with_bytes(payload: bytes, *, suffix: str = ".zip"):
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkstemp(suffix=suffix)[1])
    tmp.write_bytes(payload)
    return tmp
