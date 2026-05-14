"""version: 1.0.0
description: Shared async HTTP client primitives for marketplace APIs.
updated: 2026-05-14
"""

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx


class MarketplaceApiError(RuntimeError):
    """Raised when marketplace API returns an unsuccessful response."""

    def __init__(self, status_code: int, message: str, payload: Any | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class AsyncApiClient:
    """Base HTTP client with retries and 429 backoff."""

    def __init__(self, base_url: str, timeout: float = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        retries: int = 3,
    ) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(retries):
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                )
                if response.status_code == 429 and attempt < retries - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                if response.is_error:
                    payload = self._safe_json(response)
                    raise MarketplaceApiError(response.status_code, response.text, payload)
                return self._safe_json(response)
        raise MarketplaceApiError(429, "Превышен лимит запросов")

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"text": response.text}
