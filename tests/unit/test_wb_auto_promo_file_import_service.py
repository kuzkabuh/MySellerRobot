"""Tests for WB auto-promotion seller-cabinet file import."""

import csv
import os
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import AsyncMock, MagicMock

import openpyxl
import pytest

from app.services.pricing.wb_auto_promo_file_import_service import (
    WbAutoPromoFileImportService,
)
from app.services.pricing.wb_auto_promo_participation_service import (
    STATUS_CAN_APPLY,
    WbAutoPromoParticipationService,
)

WB_HEADERS = [
    "Товар уже участвует в акции",
    "Бренд",
    "Предмет",
    "Наименование",
    "Артикул поставщика",
    "Артикул WB",
    "Последний баркод",
    "",
    "",
    "",
    "",
    "Плановая цена для акции",
    "Текущая розничная цена",
    "Валюта",
    "Текущая скидка на сайте, %",
    "Загружаемая скидка для участия в акции",
    "Статус",
]


def _xlsx(rows: list[list], headers: list[str] | None = None) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Отчёт по скидкам"
    ws.append(headers or WB_HEADERS)
    for row in rows:
        ws.append(row)
    tmp = NamedTemporaryFile(suffix=".xlsx", delete=False)
    wb.save(tmp.name)
    tmp.close()
    return Path(tmp.name)


def _csv(rows: list[list], headers: list[str] | None = None) -> Path:
    tmp = NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8", newline="")
    writer = csv.writer(tmp)
    writer.writerow(headers or WB_HEADERS)
    writer.writerows(rows)
    tmp.close()
    return Path(tmp.name)


def _remove(path: Path) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


@pytest.mark.asyncio
async def test_parse_wb_excel_with_russian_headers() -> None:
    path = _xlsx([[
        "Нет", "Brand", "Cream", "Крем", "SUP-1", 303892412, "123", "", "", "", "",
        446, 1820, "RUB", "75%", 76, "Готов",
    ]])
    try:
        result = await WbAutoPromoFileImportService().parse_file(path)
    finally:
        _remove(path)

    row = result.rows[0]
    assert row.wb_nm_id == 303892412
    assert row.plan_price == Decimal("446.00")
    assert row.current_full_price == Decimal("1820.00")
    assert row.current_discount_percent == Decimal("75.00")
    assert row.current_discounted_price == Decimal("455.00")
    assert row.wb_upload_discount_percent == Decimal("76.00")
    assert row.condition_type == "max_price"


@pytest.mark.asyncio
async def test_parse_fallback_by_column_indexes() -> None:
    path = _xlsx([[
        "Да", "Brand", "Cream", "Крем", "SUP-1", 303892412, "123", "", "", "", "",
        446, 1820, "RUB", 75, 76, "Готов",
    ]], headers=[f"col{i}" for i in range(17)])
    try:
        result = await WbAutoPromoFileImportService().parse_file(path)
    finally:
        _remove(path)

    row = result.rows[0]
    assert row.already_participating is True
    assert row.wb_nm_id == 303892412
    assert row.plan_price == Decimal("446.00")
    assert result.preview.with_plan_price_count == 1


def test_decimal_and_percent_normalization() -> None:
    assert WbAutoPromoFileImportService.parse_decimal("1 820,50") == Decimal("1820.50")
    assert WbAutoPromoFileImportService.parse_decimal("75%") == Decimal("75.00")
    assert WbAutoPromoFileImportService.parse_bool("Да") is True
    assert WbAutoPromoFileImportService.parse_bool("Нет") is False


@pytest.mark.asyncio
async def test_plan_price_446_recommendation_full_price_1784() -> None:
    rec = WbAutoPromoParticipationService.calculate(
        wb_nm_id=303892412,
        mrc_price=Decimal("446"),
        current_full_price=Decimal("1820"),
        current_discount=75,
        current_discounted_price=Decimal("455"),
        max_auto_promo_price=Decimal("446"),
        wb_condition_discount_percent=Decimal("76"),
        condition_type="max_price",
        discount=Decimal("75"),
    )

    assert rec.status == STATUS_CAN_APPLY
    assert rec.candidate_discounted_price == Decimal("446")
    assert rec.recommended_full_price == Decimal("1784")


@pytest.mark.asyncio
async def test_missing_plan_price_uses_upload_discount_fallback() -> None:
    path = _xlsx([[
        "Нет", "Brand", "Cream", "Крем", "SUP-1", 303892412, "123", "", "", "", "",
        "", 1820, "RUB", 75, 76, "Готов",
    ]])
    try:
        result = await WbAutoPromoFileImportService().parse_file(path)
    finally:
        _remove(path)

    row = result.rows[0]
    assert row.status == "warning"
    assert row.candidate_discounted_price == Decimal("436.80")
    assert row.condition_type == "discount_projection"


@pytest.mark.asyncio
async def test_row_without_nm_id_is_error() -> None:
    path = _xlsx([[
        "Нет", "Brand", "Cream", "Крем", "SUP-1", "", "123", "", "", "", "",
        446, 1820, "RUB", 75, 76, "Готов",
    ]])
    try:
        result = await WbAutoPromoFileImportService().parse_file(path)
    finally:
        _remove(path)

    assert result.rows[0].status == "error"
    assert result.preview.error_rows == 1


@pytest.mark.asyncio
async def test_row_without_plan_and_upload_discount_is_warning() -> None:
    path = _xlsx([[
        "Нет", "Brand", "Cream", "Крем", "SUP-1", 303892412, "123", "", "", "", "",
        "", 1820, "RUB", 75, "", "Готов",
    ]])
    try:
        result = await WbAutoPromoFileImportService().parse_file(path)
    finally:
        _remove(path)

    assert result.rows[0].status == "warning"
    assert result.rows[0].condition_type == "unknown"


@pytest.mark.asyncio
async def test_csv_file_is_supported() -> None:
    path = _csv([[
        "Нет", "Brand", "Cream", "Крем", "SUP-1", 303892412, "123", "", "", "", "",
        446, 1820, "RUB", 75, 76, "Готов",
    ]])
    try:
        result = await WbAutoPromoFileImportService().parse_file(path)
    finally:
        _remove(path)

    assert result.preview.total_rows == 1
    assert result.rows[0].plan_price == Decimal("446.00")


@pytest.mark.asyncio
async def test_apply_import_creates_wb_file_conditions() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    session.add = MagicMock()
    session.flush = AsyncMock()
    service = WbAutoPromoFileImportService(session)
    path = _xlsx([[
        "Нет", "Brand", "Cream", "Крем", "SUP-1", 303892412, "123", "", "", "", "",
        446, 1820, "RUB", 75, 76, "Готов",
    ]])
    try:
        parsed = await WbAutoPromoFileImportService().parse_file(path)
    finally:
        _remove(path)
    parsed_row = parsed.rows[0]

    saved = await service.apply_import(
        [parsed_row],
        user_id=1,
        marketplace_account_id=2,
        promotion_name="Встречаем лето",
    )

    assert saved == 1
    condition = session.add.call_args[0][0]
    assert condition.source == "wb_file"
    assert condition.wb_nm_id == 303892412
    assert condition.required_price == Decimal("446.00")
    assert condition.max_auto_promo_price == Decimal("446.00")
    assert condition.current_wb_price == Decimal("455.00")
    assert condition.promotion_name == "Встречаем лето"
