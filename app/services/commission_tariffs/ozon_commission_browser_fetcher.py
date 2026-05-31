"""version: 1.0.0
description: Ozon commission browser fetcher — Playwright-based fallback for HTTP 403.
updated: 2026-05-31
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.core.config import get_settings
from app.services.commission_tariffs.xlsx_validator import validate_xlsx_file

logger = logging.getLogger(__name__)

PERIOD_BLOCK_PATTERN = re.compile(
    r"Таблица\s+категорий\s+с\s+(\d{1,2})\s+([а-яё]+)\s+(\d{4})\s*г\.?",
    re.IGNORECASE,
)

DOWNLOAD_LINK_TEXT_PATTERN = re.compile(
    r"скачать\s+таблицу\s+категорий(?!.*селект)(?!.*select)",
    re.IGNORECASE,
)

MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


@dataclass
class OzonCommissionFetchResult:
    ok: bool
    method: str
    source_url: str
    final_url: str | None = None
    period_label: str | None = None
    active_from: date | None = None
    file_url: str | None = None
    filename: str | None = None
    local_file_path: str | None = None
    file_size: int | None = None
    file_hash: str | None = None
    status: str | None = None
    message: str | None = None
    technical_details: str | None = None
    file_bytes: bytes | None = field(default=None, repr=False)


async def fetch_ozon_commissions_via_browser(
    source_url: str | None = None,
) -> OzonCommissionFetchResult:
    settings = get_settings()
    if source_url is None:
        source_url = settings.ozon_commissions_source_url

    timeout_ms = settings.ozon_commissions_browser_timeout_seconds * 1000
    headless = settings.ozon_commissions_browser_headless
    download_dir = Path(settings.ozon_commissions_download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240

    logger.info(
        "ozon_commission_browser_fetch_started",
        extra={"source_url": source_url, "headless": headless},
    )

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return OzonCommissionFetchResult(
            ok=False,
            method="browser",
            source_url=source_url,
            status="browser_unavailable",
            message=(
                "Playwright не установлен. Установите: "
                "pip install playwright && playwright install chromium"
            ),
        )

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            context = await browser.new_context(
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/146.0.0.0 YaBrowser/26.4.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 1000},
                extra_http_headers={
                    "Accept-Language": "ru,en;q=0.9",
                },
            )

            page = await context.new_page()

            response = await page.goto(
                source_url, wait_until="domcontentloaded", timeout=timeout_ms
            )

            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
            await page.wait_for_timeout(3000)

            html = await page.content()
            final_url = page.url

            logger.info(
                "ozon_commission_browser_page_loaded",
                extra={
                    "status_code": response.status if response else None,
                    "final_url": final_url,
                    "content_length": len(html),
                },
            )

            if response and response.status == 403:
                await browser.close()
                return OzonCommissionFetchResult(
                    ok=False,
                    method="browser",
                    source_url=source_url,
                    final_url=final_url,
                    status="source_unavailable",
                    message="HTTP 403 даже через браузер",
                )

            period_info = _extract_latest_period(html)

            download_link = await _find_download_link(page)
            if not download_link:
                await browser.close()
                return OzonCommissionFetchResult(
                    ok=False,
                    method="browser",
                    source_url=source_url,
                    final_url=final_url,
                    period_label=period_info.get("period_label"),
                    active_from=period_info.get("active_from"),
                    status="file_link_not_found",
                    message="Ссылка 'Скачать таблицу категорий' не найдена на странице",
                )

            file_url = download_link.get("href")
            file_bytes = None
            filename = None

            if file_url:
                file_result = await _download_file_via_context(
                    context, page, download_link, download_dir, timeout_ms
                )
                file_bytes = file_result.get("bytes")
                filename = file_result.get("filename")
                file_url = file_result.get("url", file_url)

            await browser.close()

            if not file_bytes:
                return OzonCommissionFetchResult(
                    ok=False,
                    method="browser",
                    source_url=source_url,
                    final_url=final_url,
                    period_label=period_info.get("period_label"),
                    active_from=period_info.get("active_from"),
                    file_url=file_url,
                    status="file_download_failed",
                    message="Не удалось скачать файл через браузер",
                )

            validation = validate_xlsx_file(file_bytes=file_bytes, file_name=filename)
            if not validation.valid:
                return OzonCommissionFetchResult(
                    ok=False,
                    method="browser",
                    source_url=source_url,
                    final_url=final_url,
                    period_label=period_info.get("period_label"),
                    active_from=period_info.get("active_from"),
                    file_url=file_url,
                    filename=filename,
                    file_size=len(file_bytes),
                    status=validation.status,
                    message=validation.message,
                )

            file_hash = hashlib.sha256(file_bytes).hexdigest()
            target_path = download_dir / (filename or "ozon_commissions.xlsx")
            target_path.write_bytes(file_bytes)

            logger.info(
                "ozon_commission_browser_fetch_completed",
                extra={
                    "source_filename": filename,
                    "file_size": len(file_bytes),
                    "file_hash": file_hash[:16],
                },
            )

            return OzonCommissionFetchResult(
                ok=True,
                method="browser",
                source_url=source_url,
                final_url=final_url,
                period_label=period_info.get("period_label"),
                active_from=period_info.get("active_from"),
                file_url=file_url,
                filename=filename,
                local_file_path=str(target_path),
                file_size=len(file_bytes),
                file_hash=file_hash,
                status="ok",
                message="Файл успешно скачан через браузер",
                file_bytes=file_bytes,
            )

    except Exception as exc:
        logger.exception(
            "ozon_commission_browser_fetch_error",
            extra={"error_type": type(exc).__name__, "error": str(exc)[:300]},
        )
        return OzonCommissionFetchResult(
            ok=False,
            method="browser",
            source_url=source_url,
            status="browser_error",
            message=f"{type(exc).__name__}: {str(exc)[:200]}",
        )


def _extract_latest_period(html: str) -> dict:
    matches = list(PERIOD_BLOCK_PATTERN.finditer(html))
    if not matches:
        return {"period_label": None, "active_from": None}

    best = None
    best_sort_key = (0, 0, 0)

    for match in matches:
        day = int(match.group(1))
        month_name = match.group(2).lower()
        year = int(match.group(3))
        month = MONTHS.get(month_name)
        if not month:
            continue
        sort_key = (year, month, day)
        if sort_key > best_sort_key:
            best_sort_key = sort_key
            try:
                active_from = date(year, month, day)
            except ValueError:
                active_from = None
            best = {
                "period_label": match.group(0).strip()[:100],
                "active_from": active_from,
            }

    return best or {"period_label": None, "active_from": None}


async def _find_download_link(page) -> None:
    try:
        selectors = [
            'a:has-text("Скачать таблицу категорий")',
            'a:has-text("скачать таблицу категорий")',
        ]
        for selector in selectors:
            elements = await page.query_selector_all(selector)
            for el in elements:
                text = await el.inner_text()
                text_lower = text.strip().lower()
                if "селект" in text_lower or "select" in text_lower:
                    continue
                if "скачать таблицу категорий" in text_lower:
                    return el
    except Exception:
        logger.debug("ozon_commission_browser_find_link_failed", exc_info=True)

    return None


async def _download_file_via_context(
    context, page, link_element, download_dir: Path, timeout_ms: int
) -> dict:
    try:
        href = await link_element.get_attribute("href")
        if href:
            if href.startswith("/"):
                href = f"https://seller-edu.ozon.ru{href}"

            api_response = await context.request.get(href)
            if api_response.ok:
                body = await api_response.body()
                content_type = api_response.headers.get("content-type", "")
                disposition = api_response.headers.get("content-disposition", "")

                filename = _extract_filename_from_disposition(disposition)
                if not filename and href:
                    filename = _extract_filename_from_url(href)
                if not filename:
                    filename = "ozon_commissions.xlsx"

                return {
                    "bytes": body,
                    "filename": filename,
                    "url": href,
                    "content_type": content_type,
                }

    except Exception:
        logger.debug("ozon_commission_browser_direct_download_failed", exc_info=True)

    try:
        async with page.expect_download(timeout=timeout_ms) as download_info:
            await link_element.click()

        download = await download_info.value
        suggested_filename = download.suggested_filename or "ozon_commissions.xlsx"
        target_path = download_dir / suggested_filename
        await download.save_as(str(target_path))

        file_bytes = target_path.read_bytes()
        return {
            "bytes": file_bytes,
            "filename": suggested_filename,
            "url": str(download.url),
        }
    except Exception:
        logger.debug("ozon_commission_browser_click_download_failed", exc_info=True)
        return {}


def _extract_filename_from_disposition(disposition: str) -> str | None:
    if not disposition:
        return None
    match = re.search(r'filename[*]?=["\']?([^"\';]+)', disposition, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _extract_filename_from_url(url: str) -> str | None:
    parts = url.split("/")
    for part in reversed(parts):
        if part and (".xlsx" in part.lower() or ".xls" in part.lower()):
            return part.split("?")[0]
    return None
