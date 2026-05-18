"""version: 1.1.0
description: Unit tests for stock service helper parsing and marketplace stock quantities.
updated: 2026-05-17
"""

from app.models.enums import Marketplace
from app.services.stock_service import StockService


class _DummyProducts:
    async def find_for_order_item(self, **_kwargs):  # type: ignore[no-untyped-def]
        return None


class _PagedWbClient:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    async def get_wb_warehouses_stocks(self, *, limit: int, offset: int):  # type: ignore[no-untyped-def]
        self.calls.append((limit, offset))
        if offset == 0:
            return {"data": [{"nmID": index, "quantity": 1} for index in range(limit)]}
        return {"data": [{"nmID": "last", "quantity": 2}]}


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


async def test_wb_analytics_stock_sync_reads_all_pages() -> None:
    service = StockService(session=None)  # type: ignore[arg-type]
    service.products = _DummyProducts()  # type: ignore[assignment]
    snapshots: list[tuple[int, dict[str, object]]] = []

    async def add_snapshot(_account, _product, quantity, raw):  # type: ignore[no-untyped-def]
        snapshots.append((quantity, raw))

    service._add_snapshot = add_snapshot  # type: ignore[method-assign]
    account = type(
        "Account",
        (),
        {"id": 1, "user_id": 2, "marketplace": Marketplace.WB},
    )()
    client = _PagedWbClient()

    count = await service._sync_wb_analytics_stocks(account, client)  # type: ignore[arg-type]

    assert count == 1001
    assert client.calls == [(1000, 0), (1000, 1000)]
    assert snapshots[-1][0] == 2
    assert snapshots[-1][1]["stock_source"] == "WB_ANALYTICS_STOCKS"
