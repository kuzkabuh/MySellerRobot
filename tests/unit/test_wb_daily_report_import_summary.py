"""Regression tests for WB daily report import summary."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.wb_daily_report_import_service import WbDailyReportImportService


def _result_one(values: tuple[object, ...]) -> MagicMock:
    result = MagicMock()
    result.one.return_value = values
    return result


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _rows_result(rows: list[tuple[object, object]]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


@pytest.mark.asyncio
async def test_import_summary_groups_skip_reasons_and_maps_empty_reason() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result_one((0,) * 20),
            _scalar_result(1),
            _rows_result([("Дубль", 1), ("Без причины", 1), ("Ошибка формата", 1)]),
        ]
    )

    summary = await WbDailyReportImportService(session).import_summary(import_id=6)

    assert summary.duplicate_rows == 1
    assert summary.skip_reasons == [
        ("Дубль", 1),
        ("Без причины", 1),
        ("Ошибка формата", 1),
    ]


@pytest.mark.asyncio
async def test_import_summary_handles_missing_rows_and_logs() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result_one((None,) * 20),
            _scalar_result(0),
            _rows_result([]),
        ]
    )

    summary = await WbDailyReportImportService(session).import_summary(import_id=7)

    assert summary.sales_amount == 0
    assert summary.duplicate_rows == 0
    assert summary.skip_reasons == []
