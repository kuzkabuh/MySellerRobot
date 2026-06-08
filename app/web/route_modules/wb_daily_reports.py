"""version: 1.0.0
description: Web routes for WB daily realisation report XLSX/ZIP import.
updated: 2026-06-07
"""
# ruff: noqa: E501
from __future__ import annotations

import csv
import logging
from collections import Counter
from datetime import UTC, datetime, time
from decimal import Decimal
from html import escape
from io import StringIO
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.models.domain import (
    MarketplaceAccount,
    User,
    WbDailyReportImport,
    WbDailyReportImportRowLog,
)
from app.models.enums import Marketplace
from app.services.api_key_validation_service import ApiKeyValidationService
from app.services.audit_log_service import AuditLogService
from app.services.history_backfill_service import HistoryBackfillService
from app.services.wb_daily_report_import_service import (
    WbDailyReportImportService,
    WbDailyReportRowFilters,
)
from app.services.wb_daily_report_parser import (
    WbDailyReportParsed,
    compute_file_hash,
    parse_wb_daily_report_upload,
)
from app.services.wb_report_relink_service import WbReportRelinkService
from app.utils.client_ip import get_client_ip
from app.utils.datetime import format_datetime_for_user
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY, is_admin_user
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
    details_id: int | None = Query(default=None),
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    accounts = await _load_user_accounts(session, user.id)
    imports = await WbDailyReportImportService(session).list_imports(
        user_id=None if is_admin_user(user) else user.id,
        limit=20,
    )

    if not accounts and not is_admin_user(user):
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
        details_link = (
            f' <a class="btn btn-sm btn-primary" href="{_settings_path()}/imports/{details_id}">'
            "Открыть подробности</a>"
            if details_id
            else ""
        )
        status_banner = f'<div class="notice success">{escape(message)}{details_link}</div>'
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
        <h2>Что происходит после загрузки отчёта</h2>
        <p class="muted">
          Мы проверяем файл на дубли, сохраняем новые строки в базу и показываем результат
          в финансовой аналитике. Эти данные помогают считать выручку, комиссии, логистику,
          хранение, удержания, штрафы, возвраты и сумму к выплате. После загрузки отчёт
          можно открыть в истории импортов, а пропущенные строки и причины пропуска посмотреть
          на странице подробностей.
        </p>
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
                <th>Действия</th>
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
        url=f"{_settings_path()}?message={_q(message)}&details_id={result.import_id}",
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
    imports = await WbDailyReportImportService(session).list_imports(
        user_id=None if is_admin_user(user) else user.id,
        limit=100,
    )
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
                  <th>Файл</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>{_render_imports_rows(imports, user.timezone)}</tbody>
            </table>
          </div>
        </section>
        """,
    )


@router.get("/reports/wb-daily/imports/{import_id}", response_class=HTMLResponse)
async def wb_daily_report_import_detail(
    import_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    message: str | None = Query(default=None),
    page_number: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=10, le=100),
    operation_type: str = Query(default=""),
    nm_id: int | None = Query(default=None),
    supplier_article: str = Query(default=""),
    barcode: str = Query(default=""),
    srid: str = Query(default=""),
    status: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    amount_from: Decimal | None = None,
    amount_to: Decimal | None = None,
    linked_order: str = Query(default=""),
    linked_product: str = Query(default=""),
    search: str = Query(default=""),
) -> str:
    import_record = await _load_import_record(session, user, import_id)
    service = WbDailyReportImportService(session)
    filters = WbDailyReportRowFilters(
        operation_type=operation_type,
        nm_id=nm_id,
        supplier_article=supplier_article,
        barcode=barcode,
        srid=srid,
        status=status,
        date_from=date_from,
        date_to=date_to,
        amount_from=amount_from,
        amount_to=amount_to,
        linked_order=linked_order,
        linked_product=linked_product,
        search=search,
    )
    rows_page = await service.list_rows(
        import_id=import_id,
        filters=filters,
        page=page_number,
        per_page=per_page,
    )
    summary = await service.import_summary(import_id=import_id)
    account = await session.get(MarketplaceAccount, import_record.marketplace_account_id)
    content = _import_detail_content(
        import_record,
        account,
        summary,
        rows_page,
        filters,
        user,
        is_admin_user(user),
        message,
    )
    return _page_layout(f"Импорт WB #{import_id}", user, content)


@router.get("/reports/wb-daily/imports/{import_id}/log.csv")
async def wb_daily_report_import_log_download(
    import_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> Response:
    await _load_import_record(session, user, import_id)
    result = await session.execute(
        select(WbDailyReportImportRowLog)
        .where(WbDailyReportImportRowLog.import_id == import_id)
        .order_by(WbDailyReportImportRowLog.row_number.asc().nullslast())
    )
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["row_number", "source_hash", "status", "skip_reason", "error_message"])
    for row in result.scalars().all():
        writer.writerow(
            [
                row.row_number,
                row.source_hash,
                row.status,
                row.skip_reason or "",
                row.error_message or "",
            ]
        )
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="wb-import-{import_id}-log.csv"'},
    )


@router.post("/reports/wb-daily/imports/{import_id}/relink")
async def wb_daily_report_import_relink(
    import_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    import_record = await _load_import_record(session, user, import_id)
    result = await WbReportRelinkService(session).relink_pending_rows(import_id=import_id)
    import_record.rows_matched_count = (import_record.rows_matched_count or 0) + result.matched
    import_record.rows_pending_match_count = result.pending
    import_record.rows_ambiguous_count = result.ambiguous
    await session.commit()
    message = (
        f"Повторная привязка выполнена. Связано: {result.matched}, "
        f"ожидают: {result.pending}, неоднозначно: {result.ambiguous}."
    )
    return RedirectResponse(
        url=f"{_settings_path()}/imports/{import_id}?message={_q(message)}",
        status_code=303,
    )


@router.post("/reports/wb-daily/imports/{import_id}/delete")
async def wb_daily_report_import_delete(
    import_id: int,
    reason: str = Form(""),
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    await _load_import_record(session, user, import_id)
    deleted = await WbDailyReportImportService(session).soft_delete_import(
        import_id=import_id,
        user_id=user.id,
        reason=reason or "Удалено пользователем",
    )
    await session.commit()
    message = (
        "Отчёт удалён. Связанные строки и финансовые операции больше не учитываются в аналитике."
        if deleted
        else "Импорт не найден."
    )
    return RedirectResponse(
        url=f"{_settings_path()}?message={_q(message)}&details_id={import_id}",
        status_code=303,
    )


@router.post("/reports/wb-daily/imports/{import_id}/backfill-orders")
async def wb_daily_report_import_backfill_orders(
    import_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    import_record = await _load_import_record(session, user, import_id)
    account = await session.get(MarketplaceAccount, import_record.marketplace_account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Кабинет WB не найден")
    start = import_record.report_period_start or import_record.report_date
    end = import_record.report_period_end or import_record.report_date
    if start is None or end is None:
        return RedirectResponse(
            url=f"{_settings_path()}/imports/{import_id}?message={_q('Не удалось определить период отчёта.')}",
            status_code=303,
        )
    job = await HistoryBackfillService(session).schedule_period(
        account,
        date_from=datetime.combine(start, time.min, tzinfo=UTC),
        date_to=datetime.combine(end, time.max, tzinfo=UTC),
    )
    message = (
        f"Дозагрузка заказов WB за период отчёта поставлена в очередь, задача #{job.id}. "
        "После выполнения worker автоматически повторит привязку."
    )
    return RedirectResponse(
        url=f"{_settings_path()}/imports/{import_id}?message={_q(message)}",
        status_code=303,
    )


@router.post("/reports/wb-daily/imports/{import_id}/restore")
async def wb_daily_report_import_restore(
    import_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Восстановление доступно только администратору")
    await _load_import_record(session, user, import_id)
    restored = await WbDailyReportImportService(session).restore_import(
        import_id=import_id,
        user_id=user.id,
    )
    result = await WbReportRelinkService(session).relink_pending_rows(import_id=import_id)
    await session.commit()
    message = (
        f"Отчёт восстановлен. Повторно связано: {result.matched}."
        if restored
        else "Импорт не найден."
    )
    return RedirectResponse(
        url=f"{_settings_path()}/imports/{import_id}?message={_q(message)}",
        status_code=303,
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


async def _load_import_record(
    session: AsyncSession,
    user: User,
    import_id: int,
) -> WbDailyReportImport:
    conditions = [WbDailyReportImport.id == import_id]
    if not is_admin_user(user):
        conditions.append(WbDailyReportImport.user_id == user.id)
    result = await session.execute(select(WbDailyReportImport).where(*conditions))
    import_record = result.scalar_one_or_none()
    if import_record is None:
        raise HTTPException(status_code=404, detail="Импорт не найден")
    return import_record


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
          <div class="kpi"><span>Тип отчёта</span><strong>{escape(_report_type_label(parsed.report_type))}</strong></div>
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
        operation_text = f"{row.doc_type_name or ''} {row.payment_reason or ''}".lower()
        if "возврат" in operation_text:
            returns_count += 1
        else:
            sales_count += 1
        if row.retail_amount is not None:
            sales_total += row.retail_amount
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
            '<tr><td colspan="9">'
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
            '<td><div style="display:flex;gap:6px;flex-wrap:wrap">'
            f'<a class="btn btn-sm btn-primary" href="{_settings_path()}/imports/{item.id}">'
            "Открыть</a>"
            f'<a class="btn btn-sm" href="{_settings_path()}/imports/{item.id}/log.csv">'
            "Скачать журнал</a>"
            "</div></td>"
            "</tr>"
        )
    return "".join(rows)


def _import_detail_content(
    import_record: WbDailyReportImport,
    account: MarketplaceAccount | None,
    summary: object,
    rows_page: object,
    filters: WbDailyReportRowFilters,
    user: User,
    is_admin: bool,
    message: str | None = None,
) -> str:
    account_name = account.name if account is not None else f"#{import_record.marketplace_account_id}"
    user_line = (
        f"<span>Пользователь</span><strong>#{import_record.user_id}</strong>"
        if is_admin
        else ""
    )
    reasons = getattr(summary, "skip_reasons", [])
    reasons_html = (
        "".join(
            f'<span class="badge warn">{escape(reason)}: {count}</span>'
            for reason, count in reasons
        )
        or '<span class="badge good">Причин пропуска нет</span>'
    )
    return f"""
      {f'<div class="notice success">{escape(message)}</div>' if message else ''}
      <section class="page-header">
        <div>
          <h2>Импорт WB #{import_record.id}</h2>
          <div class="summary-strip">
            <span>Кабинет: <strong>{escape(account_name)}</strong></span>
            <span>Отчёт: <strong>{escape(import_record.report_number)}</strong></span>
            <span>Статус: <strong>{escape(_status_label(import_record.status))}</strong></span>
          </div>
        </div>
        <div class="page-actions">
          <a class="btn" href="{_settings_path()}">К истории</a>
          <a class="btn btn-primary" href="/web/profit?marketplace=WB">Финансовая аналитика</a>
        </div>
      </section>
      <section class="detail-grid">
        <section class="band">
          <h2>Общая информация</h2>
          <div class="kv">
            <span>ID импорта</span><strong>#{import_record.id}</strong>
            <span>Кабинет WB</span><strong>#{import_record.marketplace_account_id}</strong>
            <span>Имя кабинета</span><strong>{escape(account_name)}</strong>
            <span>Дата загрузки</span><strong>{escape(format_datetime_for_user(import_record.created_at, user.timezone))}</strong>
            <span>Файл</span><strong>{escape(import_record.original_filename or "—")}</strong>
            <span>Тип отчёта</span><strong>{escape(_report_type_label(getattr(import_record, "report_type", "daily")))}</strong>
            <span>Тип файла</span><strong>{escape(_file_type(import_record.original_filename))}</strong>
            <span>Период отчёта</span><strong>{escape(_report_period(import_record))}</strong>
            <span>Номер отчёта</span><strong>{escape(import_record.report_number)}</strong>
            <span>Статус</span><strong>{escape(_status_label(import_record.status))}</strong>
            <span>Всего строк</span><strong>{import_record.rows_total}</strong>
            <span>Новых строк</span><strong>{import_record.rows_inserted}</strong>
            <span>Пропущенных строк</span><strong>{import_record.rows_skipped}</strong>
            <span>Строк с ошибками</span><strong>{getattr(summary, "unrecognized_rows", 0)}</strong>
            <span>Источник</span><strong>{escape(import_record.source_type)}</strong>
            {user_line}
          </div>
        </section>
        <section class="band">
          <h2>Финансовая сводка</h2>
          <div class="kv">
            <span>Продажи</span><strong>{_rub(getattr(summary, "sales_amount", 0))}</strong>
            <span>Возвраты</span><strong>{_rub(getattr(summary, "returns_amount", 0))}</strong>
            <span>Перечисления</span><strong>{_rub(getattr(summary, "payout_amount", 0))}</strong>
            <span>Комиссия WB</span><strong>{_rub(getattr(summary, "commission_amount", 0))}</strong>
            <span>Логистика</span><strong>{_rub(getattr(summary, "logistics_amount", 0))}</strong>
            <span>Хранение</span><strong>{_rub(getattr(summary, "storage_amount", 0))}</strong>
            <span>Удержания</span><strong>{_rub(getattr(summary, "deductions_amount", 0))}</strong>
            <span>Штрафы</span><strong>{_rub(getattr(summary, "penalties_amount", 0))}</strong>
            <span>Платная приемка FBS</span><strong>{_rub(getattr(summary, "acceptance_amount", 0))}</strong>
            <span>Итог к выплате</span><strong>{_rub(getattr(summary, "payout_amount", 0))}</strong>
            <span>Заказов</span><strong>{getattr(summary, "orders_count", 0)}</strong>
            <span>Продаж</span><strong>{getattr(summary, "sales_count", 0)}</strong>
            <span>Возвратов</span><strong>{getattr(summary, "returns_count", 0)}</strong>
            <span>Уникальных nm_id</span><strong>{getattr(summary, "unique_nm_ids", 0)}</strong>
            <span>Уникальных артикулов</span><strong>{getattr(summary, "unique_articles", 0)}</strong>
          </div>
        </section>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Статус обработки</h2>
        <div class="summary-strip">
          <span>Распознано: <strong>{getattr(summary, "recognized_rows", 0)}</strong></span>
          <span>Не распознано: <strong>{getattr(summary, "unrecognized_rows", 0)}</strong></span>
          <span>Связано с товарами: <strong>{getattr(summary, "linked_products", 0)}</strong></span>
          <span>Без товара: <strong>{getattr(summary, "unlinked_products", 0)}</strong></span>
          <span>Связано с заказами: <strong>{getattr(summary, "linked_orders", 0)}</strong></span>
          <span>Без заказа: <strong>{getattr(summary, "unlinked_orders", 0)}</strong></span>
          <span>Дубли: <strong>{getattr(summary, "duplicate_rows", 0)}</strong></span>
        </div>
        <p class="muted">Дедупликация выполняется по ключу: кабинет WB + тип отчёта + номер отчёта + хеш нормализованной строки.</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap">{reasons_html}</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
          <form method="post" action="{_settings_path()}/imports/{import_record.id}/relink">
            <button class="btn btn-primary" type="submit">Повторить привязку</button>
          </form>
          <form method="post" action="{_settings_path()}/imports/{import_record.id}/backfill-orders">
            <button class="btn" type="submit">Дозагрузить заказы за период</button>
          </form>
          <form method="post" action="{_settings_path()}/imports/{import_record.id}/delete" onsubmit="return confirm('Удалить отчёт? Связанные строки и финансовые операции перестанут учитываться в аналитике.')">
            <input name="reason" placeholder="Причина удаления" value="">
            <button class="btn btn-danger" type="submit">Удалить отчёт</button>
          </form>
          {f'<form method="post" action="{_settings_path()}/imports/{import_record.id}/restore"><button class="btn" type="submit">Восстановить отчёт</button></form>' if is_admin else ''}
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Строки отчёта</h2>
        {_row_filters(import_record.id, filters)}
        {_rows_table(rows_page, user.timezone)}
        {_pagination(import_record.id, rows_page, filters)}
      </section>
    """


def _row_filters(import_id: int, filters: WbDailyReportRowFilters) -> str:
    return f"""
      <form class="filters" method="get" action="{_settings_path()}/imports/{import_id}">
        <div><label>Поиск</label><input name="search" value="{escape(filters.search)}"></div>
        <div><label>Тип операции</label><input name="operation_type" value="{escape(filters.operation_type)}"></div>
        <div><label>nm_id</label><input name="nm_id" value="{filters.nm_id or ''}"></div>
        <div><label>Артикул продавца</label><input name="supplier_article" value="{escape(filters.supplier_article)}"></div>
        <div><label>Barcode</label><input name="barcode" value="{escape(filters.barcode)}"></div>
        <div><label>srid</label><input name="srid" value="{escape(filters.srid)}"></div>
        <div><label>Статус</label>{_select_status(filters.status)}</div>
        <div><label>Дата от</label><input type="date" name="date_from" value="{escape(filters.date_from)}"></div>
        <div><label>Дата до</label><input type="date" name="date_to" value="{escape(filters.date_to)}"></div>
        <div><label>Сумма от</label><input name="amount_from" value="{filters.amount_from or ''}"></div>
        <div><label>Сумма до</label><input name="amount_to" value="{filters.amount_to or ''}"></div>
        <div><label>Заказ</label>{_yes_no_select("linked_order", filters.linked_order)}</div>
        <div><label>Товар</label>{_yes_no_select("linked_product", filters.linked_product)}</div>
        <button class="btn btn-primary" type="submit">Показать</button>
      </form>
    """


def _rows_table(rows_page: object, timezone: str) -> str:
    rows = getattr(rows_page, "rows", [])
    if not rows:
        body = '<tr><td colspan="19"><div class="empty-state">Строк по выбранным фильтрам нет.</div></td></tr>'
    else:
        body = "".join(_row_html(row, timezone) for row in rows)
    return f"""
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Дата операции</th><th>Обоснование</th><th>Статья</th><th>Тип операции</th><th>nm_id</th>
              <th>Артикул</th><th>Barcode</th><th>ШК</th><th>srid</th><th class="num">Кол-во</th>
              <th class="num">Цена</th><th class="num">Сумма продажи</th>
              <th class="num">Комиссия</th><th class="num">Логистика</th>
              <th class="num">Хранение</th><th class="num">Штрафы</th>
              <th class="num">Удержания</th><th class="num">Приемка FBS</th><th class="num">К перечислению</th>
              <th>Статус</th><th>Причина</th><th>Заказ/продажа</th><th>Товар</th>
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    """


def _row_html(row: object, timezone: str) -> str:
    sale_dt = getattr(row, "sale_dt", None)
    row_status = getattr(row, "row_status", "new")
    order_id = getattr(row, "linked_order_id", None)
    product_id = getattr(row, "linked_product_id", None)
    order_link = (
        f'<a href="/web/orders/{order_id}">Заказ #{order_id}</a>'
        if order_id
        else '<span class="muted">Не связано</span>'
    )
    product_link = (
        f'<a href="/web/products?sku={escape(str(getattr(row, "supplier_article", "") or ""))}">Товар #{product_id}</a>'
        if product_id
        else '<span class="muted">Не связано</span>'
    )
    return (
        "<tr>"
        f"<td>{escape(format_datetime_for_user(sale_dt, timezone) if sale_dt else '—')}</td>"
        f"<td>{escape(getattr(row, 'payment_reason', None) or '—')}</td>"
        f"<td>{escape(_finance_category_label(getattr(row, 'finance_category', None)))}</td>"
        f"<td>{escape(getattr(row, 'finance_operation_type', None) or getattr(row, 'doc_type_name', None) or '—')}</td>"
        f"<td>{escape(str(getattr(row, 'nm_id', '') or '—'))}</td>"
        f"<td>{escape(getattr(row, 'supplier_article', None) or '—')}</td>"
        f"<td>{escape(getattr(row, 'barcode', None) or '—')}</td>"
        f"<td>{escape(getattr(row, 'shk', None) or '—')}</td>"
        f"<td>{escape(getattr(row, 'srid', None) or '—')}</td>"
        f"<td class='num'>{escape(str(getattr(row, 'quantity', '') or '—'))}</td>"
        f"<td class='num'>{_rub(getattr(row, 'retail_price', None))}</td>"
        f"<td class='num'>{_rub(getattr(row, 'retail_amount', None))}</td>"
        f"<td class='num'>{_rub(getattr(row, 'commission_rub', None))}</td>"
        f"<td class='num'>{_rub(getattr(row, 'delivery_rub', None))}</td>"
        f"<td class='num'>{_rub(getattr(row, 'storage_fee', None))}</td>"
        f"<td class='num'>{_rub(getattr(row, 'penalty', None))}</td>"
        f"<td class='num'>{_rub(getattr(row, 'deduction', None))}</td>"
        f"<td class='num'>{_rub(getattr(row, 'acceptance', None))}</td>"
        f"<td class='num'>{_rub(getattr(row, 'for_pay', None))}</td>"
        f"<td><span class='badge {_row_status_class(row_status)}'>{escape(_row_status_label(row_status))}</span></td>"
        f"<td>{escape(getattr(row, 'skip_reason', None) or getattr(row, 'error_message', None) or '—')}</td>"
        f"<td>{order_link}</td>"
        f"<td>{product_link}</td>"
        "</tr>"
    )


def _status_label(status: str) -> str:
    return {
        "success": "Успешно",
        "partial": "Частично",
        "empty": "Пусто",
        "failed": "Ошибка",
        "pending": "В обработке",
        "duplicate": "Дубликат",
        "deleted": "Удалён",
    }.get(status, status)


def _status_class(status: str) -> str:
    return {
        "success": "good",
        "partial": "warn",
        "empty": "warn",
        "failed": "bad",
        "pending": "action",
        "duplicate": "warn",
        "deleted": "bad",
    }.get(status, "")


def _select_status(selected: str) -> str:
    options = {
        "": "Все",
        "new": "Новая",
        "partial": "Частично связана",
        "order_pending_match": "Ожидает привязки",
        "ambiguous_order_match": "Неоднозначный заказ",
        "ambiguous_product_match": "Неоднозначный товар",
        "duplicate": "Дубль",
        "error": "Ошибка",
        "skipped": "Пропущена",
    }
    return "<select name='status'>" + "".join(
        f'<option value="{escape(value)}" {"selected" if value == selected else ""}>'
        f"{escape(label)}</option>"
        for value, label in options.items()
    ) + "</select>"


def _yes_no_select(name: str, selected: str) -> str:
    options = {"": "Все", "yes": "Да", "no": "Нет"}
    return f"<select name='{escape(name)}'>" + "".join(
        f'<option value="{escape(value)}" {"selected" if value == selected else ""}>'
        f"{escape(label)}</option>"
        for value, label in options.items()
    ) + "</select>"


def _pagination(import_id: int, rows_page: object, filters: WbDailyReportRowFilters) -> str:
    page_number = int(getattr(rows_page, "page", 1))
    total_pages = int(getattr(rows_page, "total_pages", 1))
    total_count = int(getattr(rows_page, "total_count", 0))
    if total_pages <= 1:
        return f'<p class="muted">Всего строк: {total_count}</p>'

    def url(page: int) -> str:
        params = _filter_params(filters)
        params["page_number"] = str(page)
        return f"{_settings_path()}/imports/{import_id}?{urlencode(params)}"

    items = [f'<span class="muted">Всего строк: {total_count}</span>']
    if page_number > 1:
        items.append(f'<a class="btn" href="{url(page_number - 1)}">Назад</a>')
    items.append(f'<span class="btn btn-primary" style="cursor:default">{page_number}</span>')
    if page_number < total_pages:
        items.append(f'<a class="btn" href="{url(page_number + 1)}">Далее</a>')
    return '<div style="display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap">' + "".join(items) + "</div>"


def _filter_params(filters: WbDailyReportRowFilters) -> dict[str, str]:
    values = {
        "operation_type": filters.operation_type,
        "nm_id": str(filters.nm_id or ""),
        "supplier_article": filters.supplier_article,
        "barcode": filters.barcode,
        "srid": filters.srid,
        "status": filters.status,
        "date_from": filters.date_from,
        "date_to": filters.date_to,
        "amount_from": str(filters.amount_from or ""),
        "amount_to": str(filters.amount_to or ""),
        "linked_order": filters.linked_order,
        "linked_product": filters.linked_product,
        "search": filters.search,
    }
    return {key: value for key, value in values.items() if value}


def _row_status_label(status: str) -> str:
    return {
        "new": "Новая",
        "partial": "Частично связана",
        "duplicate": "Дубль",
        "error": "Ошибка",
        "skipped": "Пропущена",
    }.get(status, status)


def _row_status_class(status: str) -> str:
    return {
        "new": "good",
        "partial": "warn",
        "duplicate": "warn",
        "error": "bad",
        "skipped": "warn",
    }.get(status, "")


def _file_type(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".zip":
        return "ZIP"
    if suffix == ".xlsx":
        return "XLSX"
    return "—"


def _report_type_label(report_type: str | None) -> str:
    return {"daily": "Ежедневный", "weekly": "Еженедельный"}.get(report_type or "", report_type or "—")


def _report_period(import_record: WbDailyReportImport) -> str:
    start = getattr(import_record, "report_period_start", None) or import_record.report_date
    end = getattr(import_record, "report_period_end", None) or import_record.report_date
    if start and end and start != end:
        return f"{start} — {end}"
    return str(start or "—")


def _finance_category_label(category: str | None) -> str:
    return {
        "revenue": "Выручка",
        "wb_commission": "Комиссия WB",
        "logistics": "Логистика",
        "storage": "Хранение",
        "penalty": "Штрафы",
        "deduction": "Удержания",
        "paid_acceptance": "Платная приемка FBS",
        "compensation": "Компенсации",
        "return": "Возврат",
        "other": "Прочее WB",
    }.get(category or "other", category or "Прочее WB")


def _rub(value: object) -> str:
    if value is None or value == "":
        return "—"
    try:
        amount = Decimal(str(value))
    except Exception:
        return "—"
    return f"{amount.quantize(Decimal('0.01'))} ₽"


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
