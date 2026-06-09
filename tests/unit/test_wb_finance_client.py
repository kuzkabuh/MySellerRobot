"""Unit tests for the dedicated WB finance API client."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.exceptions import AuthenticationError
from app.integrations.wildberries.finance_client import WbFinanceApiClient


@pytest.fixture
def client() -> WbFinanceApiClient:
    return WbFinanceApiClient("test-api-key")


class TestSalesReportsDetailed:
    @pytest.mark.asyncio
    async def test_returns_list_on_200(self, client: WbFinanceApiClient) -> None:
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = b'[{"rrdId": 1, "forPay": 1000}]'
        mock_response.json = MagicMock(return_value=[{"rrdId": 1, "forPay": 1000}])

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_response):
            result = await client.get_sales_reports_detailed(
                date_from=date(2026, 3, 17),
                date_to=date(2026, 3, 17),
            )

        assert result is not None
        assert len(result) == 1
        assert result[0]["rrdId"] == 1

    @pytest.mark.asyncio
    async def test_returns_none_on_204(self, client: WbFinanceApiClient) -> None:
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 204
        mock_response.content = b""

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_response):
            result = await client.get_sales_reports_detailed(
                date_from=date(2026, 3, 17),
                date_to=date(2026, 3, 17),
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_raises_on_401(self, client: WbFinanceApiClient) -> None:
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.content = b""

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(AuthenticationError):
                await client.get_sales_reports_detailed(
                    date_from=date(2026, 3, 17),
                    date_to=date(2026, 3, 17),
                )

    @pytest.mark.asyncio
    async def test_raises_on_403(self, client: WbFinanceApiClient) -> None:
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 403
        mock_response.content = b""

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(AuthenticationError):
                await client.get_sales_reports_detailed(
                    date_from=date(2026, 3, 17),
                    date_to=date(2026, 3, 17),
                )

    @pytest.mark.asyncio
    async def test_retries_on_429(self, client: WbFinanceApiClient) -> None:
        mock_429 = AsyncMock(spec=httpx.Response)
        mock_429.status_code = 429
        mock_429.content = b""
        mock_429.headers = {}

        mock_200 = AsyncMock(spec=httpx.Response)
        mock_200.status_code = 200
        mock_200.content = b'[{"rrdId": 1}]'
        mock_200.json = MagicMock(return_value=[{"rrdId": 1}])

        with patch(
            "httpx.AsyncClient.request",
            new_callable=AsyncMock,
            side_effect=[mock_429, mock_200],
        ):
            result = await client.get_sales_reports_detailed(
                date_from=date(2026, 3, 17),
                date_to=date(2026, 3, 17),
            )

        assert result is not None
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_retries_on_500_then_succeeds(self, client: WbFinanceApiClient) -> None:
        mock_500 = AsyncMock(spec=httpx.Response)
        mock_500.status_code = 500
        mock_500.content = b""

        mock_200 = AsyncMock(spec=httpx.Response)
        mock_200.status_code = 200
        mock_200.content = b'[{"rrdId": 1}]'
        mock_200.json = MagicMock(return_value=[{"rrdId": 1}])

        with patch(
            "httpx.AsyncClient.request",
            new_callable=AsyncMock,
            side_effect=[mock_500, mock_200],
        ):
            result = await client.get_sales_reports_detailed(
                date_from=date(2026, 3, 17),
                date_to=date(2026, 3, 17),
            )

        assert result is not None
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_passes_pagination_params(self, client: WbFinanceApiClient) -> None:
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = b'[]'
        mock_response.json = MagicMock(return_value=[])

        call_kwargs = {}

        async def mock_request(method, url, **kwargs):
            nonlocal call_kwargs
            call_kwargs = {"method": method, "url": url, **kwargs}
            return mock_response

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_request):
            await client.get_sales_reports_detailed(
                date_from=date(2026, 3, 17),
                date_to=date(2026, 3, 17),
                rrd_id=42,
                limit=50000,
                period="daily",
                fields=["rrdId", "forPay"],
            )

        sent_json = call_kwargs.get("json", {})
        assert sent_json["rrdId"] == 42
        assert sent_json["limit"] == 50000
        assert sent_json["period"] == "daily"
        assert sent_json["fields"] == ["rrdId", "forPay"]

    @pytest.mark.asyncio
    async def test_rate_limit_wait_enforced(self) -> None:
        client = WbFinanceApiClient("test-api-key")
        client._min_interval = 0.01

        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = b'[]'
        mock_response.json = MagicMock(return_value=[])

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_response):
            import time

            t0 = time.monotonic()
            await client.get_sales_reports_detailed(
                date_from=date(2026, 3, 17),
                date_to=date(2026, 3, 17),
            )
            await client.get_sales_reports_detailed(
                date_from=date(2026, 3, 17),
                date_to=date(2026, 3, 17),
            )
            elapsed = time.monotonic() - t0

        assert elapsed >= 0.01


class TestExtractRows:
    def test_extract_from_list(self) -> None:
        rows = [{"rrdId": 1}, {"rrdId": 2}]
        assert WbFinanceApiClient.extract_rows(rows) == rows

    def test_extract_none(self) -> None:
        assert WbFinanceApiClient.extract_rows(None) == []

    def test_extract_filters_non_dicts(self) -> None:
        rows = [{"rrdId": 1}, "string", 42]
        result = WbFinanceApiClient.extract_rows(rows)
        assert len(result) == 1
        assert result[0]["rrdId"] == 1
