"""version: 1.1.0
description: Unit tests for stock service helper parsing and marketplace stock quantities.
updated: 2026-05-17
"""

from app.services.stock_service import StockService


def test_extract_stock_rows_from_nested_result() -> None:
    rows = StockService._extract_rows({"result": {"items": [{"sku": 1}]}})

    assert rows == [{"sku": 1}]


def test_wb_seller_stock_quantity_uses_amount() -> None:
    quantity = StockService._quantity_from_stock_row({"chrtId": 123, "amount": 17})

    assert quantity == 17


def test_wb_analytics_stock_quantity_uses_quantity() -> None:
    quantity = StockService._quantity_from_stock_row({"nmID": 55, "quantity": 9})

    assert quantity == 9


def test_ozon_stock_quantity_sums_nested_stocks_list() -> None:
    quantity = StockService._quantity_from_stock_row(
        {
            "offer_id": "SKU-1",
            "stocks": [
                {"type": "fbo", "present": 4, "reserved": 1},
                {"type": "fbs", "present": 6, "reserved": 2},
            ],
        }
    )

    assert quantity == 10


def test_stock_quantity_ignores_malformed_values() -> None:
    quantity = StockService._quantity_from_stock_row({"stocks": [{"present": "bad"}]})

    assert quantity == 0
