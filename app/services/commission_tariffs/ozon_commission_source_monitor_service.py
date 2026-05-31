"""version: 3.0.0
description: Ozon commission source page monitor — detects new tariff tables on the official page.
updated: 2026-05-31
"""

import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings
from app.models.commission_tariffs import MarketplaceTariffSourceCheck
from app.models.enums import Marketplace
from app.utils.log_sanitizer import sanitize_headers

logger = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 YaBrowser/26.4.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ru,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://seller-edu.ozon.ru/",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "YaBrowser";v="26.4", "Yowser";v="2.5"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}

API_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru,en;q=0.9",
    "x-o3-app-name": "seller-edu-center",
    "x-o3-app-version": "release/2026-05-29-01",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

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
        - active_from: str | None (ISO date if detected)
        """
        blocks = self._extract_all_period_blocks(html_content)
        if not blocks:
            return {
                "period_label": None,
                "download_url": None,
                "file_name": None,
                "active_from": None,
            }

        latest = blocks[0]
        return {
            "period_label": latest["period_label"],
            "download_url": latest["download_url"],
            "file_name": self._extract_file_name(latest["download_url"]),
            "active_from": latest.get("active_from"),
        }

    def _extract_all_period_blocks(self, html: str) -> list[dict[str, Any]]:
        """Find all period blocks with their download URLs, sorted by recency."""
        blocks = []
        base_url = "https://seller-edu.ozon.ru"

        pattern = re.compile(
            r'Таблица\s+категорий\s+с\s+(\d{1,2})\s+([а-яё]+)\s+(\d{4})\s*г\.?'
            r'(.*?)'
            r'(?=Таблица\s+категорий\s+с|\Z)',
            re.IGNORECASE | re.DOTALL,
        )

        for match in pattern.finditer(html):
            day = int(match.group(1))
            month_name = match.group(2).lower()
            year = int(match.group(3))
            block_content = match.group(4)

            month = self._parse_russian_month(month_name)
            active_from = None
            if month:
                try:
                    from datetime import date

                    active_from = date(year, month, day).isoformat()
                except ValueError:
                    pass

            period_label = match.group(0).split("\n")[0].strip()[:100]

            download_url = self._find_download_url_in_block(block_content, base_url)

            if download_url:
                blocks.append({
                    "period_label": period_label,
                    "download_url": download_url,
                    "active_from": active_from,
                    "sort_key": (year, month or 1, day),
                })

        blocks.sort(key=lambda b: b["sort_key"], reverse=True)
        return blocks

    def _find_download_url_in_block(self, block: str, base_url: str) -> str | None:
        """Find the primary download URL in a period block."""
        link_pattern = re.compile(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>',
            re.IGNORECASE,
        )

        for match in link_pattern.finditer(block):
            url = match.group(1)
            text = match.group(2).strip()

            if DOWNLOAD_LINK_TEXT_PATTERN.search(text):
                if "селект" in text.lower() or "select" in text.lower():
                    continue
                if url.startswith("/"):
                    url = urljoin(base_url, url)
                return str(url)

        for match in link_pattern.finditer(block):
            url = match.group(1)
            text = match.group(2).strip()

            if DOWNLOAD_LINK_TEXT_PATTERN.search(text):
                if url.startswith("/"):
                    url = urljoin(base_url, url)
                return str(url)

        xlsx_pattern = re.compile(
            r'<a[^>]+href=["\']([^"\']*\.xlsx[^"\']*)["\']',
            re.IGNORECASE,
        )
        for match in xlsx_pattern.finditer(block):
            url = match.group(1)
            if url.startswith("/"):
                url = urljoin(base_url, url)
            return str(url)

        return None

    @staticmethod
    def _parse_russian_month(name: str) -> int | None:
        """Parse Russian month name to number."""
        months = {
            "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
            "мая": 5, "июня": 6, "июля": 7, "августа": 8,
            "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
            "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
            "май": 5, "июнь": 6, "июль": 7, "август": 8,
            "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
        }
        return months.get(name.lower())

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

    async def check(self, url: str | None = None) -> dict[str, Any]:
        """Fetch the page, parse it, compare with last check, and persist the result.

        Tries HTTP first. On 403/404, falls back to browser if enabled.
        Returns a summary dict.
        """
        settings = get_settings()
        if url is None:
            url = settings.ozon_commissions_source_url

        fetch_mode = settings.ozon_commissions_fetch_mode

        logger.info(
            "ozon_commission_source_check_started",
            extra={"source_url": url, "fetch_mode": fetch_mode},
        )

        if fetch_mode == "browser":
            return await self._check_via_browser(url)

        if fetch_mode == "manual":
            return await self._record_check(
                url=url,
                html_content=None,
                change_type="manual_mode",
                error="Ручной режим: автоматическая проверка отключена",
                fetch_method="manual",
            )

        http_result = await self._check_via_http(url)

        if http_result is not None:
            return http_result

        if fetch_mode == "http":
            return await self._record_check(
                url=url,
                html_content=None,
                change_type="source_blocked",
                error=(
                    "Ozon заблокировал автоматическую проверку (HTTP 403). "
                    "Browser fallback отключён."
                ),
                fetch_method="http",
            )

        if settings.ozon_commissions_browser_fallback_enabled:
            logger.info("ozon_commission_source_http_blocked_trying_browser")
            browser_result = await self._check_via_browser(url)
            if browser_result.get("change_type") in (
                "source_unavailable", "source_blocked",
            ):
                return await self._record_check(
                    url=url,
                    html_content=None,
                    change_type="source_blocked",
                    error=(
                        "Ozon заблокировал проверку даже через "
                        "браузер (HTTP 403)."
                    ),
                    fetch_method="browser",
                )
            return browser_result

        return await self._record_check(
            url=url,
            html_content=None,
            change_type="source_blocked",
            error=(
                "Ozon заблокировал автоматическую проверку (HTTP 403). "
                "Browser fallback отключён."
            ),
            fetch_method="http",
        )

    async def _check_via_http(self, url: str) -> dict[str, Any] | None:
        """Try HTTP fetch. Returns None if 403/404 (caller should try browser fallback)."""
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(5.0, connect=3.0),
                headers=BROWSER_HEADERS,
            ) as client:
                response = await client.get(url)
                final_url = str(response.url)
                status_code = response.status_code

                logger.info(
                    "ozon_commission_source_page_fetched",
                    extra={
                        "source_url": url,
                        "final_url": final_url,
                        "status_code": status_code,
                        "content_length": len(response.content),
                    },
                )

                if status_code in (403, 404):
                    logger.warning(
                        "ozon_commission_source_http_blocked",
                        extra={
                            "status": status_code,
                            "url": url,
                            "final_url": final_url,
                        },
                    )
                    return None

                response.raise_for_status()
                html = response.text

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            final_url = str(exc.response.url)

            if status in (403, 404):
                return None

            if status == 429:
                logger.warning(
                    "ozon_commission_source_rate_limited",
                    extra={"status": status, "url": url, "final_url": final_url},
                )
                return await self._record_check(
                    url=url,
                    html_content=None,
                    change_type="source_unavailable",
                    error="HTTP 429: rate limited",
                    source_status_code=status,
                    source_final_url=final_url,
                    fetch_method="http",
                )
            logger.error(
                "ozon_commission_source_http_error",
                extra={
                    "status": status,
                    "url": url,
                    "final_url": final_url,
                    "error": str(exc)[:300],
                },
            )
            return await self._record_check(
                url=url,
                html_content=None,
                change_type="parse_error",
                error=f"HTTP {status}: {str(exc)[:200]}",
                source_status_code=status,
                source_final_url=final_url,
                fetch_method="http",
            )
        except httpx.TimeoutException as exc:
            logger.error(
                "ozon_commission_source_timeout",
                extra={"url": url, "error": str(exc)[:300]},
            )
            return await self._record_check(
                url=url,
                html_content=None,
                change_type="source_unavailable",
                error=f"Timeout: {str(exc)[:200]}",
                fetch_method="http",
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
                fetch_method="http",
            )

        page_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()

        try:
            parsed = self._parser.parse(html)
            logger.info(
                "ozon_commission_source_page_parsed",
                extra={
                    "period_label": parsed.get("period_label"),
                    "download_url": parsed.get("download_url"),
                    "file_name": parsed.get("file_name"),
                    "active_from": parsed.get("active_from"),
                },
            )
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
                error=f"HTML parse error: {str(exc)[:300]}",
                source_status_code=status_code,
                source_final_url=final_url,
                fetch_method="http",
            )

        file_url = parsed.get("download_url")
        file_hash = None
        file_status_code = None

        if file_url:
            file_result = await self._download_and_verify_file(file_url, url)
            file_hash = file_result.get("hash")
            file_status_code = file_result.get("status_code")

            if not file_result.get("valid"):
                logger.warning(
                    "ozon_commission_source_file_invalid",
                    extra={
                        "file_url": file_url,
                        "error": file_result.get("error"),
                    },
                )
                return await self._record_check(
                    url=url,
                    html_content=html,
                    page_hash=page_hash,
                    parsed=parsed,
                    change_type="file_unavailable",
                    error=file_result.get("error", "File validation failed"),
                    source_status_code=status_code,
                    source_final_url=final_url,
                    file_status_code=file_status_code,
                    file_hash=file_hash,
                    fetch_method="http",
                )

        last_check = await self._get_last_successful_check()
        change_type, has_changes = self._detect_changes(last_check, parsed, file_hash)

        logger.info(
            "ozon_commission_source_check_completed",
            extra={
                "change_type": change_type,
                "has_changes": has_changes,
                "period_label": parsed.get("period_label"),
                "fetch_method": "http",
            },
        )

        return await self._record_check(
            url=url,
            html_content=html,
            page_hash=page_hash,
            parsed=parsed,
            change_type=change_type,
            has_changes=has_changes,
            source_status_code=status_code,
            source_final_url=final_url,
            file_status_code=file_status_code,
            file_hash=file_hash,
            fetch_method="http",
        )

    async def _check_via_browser(self, url: str) -> dict[str, Any]:
        """Fallback check via Playwright browser."""
        from app.services.commission_tariffs.ozon_commission_browser_fetcher import (
            fetch_ozon_commissions_via_browser,
        )

        result = await fetch_ozon_commissions_via_browser(url)

        if not result.ok:
            if result.status == "source_unavailable":
                change_type = "source_blocked"
            elif result.status in ("browser_unavailable", "browser_error"):
                change_type = "source_unavailable"
            else:
                change_type = "file_unavailable"
            return await self._record_check(
                url=url,
                html_content=None,
                change_type=change_type,
                error=result.message,
                source_final_url=result.final_url,
                fetch_method="browser",
                technical_details=result.technical_details,
            )

        parsed = {
            "period_label": result.period_label,
            "download_url": result.file_url,
            "file_name": result.filename,
            "active_from": result.active_from.isoformat() if result.active_from else None,
        }

        last_check = await self._get_last_successful_check()
        change_type, has_changes = self._detect_changes(last_check, parsed, result.file_hash)

        logger.info(
            "ozon_commission_source_browser_check_completed",
            extra={
                "change_type": change_type,
                "has_changes": has_changes,
                "period_label": result.period_label,
                "fetch_method": "browser",
            },
        )

        return await self._record_check(
            url=url,
            html_content=None,
            page_hash=result.file_hash,
            parsed=parsed,
            change_type=change_type,
            has_changes=has_changes,
            source_final_url=result.final_url,
            file_hash=result.file_hash,
            fetch_method="browser",
            local_file_path=result.local_file_path,
            file_bytes=result.file_bytes,
        )

    async def _download_and_verify_file(
        self, file_url: str, referer_url: str
    ) -> dict[str, Any]:
        """Download the XLSX file and verify it's valid."""
        logger.info(
            "ozon_commission_source_file_download_started",
            extra={"file_url": file_url},
        )

        headers = dict(BROWSER_HEADERS)
        headers["Referer"] = referer_url

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(10.0, connect=3.0),
                headers=headers,
            ) as client:
                response = await client.get(file_url)
                status_code = response.status_code
                content = response.content

                logger.info(
                    "ozon_commission_source_file_downloaded",
                    extra={
                        "file_url": file_url,
                        "status_code": status_code,
                        "content_length": len(content),
                        "content_type": response.headers.get("content-type"),
                        "response_headers": sanitize_headers(dict(response.headers)),
                    },
                )

                if status_code != 200:
                    return {
                        "valid": False,
                        "status_code": status_code,
                        "error": f"HTTP {status_code}",
                    }

                if len(content) < 100:
                    return {
                        "valid": False,
                        "status_code": status_code,
                        "error": "File too small",
                    }

                if not content.startswith(b"PK"):
                    content_type = response.headers.get("content-type", "").lower()
                    if "html" in content_type or content[:15].lower().startswith(b"<!doctype"):
                        return {
                            "valid": False,
                            "status_code": status_code,
                            "error": "Received HTML instead of XLSX",
                        }
                    return {
                        "valid": False,
                        "status_code": status_code,
                        "error": "Invalid XLSX signature",
                    }

                file_hash = hashlib.sha256(content).hexdigest()

                return {
                    "valid": True,
                    "status_code": status_code,
                    "hash": file_hash,
                    "size": len(content),
                }

        except Exception as exc:
            logger.exception(
                "ozon_commission_source_file_download_failed",
                extra={
                    "file_url": file_url,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:300],
                },
            )
            return {
                "valid": False,
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }

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
        source_status_code: int | None = None,
        source_final_url: str | None = None,
        file_status_code: int | None = None,
        file_hash: str | None = None,
        fetch_method: str = "http",
        technical_details: str | None = None,
        local_file_path: str | None = None,
        file_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        """Persist the check result and return a summary."""
        if parsed is None:
            parsed = {}

        details = {
            "period_label": parsed.get("period_label"),
            "download_url": parsed.get("download_url"),
            "file_name": parsed.get("file_name"),
            "active_from": parsed.get("active_from"),
            "error": error,
            "source_status_code": source_status_code,
            "source_final_url": source_final_url,
            "file_status_code": file_status_code,
            "file_hash": file_hash,
            "fetch_method": fetch_method,
            "technical_details": technical_details,
            "local_file_path": local_file_path,
        }

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
            details=details,
            fetch_method=fetch_method,
        )
        self.session.add(check)
        await self.session.commit()

        period_label = parsed.get("period_label")

        summary = {
            "success": change_type not in (
                "parse_error", "source_unavailable", "source_blocked",
                "file_unavailable", "manual_mode",
            ),
            "has_changes": has_changes,
            "change_type": change_type,
            "period_label": period_label,
            "download_url": parsed.get("download_url"),
            "file_name": parsed.get("file_name"),
            "check_id": check.id,
            "error": error,
            "fetch_method": fetch_method,
            "local_file_path": local_file_path,
            "file_bytes": file_bytes,
        }

        if has_changes and change_type not in (
            "parse_error", "source_unavailable", "source_blocked",
            "file_unavailable", "manual_mode",
        ):
            logger.info(
                "ozon_commission_source_update_detected",
                extra={
                    "change_type": change_type,
                    "period_label": period_label,
                    "download_url": parsed.get("download_url"),
                    "fetch_method": fetch_method,
                },
            )

        return summary

    async def _get_last_successful_check(self) -> MarketplaceTariffSourceCheck | None:
        from sqlalchemy import select

        from app.models.commission_tariffs import MarketplaceTariffSourceCheck as Check

        result = await self.session.execute(
            select(Check)
            .where(Check.marketplace == Marketplace.OZON)
            .where(Check.change_type.notin_(
                ["parse_error", "source_unavailable", "source_blocked", "file_unavailable"]
            ))
            .order_by(Check.checked_at.desc())
            .limit(1)
        )
        return cast(MarketplaceTariffSourceCheck | None, result.scalar_one_or_none())

    @staticmethod
    def _detect_changes(
        last_check: MarketplaceTariffSourceCheck | None,
        parsed: dict[str, Any],
        file_hash: str | None = None,
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

        if file_hash and last_check.details:
            last_hash = last_check.details.get("file_hash")
            if last_hash and file_hash != last_hash:
                return "file_content_changed", True

        return "no_change", False
