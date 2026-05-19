# ruff: noqa: E501

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.models.domain import User
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.views import _placeholder_page

logger = logging.getLogger(__name__)
router = APIRouter()


def _qp(request: Request, name: str, default: str = "") -> str:
    return request.query_params.get(name, default)


def _qp_int(request: Request, name: str, default: int) -> int:
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
    session: Any = SESSION_DEPENDENCY,  # type: ignore[assignment]
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
                page=_qp_int(request, "page", 1),
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
            await facade.product_detail_page(master_product_id=product_id, user=user, session=session)
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

    return HTMLResponse("<h1>Раздел не найден</h1>", status_code=404)
