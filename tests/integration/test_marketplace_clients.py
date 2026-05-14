"""version: 1.0.0
description: Integration-style tests for marketplace API clients with mocked HTTP.
updated: 2026-05-14
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
