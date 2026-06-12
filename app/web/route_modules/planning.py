# ruff: noqa: E501, F401, F403, F405

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import AlertEvent, MarketplaceAccount, User
from app.models.enums import FeatureCode, Marketplace
from app.models.subscriptions import SubscriptionTier
from app.repositories.products import ProductCostRepository
from app.schemas.products import CostUpdate
from app.services.account.web_auth_service import WEB_SESSION_COOKIE, WebAuthService
from app.services.account.web_cabinet_service import WebCabinetService
from app.services.common.data_quality_service import DataQualityService
from app.services.common.web_dashboard_service import WebDashboardService
from app.services.common.web_orders_profit_service import WebOrdersProfitService
from app.services.common.web_sync_service import WebSyncService
from app.services.subscriptions.feature_access_service import FeatureAccessService
from app.services.subscriptions.subscription_service import SubscriptionService
from app.services.unit_economics.cost_management_service import CostManagementError
from app.services.unit_economics.master_product_service import MasterProductService
from app.services.unit_economics.plan_fact_service import PlanFactService
from app.services.unit_economics.stock_forecast_service import StockForecastService
from app.services.unit_economics.unit_economics_service import UnitEconomicsService
from app.web.dependencies import (
    CURRENT_WEB_USER_DEPENDENCY,
    SESSION_DEPENDENCY,
    WEB_DASHBOARD_PATH,
    WEB_LOGIN_REQUIRED_PATH,
    WEB_SESSION_COOKIE_PATH,
)
from app.web.rendering import page
from app.web.views import *

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/plan-fact", response_class=HTMLResponse)
async def plan_fact_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="30d"),
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    sku: str = Query(default=""),
    sort: str = Query(default="deviation"),
    direction: str = Query(default="asc"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.PLAN_FACT)
    if not access.allowed:
        return page(
            "План/факт",
            user.first_name or user.username or str(user.telegram_id),
            _feature_locked_html(access),
            active_path="/web/plan-fact",
        )

    data = await PlanFactService(session).compare(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
        sku=sku,
        sort=sort,
        direction=direction,
    )
    content = _plan_fact_content(data)
    return page(
        "План/факт",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/plan-fact",
    )


@router.post("/plan-fact/plans")
async def save_plan_fact_plan(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    await _ensure_plan_fact_access(session, user.id)
    form = await _urlencoded_form(request)
    target_id = _optional_int((form.get("target_id") or [""])[0])
    period_start = date.fromisoformat((form.get("period_start") or [""])[0])
    period_end = date.fromisoformat((form.get("period_end") or [""])[0])
    marketplace = _plan_marketplace((form.get("marketplace") or ["all"])[0])
    await PlanFactService(session).save_plan(
        user_id=user.id,
        target_id=target_id,
        period_start=period_start,
        period_end=period_end,
        marketplace=marketplace,
        revenue_plan=_optional_decimal((form.get("revenue_plan") or [""])[0]),
        profit_plan=_optional_decimal((form.get("profit_plan") or [""])[0]),
        orders_plan=_optional_int((form.get("orders_plan") or [""])[0]),
        buyouts_plan=_optional_int((form.get("buyouts_plan") or [""])[0]),
    )
    await session.commit()
    return RedirectResponse(url="/web/plan-fact", status_code=303)


@router.post("/plan-fact/plans/{target_id}/delete")
async def delete_plan_fact_plan(
    target_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    await _ensure_plan_fact_access(session, user.id)
    await PlanFactService(session).delete_plan(user_id=user.id, target_id=target_id)
    await session.commit()
    return RedirectResponse(url="/web/plan-fact", status_code=303)


@router.post("/web/plan-fact/plans", include_in_schema=False)
async def save_plan_fact_plan_legacy_double_web(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Accept plan saves from legacy /web/web/plan-fact/plans and redirect canonically."""
    return await save_plan_fact_plan(
        request=request,
        user=user,
        session=session,
    )


@router.post("/web/plan-fact/plans/{target_id}/delete", include_in_schema=False)
async def delete_plan_fact_plan_legacy_double_web(
    target_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Accept plan deletes from legacy /web/web/plan-fact/plans/{id}/delete and redirect canonically."""
    return await delete_plan_fact_plan(
        target_id=target_id,
        user=user,
        session=session,
    )


@router.get("/break-even", response_class=HTMLResponse)
async def break_even_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    target_margin: str = Query(default="20"),
    price_delta: str = Query(default="0"),
) -> str:
    access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.BREAK_EVEN)
    if not access.allowed:
        return page(
            "Безубыточная цена",
            user.first_name or user.username or str(user.telegram_id),
            _feature_locked_html(access),
            active_path="/web/break-even",
        )

    content = _break_even_content([], target_margin, price_delta)
    return page(
        "Безубыточная цена",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/break-even",
    )


@router.get("/break-even/api/summary")
async def break_even_summary_api(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    target_margin: str = Query(default="20"),
) -> JSONResponse:
    await _ensure_break_even_access(session, user.id)
    try:
        summary = await UnitEconomicsService(session).summary(
            user_id=user.id,
            target_margin_percent=_decimal_from_query(target_margin, Decimal("20")),
        )
    except Exception as exc:
        logger.exception("break_even_summary_api_failed", extra={"user_id": user.id})
        return JSONResponse(
            {"error": "Не удалось загрузить сводку безубыточности", "detail": str(exc)},
            status_code=500,
        )
    return JSONResponse(
        {
            "total_products": summary.total_products,
            "loss_products": summary.loss_products,
            "risky_products": summary.risky_products,
            "profitable_products": summary.profitable_products,
            "high_margin_products": summary.high_margin_products,
            "average_margin_percent": str(summary.average_margin_percent),
            "average_profit": str(summary.average_profit),
            "potential_lost_profit": str(summary.potential_lost_profit),
            "additional_profit_after_optimization": str(
                summary.additional_profit_after_optimization
            ),
        }
    )


@router.get("/break-even/api/products")
async def break_even_products_api(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> JSONResponse:
    await _ensure_break_even_access(session, user.id)
    params = request.query_params
    draw = _optional_int(params.get("draw")) or 1
    service = UnitEconomicsService(session)
    filters = {
        "target_margin": params.get("target_margin"),
        "price_delta": params.get("price_delta"),
        "search": params.get("search[value]") or params.get("q") or "",
        "marketplace": params.get("marketplace") or "all",
        "status": params.get("status") or "all",
        "category": params.get("category") or "",
        "brand": params.get("brand") or "",
        "start": max(0, _optional_int(params.get("start")) or 0),
        "length": min(200, max(10, _optional_int(params.get("length")) or 50)),
    }
    logger.info("break_even_products_api_requested", extra={"user_id": user.id, **filters})
    try:
        result = await service.table(
            user_id=user.id,
            target_margin_percent=_decimal_from_query(
                filters["target_margin"], Decimal("20")
            ),
            price_delta_percent=_decimal_from_query(filters["price_delta"], Decimal("0")),
            search=str(filters["search"]),
            marketplace=str(filters["marketplace"]),
            status=str(filters["status"]),
            category=str(filters["category"]),
            brand=str(filters["brand"]),
            min_profit=_optional_decimal(params.get("min_profit") or ""),
            max_profit=_optional_decimal(params.get("max_profit") or ""),
            min_margin=_optional_decimal(params.get("min_margin") or ""),
            max_margin=_optional_decimal(params.get("max_margin") or ""),
            min_price=_optional_decimal(params.get("min_price") or ""),
            max_price=_optional_decimal(params.get("max_price") or ""),
            start=int(filters["start"]),
            length=int(filters["length"]),
        )
    except Exception as exc:
        logger.exception(
            "break_even_products_api_failed",
            extra={"user_id": user.id, "filters": filters},
        )
        return JSONResponse(
            {
                "draw": draw,
                "recordsTotal": 0,
                "recordsFiltered": 0,
                "data": [],
                "error": "Не удалось загрузить товары для безубыточности",
                "detail": str(exc),
            },
            status_code=500,
        )
    return JSONResponse(
        {
            "draw": draw,
            "recordsTotal": result.total_count,
            "recordsFiltered": result.filtered_count,
            "data": [service.row_to_dict(row) for row in result.rows],
        }
    )


@router.get("/break-even/api/products/{product_id}")
async def break_even_product_detail_api(
    product_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    target_margin: str = Query(default="20"),
) -> JSONResponse:
    await _ensure_break_even_access(session, user.id)
    detail = await UnitEconomicsService(session).detail(
        user_id=user.id,
        product_id=product_id,
        target_margin_percent=_decimal_from_query(target_margin, Decimal("20")),
    )
    if not detail:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return JSONResponse(detail)


@router.post("/break-even/expenses")
async def save_break_even_expenses(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    scope: str = Form("global"),
    category: str = Form(""),
    product_id: str = Form(""),
    tax_rate: str = Form("6"),
    acquiring_rate: str = Form("1.5"),
    advertising_rate: str = Form("5"),
    packaging_cost: str = Form("0"),
    storage_cost: str = Form("0"),
    other_cost: str = Form("0"),
) -> RedirectResponse:
    await _ensure_break_even_access(session, user.id)
    row = await UnitEconomicsService(session).save_expense_setting(
        user_id=user.id,
        scope=scope,
        category=category,
        product_id=_optional_int(product_id),
        tax_rate=_decimal_from_query(tax_rate, Decimal("6")),
        acquiring_rate=_decimal_from_query(acquiring_rate, Decimal("1.5")),
        advertising_rate=_decimal_from_query(advertising_rate, Decimal("5")),
        packaging_cost=_decimal_from_query(packaging_cost, Decimal("0")),
        storage_cost=_decimal_from_query(storage_cost, Decimal("0")),
        other_cost=_decimal_from_query(other_cost, Decimal("0")),
    )
    try:
        from app.services.admin.audit_log_service import AuditLogService

        await AuditLogService(session).log(
            "break_even_expenses_saved",
            user_id=user.id,
            actor_user_id=user.id,
            entity_type="break_even_expense_setting",
            entity_id=row.id,
            details={"scope": row.scope, "category": row.category, "product_id": row.product_id},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except Exception:
        logger.exception("break_even_expense_audit_failed")
    await session.commit()
    return RedirectResponse(url="/web/break-even?expenses_saved=1", status_code=303)


@router.get("/break-even/export.csv")
async def break_even_export_csv(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> Response:
    await _ensure_break_even_access(session, user.id)
    content = await UnitEconomicsService(session).export_csv(user_id=user.id)
    return Response(
        content=content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="break_even.csv"'},
    )


@router.get("/break-even/export.xlsx")
async def break_even_export_xlsx(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> Response:
    await _ensure_break_even_access(session, user.id)
    content = await UnitEconomicsService(session).export_xlsx(user_id=user.id)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="break_even.xlsx"'},
    )


@router.get("/break-even/export.pdf")
async def break_even_export_pdf(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> Response:
    await _ensure_break_even_access(session, user.id)
    content = await UnitEconomicsService(session).export_pdf(user_id=user.id)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="break_even.pdf"'},
    )


def _feature_locked_html(access: Any) -> str:
    from html import escape as _esc

    reason = _esc(access.reason or "") if access.reason else ""
    required = _esc(access.required_plan or "Pro")
    return f"""
    <div class="locked-feature">
        <h2>🔒 Раздел недоступен</h2>
        <p>{reason}</p>
        <p>Для доступа обновите тариф до <b>{required}</b> или выше.</p>
        <a class="btn btn-primary" href="/web/settings?tab=subscription">Перейти к подписке</a>
    </div>"""


async def _ensure_plan_fact_access(session: AsyncSession, user_id: int) -> None:
    access = await FeatureAccessService(session).can_use_feature(user_id, FeatureCode.PLAN_FACT)
    if not access.allowed:
        raise HTTPException(status_code=403, detail=access.reason or "Раздел недоступен")


async def _ensure_break_even_access(session: AsyncSession, user_id: int) -> None:
    access = await FeatureAccessService(session).can_use_feature(user_id, FeatureCode.BREAK_EVEN)
    if not access.allowed:
        raise HTTPException(status_code=403, detail=access.reason or "Раздел недоступен")
