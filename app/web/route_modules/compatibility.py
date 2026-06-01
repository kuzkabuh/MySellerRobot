# ruff: noqa: E501, B008

import logging
from typing import Any, cast, overload

from fastapi import APIRouter, File, Form, Request
from fastapi.responses import HTMLResponse, Response

from app.models.domain import User
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.views import _placeholder_page

logger = logging.getLogger(__name__)
router = APIRouter()

OZON_COMMISSION_FILE_FORM = File(...)
OZON_COMMISSION_EFFECTIVE_FROM_FORM = Form(...)


def _qp(request: Request, name: str, default: str = "") -> str:
    return request.query_params.get(name, default)


@overload
def _qp_int(request: Request, name: str, default: int) -> int: ...


@overload
def _qp_int(request: Request, name: str, default: None) -> int | None: ...


def _qp_int(request: Request, name: str, default: int | None) -> int | None:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _facade() -> Any:
    import app.web.routes as facade

    return facade


@router.get("/{section}", response_class=HTMLResponse)
async def placeholder(
    section: str,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> str:
    return _placeholder_page(section, user)


@router.get("/web/{section:path}", response_class=HTMLResponse, include_in_schema=False)
async def double_web_compat(
    section: str,
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: Any = SESSION_DEPENDENCY,
) -> Response:
    """Serve cabinet pages when a reverse proxy prepends /web upstream.

    We render content directly instead of redirecting, because a redirect
    would send the browser back through the same proxy, creating an
    ERR_TOO_MANY_REDIRECTS loop.

    Query parameters are extracted from the request as plain values so they
    bypass FastAPI's Query(...) resolution (which caused TypeError when
    handlers were previously invoked manually).
    """

    normalized = section.strip("/")
    logger.warning(
        "legacy_double_web_path_served",
        extra={"path": str(request.url.path), "section": normalized or "dashboard"},
    )

    facade = _facade()

    if normalized == "" or normalized == "dashboard":
        return HTMLResponse(
            await facade.dashboard(
                user=user,
                session=session,
                period=_qp(request, "period", "today"),
                marketplace=_qp(request, "marketplace", "all"),
                sale_model=_qp(request, "sale_model", "all"),
                date_from=_qp(request, "date_from") or None,
                date_to=_qp(request, "date_to") or None,
            )
        )

    if normalized == "orders":
        return HTMLResponse(
            await facade.orders_page(
                user=user,
                session=session,
                period=_qp(request, "period", "today"),
                marketplace=_qp(request, "marketplace", "all"),
                sale_model=_qp(request, "sale_model", "all"),
                economy=_qp(request, "economy", "all"),
                status=_qp(request, "status", "all"),
                sku=_qp(request, "sku", ""),
                sort=_qp(request, "sort", "date"),
                direction=_qp(request, "direction", "desc"),
                date_from=_qp(request, "date_from") or None,
                date_to=_qp(request, "date_to") or None,
                page_number=_qp_int(request, "page", 1),
                per_page=_qp_int(request, "per_page", 50),
            )
        )

    if normalized.startswith("orders/"):
        try:
            order_id = int(normalized.split("/", 1)[1])
        except (ValueError, IndexError):
            return HTMLResponse("<h1>Заказ не найден</h1>", status_code=404)
        return HTMLResponse(
            await facade.order_detail_page(order_id=order_id, user=user, session=session)
        )

    if normalized == "profit":
        return HTMLResponse(
            await facade.profit_page(
                user=user,
                session=session,
                period=_qp(request, "period", "7d"),
                marketplace=_qp(request, "marketplace", "all"),
                sale_model=_qp(request, "sale_model", "all"),
                economy=_qp(request, "economy", "all"),
                sku=_qp(request, "sku", ""),
                sort=_qp(request, "sort", "profit"),
                direction=_qp(request, "direction", "desc"),
                date_from=_qp(request, "date_from") or None,
                date_to=_qp(request, "date_to") or None,
            )
        )

    if normalized == "plan-fact":
        return HTMLResponse(
            await facade.plan_fact_page(
                user=user,
                session=session,
                period=_qp(request, "period", "30d"),
                marketplace=_qp(request, "marketplace", "all"),
                sale_model=_qp(request, "sale_model", "all"),
                sku=_qp(request, "sku", ""),
                sort=_qp(request, "sort", "deviation"),
                direction=_qp(request, "direction", "asc"),
                date_from=_qp(request, "date_from") or None,
                date_to=_qp(request, "date_to") or None,
            )
        )

    if normalized == "break-even":
        return HTMLResponse(
            await facade.break_even_page(
                user=user,
                session=session,
                target_margin=_qp(request, "target_margin", "20"),
                price_delta=_qp(request, "price_delta", "0"),
            )
        )

    if normalized == "products":
        return HTMLResponse(await facade.products_page(user=user, session=session))

    if normalized.startswith("products/"):
        try:
            product_id = int(normalized.split("/", 1)[1])
        except (ValueError, IndexError):
            return HTMLResponse("<h1>Товар не найден</h1>", status_code=404)
        return HTMLResponse(
            await facade.product_detail_page(
                master_product_id=product_id, user=user, session=session
            )
        )

    if normalized == "product-matching":
        return HTMLResponse(await facade.product_matching_page(user=user, session=session))

    if normalized == "stocks":
        return HTMLResponse(await facade.stocks_page(user=user, session=session))

    if normalized == "alerts":
        return HTMLResponse(await facade.alerts_page(user=user, session=session))

    if normalized == "data-quality":
        return HTMLResponse(await facade.data_quality_page(user=user, session=session))

    if normalized == "sales":
        return HTMLResponse(
            await facade.sales_page(
                user=user,
                session=session,
                period=_qp(request, "period", "30d"),
                marketplace=_qp(request, "marketplace", "all"),
                sku=_qp(request, "sku", ""),
                date_from=_qp(request, "date_from") or None,
                date_to=_qp(request, "date_to") or None,
            )
        )

    if normalized == "returns":
        return HTMLResponse(
            await facade.returns_page(
                user=user,
                session=session,
                period=_qp(request, "period", "30d"),
                marketplace=_qp(request, "marketplace", "all"),
                sku=_qp(request, "sku", ""),
                date_from=_qp(request, "date_from") or None,
                date_to=_qp(request, "date_to") or None,
            )
        )

    if normalized == "analytics":
        return HTMLResponse(await facade.analytics_page(user=user, session=session))

    if normalized == "control":
        return HTMLResponse(await facade.control_page(user=user, session=session))

    if normalized == "costs":
        return HTMLResponse(await facade.costs_page(user=user, session=session))

    if normalized.startswith("costs/"):
        try:
            product_id = int(normalized.split("/", 1)[1])
        except (ValueError, IndexError):
            return HTMLResponse("<h1>Товар не найден</h1>", status_code=404)
        return HTMLResponse(
            await facade.cost_edit_page(product_id=product_id, user=user, session=session)
        )

    if normalized == "profile":
        return HTMLResponse(await facade.profile_page(user=user, session=session))

    if normalized == "subscription":
        return HTMLResponse(await facade.subscription_page_web(user=user, session=session))

    if normalized == "accounts":
        return HTMLResponse(await facade.accounts_page_web(user=user, session=session))

    if normalized == "settings":
        return HTMLResponse(await facade.settings_page(user=user))

    if normalized == "admin/commissions":
        return HTMLResponse(
            await facade.commissions_admin_page(
                user=user,
                session=session,
            )
        )

    if normalized == "pricing":
        return HTMLResponse(await facade.pricing_page(user=user, session=session))

    if normalized == "mrc-pricing":
        return HTMLResponse(
            await facade.mrc_pricing_page(
                user=user,
                session=session,
                page_number=_qp_int(request, "page", 1),
                filter_type=_qp(request, "filter_type", "all"),
                search=_qp(request, "search", ""),
            )
        )

    if normalized == "auto-promo-prices":
        return HTMLResponse(
            await facade.auto_promo_prices_page(
                user=user,
                session=session,
                marketplace_account_id=_qp_int(request, "marketplace_account_id", None),
            )
        )

    if normalized == "auto-promo-import":
        return HTMLResponse(
            await facade.auto_promo_import_page(
                user=user,
                session=session,
                marketplace_account_id=_qp_int(request, "marketplace_account_id", None),
            )
        )

    return HTMLResponse("<h1>Раздел не найден</h1>", status_code=404)


@router.post("/web/admin/commissions/sync-wb", response_class=HTMLResponse, include_in_schema=False)
async def double_web_sync_wb(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: Any = SESSION_DEPENDENCY,
) -> Response:
    facade = _facade()
    return cast(
        Response,
        await facade.sync_wb_commissions_web(request=request, user=user, session=session),
    )


@router.post(
    "/web/admin/commissions/check-ozon", response_class=HTMLResponse, include_in_schema=False
)
async def double_web_check_ozon(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: Any = SESSION_DEPENDENCY,
) -> Response:
    facade = _facade()
    return cast(
        Response,
        await facade.check_ozon_commissions_web(request=request, user=user, session=session),
    )


@router.post(
    "/web/admin/commissions/import-ozon", response_class=HTMLResponse, include_in_schema=False
)
async def double_web_import_ozon(
    request: Request,
    file: Any = OZON_COMMISSION_FILE_FORM,
    effective_from: Any = OZON_COMMISSION_EFFECTIVE_FROM_FORM,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: Any = SESSION_DEPENDENCY,
) -> Response:
    facade = _facade()
    return cast(
        Response,
        await facade.import_ozon_commissions_web(
            request=request,
            file=file,
            effective_from=effective_from,
            user=user,
            session=session,
        ),
    )
