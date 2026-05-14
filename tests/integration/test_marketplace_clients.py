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
