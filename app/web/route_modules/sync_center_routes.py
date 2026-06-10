"""Sync Center routes: run sync, verify API key, run status, history, errors."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, User
from app.services.account.web_cabinet_service import WebCabinetService
from app.services.common.sync_period_limits import (
    get_manual_sync_period_limits,
    get_period_supported_sync_types,
)
from app.services.common.web_sync_run_service import SYNC_TYPE_MAP, WebSyncRunService
from app.web.dependencies import (
    CURRENT_WEB_USER_DEPENDENCY,
    SESSION_DEPENDENCY,
    is_admin_user,
)
from app.web.rendering import page
from app.web.view_modules.sync_center import (
    _sync_center_content,
    _sync_center_errors_content,
    _sync_center_history_content,
    _sync_center_settings_content,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/sync-center", response_class=HTMLResponse)
async def sync_center_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    tab: str = Query(default="overview"),
) -> str:
    run_svc = WebSyncRunService(session)
    stale_count = await run_svc.mark_stale_syncs_as_failed()
    if stale_count:
        logger.info("stale_syncs_cleaned", extra={"count": stale_count})

    svc = WebCabinetService(session)
    data = await svc.sync_center_page(user.id, user.timezone)
    is_admin = is_admin_user(user)

    limits = await get_manual_sync_period_limits(session, user.id)
    period_supported = get_period_supported_sync_types()

    if tab == "history":
        runs = await run_svc.history(user_id=user.id, limit=100)
        content = _sync_center_history_content(runs, is_admin)
    elif tab == "errors":
        errors = await run_svc.errors(user_id=user.id, limit=50)
        content = _sync_center_errors_content(errors, is_admin)
    elif tab == "settings":
        content = _sync_center_settings_content()
    else:
        content = _sync_center_content(data, is_admin, limits=limits, period_supported=period_supported)

    return page(
        "Центр синхронизации",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/sync-center",
    )


@router.post("/sync-center/accounts/{account_id}/run")
async def sync_center_run_sync(
    account_id: int,
    sync_type: str = Query(...),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    period_preset: str | None = Query(None),
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> JSONResponse:
    account = await _get_user_account(session, user.id, account_id)
    if account is None:
        return JSONResponse(
            {"ok": False, "status": "not_found", "message": "Кабинет не найден."},
            status_code=404,
        )

    if sync_type not in SYNC_TYPE_MAP:
        return JSONResponse(
            {"ok": False, "status": "unknown_type", "message": f"Неизвестный тип синхронизации: {sync_type}"},
            status_code=400,
        )

    svc = WebSyncRunService(session)
    result = await svc.trigger_sync(
        user.id, account, sync_type,
        date_from=date_from,
        date_to=date_to,
        period_preset=period_preset,
    )
    await session.commit()

    status_code = 200 if result.get("ok") else (
        409 if result.get("status") == "already_running" else 400
    )
    return JSONResponse(result, status_code=status_code)


@router.post("/sync-center/accounts/{account_id}/verify-api-key")
async def sync_center_verify_api_key(
    account_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> JSONResponse:
    account = await _get_user_account(session, user.id, account_id)
    if account is None:
        return JSONResponse(
            {"ok": False, "status": "not_found", "message": "Кабинет не найден."},
            status_code=404,
        )

    svc = WebSyncRunService(session)
    result = await svc.verify_api_key(user, account)
    await session.commit()

    status_code = 200 if result.get("status") == "valid" else 400
    return JSONResponse(result, status_code=status_code)


@router.get("/sync-center/runs/{run_id}/status")
async def sync_center_run_status(
    run_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> JSONResponse:
    svc = WebSyncRunService(session)
    run = await svc.get_run(run_id)
    if run is None:
        return JSONResponse(
            {"ok": False, "status": "not_found", "message": "Запуск не найден."},
            status_code=404,
        )
    if run.user_id != user.id and not is_admin_user(user):
        return JSONResponse(
            {"ok": False, "status": "forbidden", "message": "Нет доступа к этому запуску."},
            status_code=403,
        )

    result = await svc.get_run_status(run_id)
    return JSONResponse(result)


@router.get("/sync-center/history")
async def sync_center_history(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    status_filter: str | None = Query(default=None),
) -> JSONResponse:
    svc = WebSyncRunService(session)
    runs = await svc.history(
        user_id=user.id,
        limit=limit,
        offset=offset,
        status_filter=status_filter,
    )
    total = await svc.history_count(user_id=user.id, status_filter=status_filter)
    return JSONResponse({
        "ok": True,
        "runs": [
            {
                "id": r.id,
                "marketplace": r.marketplace,
                "sync_type": r.sync_type,
                "trigger_source": r.trigger_source,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "duration_seconds": float(r.duration_seconds) if r.duration_seconds else None,
                "records_loaded": r.records_loaded,
                "records_created": r.records_created,
                "records_updated": r.records_updated,
                "records_skipped": r.records_skipped,
                "error_message": r.error_message,
                "details_json": r.details_json,
            }
            for r in runs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    })


async def _get_user_account(
    session: AsyncSession, user_id: int, account_id: int
) -> MarketplaceAccount | None:
    result = await session.execute(
        select(MarketplaceAccount).where(
            MarketplaceAccount.id == account_id,
            MarketplaceAccount.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()
