"""version: 1.0.0
description: XLSX file validation utilities for commission tariff files.
updated: 2026-05-31
"""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

XLSX_MAGIC_BYTES = b"PK"
MIN_VALID_XLSX_SIZE = 100
HTML_DOCTYPE_PREFIXES = (b"<!doctype", b"<html", b"<!DOCTYPE", b"<HTML")


@dataclass
class XlsxValidationResult:
    valid: bool
    status: str
    message: str | None = None
    file_size: int | None = None
    sheet_names: list[str] | None = None


def validate_xlsx_file(
    path: str | Path | None = None,
    file_bytes: bytes | None = None,
    file_name: str | None = None,
) -> XlsxValidationResult:
    if file_bytes is not None:
        return _validate_bytes(file_bytes, file_name)

    if path is not None:
        p = Path(path)
        if not p.exists():
            return XlsxValidationResult(
                valid=False, status="file_unavailable", message=f"Файл не найден: {p.name}"
            )
        if p.stat().st_size == 0:
            return XlsxValidationResult(valid=False, status="invalid_file", message="Файл пустой")
        try:
            data = p.read_bytes()
        except OSError as exc:
            return XlsxValidationResult(
                valid=False, status="file_unavailable", message=f"Ошибка чтения: {exc}"
            )
        return _validate_bytes(data, p.name)

    return XlsxValidationResult(
        valid=False, status="invalid_file", message="Не указан файл или байты"
    )


def _validate_bytes(data: bytes, file_name: str | None = None) -> XlsxValidationResult:
    size = len(data)

    if size == 0:
        return XlsxValidationResult(
            valid=False, status="invalid_file", message="Файл пустой", file_size=0
        )

    if size < MIN_VALID_XLSX_SIZE:
        return XlsxValidationResult(
            valid=False,
            status="invalid_file",
            message=f"Файл слишком мал ({size} байт)",
            file_size=size,
        )

    if file_name and not file_name.lower().endswith((".xlsx", ".xls")):
        return XlsxValidationResult(
            valid=False,
            status="invalid_file",
            message=f"Неверное расширение: {file_name}",
            file_size=size,
        )

    if not data[:2].startswith(XLSX_MAGIC_BYTES):
        for prefix in HTML_DOCTYPE_PREFIXES:
            if data[: len(prefix)].lower().startswith(prefix.lower()):
                return XlsxValidationResult(
                    valid=False,
                    status="invalid_file",
                    message="Получена HTML-страница вместо XLSX",
                    file_size=size,
                )
        return XlsxValidationResult(
            valid=False,
            status="invalid_file",
            message="Неверная сигнатура файла (ожидается PK для XLSX)",
            file_size=size,
        )

    try:
        from io import BytesIO

        import openpyxl

        wb = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)
        sheet_names = wb.sheetnames
        wb.close()
    except Exception as exc:
        return XlsxValidationResult(
            valid=False,
            status="parse_error",
            message=f"Не удалось открыть XLSX: {exc}",
            file_size=size,
        )

    if not sheet_names:
        return XlsxValidationResult(
            valid=False,
            status="invalid_file",
            message="XLSX не содержит листов",
            file_size=size,
            sheet_names=sheet_names,
        )

    return XlsxValidationResult(
        valid=True,
        status="valid",
        file_size=size,
        sheet_names=sheet_names,
    )
