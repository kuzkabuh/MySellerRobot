"""version: 1.1.0
description: Integration-style tests for marketplace API clients with mocked HTTP.
updated: 2026-05-17
"""

from datetime import UTC, datetime

import pytest
from pytest_httpx import HTTPXMock

from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient


@pytest.mark.asyncio
async def test_wb_get_new_fbs_orders(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://marketplace-api.wildberries.ru/api/v3/orders/new",
        json={"orders": [{"id": 1, "createdAt": "2026-05-14T09:00:00Z"}]},
    )

    orders = await WildberriesClient("token").get_new_fbs_orders()

    assert orders[0]["id"] == 1


@pytest.mark.asyncio
async def test_wb_get_historical_fbs_orders(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://marketplace-api.wildberries.ru/api/v3/orders"
            "?dateFrom=2026-05-13T00%3A00%3A00%2B00%3A00"
            "&dateTo=2026-05-14T00%3A00%3A00%2B00%3A00"
        ),
        json={"orders": [{"id": 2, "createdAt": "2026-05-13T09:00:00Z"}]},
    )

    orders = await WildberriesClient("token").get_fbs_orders(
        date_from=datetime(2026, 5, 13, tzinfo=UTC),
        date_to=datetime(2026, 5, 14, tzinfo=UTC),
    )

    assert orders[0]["id"] == 2


@pytest.mark.asyncio
async def test_wb_check_connection_uses_common_ping(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://common-api.wildberries.ru/ping",
        json={"Status": "OK"},
    )

    assert await WildberriesClient("token").check_connection()


@pytest.mark.asyncio
async def test_wb_get_seller_info(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://common-api.wildberries.ru/api/v1/seller-info",
        json={"name": "ИП Тест", "inn": "7700000000"},
    )

    data = await WildberriesClient("token").get_seller_info()

    assert data["name"] == "ИП Тест"


@pytest.mark.asyncio
async def test_wb_get_news_with_from_id(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://common-api.wildberries.ru/api/communications/v2/news?fromID=7373",
        json=[{"id": 7373, "title": "Новость"}],
    )

    news = await WildberriesClient("token").get_news(from_id=7373)

    assert news[0]["id"] == 7373


@pytest.mark.asyncio
async def test_wb_get_product_search_texts(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://seller-analytics-api.wildberries.ru/api/v2/search-report/product/search-texts",
        json={"data": [{"text": "полотенце"}]},
    )

    data = await WildberriesClient("token").get_product_search_texts({"nmIDs": [123]})

    assert data["data"][0]["text"] == "полотенце"


@pytest.mark.asyncio
async def test_wb_get_supplier_sales_for_day_uses_flag_one(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://statistics-api.wildberries.ru/api/v1/supplier/sales?dateFrom=2026-05-17&flag=1",
        json=[{"saleID": "S1", "forPay": 100}],
    )

    sales = await WildberriesClient("token").get_supplier_sales_for_day(
        datetime(2026, 5, 17, tzinfo=UTC).date()
    )

    assert sales[0]["saleID"] == "S1"


@pytest.mark.asyncio
async def test_wb_get_seller_warehouses(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://marketplace-api.wildberries.ru/api/v3/warehouses",
        json=[{"ID": 100, "name": "Основной склад"}],
    )

    warehouses = await WildberriesClient("token").get_seller_warehouses()

    assert warehouses[0]["ID"] == 100


@pytest.mark.asyncio
async def test_wb_get_seller_warehouse_stocks_uses_chrt_ids(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://marketplace-api.wildberries.ru/api/v3/stocks/100",
        json={"stocks": [{"chrtId": 12345678, "amount": 10}]},
        match_json={"chrtIds": [12345678]},
    )

    stocks = await WildberriesClient("token").get_seller_warehouse_stocks(
        warehouse_id=100,
        chrt_ids=[12345678],
    )

    assert stocks == [{"chrtId": 12345678, "amount": 10}]


@pytest.mark.asyncio
async def test_ozon_get_fbs_postings(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api-seller.ozon.ru/v3/posting/fbs/list",
        json={"result": {"postings": [{"posting_number": "123"}]}},
    )

    data = await OzonClient("client", "key").get_fbs_postings(
        datetime(2026, 5, 14, tzinfo=UTC),
        datetime(2026, 5, 15, tzinfo=UTC),
    )

    assert data["result"]["postings"][0]["posting_number"] == "123"


@pytest.mark.asyncio
async def test_ozon_get_fbs_unfulfilled(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api-seller.ozon.ru/v3/posting/fbs/unfulfilled/list",
        json={"result": {"postings": [{"posting_number": "123"}]}},
    )

    data = await OzonClient("client", "key").get_fbs_unfulfilled(
        datetime(2026, 5, 14, tzinfo=UTC),
        datetime(2026, 5, 15, tzinfo=UTC),
    )

    assert data["result"]["postings"][0]["posting_number"] == "123"


@pytest.mark.asyncio
async def test_ozon_get_fbo_postings(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api-seller.ozon.ru/v2/posting/fbo/list",
        json={"result": [{"posting_number": "fbo-1"}]},
    )

    data = await OzonClient("client", "key").get_fbo_postings(
        datetime(2026, 5, 14, tzinfo=UTC),
        datetime(2026, 5, 15, tzinfo=UTC),
    )

    assert data["result"][0]["posting_number"] == "fbo-1"


@pytest.mark.asyncio
async def test_ozon_check_connection_uses_product_list(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api-seller.ozon.ru/v3/product/list",
        json={"result": {"items": []}},
    )

    assert await OzonClient("client", "key").check_connection()


@pytest.mark.asyncio
async def test_ozon_get_seller_info(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api-seller.ozon.ru/v1/seller/info",
        json={"result": {"company_id": 123, "name": "ООО Тест"}},
    )

    data = await OzonClient("client", "key").get_seller_info()

    assert data["result"]["company_id"] == 123


@pytest.mark.asyncio
async def test_ozon_get_returns_with_period(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api-seller.ozon.ru/v1/returns/list",
        json={"returns": [{"id": 1}]},
    )

    data = await OzonClient("client", "key").get_returns(
        date_from=datetime(2026, 5, 13, tzinfo=UTC),
        date_to=datetime(2026, 5, 14, tzinfo=UTC),
    )

    assert data["returns"][0]["id"] == 1


@pytest.mark.asyncio
async def test_ozon_get_product_info_prices_uses_v5(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api-seller.ozon.ru/v5/product/info/prices",
        json={"items": [{"offer_id": "SKU-1", "price": {"price": "100"}}]},
    )

    data = await OzonClient("client", "key").get_product_info_prices(offer_ids=["SKU-1"])

    assert data["items"][0]["offer_id"] == "SKU-1"


@pytest.mark.asyncio
async def test_ozon_get_product_info_stocks_page_uses_cursor(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api-seller.ozon.ru/v4/product/info/stocks",
        match_json={
            "filter": {"offer_id": [], "visibility": "ALL"},
            "limit": 1000,
            "cursor": "next",
        },
        json={"result": {"items": [{"offer_id": "SKU-1"}], "cursor": ""}},
    )

    data = await OzonClient("client", "key").get_product_info_stocks_page(cursor="next")

    assert data["result"]["items"][0]["offer_id"] == "SKU-1"


@pytest.mark.asyncio
async def test_ozon_get_warehouses_uses_v2(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api-seller.ozon.ru/v2/warehouse/list",
        json={"result": [{"warehouse_id": 1, "name": "FBS"}]},
    )

    data = await OzonClient("client", "key").get_warehouses()

    assert data["result"][0]["warehouse_id"] == 1


@pytest.mark.asyncio
async def test_ozon_get_actions_and_promo_products(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api-seller.ozon.ru/v1/actions",
        json={"result": [{"id": 77, "title": "Акция"}]},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api-seller.ozon.ru/v1/actions/products",
        json={"result": {"products": [{"offer_id": "SKU-1"}]}},
    )

    actions = await OzonClient("client", "key").get_actions()
    products = await OzonClient("client", "key").get_promos_products(77)

    assert actions["result"][0]["id"] == 77
    assert products["result"]["products"][0]["offer_id"] == "SKU-1"
