"""version: 2.1.0
description: WEB admin routes for commission tariff management.
updated: 2026-05-31
"""

# ruff: noqa: E501

import asyncio
import hashlib
import logging
from datetime import UTC, date, datetime
from html import escape

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.commission_tariffs import (
    MarketplaceCommissionImportLog,
    MarketplaceCommissionRate,
    MarketplaceCommissionVersion,
    MarketplaceTariffSourceCheck,
)
from app.models.domain import User
from app.models.enums import Marketplace
from app.services.ozon.commissions.ozon_commission_source_monitor_service import (
    OzonCommissionSourceMonitorService,
)
from app.services.ozon.commissions.ozon_commission_xlsx_importer import OzonCommissionXlsxImporter
from app.services.wb.commissions.wb_commission_sync_service import WbCommissionSyncService
from app.services.commissions.xlsx_validator import validate_xlsx_file
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY, is_admin_user
from app.web.rendering import page

logger = logging.getLogger(__name__)
router = APIRouter()

_ozon_check_lock = asyncio.Lock()
_ozon_check_last_started: datetime | None = None
_ozon_check_in_progress: bool = False
OZON_CHECK_COOLDOWN_SECONDS = 300

OZON_COMMISSION_FILE_FORM = File(...)
OZON_COMMISSION_EFFECTIVE_FROM_FORM = Form(...)
OZON_COMMISSION_VERSION_LABEL_FORM = Form(default="")


def _is_admin_user(user: User) -> bool:
    return is_admin_user(user)


def _admin_page(title: str, user: User, content: str) -> str:
    return page(
        title,
        f"{user.first_name or user.username or 'admin'} (admin)",
        content,
        active_path="/web/admin/commissions",
    )


def _require_admin(user: User) -> None:
    if not _is_admin_user(user):
        raise HTTPException(status_code=403, detail="Доступно только администраторам")


@router.get("/admin/commissions", response_class=HTMLResponse)
async def commissions_admin_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)

    wb_version, wb_rate_count = await _get_active_version_info(session, Marketplace.WB)
    ozon_version, ozon_rate_count = await _get_active_version_info(session, Marketplace.OZON)
    last_ozon_check = await _get_last_ozon_check(session)
    import_logs = await _get_recent_import_logs(session)
    recent_checks = await _get_recent_checks(session)
    all_versions = await _get_all_versions(session)

    content = _render_commissions_page(
        wb_version=wb_version,
        wb_rate_count=wb_rate_count,
        ozon_version=ozon_version,
        ozon_rate_count=ozon_rate_count,
        last_ozon_check=last_ozon_check,
        import_logs=import_logs,
        recent_checks=recent_checks,
        all_versions=all_versions,
    )
    return _admin_page("Комиссии маркетплейсов", user, content)


@router.post("/admin/commissions/sync-wb", response_class=HTMLResponse)
async def sync_wb_commissions_web(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)

    from app.core.security import TokenCipher
    from app.models.domain import MarketplaceAccount

    account_result = await session.execute(
        select(MarketplaceAccount)
        .where(MarketplaceAccount.marketplace == Marketplace.WB)
        .where(MarketplaceAccount.is_active.is_(True))
        .limit(1)
    )
    account = account_result.scalar_one_or_none()
    if not account:
        return _admin_page("Комиссии маркетплейсов", user, "<p>Нет активных WB-кабинетов.</p>")

    try:
        api_key = TokenCipher().decrypt(account.encrypted_api_key)
    except Exception:
        return _admin_page(
            "Комиссии маркетплейсов", user, "<p>Ошибка расшифровки API-ключа WB.</p>"
        )

    service = WbCommissionSyncService(session)
    result = await service.sync(api_key)
    await session.commit()

    message = result.get("message", "Синхронизация завершена.")
    return _admin_page(
        "Комиссии маркетплейсов",
        user,
        f'<div class="band"><h2>Результат синхронизации WB</h2><p>{escape(message)}</p>'
        f'<a href="/web/admin/commissions" class="button">Назад</a></div>',
    )


@router.get("/admin/commissions/check-ozon", response_class=HTMLResponse)
async def check_ozon_status_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)

    last_check = await _get_last_ozon_check(session)
    source_url = get_settings().ozon_commissions_source_url

    if _ozon_check_in_progress:
        content = _render_ozon_check_in_progress(source_url)
        return _admin_page("Проверка Ozon", user, content)

    if last_check:
        content = _render_ozon_check_result(last_check, source_url)
    else:
        content = _render_ozon_check_no_data(source_url)

    return _admin_page("Проверка Ozon", user, content)


@router.post("/admin/commissions/check-ozon", response_class=HTMLResponse)
async def check_ozon_commissions_web(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    global _ozon_check_in_progress, _ozon_check_last_started

    source_url = get_settings().ozon_commissions_source_url

    if _ozon_check_in_progress:
        content = _render_ozon_check_in_progress(source_url)
        return _admin_page("Проверка Ozon", user, content)

    now = datetime.now(tz=UTC)
    if _ozon_check_last_started:
        elapsed = (now - _ozon_check_last_started).total_seconds()
        if elapsed < OZON_CHECK_COOLDOWN_SECONDS:
            remaining = int(OZON_CHECK_COOLDOWN_SECONDS - elapsed)
            content = _render_ozon_check_cooldown(remaining, source_url)
            return _admin_page("Проверка Ozon", user, content)

    _ozon_check_in_progress = True
    _ozon_check_last_started = now
    asyncio.create_task(_run_ozon_check_background())

    content = _render_ozon_check_started(source_url)
    return _admin_page("Проверка Ozon", user, content)


@router.get("/admin/commissions/check-ozon/status", response_class=HTMLResponse)
async def check_ozon_status_json(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)

    last_check = await _get_last_ozon_check(session)
    source_url = get_settings().ozon_commissions_source_url

    if _ozon_check_in_progress:
        return _render_ozon_check_in_progress(source_url, auto_refresh=True)

    if last_check:
        return _render_ozon_check_result(last_check, source_url)

    return _render_ozon_check_no_data(source_url)


async def _run_ozon_check_background() -> None:
    global _ozon_check_in_progress
    try:
        from app.core.db import get_session_context

        async with get_session_context() as session:
            service = OzonCommissionSourceMonitorService(session)
            await service.check()
    except Exception:
        logger.exception("ozon_check_background_failed")
    finally:
        _ozon_check_in_progress = False


def _render_ozon_check_started(source_url: str) -> str:
    return (
        '<div class="band"><h2>Проверка Ozon запущена</h2>'
        "<p>Проверка выполняется в фоне. Страница обновится автоматически.</p>"
        '<p class="muted">Обычно это занимает 5–15 секунд.</p>'
        '<meta http-equiv="refresh" content="5;url=/web/admin/commissions/check-ozon/status">'
        '<div class="filters">'
        '<a href="/web/admin/commissions/check-ozon" class="button">Обновить статус</a>'
        '<a href="/web/admin/commissions" class="button">Назад</a>'
        "</div></div>"
    )


def _render_ozon_check_in_progress(source_url: str, *, auto_refresh: bool = False) -> str:
    refresh = '<meta http-equiv="refresh" content="5">' if auto_refresh else ""
    return (
        f'<div class="band"><h2>Проверка выполняется</h2>'
        f"{refresh}"
        "<p>Автоматическая проверка Ozon выполняется в фоне.</p>"
        '<p class="muted">Подождите несколько секунд и обновите страницу.</p>'
        f'<div class="filters">'
        f'<a href="/web/admin/commissions/check-ozon/status" class="button">Обновить статус</a>'
        f'<a href="/web/admin/commissions" class="button">Назад</a>'
        f"</div></div>"
    )


def _render_ozon_check_cooldown(remaining: int, source_url: str) -> str:
    minutes = remaining // 60
    seconds = remaining % 60
    time_str = f"{minutes} мин {seconds} сек" if minutes else f"{seconds} сек"
    last_check_html = ""
    return (
        f'<div class="band"><h2>Проверка недавно выполнялась</h2>'
        f"<p>Повторная проверка будет доступна через {escape(time_str)}.</p>"
        f'<p class="muted">Cooldown: {OZON_CHECK_COOLDOWN_SECONDS // 60} минут между проверками.</p>'
        f"{last_check_html}"
        f'<div class="filters">'
        f'<a href="{escape(source_url)}" target="_blank" rel="noopener" class="button">'
        f"Открыть страницу Ozon</a>"
        f'<a href="/web/admin/commissions/manual-upload" class="button">Загрузить XLSX вручную</a>'
        f'<a href="/web/admin/commissions" class="button">Назад</a>'
        f"</div></div>"
    )


def _render_ozon_check_no_data(source_url: str) -> str:
    return (
        '<div class="band"><h2>Проверка Ozon</h2>'
        "<p>Проверки ещё не выполнялись.</p>"
        f'<div class="filters">'
        f'<form action="/web/admin/commissions/check-ozon" method="post" style="display:inline">'
        f'<button type="submit" class="button primary">Запустить проверку</button></form>'
        f'<a href="{escape(source_url)}" target="_blank" rel="noopener" class="button">'
        f"Открыть страницу Ozon</a>"
        f'<a href="/web/admin/commissions/manual-upload" class="button">Загрузить XLSX вручную</a>'
        f'<a href="/web/admin/commissions" class="button">Назад</a>'
        f"</div></div>"
    )


def _render_ozon_check_result(last_check: MarketplaceTariffSourceCheck, source_url: str) -> str:
    period_raw = last_check.current_detected_period_label
    period = escape(period_raw if period_raw else "Период не определён")
    change_type = last_check.change_type
    fetch_method = getattr(last_check, "fetch_method", None) or "http"
    status_badge = _change_type_badge(change_type)
    method_info = _fetch_method_label(fetch_method)

    download_link = ""
    if last_check.has_changes and last_check.current_detected_file_url:
        safe_url = escape(last_check.current_detected_file_url)
        safe_name = escape(last_check.current_detected_file_name or "Актуальный файл Ozon")
        download_link = (
            f'<p><a href="{safe_url}" target="_blank" rel="noopener" '
            f'class="button primary">📥 Скачать актуальный файл: {safe_name}</a></p>'
        )

    error_info = ""
    if change_type in ("source_unavailable", "file_unavailable", "unavailable", "rate_limited"):
        error_detail = ""
        if isinstance(last_check.details, dict) and last_check.details.get("error"):
            error_detail = escape(str(last_check.details["error"])[:300])
        error_info = (
            '<div class="band" style="border-left: 3px solid var(--warning);">'
            "<h3>Автоматическая проверка Ozon заблокирована источником</h3>"
            "<p>Ozon вернул HTTP 403 даже при проверке через браузерный режим.</p>"
            "<p>Последняя рабочая версия комиссий сохранена и продолжает использоваться.</p>"
            "<p><b>Вы можете:</b></p>"
            "<ol>"
            "<li>открыть страницу Ozon вручную;</li>"
            "<li>скачать XLSX-файл;</li>"
            "<li>загрузить его вручную в MP Control.</li>"
            "</ol>"
        )
        if error_detail:
            error_info += (
                f"<details><summary>Техническая информация</summary>"
                f'<pre class="mono">{error_detail}</pre></details>'
            )
        error_info += "</div>"
    elif change_type == "parse_error":
        error_msg = ""
        if isinstance(last_check.details, dict) and last_check.details.get("error"):
            error_msg = escape(str(last_check.details["error"])[:300])
        error_info = (
            "<p>⚠️ Ошибка парсинга</p>"
            "<p>Формат страницы или файла Ozon мог измениться. Требуется обновление парсера.</p>"
        )
        if error_msg:
            error_info += f'<details><summary>Техническая информация</summary><pre class="mono">{error_msg}</pre></details>'
    elif change_type == "manual_mode":
        error_info = "<p>Автоматическая проверка отключена. Используйте ручную загрузку XLSX.</p>"

    checked_at_str = (
        last_check.checked_at.strftime("%d.%m.%Y %H:%M:%S UTC") if last_check.checked_at else "—"
    )

    buttons = (
        f'<div class="filters">'
        f'<a href="{escape(source_url)}" target="_blank" rel="noopener" class="button">'
        f"Открыть страницу Ozon</a>"
        f'<form action="/web/admin/commissions/check-ozon" method="post" style="display:inline">'
        f'<button type="submit" class="button">Повторить проверку</button></form>'
        f'<a href="/web/admin/commissions/manual-upload" class="button">Загрузить XLSX вручную</a>'
        f'<a href="/web/admin/commissions" class="button">Назад</a>'
        f"</div>"
    )

    return (
        f'<div class="band"><h2>Результат последней проверки Ozon</h2>'
        f"<p><b>Дата проверки:</b> {checked_at_str}</p>"
        f"<p><b>Текущий период:</b> {period}</p>"
        f"<p><b>Результат:</b> {status_badge}</p>"
        f"<p><b>Способ получения:</b> {method_info}</p>"
        f"{download_link}"
        f"{error_info}"
        f"{buttons}"
        f"</div>"
    )


@router.post("/admin/commissions/import-ozon", response_class=HTMLResponse)
async def import_ozon_commissions_web(
    file: UploadFile = OZON_COMMISSION_FILE_FORM,
    effective_from: str = OZON_COMMISSION_EFFECTIVE_FROM_FORM,
    version_label: str = OZON_COMMISSION_VERSION_LABEL_FORM,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        return _admin_page(
            "Комиссии маркетплейсов",
            user,
            '<div class="band"><h2>Ошибка</h2><p>Файл должен быть в формате .xlsx</p>'
            '<a href="/web/admin/commissions" class="button">Назад</a></div>',
        )

    try:
        parts = effective_from.strip().split(".")
        eff_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
    except Exception:
        return _admin_page(
            "Комиссии маркетплейсов",
            user,
            '<div class="band"><h2>Ошибка</h2><p>Неверный формат даты. Используйте ДД.ММ.ГГГГ</p>'
            '<a href="/web/admin/commissions" class="button">Назад</a></div>',
        )

    file_bytes = await file.read()
    importer = OzonCommissionXlsxImporter(session)
    result = await importer.validate_and_import(
        file_bytes=file_bytes,
        file_name=file.filename,
        effective_from=eff_date,
        version_label=version_label or None,
        uploaded_by_user_id=user.id,
    )

    message = result.get("message", "Импорт завершён.")
    success = result.get("success", False)

    return _admin_page(
        "Комиссии маркетплейсов",
        user,
        f'<div class="band"><h2>{"✅ Успех" if success else "❌ Ошибка"}</h2>'
        f"<p>{escape(message)}</p>"
        f'<a href="/web/admin/commissions" class="button">Назад</a></div>',
    )


async def _get_active_version_info(
    session: AsyncSession,
    marketplace: Marketplace,
) -> tuple[MarketplaceCommissionVersion | None, int]:
    version_result = await session.execute(
        select(MarketplaceCommissionVersion)
        .where(MarketplaceCommissionVersion.marketplace == marketplace)
        .where(MarketplaceCommissionVersion.is_active.is_(True))
        .order_by(MarketplaceCommissionVersion.effective_from.desc())
        .limit(1)
    )
    version = version_result.scalar_one_or_none()
    if not version:
        return None, 0

    count_result = await session.execute(
        select(func.count(MarketplaceCommissionRate.id)).where(
            MarketplaceCommissionRate.version_id == version.id
        )
    )
    return version, int(count_result.scalar_one() or 0)


async def _get_last_ozon_check(session: AsyncSession) -> MarketplaceTariffSourceCheck | None:
    result = await session.execute(
        select(MarketplaceTariffSourceCheck)
        .where(MarketplaceTariffSourceCheck.marketplace == Marketplace.OZON)
        .order_by(MarketplaceTariffSourceCheck.checked_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_recent_import_logs(session: AsyncSession) -> list[MarketplaceCommissionImportLog]:
    result = await session.execute(
        select(MarketplaceCommissionImportLog)
        .where(MarketplaceCommissionImportLog.marketplace == Marketplace.OZON)
        .order_by(MarketplaceCommissionImportLog.created_at.desc())
        .limit(10)
    )
    return list(result.scalars().all())


async def _get_recent_checks(session: AsyncSession) -> list[MarketplaceTariffSourceCheck]:
    result = await session.execute(
        select(MarketplaceTariffSourceCheck)
        .where(MarketplaceTariffSourceCheck.marketplace == Marketplace.OZON)
        .order_by(MarketplaceTariffSourceCheck.checked_at.desc())
        .limit(10)
    )
    return list(result.scalars().all())


async def _get_all_versions(session: AsyncSession) -> list[MarketplaceCommissionVersion]:
    result = await session.execute(
        select(MarketplaceCommissionVersion)
        .order_by(
            MarketplaceCommissionVersion.marketplace,
            MarketplaceCommissionVersion.effective_from.desc(),
        )
        .limit(50)
    )
    return list(result.scalars().all())


def _render_commissions_page(
    *,
    wb_version: MarketplaceCommissionVersion | None,
    wb_rate_count: int,
    ozon_version: MarketplaceCommissionVersion | None,
    ozon_rate_count: int,
    last_ozon_check: MarketplaceTariffSourceCheck | None,
    import_logs: list[MarketplaceCommissionImportLog],
    recent_checks: list[MarketplaceTariffSourceCheck],
    all_versions: list[MarketplaceCommissionVersion],
) -> str:
    sections = []

    sections.append(_wb_card(wb_version, wb_rate_count))
    sections.append(_ozon_card(ozon_version, ozon_rate_count, last_ozon_check))
    sections.append(_import_form())
    sections.append(_versions_table(all_versions))
    sections.append(_import_logs_table(import_logs))
    sections.append(_checks_table(recent_checks))

    return "\n".join(sections)


def _wb_card(version: MarketplaceCommissionVersion | None, rate_count: int) -> str:
    if version:
        status = f"Активна с {version.effective_from.isoformat()}"
        label = escape(version.version_label)
    else:
        status = "Нет активной версии"
        label = "—"
    return (
        '<div class="band">'
        '<div class="section-head">'
        "<h2>🟣 Wildberries</h2>"
        '<form action="/web/admin/commissions/sync-wb" method="post">'
        '<button type="submit" class="button primary">🔄 Обновить комиссии WB</button>'
        "</form></div>"
        f"<p><b>Версия:</b> {label}</p>"
        f"<p><b>Статус:</b> {escape(status)}</p>"
        f"<p><b>Ставок:</b> {rate_count}</p>"
        "</div>"
    )


def _ozon_card(
    version: MarketplaceCommissionVersion | None,
    rate_count: int,
    last_check: MarketplaceTariffSourceCheck | None,
) -> str:
    if version:
        status = f"Активна с {version.effective_from.isoformat()}"
        label = escape(version.version_label)
        file_name = escape(version.source_file_name or "—")
    else:
        status = "Нет активной версии"
        label = "—"
        file_name = "—"

    source_url = get_settings().ozon_commissions_source_url

    check_info = ""
    if last_check:
        period_raw = last_check.current_detected_period_label
        period = escape(period_raw if period_raw else "Период не определён")
        change_badge = _change_type_badge(last_check.change_type)
        fetch_method = getattr(last_check, "fetch_method", None) or "http"
        method_badge = _fetch_method_label(fetch_method)
        check_info = (
            f"<p><b>Последняя проверка:</b> {change_badge}</p>"
            f"<p><b>Период:</b> {period}</p>"
            f"<p><b>Способ:</b> {method_badge}</p>"
        )
        if last_check.has_changes and last_check.current_detected_file_url:
            safe_url = escape(last_check.current_detected_file_url)
            safe_name = escape(last_check.current_detected_file_name or "Актуальный файл Ozon")
            check_info += (
                f'<p><a href="{safe_url}" target="_blank" rel="noopener" '
                f'class="button primary">📥 Скачать актуальный файл: {safe_name}</a></p>'
            )
        elif last_check.change_type in (
            "source_unavailable",
            "source_blocked",
            "unavailable",
            "rate_limited",
            "file_unavailable",
        ):
            error_msg = ""
            if isinstance(last_check.details, dict) and last_check.details.get("error"):
                error_msg = escape(str(last_check.details["error"])[:200])
            check_info += (
                '<p class="muted">Автоматическая проверка Ozon заблокирована источником. '
                "Последняя рабочая версия комиссий сохранена и продолжает использоваться.</p>"
            )
            check_info += (
                '<p class="muted">Вы можете:</p>'
                '<ol class="muted">'
                "<li>открыть страницу Ozon вручную;</li>"
                "<li>скачать XLSX-файл;</li>"
                "<li>загрузить его вручную в MP Control.</li>"
                "</ol>"
            )
            check_info += (
                f'<div class="filters">'
                f'<a href="{escape(source_url)}" target="_blank" rel="noopener" class="button">'
                f"Открыть страницу Ozon</a>"
                f'<a href="/web/admin/commissions/manual-upload" class="button">'
                f"Загрузить XLSX вручную</a>"
                f'<a href="/web/admin/commissions/check-ozon" class="button">'
                f"История проверок</a>"
                f"</div>"
            )
            if error_msg:
                check_info += f'<details><summary>Техническая информация</summary><pre class="mono">{error_msg}</pre></details>'

    return (
        '<div class="band">'
        '<div class="section-head">'
        "<h2>🔵 Ozon</h2>"
        '<form action="/web/admin/commissions/check-ozon" method="post">'
        '<button type="submit" class="button">🔍 Проверить страницу Ozon</button>'
        "</form></div>"
        f"<p><b>Версия:</b> {label}</p>"
        f"<p><b>Статус:</b> {escape(status)}</p>"
        f"<p><b>Файл:</b> {file_name}</p>"
        f"<p><b>Ставок:</b> {rate_count}</p>"
        f'<p><a href="{escape(source_url)}" target="_blank" rel="noopener">Открыть страницу комиссий Ozon</a></p>'
        f"{check_info}"
        "</div>"
    )


def _import_form() -> str:
    return (
        '<div class="band" id="manual-upload">'
        "<h2>📥 Загрузить таблицу комиссий Ozon</h2>"
        '<p><a href="/web/admin/commissions/manual-upload" class="button primary">'
        "Ручная загрузка с preview</a></p>"
        "<details><summary>Быстрая загрузка (без preview)</summary>"
        '<form action="/web/admin/commissions/import-ozon" method="post" enctype="multipart/form-data">'
        '<div class="filters">'
        "<div><label>Файл XLSX</label>"
        '<input type="file" name="file" accept=".xlsx,.xls" required></div>'
        "<div><label>Дата начала (ДД.ММ.ГГГГ)</label>"
        '<input type="text" name="effective_from" placeholder="06.04.2026" required></div>'
        "<div><label>Название версии (опционально)</label>"
        '<input type="text" name="version_label" placeholder="Ozon commissions from ..."></div>'
        "</div>"
        '<button type="submit" class="button primary">Загрузить и импортировать</button>'
        "</form></details></div>"
    )


def _versions_table(versions: list[MarketplaceCommissionVersion]) -> str:
    rows = ""
    for v in versions:
        mp_class = "wb" if v.marketplace == Marketplace.WB else "ozon"
        active_badge = (
            '<span class="badge good">активна</span>'
            if v.is_active
            else '<span class="badge">архив</span>'
        )
        effective_to = v.effective_to.isoformat() if v.effective_to else "—"
        rows += (
            "<tr>"
            f'<td><span class="marketplace-badge {mp_class}">{v.marketplace.value}</span></td>'
            f"<td>{escape(v.version_label)}</td>"
            f"<td>{v.effective_from.isoformat()}</td>"
            f"<td>{effective_to}</td>"
            f"<td>{escape(v.source_type)}</td>"
            f"<td>{active_badge}</td>"
            f"<td>{v.imported_at.strftime('%d.%m.%Y %H:%M') if v.imported_at else '—'}</td>"
            "</tr>"
        )

    return (
        '<div class="band"><h2>📋 История версий</h2>'
        '<div class="table-wrap"><table class="table">'
        "<thead><tr>"
        "<th>МП</th><th>Версия</th><th>С</th><th>По</th><th>Источник</th><th>Статус</th><th>Импортирована</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table></div></div>"
    )


def _import_logs_table(logs: list[MarketplaceCommissionImportLog]) -> str:
    rows = ""
    for log in logs:
        status_badge = {
            "imported": '<span class="badge good">импортирован</span>',
            "failed": '<span class="badge bad">ошибка</span>',
            "validation_failed": '<span class="badge warn">валидация</span>',
            "uploaded": '<span class="badge">загружен</span>',
            "validated": '<span class="badge action">валидирован</span>',
        }.get(log.status, f'<span class="badge">{log.status}</span>')
        rows += (
            "<tr>"
            f"<td>{escape(log.file_name)}</td>"
            f"<td>{status_badge}</td>"
            f"<td>{log.rows_total}</td>"
            f"<td>{log.rows_imported}</td>"
            f"<td>{log.rows_failed}</td>"
            f"<td>{log.created_at.strftime('%d.%m.%Y %H:%M') if log.created_at else '—'}</td>"
            "</tr>"
        )

    return (
        '<div class="band"><h2>📄 История импортов Ozon</h2>'
        '<div class="table-wrap"><table class="table">'
        "<thead><tr>"
        "<th>Файл</th><th>Статус</th><th>Всего строк</th><th>Импортировано</th><th>Ошибки</th><th>Дата</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table></div></div>"
    )


def _checks_table(checks: list[MarketplaceTariffSourceCheck]) -> str:
    rows = ""
    for c in checks:
        change_label = _change_type_badge(c.change_type)
        period_raw = c.current_detected_period_label
        period = escape(period_raw if period_raw else "Период не определён")
        fetch_method = getattr(c, "fetch_method", None) or "http"
        method_badge = _fetch_method_label(fetch_method)

        file_cell = "—"
        if c.current_detected_file_url:
            safe_url = escape(c.current_detected_file_url)
            safe_name = escape(c.current_detected_file_name or "Скачать файл")
            file_cell = f'<a href="{safe_url}" target="_blank" rel="noopener">{safe_name}</a>'
        elif c.current_detected_file_name:
            file_cell = escape(c.current_detected_file_name)

        actions = ""
        if c.has_changes and c.current_detected_file_url:
            actions = (
                f'<a href="{escape(c.current_detected_file_url)}" target="_blank" '
                f'rel="noopener" class="button primary">Скачать актуальный файл</a>'
            )
        elif c.change_type == "parse_error":
            error_detail = ""
            if isinstance(c.details, dict) and c.details.get("error"):
                error_detail = escape(str(c.details["error"])[:200])
            actions = (
                f"<details><summary>Подробнее</summary>"
                f'<pre class="mono">{error_detail}</pre></details>'
            )

        rows += (
            "<tr>"
            f"<td>{c.checked_at.strftime('%d.%m.%Y %H:%M') if c.checked_at else '—'}</td>"
            f"<td>{period}</td>"
            f"<td>{change_label}</td>"
            f"<td>{method_badge}</td>"
            f"<td>{file_cell}</td>"
            f"<td>{actions}</td>"
            "</tr>"
        )

    return (
        '<div class="band"><h2>🔍 История проверок Ozon</h2>'
        '<div class="table-wrap"><table class="table">'
        "<thead><tr>"
        "<th>Дата</th><th>Период</th><th>Изменения</th><th>Способ</th><th>Файл</th><th>Действия</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table></div></div>"
    )


@router.get("/admin/commissions/manual-upload", response_class=HTMLResponse)
async def manual_upload_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    return _admin_page("Ручная загрузка комиссий Ozon", user, _manual_upload_form())


@router.post("/admin/commissions/manual-upload/preview", response_class=HTMLResponse)
async def manual_upload_preview(
    file: UploadFile = OZON_COMMISSION_FILE_FORM,
    effective_from: str = OZON_COMMISSION_EFFECTIVE_FROM_FORM,
    version_label: str = OZON_COMMISSION_VERSION_LABEL_FORM,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        return _admin_page(
            "Ручная загрузка комиссий Ozon",
            user,
            '<div class="band"><h2>Ошибка</h2><p>Файл должен быть в формате .xlsx</p>'
            '<a href="/web/admin/commissions/manual-upload" class="button">Назад</a></div>',
        )

    try:
        parts = effective_from.strip().split(".")
        eff_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
    except Exception:
        return _admin_page(
            "Ручная загрузка комиссий Ozon",
            user,
            '<div class="band"><h2>Ошибка</h2><p>Неверный формат даты. Используйте ДД.ММ.ГГГГ</p>'
            '<a href="/web/admin/commissions/manual-upload" class="button">Назад</a></div>',
        )

    file_bytes = await file.read()

    validation = validate_xlsx_file(file_bytes=file_bytes, file_name=file.filename)
    if not validation.valid:
        return _admin_page(
            "Ручная загрузка комиссий Ozon",
            user,
            f'<div class="band"><h2>Файл невалидный</h2>'
            f"<p>Статус: {escape(validation.status)}</p>"
            f"<p>{escape(validation.message or '')}</p>"
            f'<a href="/web/admin/commissions/manual-upload" class="button">Назад</a></div>',
        )

    file_hash = hashlib.sha256(file_bytes).hexdigest()

    importer = OzonCommissionXlsxImporter(session)
    existing = await importer._find_import_by_sha256(file_hash)
    if existing and existing.status == "imported":
        return _admin_page(
            "Ручная загрузка комиссий Ozon",
            user,
            f'<div class="band"><h2>Дубликат</h2>'
            f"<p>Этот файл уже был импортирован ранее (ID: {existing.id}).</p>"
            f'<a href="/web/admin/commissions" class="button">Назад</a></div>',
        )

    from io import BytesIO

    import openpyxl

    wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    sheet = importer._find_sheet(wb)
    rates_count = 0
    if sheet:
        rates_data = importer._parse_rates(sheet)
        rates_count = len(rates_data)
    wb.close()

    active_version = await importer._get_active_ozon_version()
    diff_summary = {}
    if active_version and rates_count > 0:
        temp_version_label = f"preview_{file_hash[:8]}"
        preview_result = await importer.validate_and_import(
            file_bytes=file_bytes,
            file_name=file.filename,
            effective_from=eff_date,
            version_label=temp_version_label,
            uploaded_by_user_id=user.id,
        )
        if preview_result.get("success"):
            diff_summary = preview_result.get("diff_summary", {})
            preview_version_id = preview_result.get("version_id")
            if preview_version_id:
                await _deactivate_version(session, preview_version_id)
                if active_version:
                    await _reactivate_version(session, active_version.id)

    preview_html = _render_preview(
        file_name=file.filename,
        file_size=len(file_bytes),
        file_hash=file_hash,
        effective_from=eff_date,
        version_label=version_label,
        rates_count=rates_count,
        diff_summary=diff_summary,
        sheet_names=validation.sheet_names,
    )

    return _admin_page("Ручная загрузка комиссий Ozon", user, preview_html)


@router.post("/admin/commissions/manual-upload/apply", response_class=HTMLResponse)
async def manual_upload_apply(
    file: UploadFile = OZON_COMMISSION_FILE_FORM,
    effective_from: str = OZON_COMMISSION_EFFECTIVE_FROM_FORM,
    version_label: str = OZON_COMMISSION_VERSION_LABEL_FORM,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        return _admin_page(
            "Ручная загрузка комиссий Ozon",
            user,
            '<div class="band"><h2>Ошибка</h2><p>Файл должен быть в формате .xlsx</p>'
            '<a href="/web/admin/commissions" class="button">Назад</a></div>',
        )

    try:
        parts = effective_from.strip().split(".")
        eff_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
    except Exception:
        return _admin_page(
            "Ручная загрузка комиссий Ozon",
            user,
            '<div class="band"><h2>Ошибка</h2><p>Неверный формат даты.</p>'
            '<a href="/web/admin/commissions" class="button">Назад</a></div>',
        )

    file_bytes = await file.read()

    validation = validate_xlsx_file(file_bytes=file_bytes, file_name=file.filename)
    if not validation.valid:
        return _admin_page(
            "Ручная загрузка комиссий Ozon",
            user,
            f'<div class="band"><h2>Файл невалидный</h2>'
            f"<p>{escape(validation.message or '')}</p>"
            f'<a href="/web/admin/commissions" class="button">Назад</a></div>',
        )

    importer = OzonCommissionXlsxImporter(session)
    result = await importer.validate_and_import(
        file_bytes=file_bytes,
        file_name=file.filename,
        effective_from=eff_date,
        version_label=version_label or None,
        uploaded_by_user_id=user.id,
    )

    message = result.get("message", "Импорт завершён.")
    success = result.get("success", False)

    return _admin_page(
        "Ручная загрузка комиссий Ozon",
        user,
        f'<div class="band"><h2>{"✅ Успех" if success else "❌ Ошибка"}</h2>'
        f"<p>{escape(message)}</p>"
        f'<a href="/web/admin/commissions" class="button">Назад</a></div>',
    )


async def _deactivate_version(session: AsyncSession, version_id: int) -> None:
    from sqlalchemy import update

    await session.execute(
        update(MarketplaceCommissionVersion)
        .where(MarketplaceCommissionVersion.id == version_id)
        .values(is_active=False)
    )
    await session.flush()


async def _reactivate_version(session: AsyncSession, version_id: int) -> None:
    from sqlalchemy import update

    await session.execute(
        update(MarketplaceCommissionVersion)
        .where(MarketplaceCommissionVersion.id == version_id)
        .values(is_active=True, effective_to=None)
    )
    await session.flush()


def _manual_upload_form() -> str:
    return (
        '<div class="band" id="manual-upload">'
        "<h2>📥 Ручная загрузка файла комиссий Ozon</h2>"
        '<form action="/web/admin/commissions/manual-upload/preview" method="post" enctype="multipart/form-data">'
        '<div class="filters">'
        "<div><label>Файл XLSX</label>"
        '<input type="file" name="file" accept=".xlsx,.xls" required></div>'
        "<div><label>Дата начала (ДД.ММ.ГГГГ)</label>"
        '<input type="text" name="effective_from" placeholder="06.04.2026" required></div>'
        "<div><label>Название версии (опционально)</label>"
        '<input type="text" name="version_label" placeholder="Ozon commissions from ..."></div>'
        "</div>"
        '<button type="submit" class="button primary">Предпросмотр</button>'
        "</form>"
        '<p class="muted">Файл будет проверен и показан preview перед активацией.</p>'
        '<p><a href="/web/admin/commissions" class="button">Назад</a></p>'
        "</div>"
    )


def _render_preview(
    *,
    file_name: str,
    file_size: int,
    file_hash: str,
    effective_from: date,
    version_label: str,
    rates_count: int,
    diff_summary: dict[str, object],
    sheet_names: list[str] | None = None,
) -> str:
    diff_parts = []
    if diff_summary:
        added = diff_summary.get("added", 0)
        removed = diff_summary.get("removed", 0)
        changed = diff_summary.get("changed", 0)
        if added:
            diff_parts.append(f'<span class="badge good">+{added} добавлено</span>')
        if removed:
            diff_parts.append(f'<span class="badge bad">-{removed} удалено</span>')
        if changed:
            diff_parts.append(f'<span class="badge action">~{changed} изменено</span>')
    diff_html = " ".join(diff_parts) if diff_parts else '<span class="badge">Нет изменений</span>'

    sheets_html = ""
    if sheet_names:
        sheets_html = f"<p><b>Листы:</b> {escape(', '.join(sheet_names))}</p>"

    return (
        f'<div class="band"><h2>Preview файла комиссий</h2>'
        f"<p><b>Файл:</b> {escape(file_name)}</p>"
        f"<p><b>Размер:</b> {file_size:,} байт</p>"
        f"<p><b>SHA256:</b> <code>{file_hash[:16]}...</code></p>"
        f"<p><b>Дата начала:</b> {effective_from.isoformat()}</p>"
        f"<p><b>Ставок:</b> {rates_count}</p>"
        f"{sheets_html}"
        f"<p><b>Изменения:</b> {diff_html}</p>"
        f'<form action="/web/admin/commissions/manual-upload/apply" method="post" enctype="multipart/form-data">'
        f'<input type="hidden" name="effective_from" value="{effective_from.strftime("%d.%m.%Y")}">'
        f'<input type="hidden" name="version_label" value="{escape(version_label)}">'
        f'<input type="hidden" name="file" value="">'
        f'<p class="muted">Для активации загрузите тот же файл повторно:</p>'
        f'<div class="filters">'
        f"<div><label>Файл XLSX (тот же)</label>"
        f'<input type="file" name="file" accept=".xlsx,.xls" required></div>'
        f"</div>"
        f'<button type="submit" class="button primary">Активировать версию</button>'
        f"</form>"
        f'<p><a href="/web/admin/commissions" class="button">Отмена</a></p>'
        f"</div>"
    )


def _fetch_method_label(method: str) -> str:
    mapping = {
        "http": '<span class="badge good">HTTP</span>',
        "browser": '<span class="badge action">Browser (Playwright)</span>',
        "manual": '<span class="badge">Ручной</span>',
    }
    return mapping.get(method, f'<span class="badge">{escape(method)}</span>')


def _change_type_badge(change_type: str) -> str:
    mapping = {
        "no_change": '<span class="badge good">Без изменений</span>',
        "new_period_detected": '<span class="badge action">Есть изменения (новый период)</span>',
        "file_url_changed": '<span class="badge action">Есть изменения (URL изменён)</span>',
        "file_content_changed": '<span class="badge action">Есть изменения (файл обновлён)</span>',
        "parse_error": '<span class="badge bad">Ошибка парсинга</span>',
        "source_unavailable": '<span class="badge warn">Источник недоступен</span>',
        "source_blocked": '<span class="badge warn">Источник заблокирован (403)</span>',
        "file_unavailable": '<span class="badge warn">Файл недоступен</span>',
        "unavailable": '<span class="badge warn">Источник недоступен</span>',
        "rate_limited": '<span class="badge warn">Источник времен недоступен</span>',
        "manual_mode": '<span class="badge">Ручной режим</span>',
        "browser_fallback": '<span class="badge action">Browser fallback</span>',
    }
    return mapping.get(change_type, f'<span class="badge">{escape(change_type)}</span>')
