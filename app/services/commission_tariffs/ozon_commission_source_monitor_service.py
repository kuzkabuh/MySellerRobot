"""version: 1.0.0
description: Ozon commission source page monitor — detects new tariff tables on the official page.
updated: 2026-05-20
"""

import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from app.models.commission_tariffs import MarketplaceTariffSourceCheck
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)

OZON_COMMISSIONS_PAGE_URL = (
    "https://seller-edu.ozon.ru/libra/commissions-tariffs/commissions-tariffs-ozon/"
    "komissii-tovary-uslugi"
)

DOWNLOAD_LINK_TEXT_PATTERN = re.compile(r"скачать\s+таблицу\s+категорий", re.IGNORECASE)
PERIOD_PATTERN = re.compile(
    r"таблица\s+категорий\s+(?:с\s+|по\s+|от\s+)?(.+?)(?:\s*г\.?)?(?:\s*по\s*(.+?)(?:\s*г\.?)?)?",
    re.IGNORECASE,
)


class OzonCommissionPageParser:
    """Parse the Ozon commissions page HTML to detect the latest tariff table link."""

    def parse(self, html_content: str) -> dict[str, Any]:
        """Extract period label, download URL, and file name from the page.

        Returns a dict with:
        - period_label: str | None
        - download_url: str | None
        - file_name: str | None
        """
        period_label = self._extract_latest_period(html_content)
        download_url = self._extract_download_url(html_content)
        file_name = self._extract_file_name(download_url) if download_url else None

        return {
            "period_label": period_label,
            "download_url": download_url,
            "file_name": file_name,
        }

    def _extract_latest_period(self, html: str) -> str | None:
        """Find the most recent period heading on the page."""
        blocks = re.findall(
            r'(?:таблица\s+категорий\s+[^<]{5,80})',
            html,
            re.IGNORECASE,
        )
        if blocks:
            return blocks[0].strip()
        return None

    def _extract_download_url(self, html: str) -> str | None:
        """Find the download link for the latest commission table."""
        for match in re.finditer(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*скачать[^<]*)</a>',
            html,
            re.IGNORECASE,
        ):
            url = match.group(1)
            link_text = match.group(2)
            if DOWNLOAD_LINK_TEXT_PATTERN.search(link_text):
                if url.startswith("/"):
                    url = urljoin("https://seller-edu.ozon.ru", url)
                return url
        for match in re.finditer(
            r'<a[^>]+href=["\']([^"\']*\.xlsx[^"\']*)["\']',
            html,
            re.IGNORECASE,
        ):
            url = match.group(1)
            if url.startswith("/"):
                url = urljoin("https://seller-edu.ozon.ru", url)
            return url
        return None

    @staticmethod
    def _extract_file_name(url: str | None) -> str | None:
        if not url:
            return None
        parts = url.split("/")
        for part in reversed(parts):
            if part and (".xlsx" in part.lower() or ".xls" in part.lower()):
                return part.split("?")[0]
        return None


class OzonCommissionSourceMonitorService:
    """Monitor the Ozon commissions page for new tariff tables."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self._parser = OzonCommissionPageParser()

    async def check(self, url: str = OZON_COMMISSIONS_PAGE_URL) -> dict[str, Any]:
        """Fetch the page, parse it, compare with last check, and persist the result.

        Returns a summary dict.
        """
        logger.info("ozon_commission_source_check_started", extra={"source_url": url})

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=30.0,
                headers={"User-Agent": "MPControl/1.0 (commission-monitor)"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (403, 404):
                logger.warning(
                    "ozon_commission_source_unavailable",
                    extra={"status": status, "url": url, "error": str(exc)[:300]},
                )
                return await self._record_check(
                    url=url,
                    html_content=None,
                    change_type="unavailable",
                    error=f"HTTP {status}: {exc.response.reason_phrase or 'Forbidden/Not Found'}",
                )
            elif status == 429:
                logger.warning(
                    "ozon_commission_source_rate_limited",
                    extra={"status": status, "url": url},
                )
                return await self._record_check(
                    url=url,
                    html_content=None,
                    change_type="rate_limited",
                    error=f"HTTP 429: rate limited",
                )
            logger.error(
                "ozon_commission_source_http_error",
                extra={"status": status, "url": url, "error": str(exc)[:300]},
            )
            return await self._record_check(
                url=url,
                html_content=None,
                change_type="parse_error",
                error=f"HTTP {status}: {str(exc)[:200]}",
            )
        except httpx.TimeoutException as exc:
            logger.error(
                "ozon_commission_source_timeout",
                extra={"url": url, "error": str(exc)[:300]},
            )
            return await self._record_check(
                url=url,
                html_content=None,
                change_type="unavailable",
                error=f"Timeout: {str(exc)[:200]}",
            )
        except Exception as exc:
            logger.exception(
                "ozon_commission_source_check_failed",
                extra={"error_type": type(exc).__name__, "error": str(exc)[:300]},
            )
            return await self._record_check(
                url=url,
                html_content=None,
                change_type="parse_error",
                error=str(exc)[:300],
            )

        page_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()

        try:
            parsed = self._parser.parse(html)
        except Exception as exc:
            logger.exception(
                "ozon_commission_source_parse_error",
                extra={"error_type": type(exc).__name__, "error": str(exc)[:300]},
            )
            return await self._record_check(
                url=url,
                html_content=html,
                page_hash=page_hash,
                change_type="parse_error",
                error=str(exc)[:300],
            )

        last_check = await self._get_last_successful_check()
        change_type, has_changes = self._detect_changes(last_check, parsed)

        return await self._record_check(
            url=url,
            html_content=html,
            page_hash=page_hash,
            parsed=parsed,
            change_type=change_type,
            has_changes=has_changes,
        )

    async def _record_check(
        self,
        *,
        url: str,
        html_content: str | None,
        page_hash: str | None = None,
        parsed: dict[str, Any] | None = None,
        change_type: str = "no_change",
        has_changes: bool = False,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Persist the check result and return a summary."""
        if parsed is None:
            parsed = {}

        check = MarketplaceTariffSourceCheck(
            marketplace=Marketplace.OZON,
            source_url=url,
            checked_at=datetime.now(tz=UTC),
            page_hash=page_hash,
            current_detected_period_label=parsed.get("period_label"),
            current_detected_file_url=parsed.get("download_url"),
            current_detected_file_name=parsed.get("file_name"),
            has_changes=has_changes,
            change_type=change_type,
            details={
                "period_label": parsed.get("period_label"),
                "download_url": parsed.get("download_url"),
                "file_name": parsed.get("file_name"),
                "error": error,
            },
        )
        self.session.add(check)
        await self.session.commit()

        summary = {
            "success": change_type != "parse_error",
            "has_changes": has_changes,
            "change_type": change_type,
            "period_label": parsed.get("period_label"),
            "download_url": parsed.get("download_url"),
            "file_name": parsed.get("file_name"),
            "check_id": check.id,
        }

        if has_changes and change_type != "parse_error":
            logger.info(
                "ozon_commission_source_update_detected",
                extra={
                    "change_type": change_type,
                    "period_label": parsed.get("period_label"),
                    "download_url": parsed.get("download_url"),
                },
            )

        return summary

    async def _get_last_successful_check(self) -> MarketplaceTariffSourceCheck | None:
        from sqlalchemy import select

        from app.models.commission_tariffs import MarketplaceTariffSourceCheck as Check

        result = await self.session.execute(
            select(Check)
            .where(Check.marketplace == Marketplace.OZON)
            .where(Check.change_type != "parse_error")
            .order_by(Check.checked_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _detect_changes(
        last_check: MarketplaceTariffSourceCheck | None,
        parsed: dict[str, Any],
    ) -> tuple[str, bool]:
        """Compare parsed data with the last check to detect changes."""
        if last_check is None:
            return "new_period_detected", True

        last_period = last_check.current_detected_period_label
        last_url = last_check.current_detected_file_url
        new_period = parsed.get("period_label")
        new_url = parsed.get("download_url")

        if new_period and new_period != last_period:
            return "new_period_detected", True
        if new_url and new_url != last_url:
            return "file_url_changed", True

        return "no_change", False
