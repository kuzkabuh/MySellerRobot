"""version: 1.0.0
description: WEB admin routes for WB logistics tariff management.
updated: 2026-05-20
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User
from app.models.wb_logistics_tariffs import (
    WbLogisticsTariffRate,
    WbLogisticsTariffVersion,
)
from app.services.wb.logistics.wb_logistics_tariff_sync_service import (
    WbLogisticsTariffSyncService,
)
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY, is_admin_user

router = APIRouter()


def _is_admin_user(user: User) -> bool:
    return is_admin_user(user)


def _require_admin(user: User) -> None:
    if not _is_admin_user(user):
        raise HTTPException(status_code=403, detail="Доступно только администраторам")


@router.get("/admin/wb-logistics", response_class=HTMLResponse)
async def wb_logistics_admin(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    """Admin dashboard for WB logistics tariffs."""
    _require_admin(user)

    versions_result = await session.execute(
        select(WbLogisticsTariffVersion)
        .order_by(WbLogisticsTariffVersion.tariff_date.desc())
        .limit(20)
    )
    versions = list(versions_result.scalars().all())

    active_version = None
    for v in versions:
        if v.is_active:
            active_version = v
            break

    rates_count = 0
    if active_version:
        rates_result = await session.execute(
            select(func.count(WbLogisticsTariffRate.id)).where(
                WbLogisticsTariffRate.version_id == active_version.id
            )
        )
        rates_count = rates_result.scalar() or 0

    return _render_admin_page(versions, active_version, rates_count, _sync_message(request))


@router.post("/admin/wb-logistics/sync")
async def sync_wb_logistics(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Manually trigger WB logistics tariff sync."""
    _require_admin(user)

    from app.core.security import TokenCipher
    from app.integrations.wb import WildberriesClient
    from app.models.domain import MarketplaceAccount
    from app.models.enums import Marketplace

    account_result = await session.execute(
        select(MarketplaceAccount)
        .where(
            MarketplaceAccount.marketplace == Marketplace.WB,
            MarketplaceAccount.is_active.is_(True),
        )
        .limit(1)
    )
    account = account_result.scalar_one_or_none()

    if account is None:
        return RedirectResponse(
            url="/admin/wb-logistics?sync_status=error&sync_msg=no_wb_account",
            status_code=303,
        )

    try:
        api_key = TokenCipher().decrypt(account.encrypted_api_key)
    except Exception:
        return RedirectResponse(
            url="/admin/wb-logistics?sync_status=error&sync_msg=decrypt_failed",
            status_code=303,
        )

    wb_client = WildberriesClient(api_key=api_key)
    sync_service = WbLogisticsTariffSyncService(session, wb_client)
    result = await sync_service.sync()
    await session.commit()

    return RedirectResponse(
        url=f"/admin/wb-logistics?sync_status={result['status']}",
        status_code=303,
    )


_CSS = (
    "body{font-family:system-ui,sans-serif;max-width:900px;"
    "margin:2rem auto;padding:0 1rem}"
    "h1{margin-bottom:.5rem}"
    ".card{background:#f8fafc;border:1px solid #e2e8f0;"
    "border-radius:8px;padding:1rem;margin:1rem 0}"
    ".card.active{border-color:#10b981;background:#f0fdf4}"
    "table{width:100%;border-collapse:collapse;margin-top:1rem}"
    "th,td{text-align:left;padding:.5rem;border-bottom:1px solid #e5e7eb}"
    "th{background:#f9fafb;font-size:.875rem;color:#6b7280}"
    "code{background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:.8rem}"
    ".btn{display:inline-block;background:#111827;color:#fff;"
    "padding:.5rem 1rem;border-radius:6px;text-decoration:none;"
    "border:none;cursor:pointer}"
    ".btn:hover{background:#374151}"
)


def _render_admin_page(
    versions: list[WbLogisticsTariffVersion],
    active_version: WbLogisticsTariffVersion | None,
    rates_count: int,
    sync_message: str,
) -> str:
    """Render HTML admin page for WB logistics tariffs."""
    active_html = ""
    if active_version:
        synced = active_version.synced_at.strftime("%Y-%m-%d %H:%M")
        h = (active_version.version_hash or "")[:16]
        active_html = (
            f'<div class="card active">'
            f"<h3>Активная версия</h3>"
            f"<p><strong>Дата тарифа:</strong> {active_version.tariff_date}</p>"
            f"<p><strong>Синхронизировано:</strong> {synced}</p>"
            f"<p><strong>Складов:</strong> {active_version.rows_count}</p>"
            f"<p><strong>Записей тарифов:</strong> {rates_count}</p>"
            f"<p><strong>Hash:</strong> <code>{h}...</code></p>"
            f"</div>"
        )

    rows = ""
    for v in versions:
        status = "✅ активна" if v.is_active else "архив"
        synced = v.synced_at.strftime("%Y-%m-%d %H:%M")
        h = (v.version_hash or "")[:12]
        rows += (
            f"<tr><td>{v.tariff_date}</td><td>{synced}</td>"
            f"<td>{v.rows_count}</td><td>{status}</td>"
            f"<td><code>{h}...</code></td></tr>"
        )

    tbody = rows or '<tr><td colspan="5">Нет данных</td></tr>'

    return (
        "<!doctype html><html lang='ru'><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>WB Логистика — Админ</title>"
        f"<style>{_CSS}</style></head><body>"
        "<h1>🚚 Тарифы логистики WB</h1>"
        "<p>Управление тарифами коробочной доставки Wildberries.</p>"
        f"{sync_message}"
        f"{active_html}"
        '<form method="post" action="/admin/wb-logistics/sync">'
        '<button type="submit" class="btn">🔄 Синхронизировать тарифы</button>'
        "</form>"
        "<h2>История версий</h2>"
        "<table><thead><tr>"
        "<th>Дата тарифа</th><th>Синхронизировано</th>"
        "<th>Складов</th><th>Статус</th><th>Hash</th>"
        "</tr></thead><tbody>"
        f"{tbody}"
        "</tbody></table></body></html>"
    )


def _sync_message(request: Request) -> str:
    status = request.query_params.get("sync_status")
    msg = request.query_params.get("sync_msg")
    if not status:
        return ""
    if msg == "no_wb_account":
        text = "Нет подключённых кабинетов Wildberries."
    elif msg == "decrypt_failed":
        text = "Не удалось расшифровать API-ключ Wildberries."
    elif status == "new_version":
        text = "Тарифы Wildberries синхронизированы."
    elif status == "no_changes":
        text = "Тарифы Wildberries не изменились."
    else:
        text = "Синхронизация завершилась с ошибкой."
    color = "#065f46" if status in {"new_version", "no_changes"} else "#991b1b"
    background = "#ecfdf5" if status in {"new_version", "no_changes"} else "#fef2f2"
    return f'<div class="card" style="background:{background};color:{color};">{text}</div>'
