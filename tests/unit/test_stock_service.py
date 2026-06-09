"""version: 1.1.0
description: Unit tests for stock service helper parsing, quantities, and alerts.
updated: 2026-05-17
"""

from datetime import UTC, datetime

from app.models.domain import Product, StockSnapshot
from app.models.enums import Marketplace
from app.services.common.stock_service import StockService


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


def test_low_stock_alert_mentions_product_and_marketplace() -> None:
    snapshot = StockSnapshot(
        user_id=7,
        marketplace_account_id=55,
        product_id=10,
        marketplace=Marketplace.WB,
        warehouse="FBS: склад продавца",
        quantity=3,
        snapshot_at=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
        raw_payload={},
    )
    product = Product(
        id=10,
        user_id=7,
        marketplace_account_id=55,
        marketplace=Marketplace.WB,
        external_product_id="123456",
        seller_article="SKU <1>",
        marketplace_article="123456",
        title="Крем & тест",
    )

    text = StockService._format_low_stock_alert(snapshot, product, threshold=5)

    assert "Маркетплейс: Wildberries" in text
    assert "Товар: Крем &amp; тест" in text
    assert "Артикул продавца: SKU &lt;1&gt;" in text
    assert "Артикул маркетплейса: 123456" in text
    assert "Склад: FBS: склад продавца" in text
    assert "Остаток: 3 шт. (порог: 5 шт.)" in text


def test_low_stock_alert_uses_raw_payload_when_product_missing() -> None:
    snapshot = StockSnapshot(
        user_id=7,
        marketplace_account_id=55,
        product_id=None,
        marketplace=Marketplace.OZON,
        warehouse="Ozon: общий остаток",
        quantity=4,
        snapshot_at=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
        raw_payload={"offer_id": "OFFER-1", "sku": "987654", "name": "Товар Ozon"},
    )

    text = StockService._format_low_stock_alert(snapshot, None, threshold=5)

    assert "Маркетплейс: Ozon" in text
    assert "Товар: Товар Ozon" in text
    assert "Артикул продавца: OFFER-1" in text
    assert "Артикул маркетплейса: 987654" in text


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
