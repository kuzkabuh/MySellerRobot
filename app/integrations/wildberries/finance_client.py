"""Dedicated WB finance API client with rate limiting and 204 handling."""

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, MarketplaceApiError, RateLimitError

logger = logging.getLogger(__name__)


class WbFinanceApiClient:
    """WB finance API client with per-account rate limiting.

    WB finance API rate limit: 1 request per minute per account.
    This client enforces that limit and handles 204 (no content)
    responses for pagination termination.
    """

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 60,
        max_retries: int = 3,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key
        self.base_url = settings.wb_base_finance_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._last_request_time: float = 0.0
        self._min_interval = 60.0

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": self.api_key, "Content-Type": "application/json"}

    async def _rate_limit_wait(self) -> None:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            logger.debug("wb_finance_rate_limit_wait", extra={"wait_seconds": round(wait, 1)})
            await asyncio.sleep(wait)
        self._last_request_time = asyncio.get_event_loop().time()

    async def get_sales_reports_detailed(
        self,
        *,
        date_from: date | datetime | str,
        date_to: date | datetime | str,
        limit: int = 100000,
        rrd_id: int = 0,
        period: str = "daily",
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]] | None:
        """Fetch detailed sales report rows from WB finance API.

        Returns:
            List of row dicts if data available (HTTP 200).
            None if no more data (HTTP 204).

        Raises:
            AuthenticationError: Invalid API key (401/403).
            RateLimitError: Rate limit exceeded after retries (429).
            MarketplaceApiError: Other API errors (400, 5xx, etc.).
        """
        url = f"{self.base_url}/api/finance/v1/sales-reports/detailed"

        def _fmt(v: date | datetime | str) -> str:
            if isinstance(v, str):
                return v
            if isinstance(v, datetime):
                return v.astimezone(UTC).strftime("%Y-%m-%d")
            return v.isoformat()

        payload: dict[str, Any] = {
            "dateFrom": _fmt(date_from),
            "dateTo": _fmt(date_to),
            "limit": limit,
            "rrdId": rrd_id,
            "period": period,
        }
        if fields:
            payload["fields"] = fields

        await self._rate_limit_wait()

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(
                        "POST",
                        url,
                        headers=self.headers,
                        json=payload,
                    )

                if response.status_code == 204:
                    return None

                if response.status_code == 429:
                    retry_after = self._get_retry_after(response)
                    if attempt < self.max_retries - 1:
                        wait = retry_after or (self._min_interval * (attempt + 1))
                        logger.warning(
                            "wb_finance_rate_limit_retry",
                            extra={"attempt": attempt + 1, "wait": wait},
                        )
                        await asyncio.sleep(wait)
                        self._last_request_time = 0.0
                        continue
                    raise RateLimitError(
                        retry_after=retry_after,
                        marketplace="Wildberries",
                    )

                if response.status_code in (401, 403):
                    raise AuthenticationError(marketplace="Wildberries")

                if response.status_code == 400:
                    body = self._safe_json(response)
                    raise MarketplaceApiError(
                        message=f"WB finance API bad request: {body}",
                        status_code=400,
                        marketplace="Wildberries",
                        details={"payload": payload, "response": body},
                    )

                if response.status_code >= 500:
                    if attempt < self.max_retries - 1:
                        wait = 2**attempt * 10
                        logger.warning(
                            "wb_finance_server_error_retry",
                            extra={
                                "status": response.status_code,
                                "attempt": attempt + 1,
                                "wait": wait,
                            },
                        )
                        await asyncio.sleep(wait)
                        continue
                    raise MarketplaceApiError(
                        message=f"WB finance API server error: {response.status_code}",
                        status_code=response.status_code,
                        marketplace="Wildberries",
                        details={"payload": payload},
                    )

                if response.status_code != 200:
                    body = self._safe_json(response)
                    raise MarketplaceApiError(
                        message=f"WB finance API error: {response.status_code}",
                        status_code=response.status_code,
                        marketplace="Wildberries",
                        details={"payload": payload, "response": body},
                    )

                data = self._safe_json(response)
                if isinstance(data, list):
                    return data
                for key in ("data", "details", "rows", "result"):
                    value = data.get(key)
                    if isinstance(value, list):
                        return value
                    if isinstance(value, dict):
                        nested = value.get("details") or value.get("rows")
                        if isinstance(nested, list):
                            return nested
                return []

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < self.max_retries - 1:
                    wait = 2**attempt * 10
                    logger.warning(
                        "wb_finance_network_retry",
                        extra={"attempt": attempt + 1, "wait": wait, "error": str(exc)},
                    )
                    await asyncio.sleep(wait)
                    continue
                raise MarketplaceApiError(
                    message=f"Network error after {self.max_retries} attempts: {exc}",
                    marketplace="Wildberries",
                ) from exc

        return []

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"text": response.text}

    @staticmethod
    def _get_retry_after(response: httpx.Response) -> int | None:
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return int(retry_after)
        return None

    @staticmethod
    def extract_rows(payload: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        if payload is None:
            return []
        return [item for item in payload if isinstance(item, dict)]
