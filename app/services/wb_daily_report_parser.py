"""version: 1.0.0
description: Robust XLSX parser for WB daily realisation reports.
updated: 2026-06-07
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

logger = logging.getLogger(__name__)

REPORT_NUMBER_PATTERN = re.compile(
    r"(\d{8,})_(?P<supplier>\d+)", re.IGNORECASE
)


@dataclass(slots=True)
class WbDailyReportParsed:
    report_number: str
    report_date: date | None
    rows: list[WbDailyReportParsedRow] = field(default_factory=list)
    skipped_rows: int = 0


@dataclass(slots=True)
class WbDailyReportParsedRow:
    row_number: int | None
    sale_dt: datetime | None
    order_dt: datetime | None
    nm_id: int | None
    supplier_article: str | None
    barcode: str | None
    srid: str | None
    doc_type_name: str | None
    subject_name: str | None
    brand_name: str | None
    quantity: int | None
    retail_price: Decimal | None
    retail_amount: Decimal | None
    for_pay: Decimal | None
    delivery_rub: Decimal | None
    penalty: Decimal | None
    storage_fee: Decimal | None
    acceptance: Decimal | None
    deduction: Decimal | None
    commission_rub: Decimal | None
    raw: dict[str, object]

    def compute_hash(self) -> str:
        payload = {
            "report_number": _stable_string(self.raw.get("report_number")),
            "row_number": self.row_number,
            "nm_id": self.nm_id,
            "supplier_article": _stable_string(self.supplier_article),
            "barcode": _stable_string(self.barcode),
            "srid": _stable_string(self.srid),
            "doc_type_name": _stable_string(self.doc_type_name),
            "sale_dt": self.sale_dt.isoformat() if self.sale_dt else None,
            "order_dt": self.order_dt.isoformat() if self.order_dt else None,
            "quantity": self.quantity,
            "retail_price": _stable_decimal(self.retail_price),
            "for_pay": _stable_decimal(self.for_pay),
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


COLUMN_ALIASES: dict[str, str] = {
    "№": "row_number",
    "Номер поставки": "report_number",
    "Номер отчёта": "report_number",
    "Предмет": "subject_name",
    "Код номенклатуры": "nm_id",
    "Бренд": "brand_name",
    "Артикул поставщика": "supplier_article",
    "Название": "subject_name",
    "Размер": "size",
    "Баркод": "barcode",
    "Srid": "srid",
    "SRID": "srid",
    "srid": "srid",
    "Тип документа": "doc_type_name",
    "Обоснование для оплаты": "doc_type_name",
    "Дата заказа покупателем": "order_dt",
    "Дата продажи": "sale_dt",
    "Кол-во": "quantity",
    "Цена розничная": "retail_price",
    "Вайлдберриз реализовал Товар (Пр)": "for_pay",
    "Согласованный продуктовый дисконт, %": "agreed_product_discount",
    "Промокод, %": "promo_discount",
    "Итоговая согласованная скидка, %": "final_discount",
    "Цена розничная с учетом согласованной скидки": "retail_amount",
    "Скидка постоянного покупателя, %": "loyalty_discount",
    "Скидка продавца, %": "seller_discount",
    "Комиссия, %": "commission_percent",
    "Размер комиссии": "commission_rub",
    "Стоимость логистики": "delivery_rub",
    "Стоимость хранения": "storage_fee",
    "Стоимость приёмки": "acceptance",
    "Удержание": "deduction",
    "Штраф": "penalty",
}

DATE_KEYS = {"order_dt", "sale_dt"}


def iter_wb_daily_report_rows(
    xlsx_bytes: bytes,
    *,
    max_rows: int = 200_000,
    report_number_hint: str | None = None,
) -> WbDailyReportParsed:
    """Parse a WB daily realisation-report XLSX file.

    Returns a WbDailyReportParsed object with the detected report number and
    normalized rows. The function uses openpyxl's read_only mode and falls
    back to ``worksheet.reset_dimensions()`` for files where the stored
    ``dimension = A1`` does not reflect the real data extent.
    """
    workbook = load_workbook(BytesIO(xlsx_bytes), read_only=True, data_only=True)
    worksheet = workbook.active
    if worksheet is None:
        raise ValueError("В файле отчёта WB нет активного листа")

    try:
        worksheet.reset_dimensions()
    except Exception:
        logger.debug("ws_reset_dimensions_failed", exc_info=True)

    rows_iter = worksheet.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        raise ValueError("Файл отчёта WB пустой или не содержит заголовки") from None

    headers = [_stringify(cell) for cell in header_row]
    if not any(headers):
        raise ValueError("Файл отчёта WB пустой или не содержит заголовки")

    mapped_columns = [_resolve_column(header) for header in headers]

    report_number: str | None = _valid_report_number(report_number_hint)
    report_date: date | None = None
    parsed_rows: list[WbDailyReportParsedRow] = []
    skipped = 0
    row_index = 0

    for raw_row in rows_iter:
        row_index += 1
        if row_index > max_rows:
            logger.warning("wb_daily_report_row_limit_exceeded", extra={"max_rows": max_rows})
            break
        if raw_row is None or all(cell is None for cell in raw_row):
            continue

        record: dict[str, object] = {}
        for column, cell in zip(mapped_columns, raw_row, strict=False):
            if not column:
                continue
            record[column] = cell

        if "report_number" in record and not report_number:
            report_number = _valid_report_number(record.get("report_number"))
        if "sale_dt" in record and not report_date:
            sale_dt = _coerce_datetime(record.get("sale_dt"))
            if sale_dt is not None:
                report_date = sale_dt.date()

        if report_number is None and row_index == 1:
            match = REPORT_NUMBER_PATTERN.search(_stringify(raw_row[0]) or "")
            if match:
                report_number = f"{match.group(1)}_{match.group('supplier')}"

        if not record:
            skipped += 1
            continue

        if report_number is not None:
            record["report_number"] = report_number

        try:
            parsed = _build_row(record, row_index + 1)
        except Exception:
            logger.exception(
                "wb_daily_report_row_parse_failed",
                extra={"row_index": row_index},
            )
            skipped += 1
            continue
        parsed_rows.append(parsed)

    if report_number is None:
        raise ValueError(
            "Не удалось определить номер отчёта WB. "
            "Проверьте, что файл содержит колонку «Номер поставки»."
        )

    return WbDailyReportParsed(
        report_number=report_number,
        report_date=report_date,
        rows=parsed_rows,
        skipped_rows=skipped,
    )


def parse_wb_daily_report_file(
    uploaded_path: Path,
    *,
    max_bytes: int = 50 * 1024 * 1024,
) -> WbDailyReportParsed:
    """Read an uploaded file, transparently handling ZIP-wrapped XLSX archives."""
    if not uploaded_path.exists():
        raise FileNotFoundError(f"Файл {uploaded_path} не найден")
    raw_bytes = uploaded_path.read_bytes()
    if len(raw_bytes) > max_bytes:
        raise ValueError("Файл превышает допустимый размер 50 МБ")

    return parse_wb_daily_report_upload(
        raw_bytes,
        filename=uploaded_path.name,
        max_bytes=max_bytes,
    )


def parse_wb_daily_report_upload(
    payload: bytes,
    *,
    filename: str,
    max_bytes: int = 50 * 1024 * 1024,
) -> WbDailyReportParsed:
    """Parse uploaded XLSX bytes or a ZIP archive containing one XLSX report."""
    if len(payload) > max_bytes:
        raise ValueError("Файл превышает допустимый размер 50 МБ")

    suffix = Path(filename).suffix.lower()
    report_number_hint = _report_number_from_filename(filename)

    if suffix == ".zip":
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            xlsx_name = _find_xlsx_in_zip(archive)
            with archive.open(xlsx_name) as xlsx_file:
                xlsx_bytes = xlsx_file.read()
        return iter_wb_daily_report_rows(
            xlsx_bytes,
            report_number_hint=report_number_hint or _report_number_from_filename(xlsx_name),
        )

    if suffix == ".xlsx":
        return iter_wb_daily_report_rows(
            payload,
            report_number_hint=report_number_hint,
        )

    raise ValueError("Поддерживаются только файлы .xlsx или .zip")


def compute_file_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _find_xlsx_in_zip(archive: zipfile.ZipFile) -> str:
    candidates = [
        name
        for name in archive.namelist()
        if name.lower().endswith(".xlsx") and not name.endswith("/")
    ]
    if not candidates:
        raise ValueError("В ZIP-архиве не найден XLSX-файл отчёта WB")
    candidates.sort()
    return candidates[0]


def _report_number_from_filename(filename: str) -> str | None:
    match = REPORT_NUMBER_PATTERN.search(filename)
    if not match:
        return None
    return f"{match.group(1)}_{match.group('supplier')}"


def _valid_report_number(value: object) -> str | None:
    text = _stringify(value)
    if not text or text in {"0", "0.0", "-"}:
        return None
    return text


def _resolve_column(header: str) -> str | None:
    cleaned = header.strip()
    if not cleaned:
        return None
    if cleaned in COLUMN_ALIASES:
        return COLUMN_ALIASES[cleaned]
    lowered = cleaned.lower()
    for source, target in COLUMN_ALIASES.items():
        if source.lower() == lowered:
            return target
    return None


def _build_row(record: dict[str, object], row_number: int) -> WbDailyReportParsedRow:
    sale_dt = _coerce_datetime(record.get("sale_dt")) if "sale_dt" in record else None
    order_dt = _coerce_datetime(record.get("order_dt")) if "order_dt" in record else None
    nm_id = _coerce_int(record.get("nm_id")) if "nm_id" in record else None
    quantity = _coerce_int(record.get("quantity")) if "quantity" in record else None

    return WbDailyReportParsedRow(
        row_number=_coerce_int(record.get("row_number"), default=row_number),
        sale_dt=sale_dt,
        order_dt=order_dt,
        nm_id=nm_id,
        supplier_article=_stringify(record.get("supplier_article")) or None,
        barcode=_stringify(record.get("barcode")) or None,
        srid=_stringify(record.get("srid")) or None,
        doc_type_name=_stringify(record.get("doc_type_name")) or None,
        subject_name=_stringify(record.get("subject_name")) or None,
        brand_name=_stringify(record.get("brand_name")) or None,
        quantity=quantity,
        retail_price=_coerce_decimal(record.get("retail_price")),
        retail_amount=_coerce_decimal(record.get("retail_amount")),
        for_pay=_coerce_decimal(record.get("for_pay")),
        delivery_rub=_coerce_decimal(record.get("delivery_rub")),
        penalty=_coerce_decimal(record.get("penalty")),
        storage_fee=_coerce_decimal(record.get("storage_fee")),
        acceptance=_coerce_decimal(record.get("acceptance")),
        deduction=_coerce_decimal(record.get("deduction")),
        commission_rub=_coerce_decimal(record.get("commission_rub")),
        raw=record,
    )


def _coerce_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, (int, float)):
        try:
            return from_excel(value)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _coerce_int(value: object, *, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _coerce_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _stable_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _stable_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")
