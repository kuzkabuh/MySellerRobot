"""version: 1.1.0
description: Enhanced async HTTP client with retry logic and error handling.
updated: 2026-05-15
"""

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.core.exceptions import AuthenticationError, MarketplaceApiError, RateLimitError

logger = logging.getLogger(__name__)


class AsyncApiClient:
    """Base HTTP client with exponential backoff and comprehensive error handling."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 30,
        max_retries: int = 3,
        marketplace: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.marketplace = marketplace

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        retries: int | None = None,
    ) -> Any:
        """Execute HTTP request with retry logic and error handling."""
        url = f"{self.base_url}{path}"
        max_attempts = retries if retries is not None else self.max_retries
        last_exception: Exception | None = None

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(max_attempts):
                try:
                    response = await client.request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                        json=json,
                    )

                    if response.status_code == 429:
                        retry_after = self._get_retry_after(response)
                        if attempt < max_attempts - 1:
                            wait_time = retry_after or (2**attempt)
                            logger.warning(
                                "rate_limit_hit",
                                extra={
                                    "marketplace": self.marketplace,
                                    "url": url,
                                    "attempt": attempt + 1,
                                    "wait_time": wait_time,
                                },
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        raise RateLimitError(
                            retry_after=retry_after,
                            marketplace=self.marketplace,
                        )

                    if response.status_code == 401:
                        raise AuthenticationError(marketplace=self.marketplace)

                    if response.status_code >= 500 and attempt < max_attempts - 1:
                        wait_time = 2**attempt
                        logger.warning(
                            "server_error_retry",
                            extra={
                                "marketplace": self.marketplace,
                                "url": url,
                                "status_code": response.status_code,
                                "attempt": attempt + 1,
                                "wait_time": wait_time,
                            },
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    if response.is_error:
                        payload = self._safe_json(response)
                        raise MarketplaceApiError(
                            message=response.text or "API request failed",
                            status_code=response.status_code,
                            marketplace=self.marketplace,
                            details={"payload": payload, "url": url},
                        )

                    return self._safe_json(response)

                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    last_exception = exc
                    if attempt < max_attempts - 1:
                        wait_time = 2**attempt
                        logger.warning(
                            "network_error_retry",
                            extra={
                                "marketplace": self.marketplace,
                                "url": url,
                                "error": str(exc),
                                "attempt": attempt + 1,
                                "wait_time": wait_time,
                            },
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    raise MarketplaceApiError(
                        message=f"Network error: {exc}",
                        marketplace=self.marketplace,
                        details={"url": url, "error_type": type(exc).__name__},
                    ) from exc

        if last_exception:
            raise MarketplaceApiError(
                message=f"Request failed after {max_attempts} attempts",
                marketplace=self.marketplace,
                details={"url": url, "last_error": str(last_exception)},
            ) from last_exception

        raise MarketplaceApiError(
            message="Request failed",
            marketplace=self.marketplace,
            details={"url": url},
        )

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        """Safely parse JSON response."""
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"text": response.text}

    @staticmethod
    def _get_retry_after(response: httpx.Response) -> int | None:
        """Extract Retry-After header value."""
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return int(retry_after)
        return None
