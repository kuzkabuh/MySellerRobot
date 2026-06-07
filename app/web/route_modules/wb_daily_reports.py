"""version: 1.0.0
description: Web routes for WB daily realisation report XLSX/ZIP import.
updated: 2026-06-07
"""
from __future__ import annotations

import logging
from collections import Counter
from decimal import Decimal
from html import escape
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.models.domain import (
    MarketplaceAccount,
    User,
    WbDailyReportImport,
)
from app.models.enums import Marketplace
from app.services.api_key_validation_service import ApiKeyValidationService
from app.services.audit_log_service import AuditLogService
from app.services.wb_daily_report_import_service import WbDailyReportImportService
from app.services.wb_daily_report_parser import (
    WbDailyReportParsed,
    compute_file_hash,
    parse_wb_daily_report_upload,
)
from app.utils.client_ip import get_client_ip
from app.utils.datetime import format_datetime_for_user
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.rendering import page

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".xlsx", ".zip"}


def _settings_path() -> str:
    return "/web/reports/wb-daily"


def _name(user: User) -> str:
    return user.first_name or user.username or str(user.telegram_id)


async def _load_user_accounts(
    session: AsyncSession, user_id: int
) -> list[MarketplaceAccount]:
    result = await session.execute(
        select(MarketplaceAccount)
        .where(
            MarketplaceAccount.user_id == user_id,
            MarketplaceAccount.marketplace == Marketplace.WB,
            MarketplaceAccount.is_active.is_(True),
        )
        .order_by(MarketplaceAccount.id.asc())
    )
    return list(result.scalars().all())


def _account_options(accounts: list[MarketplaceAccount], selected_id: int | None) -> str:
    if not accounts:
        return (
            '<option value="" disabled selected>'
            "Нет подключённых WB-кабинетов — сначала добавьте кабинет в Telegram-боте"
            "</option>"
        )
    return "".join(
        f'<option value="{acc.id}" {"selected" if acc.id == selected_id else ""}>'
        f"{escape(acc.name)} (#{acc.id})</option>"
        for acc in accounts
    )


def _page_layout(title: str, user: User, content: str) -> str:
    return page(
        title,
        _name(user),
        content,
        active_path=_settings_path(),
    )


def _empty_content(message: str) -> str:
    return f"""
      <section class="band">
        <h2>Импорт ежедневного отчёта WB</h2>
        <p class="muted">{escape(message)}</p>
      </section>
    """


@router.get("/reports/wb-daily", response_class=HTMLResponse)
async def wb_daily_reports_page(
    request: Request,
    message: str | None = Query(default=None),
    error: str | None = Query(default=None),
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    accounts = await _load_user_accounts(session, user.id)
    imports = await WbDailyReportImportService(session).list_imports(user_id=user.id, limit=20)

    if not accounts:
        return _page_layout(
            "Отчёты WB — ежедневный отчёт",
            user,
            _empty_content(
                "Чтобы загружать ежедневные отчёты, подключите хотя бы один кабинет "
                "Wildberries в Telegram-боте. После подключения здесь появится форма загрузки."
            ),
        )

    status_banner = ""
    if message:
        status_banner = f'<div class="notice success">{escape(message)}</div>'
    if error:
        status_banner = f'<div class="notice danger">{escape(error)}</div>'

    rows_html = _render_imports_rows(imports, user.timezone)
    options = _account_options(accounts, None)

    content = f"""
      {status_banner}
      <section class="band">
        <h2>Импорт ежедневного отчёта WB</h2>
        <p class="muted">
          Загрузите ZIP-архив или XLSX-файл детализированного отчёта Wildberries.
          Файл будет проверен на дубликаты: повторная загрузка того же файла не приведёт
          к дублям в аналитике.
        </p>
        <form method="post" action="{_settings_path()}/preview" enctype="multipart/form-data">
          <div class="filters">
            <div>
              <label for="account_id">Кабинет WB</label>
              <select id="account_id" name="account_id" required>{options}</select>
            </div>
            <div>
              <label for="file">Файл отчёта</label>
              <input id="file" name="file" type="file" accept=".xlsx,.zip" required>
            </div>
            <div>
              <label for="source_type">Источник</label>
              <select id="source_type" name="source_type">
                <option value="file" selected>Файл с компьютера</option>
                <option value="bot">Из Telegram-бота</option>
                <option value="api">Через API WB</option>
              </select>
            </div>
          </div>
          <button class="btn btn-primary" type="submit" style="margin-top:12px">
            Проверить и показать preview
          </button>
        </form>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>История импортов</h2>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Дата</th>
                <th>Кабинет</th>
                <th>Отчёт</th>
                <th>Строк</th>
                <th>Новых</th>
                <th>Пропущено</th>
                <th>Статус</th>
                <th>Файл</th>
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
      </section>
    """
    return _page_layout("Отчёты WB — ежедневный отчёт", user, content)


@router.post("/reports/wb-daily/preview", response_class=HTMLResponse)
async def wb_daily_reports_preview(
    request: Request,
    file: UploadFile,
    account_id: int = Form(...),
    source_type: str = Form("file"),
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    account = await _load_account(session, user.id, account_id)

    payload = await _read_upload(file)
    file_hash = compute_file_hash(payload)

    try:
        parsed = parse_wb_daily_report_upload(payload, filename=file.filename or "report.xlsx")
    except ValueError as exc:
        return _page_layout(
            "Отчёты WB — preview",
            user,
            _preview_error(account, str(exc)),
        )

    counters = _summarize_parsed(parsed)
    _stash_uploaded_bytes(account.id, file_hash, payload)

    return _page_layout(
        "Отчёты WB — preview",
        user,
        _preview_content(account, parsed, counters, file_hash, file.filename or "report.xlsx"),
    )


@router.post("/reports/wb-daily/apply")
async def wb_daily_reports_apply(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    form = await request.form()
    account_id = _to_int(form.get("account_id"))
    file_hash = str(form.get("file_hash") or "").strip()
    filename = str(form.get("filename") or "report.xlsx")
    source_type = str(form.get("source_type") or "file")

    if account_id is None or not file_hash:
        return RedirectResponse(
            url=f"{_settings_path()}?error={_q('Не указан кабинет или файл')}",
            status_code=303,
        )

    account = await _load_account(session, user.id, account_id)

    raw_bytes = _consume_uploaded_bytes(account.id, file_hash)
    if raw_bytes is None:
        return RedirectResponse(
            url=f"{_settings_path()}?error={_q('Сначала загрузите файл и откройте preview')}",
            status_code=303,
        )

    try:
        parsed = parse_wb_daily_report_upload(raw_bytes, filename=filename)
    except ValueError as exc:
        return RedirectResponse(
            url=f"{_settings_path()}?error={_q(str(exc))}",
            status_code=303,
        )

    service = WbDailyReportImportService(session)
    try:
        result = await service.import_parsed(
            user_id=user.id,
            marketplace_account=account,
            parsed=parsed,
            file_hash=file_hash,
            original_filename=filename,
            source_type=source_type,
        )
    except IntegrityError as exc:
        logger.exception(
            "wb_daily_report_import_failed",
            extra={"user_id": user.id, "account_id": account.id},
        )
        return RedirectResponse(
            url=f"{_settings_path()}?error={_q('Ошибка записи: ' + str(exc.orig)[:120])}",
            status_code=303,
        )

    await AuditLogService(session).log(
        "wb_daily_report_imported",
        user_id=user.id,
        entity_type="wb_daily_report_import",
        entity_id=result.import_id,
        details={
            "rows_inserted": result.rows_inserted,
            "rows_skipped": result.rows_skipped,
            "is_duplicate": result.is_duplicate,
            "filename": filename,
        },
        ip_address=get_client_ip(request),
    )
    await session.commit()

    if result.is_duplicate:
        message = (
            f"Файл уже загружался ранее. Новых строк: 0, "
            f"пропущено: {result.rows_skipped}."
        )
    elif result.rows_inserted == 0:
        message = "Все строки файла уже были в аналитике. Ничего нового не добавлено."
    else:
        message = (
            f"Импорт выполнен. Новых строк: {result.rows_inserted}, "
            f"пропущено: {result.rows_skipped}."
        )

    return RedirectResponse(
        url=f"{_settings_path()}?message={_q(message)}",
        status_code=303,
    )


@router.post("/reports/wb-daily/api-key/{account_id}/verify")
async def wb_daily_reports_verify_api_key(
    account_id: int,
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    account = await _load_account(session, user.id, account_id)
    cipher = TokenCipher()
    try:
        result = await ApiKeyValidationService(session, cipher).check_account(account)
    except Exception as exc:
        logger.exception(
            "wb_api_key_verify_failed",
            extra={"user_id": user.id, "account_id": account_id},
        )
        return RedirectResponse(
            url=f"{_settings_path()}?error={_q('Не удалось проверить ключ: ' + str(exc)[:120])}",
            status_code=303,
        )

    await AuditLogService(session).log(
        "wb_api_key_verified",
        user_id=user.id,
        entity_type="marketplace_account",
        entity_id=account.id,
        details={
            "status": result.status,
            "message": result.message,
        },
        ip_address=get_client_ip(request),
    )
    await session.commit()

    return RedirectResponse(
        url=f"{_settings_path()}?message={_q('Проверка выполнена: ' + result.message)}",
        status_code=303,
    )


@router.get("/reports/wb-daily/imports", response_class=HTMLResponse)
async def wb_daily_reports_imports(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    imports = await WbDailyReportImportService(session).list_imports(user_id=user.id, limit=100)
    return _page_layout(
        "Отчёты WB — история импортов",
        user,
        f"""
        <section class="band">
          <h2>История импортов ({len(imports)})</h2>
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Кабинет</th>
                  <th>Отчёт</th>
                  <th>Строк</th>
                  <th>Новых</th>
                  <th>Пропущено</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>{_render_imports_rows(imports, user.timezone)}</tbody>
            </table>
          </div>
        </section>
        """,
    )


async def _load_account(
    session: AsyncSession, user_id: int, account_id: int
) -> MarketplaceAccount:
    result = await session.execute(
        select(MarketplaceAccount).where(
            MarketplaceAccount.id == account_id,
            MarketplaceAccount.user_id == user_id,
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Кабинет не найден")
    return account


async def _read_upload(file: UploadFile) -> bytes:
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Поддерживаются только файлы .xlsx или .zip",
        )
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Файл пустой")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail="Файл превышает 50 МБ",
        )
    return payload


def _preview_content(
    account: MarketplaceAccount,
    parsed: WbDailyReportParsed,
    counters: dict[str, int],
    file_hash: str,
    filename: str,
) -> str:
    report_date = parsed.report_date.isoformat() if parsed.report_date else "неизвестно"
    sales_count = counters.get("sales", 0)
    returns_count = counters.get("returns", 0)
    sales_total = counters.get("sales_total", "0.00")
    logistics_total = counters.get("logistics_total", "0.00")
    penalties_total = counters.get("penalties_total", "0.00")
    duplicates = counters.get("duplicates", 0)

    return f"""
      <section class="band">
        <h2>Preview: {escape(filename)}</h2>
        <p class="muted">Кабинет: <b>{escape(account.name)}</b> (#{account.id})</p>
          <div class="kpi-grid">
          <div class="kpi">
            <span>Номер отчёта</span><strong>{escape(parsed.report_number)}</strong>
          </div>
          <div class="kpi"><span>Дата отчёта</span><strong>{escape(report_date)}</strong></div>
          <div class="kpi"><span>Строк в файле</span><strong>{len(parsed.rows)}</strong></div>
          <div class="kpi"><span>Продаж</span><strong>{sales_count}</strong></div>
          <div class="kpi"><span>Возвратов</span><strong>{returns_count}</strong></div>
          <div class="kpi good"><span>Сумма продаж</span><strong>{sales_total} ₽</strong></div>
          <div class="kpi warn"><span>Логистика</span><strong>{logistics_total} ₽</strong></div>
          <div class="kpi bad"><span>Штрафы</span><strong>{penalties_total} ₽</strong></div>
          <div class="kpi"><span>Потенциальные дубли</span><strong>{duplicates}</strong></div>
        </div>
        <form method="post" action="{_settings_path()}/apply" style="margin-top:14px">
          <input type="hidden" name="account_id" value="{account.id}">
          <input type="hidden" name="file_hash" value="{escape(file_hash)}">
          <input type="hidden" name="filename" value="{escape(filename)}">
          <button class="btn btn-primary" type="submit">Импортировать</button>
          <a class="btn" href="{_settings_path()}">Отмена</a>
        </form>
        <p class="muted" style="margin-top:12px">
          Повторная загрузка того же файла не приведёт к дублям:
          строки сверяются по стабильному хешу, дубликаты будут пропущены.
        </p>
      </section>
    """


def _preview_error(account: MarketplaceAccount, error: str) -> str:
    return f"""
      <section class="band">
        <h2>Не удалось разобрать файл</h2>
        <p class="muted">Кабинет: <b>{escape(account.name)}</b></p>
        <div class="notice danger">{escape(error)}</div>
        <p style="margin-top:14px"><a class="btn" href="{_settings_path()}">Назад</a></p>
      </section>
    """


def _summarize_parsed(parsed: WbDailyReportParsed) -> dict[str, object]:
    sales_count = 0
    returns_count = 0
    sales_total = Decimal("0")
    logistics_total = Decimal("0")
    penalties_total = Decimal("0")
    seen_hashes: Counter[str] = Counter()
    for row in parsed.rows:
        hash_value = row.compute_hash()
        seen_hashes[hash_value] += 1
        if row.doc_type_name and "возврат" in row.doc_type_name.lower():
            returns_count += 1
        else:
            sales_count += 1
        if row.for_pay is not None:
            sales_total += row.for_pay
        if row.delivery_rub is not None:
            logistics_total += row.delivery_rub
        if row.penalty is not None:
            penalties_total += row.penalty
    duplicates = sum(count - 1 for count in seen_hashes.values() if count > 1)

    return {
        "sales": sales_count,
        "returns": returns_count,
        "sales_total": f"{sales_total:.2f}",
        "logistics_total": f"{logistics_total:.2f}",
        "penalties_total": f"{penalties_total:.2f}",
        "duplicates": duplicates,
    }


def _render_imports_rows(
    imports: list[WbDailyReportImport], timezone: str
) -> str:
    if not imports:
        return (
            '<tr><td colspan="8">'
            '<div class="empty-state">Импортов пока не было.</div>'
            "</td></tr>"
        )
    rows: list[str] = []
    for item in imports:
        status_label = _status_label(item.status)
        status_cls = _status_class(item.status)
        created = format_datetime_for_user(item.created_at, timezone)
        rows.append(
            "<tr>"
            f"<td>{escape(created)}</td>"
            f"<td>#{item.marketplace_account_id}</td>"
            f"<td>{escape(item.report_number)}"
            f'<div class="muted">'
            f'{escape(str(item.report_date) if item.report_date else "—")}'
            f"</div></td>"
            f"<td>{item.rows_total}</td>"
            f"<td>{item.rows_inserted}</td>"
            f"<td>{item.rows_skipped}</td>"
            f'<td><span class="badge {status_cls}">{escape(status_label)}</span></td>'
            f"<td>{escape(item.original_filename or '—')}</td>"
            "</tr>"
        )
    return "".join(rows)


def _status_label(status: str) -> str:
    return {
        "success": "Успешно",
        "partial": "Частично",
        "empty": "Пусто",
        "failed": "Ошибка",
        "pending": "В обработке",
    }.get(status, status)


def _status_class(status: str) -> str:
    return {
        "success": "good",
        "partial": "warn",
        "empty": "warn",
        "failed": "bad",
        "pending": "action",
    }.get(status, "")


def _q(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def _to_int(value: object) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


_PREVIEW_CACHE: dict[tuple[int, str], bytes] = {}


def _stash_uploaded_bytes(account_id: int, file_hash: str, payload: bytes) -> None:
    _PREVIEW_CACHE[(account_id, file_hash)] = payload


def _consume_uploaded_bytes(account_id: int, file_hash: str) -> bytes | None:
    return _PREVIEW_CACHE.pop((account_id, file_hash), None)
