"""version: 1.0.0
description: Unit tests for Ozon catalog enrichment parsing helpers.
updated: 2026-05-17
"""

from decimal import Decimal

from app.services.ozon_catalog_enrichment_service import _extract_rows, _money, _next_cursor


def test_extract_rows_from_nested_result_items() -> None:
    rows = _extract_rows({"result": {"items": [{"offer_id": "SKU-1"}]}}, keys=("items",))

    assert rows == [{"offer_id": "SKU-1"}]


def test_next_cursor_reads_result_cursor() -> None:
    assert _next_cursor({"result": {"cursor": "next-page"}}) == "next-page"


def test_money_normalizes_price_strings() -> None:
    assert _money("1490,50") == Decimal("1490.50")
    assert _money("") is None
