"""version: 1.0.0
description: WEB admin routes for commission tariff management.
updated: 2026-05-20
"""
# ruff: noqa: E501

import logging
from datetime import date
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
from app.services.commission_tariffs.ozon_commission_source_monitor_service import (
    OzonCommissionSourceMonitorService,
)
from app.services.commission_tariffs.ozon_commission_xlsx_importer import OzonCommissionXlsxImporter
from app.services.commission_tariffs.wb_commission_sync_service import WbCommissionSyncService
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.rendering import page

logger = logging.getLogger(__name__)
router = APIRouter()

OZON_COMMISSION_FILE_FORM = File(...)
OZON_COMMISSION_EFFECTIVE_FROM_FORM = Form(...)
OZON_COMMISSION_VERSION_LABEL_FORM = Form(default="")


def _is_admin_user(user: User) -> bool:
    settings = get_settings()
    return user.telegram_id in settings.admin_ids


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


@router.post("/admin/commissions/check-ozon", response_class=HTMLResponse)
async def check_ozon_commissions_web(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)

    service = OzonCommissionSourceMonitorService(session)
    result = await service.check()

    period = result.get("period_label", "н/д")
    has_changes = result.get("has_changes", False)
    change_type = result.get("change_type", "no_change")
    download_url = result.get("download_url")
    file_name = result.get("file_name")

    status_badge = _change_type_badge(change_type)

    download_link = ""
    if has_changes and download_url:
        safe_url = escape(str(download_url))
        safe_name = escape(str(file_name or "Актуальный файл Ozon"))
        download_link = (
            f'<p><a href="{safe_url}" target="_blank" rel="noopener" '
            f'class="button primary">📥 Скачать актуальный файл: {safe_name}</a></p>'
        )

    error_info = ""
    if change_type in ("unavailable", "rate_limited"):
        error_info = (
            '<p>⚠️ Источник Ozon недоступен. Проверьте страницу вручную или повторите позже.</p>'
        )
    elif change_type == "parse_error":
        error_info = (
            '<p>⚠️ Ошибка парсинга. Формат страницы Ozon мог измениться.</p>'
        )

    return _admin_page(
        "Комиссии маркетплейсов",
        user,
        f'<div class="band"><h2>Проверка Ozon</h2>'
        f"<p>Текущий период: {escape(str(period))}</p>"
        f"<p>Результат: {status_badge}</p>"
        f"{download_link}"
        f"{error_info}"
        f'<a href="/web/admin/commissions" class="button">Назад</a></div>',
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

    check_info = ""
    if last_check:
        period = escape(str(last_check.current_detected_period_label or "н/д"))
        change_badge = _change_type_badge(last_check.change_type)
        check_info = (
            f"<p><b>Последняя проверка:</b> {change_badge}, период: {period}</p>"
        )
        if last_check.has_changes and last_check.current_detected_file_url:
            safe_url = escape(last_check.current_detected_file_url)
            safe_name = escape(last_check.current_detected_file_name or "Актуальный файл Ozon")
            check_info += (
                f'<p><a href="{safe_url}" target="_blank" rel="noopener" '
                f'class="button primary">📥 Скачать актуальный файл: {safe_name}</a></p>'
            )
        elif last_check.change_type in ("unavailable", "rate_limited"):
            error_msg = ""
            if isinstance(last_check.details, dict) and last_check.details.get("error"):
                error_msg = escape(str(last_check.details["error"])[:200])
            check_info += (
                f'<p class="muted">⚠️ Источник Ozon недоступен. '
                f"Проверьте страницу вручную или повторите проверку позже.</p>"
            )
            if error_msg:
                check_info += f'<details><summary>Техническая информация</summary><pre class="mono">{error_msg}</pre></details>'
        elif last_check.change_type == "parse_error":
            error_msg = ""
            if isinstance(last_check.details, dict) and last_check.details.get("error"):
                error_msg = escape(str(last_check.details["error"])[:300])
            check_info += (
                '<p class="muted">⚠️ Ошибка парсинга. Формат страницы Ozon мог измениться. '
                "Требуется обновление парсера.</p>"
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
        f"{check_info}"
        "</div>"
    )


def _import_form() -> str:
    return (
        '<div class="band">'
        "<h2>📥 Загрузить таблицу комиссий Ozon</h2>"
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
        "</form></div>"
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
        period = escape(str(c.current_detected_period_label or "—"))

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
                f'<details><summary>Подробнее</summary>'
                f'<pre class="mono">{error_detail}</pre></details>'
            )

        rows += (
            "<tr>"
            f"<td>{c.checked_at.strftime('%d.%m.%Y %H:%M') if c.checked_at else '—'}</td>"
            f"<td>{period}</td>"
            f"<td>{change_label}</td>"
            f"<td>{file_cell}</td>"
            f"<td>{actions}</td>"
            "</tr>"
        )

    return (
        '<div class="band"><h2>🔍 История проверок Ozon</h2>'
        '<div class="table-wrap"><table class="table">'
        "<thead><tr>"
        "<th>Дата</th><th>Период</th><th>Изменения</th><th>Файл</th><th>Действия</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table></div></div>"
    )


def _change_type_badge(change_type: str) -> str:
    mapping = {
        "no_change": '<span class="badge good">Без изменений</span>',
        "new_period_detected": '<span class="badge action">Есть изменения (новый период)</span>',
        "file_url_changed": '<span class="badge action">Есть изменения (URL изменён)</span>',
        "parse_error": '<span class="badge bad">Ошибка парсинга</span>',
        "unavailable": '<span class="badge">Источник недоступен</span>',
        "rate_limited": '<span class="badge warn">Источник временно недоступен</span>',
    }
    return mapping.get(change_type, f'<span class="badge">{escape(change_type)}</span>')
