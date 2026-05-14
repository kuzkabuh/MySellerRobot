"""version: 1.0.0
description: Unit tests for stock service helpers.
updated: 2026-05-14
"""

from app.services.stock_service import StockService


def test_extract_stock_rows_from_nested_result() -> None:
    rows = StockService._extract_rows({"result": {"items": [{"sku": 1}]}})

    assert rows == [{"sku": 1}]
