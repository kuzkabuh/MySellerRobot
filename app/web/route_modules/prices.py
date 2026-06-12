"""version: 1.0.0
description: Unified price management web section — /web/prices.
    Main pricing hub: table with WB + Ozon prices, manual edits, bulk ops,
    price history, and analytics. Server-side pagination, sort, and filter.
updated: 2026-06-13
"""

# ruff: noqa: E501

import logging
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.models.domain import (
    MarketplaceAccount,
    OzonCurrentPrice,
    PriceChangeLog,
    Product,
    ProductCostHistory,
    StockSnapshot,
    WbProductPrice,
)
from app.models.enums import Marketplace
from app.services.ozon.pricing.ozon_price_sync_service import OzonPriceSyncService
from app.services.pricing.price_management_service import (
    BulkOperation,
    BulkPriceParams,
    BulkPricePreviewRow,
    PriceEditItem,
    PriceManagementService,
)
from app.services.wb.pricing.wb_price_sync_service import WbPriceSyncService
from app.utils.datetime import format_datetime_for_user
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.rendering import page

logger = logging.getLogger(__name__)
router = APIRouter()

PAGE_SIZE = 50

MARKETPLACE_LABELS = {"WB": "WB", "OZON": "Ozon", "": "Все"}

BULK_OP_LABELS = {
    "set": "Установить цену",
    "increase_percent": "Увеличить на %",
    "decrease_percent": "Уменьшить на %",
    "increase_fixed": "Увеличить на сумму",
    "decrease_fixed": "Уменьшить на сумму",
    "round": "Округлить",
    "min_margin": "Мин. маржа %",
    "min_profit": "Мин. прибыль ₽",
}


# ─── Data helpers ────────────────────────────────────────────────────────────

def _fmt(v: Decimal | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f} ₽".replace(",", " ")


def _fmt2(v: Decimal | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}".replace(",", " ")


def _pct(v: Decimal | None) -> str:
    if v is None:
        return "—"
    return f"{v:.1f}%"


def _e(s: Any) -> str:
    return escape(str(s)) if s is not None else ""


def _price_indicator_class(system_price: Decimal | None, market_price: Decimal | None) -> str:
    """Return CSS class based on price discrepancy."""
    if system_price is None or market_price is None:
        return "price-indicator-neutral"
    diff_pct = abs(system_price - market_price) / market_price * 100
    if diff_pct < 2:
        return "price-indicator-ok"
    if diff_pct < 10:
        return "price-indicator-warn"
    return "price-indicator-bad"


def _margin_pct(price: Decimal | None, cost: Decimal | None) -> Decimal | None:
    if price is None or cost is None or price <= 0:
        return None
    return (price - cost) / price * 100


def _profit(price: Decimal | None, cost: Decimal | None) -> Decimal | None:
    if price is None or cost is None:
        return None
    return price - cost


# ─── Page data loader ────────────────────────────────────────────────────────

@dataclass(slots=True)
class PricesRow:
    product: Product
    account_name: str
    wb_price: Decimal | None
    wb_discount: int | None
    wb_discounted_price: Decimal | None
    wb_synced_at: str | None
    ozon_price: Decimal | None
    ozon_old_price: Decimal | None
    ozon_min_price: Decimal | None
    ozon_synced_at: str | None
    cost_price: Decimal | None
    profit: Decimal | None
    margin_pct: Decimal | None
    wb_indicator: str
    ozon_indicator: str
    stock_quantity: int | None
    last_price_change: str | None
    last_price_source: str | None


@dataclass(slots=True)
class PricesPageData:
    rows: list[PricesRow]
    total: int
    page: int
    page_size: int
    total_pages: int
    search: str
    marketplace_filter: str
    sort_by: str
    sort_dir: str
    accounts: list[MarketplaceAccount]
    stats: dict[str, Any]
    price_synced: bool
    error_msg: str | None


async def _load_page_data(
    session: AsyncSession,
    user_id: int,
    page: int,
    search: str,
    marketplace_filter: str,
    sort_by: str,
    sort_dir: str,
) -> PricesPageData:
    # Accounts
    accts_result = await session.execute(
        select(MarketplaceAccount).where(
            MarketplaceAccount.user_id == user_id,
            MarketplaceAccount.is_active.is_(True),
        )
    )
    accounts = list(accts_result.scalars().all())
    acct_map: dict[int, str] = {a.id: a.name or f"Аккаунт {a.id}" for a in accounts}

    # Base product query
    q = select(Product).where(
        Product.user_id == user_id,
        Product.is_active.is_(True),
    )
    if marketplace_filter == "WB":
        q = q.where(Product.marketplace == Marketplace.WB)
    elif marketplace_filter == "OZON":
        q = q.where(Product.marketplace == Marketplace.OZON)

    if search:
        pattern = f"%{search}%"
        q = q.where(
            or_(
                Product.seller_article.ilike(pattern),
                Product.title.ilike(pattern),
                cast(Product.external_product_id, String).ilike(pattern),
            )
        )

    # Count
    count_q = select(func.count()).select_from(q.subquery())
    total = (await session.execute(count_q)).scalar_one()

    # Sort
    _sort_cols = {
        "article": Product.seller_article,
        "title": Product.title,
        "brand": Product.brand,
        "category": Product.category,
    }
    order_col = _sort_cols.get(sort_by, Product.seller_article)
    if sort_dir == "desc":
        q = q.order_by(order_col.desc().nulls_last())
    else:
        q = q.order_by(order_col.asc().nulls_last())

    # Paginate
    offset = (page - 1) * PAGE_SIZE
    q = q.offset(offset).limit(PAGE_SIZE)
    products = list((await session.execute(q)).scalars().all())

    if not products:
        return PricesPageData(
            rows=[], total=total, page=page, page_size=PAGE_SIZE,
            total_pages=max(1, math.ceil(total / PAGE_SIZE)),
            search=search, marketplace_filter=marketplace_filter,
            sort_by=sort_by, sort_dir=sort_dir, accounts=accounts,
            stats={}, price_synced=False, error_msg=None,
        )

    # Collect IDs for bulk fetch
    product_ids = [p.id for p in products]
    account_ids = list({p.marketplace_account_id for p in products})

    # WB prices: nm_id → WbProductPrice
    wb_prices: dict[int, WbProductPrice] = {}
    nm_ids: list[int] = []
    for p in products:
        if p.marketplace == Marketplace.WB:
            nm_str = p.external_product_id or p.marketplace_article
            if nm_str:
                try:
                    nm_ids.append(int(nm_str))
                except (ValueError, TypeError):
                    pass
    if nm_ids:
        wb_result = await session.execute(
            select(WbProductPrice).where(
                WbProductPrice.marketplace_account_id.in_(account_ids),
                WbProductPrice.wb_nm_id.in_(nm_ids),
            )
        )
        for row in wb_result.scalars().all():
            wb_prices[row.wb_nm_id] = row

    # Ozon prices: offer_id → OzonCurrentPrice
    ozon_prices: dict[str, OzonCurrentPrice] = {}
    offer_ids: list[str] = []
    for p in products:
        if p.marketplace == Marketplace.OZON:
            oid = p.seller_article or p.external_product_id
            if oid:
                offer_ids.append(oid)
    if offer_ids:
        oz_result = await session.execute(
            select(OzonCurrentPrice).where(
                OzonCurrentPrice.marketplace_account_id.in_(account_ids),
                OzonCurrentPrice.offer_id.in_(offer_ids),
            )
        )
        for row in oz_result.scalars().all():
            ozon_prices[row.offer_id] = row

    # Cost prices: product_id → latest cost_price
    cost_prices: dict[int, Decimal] = {}
    if product_ids:
        cp_result = await session.execute(
            select(ProductCostHistory.product_id, ProductCostHistory.cost_price)
            .where(
                ProductCostHistory.product_id.in_(product_ids),
                ProductCostHistory.valid_to.is_(None),
            )
            .order_by(ProductCostHistory.valid_from.desc())
        )
        seen: set[int] = set()
        for pid, cp in cp_result.all():
            if pid not in seen:
                cost_prices[pid] = cp
                seen.add(pid)

    # Stock quantities: product_id → latest total quantity
    stock_quantities: dict[int, int] = {}
    if product_ids:
        sq_result = await session.execute(
            select(StockSnapshot.product_id, func.sum(StockSnapshot.quantity))
            .where(StockSnapshot.product_id.in_(product_ids))
            .group_by(StockSnapshot.product_id)
        )
        for pid, qty in sq_result.all():
            if pid is not None:
                stock_quantities[pid] = int(qty or 0)

    # Last price changes: product_id → (created_at_str, source)
    last_price_changes: dict[int, tuple[str, str]] = {}
    if product_ids:
        pcl_result = await session.execute(
            select(
                PriceChangeLog.product_id,
                PriceChangeLog.created_at,
                PriceChangeLog.source,
            )
            .where(
                PriceChangeLog.product_id.in_(product_ids),
                PriceChangeLog.status == "applied",
            )
            .order_by(PriceChangeLog.created_at.desc())
        )
        seen_pcl: set[int] = set()
        for pid, ts, src in pcl_result.all():
            if pid not in seen_pcl and pid is not None:
                last_price_changes[pid] = (
                    format_datetime_for_user(ts) if ts else "",
                    src or "",
                )
                seen_pcl.add(pid)

    # Build rows
    rows: list[PricesRow] = []
    for p in products:
        acct_name = acct_map.get(p.marketplace_account_id, "")
        wb_row: WbProductPrice | None = None
        ozon_row: OzonCurrentPrice | None = None
        if p.marketplace == Marketplace.WB:
            nm_str = p.external_product_id or p.marketplace_article
            if nm_str:
                try:
                    wb_row = wb_prices.get(int(nm_str))
                except (ValueError, TypeError):
                    pass
        elif p.marketplace == Marketplace.OZON:
            oid = p.seller_article or p.external_product_id
            ozon_row = ozon_prices.get(oid) if oid else None

        wb_price = wb_row.price if wb_row else None
        wb_discounted = wb_row.discounted_price if wb_row else None
        wb_discount_pct = wb_row.discount if wb_row else None
        wb_synced = (
            format_datetime_for_user(wb_row.synced_at) if wb_row and wb_row.synced_at else None
        )
        ozon_price = ozon_row.price if ozon_row else None
        ozon_old = ozon_row.old_price if ozon_row else None
        ozon_min = ozon_row.min_price if ozon_row else None
        ozon_synced = (
            format_datetime_for_user(ozon_row.synced_at) if ozon_row and ozon_row.synced_at else None
        )

        cost = cost_prices.get(p.id)
        display_price = wb_discounted or wb_price or ozon_price
        profit = _profit(display_price, cost)
        margin = _margin_pct(display_price, cost)

        system_price = p.mrc_price or display_price
        wb_indicator = _price_indicator_class(system_price, wb_discounted or wb_price)
        ozon_indicator = _price_indicator_class(system_price, ozon_price)

        last_chg = last_price_changes.get(p.id)

        rows.append(
            PricesRow(
                product=p,
                account_name=acct_name,
                wb_price=wb_price,
                wb_discount=wb_discount_pct,
                wb_discounted_price=wb_discounted,
                wb_synced_at=wb_synced,
                ozon_price=ozon_price,
                ozon_old_price=ozon_old,
                ozon_min_price=ozon_min,
                ozon_synced_at=ozon_synced,
                cost_price=cost,
                profit=profit,
                margin_pct=margin,
                wb_indicator=wb_indicator,
                ozon_indicator=ozon_indicator,
                stock_quantity=stock_quantities.get(p.id),
                last_price_change=last_chg[0] if last_chg else None,
                last_price_source=last_chg[1] if last_chg else None,
            )
        )

    # Stats
    wb_products = sum(1 for p in products if p.marketplace == Marketplace.WB)
    ozon_products = sum(1 for p in products if p.marketplace == Marketplace.OZON)
    with_price = sum(
        1
        for r in rows
        if r.wb_discounted_price is not None or r.wb_price is not None or r.ozon_price is not None
    )
    price_mismatch = sum(
        1
        for r in rows
        if r.wb_indicator == "price-indicator-bad" or r.ozon_indicator == "price-indicator-bad"
    )
    stats = {
        "total": total,
        "wb_products": wb_products,
        "ozon_products": ozon_products,
        "with_price": with_price,
        "price_mismatch": price_mismatch,
    }

    return PricesPageData(
        rows=rows,
        total=total,
        page=page,
        page_size=PAGE_SIZE,
        total_pages=max(1, math.ceil(total / PAGE_SIZE)),
        search=search,
        marketplace_filter=marketplace_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        accounts=accounts,
        stats=stats,
        price_synced=False,
        error_msg=None,
    )


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.get("/prices", response_class=HTMLResponse)
async def prices_page(
    request: Request,
    page_num: int = Query(default=1, alias="page", ge=1),
    search: str = Query(default=""),
    mp: str = Query(default=""),
    sort: str = Query(default="article"),
    dir: str = Query(default="asc"),
    synced: str = Query(default=""),
    error: str = Query(default=""),
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    try:
        data = await _load_page_data(
            session, user.id, page_num, search, mp.upper(), sort, dir
        )
        data.price_synced = bool(synced)
        data.error_msg = error or None
        content = _render_prices_page(data)
    except Exception:
        logger.exception("prices_page_error", extra={"user_id": user.id})
        content = '<div class="band"><p>Ошибка загрузки раздела. Попробуйте обновить страницу.</p></div>'
    return page(
        "Управление ценами",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/prices",
    )


@router.post("/prices/sync-wb")
async def prices_sync_wb(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    try:
        # Only sync accounts belonging to the current user
        result = await session.execute(
            select(MarketplaceAccount).where(
                MarketplaceAccount.user_id == user.id,
                MarketplaceAccount.marketplace == Marketplace.WB,
                MarketplaceAccount.is_active.is_(True),
            )
        )
        accounts = list(result.scalars().all())
        svc = WbPriceSyncService(session)
        for account in accounts:
            await svc.sync_account(account)
        await session.commit()
        return RedirectResponse(url="/web/prices?synced=wb", status_code=303)
    except Exception:
        logger.exception("prices_sync_wb_error", extra={"user_id": user.id})
        await session.rollback()
        return RedirectResponse(url="/web/prices?error=sync_wb", status_code=303)


@router.post("/prices/sync-ozon")
async def prices_sync_ozon(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    try:
        # Only sync accounts belonging to the current user
        result = await session.execute(
            select(MarketplaceAccount).where(
                MarketplaceAccount.user_id == user.id,
                MarketplaceAccount.marketplace == Marketplace.OZON,
                MarketplaceAccount.is_active.is_(True),
            )
        )
        accounts = list(result.scalars().all())
        svc = OzonPriceSyncService(session)
        for account in accounts:
            await svc.sync_account(account)
        await session.commit()
        return RedirectResponse(url="/web/prices?synced=ozon", status_code=303)
    except Exception:
        logger.exception("prices_sync_ozon_error", extra={"user_id": user.id})
        await session.rollback()
        return RedirectResponse(url="/web/prices?error=sync_ozon", status_code=303)


@router.post("/prices/edit-single", response_class=HTMLResponse)
async def prices_edit_single(
    product_id: int = Form(...),
    marketplace: str = Form(...),
    new_price: str = Form(...),
    new_discount: str = Form(default=""),
    reason: str = Form(default=""),
    comment: str = Form(default=""),
    marketplace_account_id: int = Form(...),
    request: Request = None,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> Response:
    try:
        price_val = Decimal(new_price.replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return RedirectResponse(url="/web/prices?error=invalid_price", status_code=303)

    discount_val: int | None = None
    if new_discount.strip():
        try:
            discount_val = int(new_discount.strip())
        except (ValueError, TypeError):
            pass

    client_ip = request.client.host if request and request.client else None
    svc = PriceManagementService(session)
    item = PriceEditItem(
        product_id=product_id,
        marketplace=marketplace.upper(),
        new_price=price_val,
        new_discount=discount_val,
        reason=reason.strip() or None,
        comment=comment.strip() or None,
    )
    try:
        result = await svc.edit_single_price(
            user_id=user.id,
            marketplace_account_id=marketplace_account_id,
            item=item,
            changed_by_ip=client_ip,
        )
        await session.commit()
        if result.status in ("applied", "dry_run"):
            return RedirectResponse(url=f"/web/prices?synced=edit&pid={product_id}", status_code=303)
        return RedirectResponse(
            url=f"/web/prices?error={escape(result.error or 'edit_failed')}", status_code=303
        )
    except Exception:
        logger.exception("prices_edit_single_error", extra={"user_id": user.id, "product_id": product_id})
        await session.rollback()
        return RedirectResponse(url="/web/prices?error=edit_failed", status_code=303)


@router.post("/prices/bulk-preview", response_class=HTMLResponse)
async def prices_bulk_preview(
    product_ids: str = Form(...),
    operation: str = Form(...),
    value: str = Form(...),
    round_to: str = Form(default="0"),
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    try:
        ids = [int(x) for x in product_ids.split(",") if x.strip().isdigit()]
        val = Decimal(value.replace(",", ".").strip())
        rt = int(round_to.strip() or "0")
        params = BulkPriceParams(
            operation=BulkOperation(operation),
            value=val,
            round_to=rt,
        )
        svc = PriceManagementService(session)
        preview_rows = await svc.build_bulk_preview(user.id, ids, params)
        content = _render_bulk_preview(preview_rows, params, product_ids)
    except Exception:
        logger.exception("prices_bulk_preview_error", extra={"user_id": user.id})
        content = '<div class="band"><p>Ошибка предпросмотра. Проверьте введённые данные.</p></div>'
    return page(
        "Предпросмотр массового изменения",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/prices",
    )


@router.post("/prices/bulk-apply")
async def prices_bulk_apply(
    product_ids: str = Form(...),
    operation: str = Form(...),
    value: str = Form(...),
    round_to: str = Form(default="0"),
    marketplace_account_id: int = Form(...),
    reason: str = Form(default=""),
    comment: str = Form(default=""),
    request: Request = None,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    try:
        ids = [int(x) for x in product_ids.split(",") if x.strip().isdigit()]
        val = Decimal(value.replace(",", ".").strip())
        rt = int(round_to.strip() or "0")
        params = BulkPriceParams(
            operation=BulkOperation(operation),
            value=val,
            round_to=rt,
        )
        client_ip = request.client.host if request and request.client else None
        svc = PriceManagementService(session)
        results = await svc.apply_bulk_prices(
            user_id=user.id,
            marketplace_account_id=marketplace_account_id,
            product_ids=ids,
            params=params,
            reason=reason.strip() or None,
            comment=comment.strip() or None,
            changed_by_ip=client_ip,
        )
        await session.commit()
        applied = sum(1 for r in results if r.status == "applied")
        skipped = sum(1 for r in results if r.status == "skipped")
        return RedirectResponse(
            url=f"/web/prices?synced=bulk&applied={applied}&skipped={skipped}",
            status_code=303,
        )
    except Exception:
        logger.exception("prices_bulk_apply_error", extra={"user_id": user.id})
        await session.rollback()
        return RedirectResponse(url="/web/prices?error=bulk_failed", status_code=303)


async def _render_analytics_page(
    session: AsyncSession,
    user_id: int,
    mp_filter: str,
    days: int,
) -> str:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, and_

    cutoff = datetime.now(tz=UTC) - timedelta(days=days)

    # Query price change log aggregated by day
    q = (
        select(
            func.date_trunc("day", PriceChangeLog.created_at).label("day"),
            PriceChangeLog.marketplace,
            func.count().label("changes_count"),
            func.avg(PriceChangeLog.new_price).label("avg_new_price"),
            func.min(PriceChangeLog.new_price).label("min_new_price"),
            func.max(PriceChangeLog.new_price).label("max_new_price"),
        )
        .where(
            PriceChangeLog.user_id == user_id,
            PriceChangeLog.created_at >= cutoff,
            PriceChangeLog.status == "applied",
            PriceChangeLog.dry_run.is_(False),
        )
    )
    if mp_filter in ("WB", "OZON"):
        q = q.where(PriceChangeLog.marketplace == mp_filter)
    q = q.group_by("day", PriceChangeLog.marketplace).order_by("day")
    rows = (await session.execute(q)).all()

    # Totals
    total_changes = sum(r.changes_count for r in rows)
    avg_price = (
        sum(float(r.avg_new_price or 0) * r.changes_count for r in rows) / total_changes
        if total_changes else 0
    )

    # Build chart datasets
    days_labels: list[str] = []
    wb_data: list[int] = []
    ozon_data: list[int] = []
    seen_days: dict[str, dict[str, int]] = {}
    for r in rows:
        day_str = r.day.strftime("%d.%m") if hasattr(r.day, "strftime") else str(r.day)[:10]
        if day_str not in seen_days:
            seen_days[day_str] = {"WB": 0, "OZON": 0}
        seen_days[day_str][r.marketplace] = r.changes_count
    for day_str, mp_data in seen_days.items():
        days_labels.append(day_str)
        wb_data.append(mp_data.get("WB", 0))
        ozon_data.append(mp_data.get("OZON", 0))

    import json
    labels_json = json.dumps(days_labels)
    wb_json = json.dumps(wb_data)
    ozon_json = json.dumps(ozon_data)

    mp_options = (
        '<option value="">Все МП</option>'
        f'<option value="WB" {"selected" if mp_filter == "WB" else ""}>Wildberries</option>'
        f'<option value="OZON" {"selected" if mp_filter == "OZON" else ""}>Ozon</option>'
    )
    days_options = "".join(
        f'<option value="{d}" {"selected" if d == days else ""}>{d} дней</option>'
        for d in (7, 14, 30, 60, 90, 180)
    )

    # Sub-navigation
    subnav = (
        '<div class="subnav" style="padding:12px 20px 0;">'
        '<a href="/web/prices">Таблица цен</a>'
        '<a href="/web/prices/history">История изменений</a>'
        '<a class="active" href="/web/prices/analytics">Аналитика</a>'
        '</div>'
    )

    return f"""{_prices_styles()}
<div class="prices-page">
{subnav}
<div class="band" style="margin-top:16px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
    <h1 style="margin:0;font-size:1.3rem;">Аналитика цен</h1>
    <form method="get" action="/web/prices/analytics" style="display:flex;gap:8px;align-items:center;">
      <select name="mp" class="prices-filter-select" onchange="this.form.submit()">{mp_options}</select>
      <select name="days" class="prices-filter-select" onchange="this.form.submit()">{days_options}</select>
    </form>
  </div>

  <div class="analytics-grid">
    <div class="prices-stat-card">
      <div class="prices-stat-value">{total_changes}</div>
      <div class="prices-stat-label">Изменений цен</div>
    </div>
    <div class="prices-stat-card">
      <div class="prices-stat-value">{"%.0f ₽" % avg_price if avg_price else "—"}</div>
      <div class="prices-stat-label">Средняя новая цена</div>
    </div>
    <div class="prices-stat-card">
      <div class="prices-stat-value">{days} дн.</div>
      <div class="prices-stat-label">Период анализа</div>
    </div>
  </div>

  {"" if total_changes else '<div class="prices-empty">Нет данных об изменениях цен за выбранный период.</div>'}

  {f"""
  <div class="analytics-card" style="margin-bottom:20px;">
    <h3>Количество изменений цен по дням</h3>
    <div class="analytics-chart-wrap">
      <canvas id="chart-changes"></canvas>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <script>
  (function() {{
    const labels = {labels_json};
    const wbData = {wb_json};
    const ozonData = {ozon_json};
    const ctx = document.getElementById('chart-changes').getContext('2d');
    new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels,
        datasets: [
          {{
            label: 'Wildberries',
            data: wbData,
            backgroundColor: 'rgba(200, 80, 130, 0.7)',
            borderColor: 'rgba(200, 80, 130, 1)',
            borderWidth: 1,
          }},
          {{
            label: 'Ozon',
            data: ozonData,
            backgroundColor: 'rgba(0, 91, 255, 0.6)',
            borderColor: 'rgba(0, 91, 255, 1)',
            borderWidth: 1,
          }},
        ],
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'top' }},
        }},
        scales: {{
          x: {{ stacked: false }},
          y: {{ beginAtZero: true, ticks: {{ precision: 0 }} }},
        }},
      }},
    }});
  }})();
  </script>
  """ if total_changes else ""}
</div>
</div>"""


@router.get("/prices/analytics", response_class=HTMLResponse)
async def prices_analytics(
    mp: str = Query(default=""),
    days: int = Query(default=30, ge=7, le=180),
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    try:
        content = await _render_analytics_page(session, user.id, mp.upper(), days)
    except Exception:
        logger.exception("prices_analytics_error", extra={"user_id": user.id})
        content = '<div class="band"><p>Ошибка загрузки аналитики.</p></div>'
    return page(
        "Аналитика цен",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/prices",
    )


@router.get("/prices/history", response_class=HTMLResponse)
async def prices_history(
    page_num: int = Query(default=1, alias="page", ge=1),
    search: str = Query(default=""),
    mp: str = Query(default=""),
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    try:
        content = await _render_history_page(session, user.id, page_num, search, mp.upper())
    except Exception:
        logger.exception("prices_history_error", extra={"user_id": user.id})
        content = '<div class="band"><p>Ошибка загрузки истории.</p></div>'
    return page(
        "История цен",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/prices",
    )


# ─── Rendering helpers ────────────────────────────────────────────────────────

def _render_prices_page(data: PricesPageData) -> str:
    stats = data.stats
    notice = ""
    if data.price_synced:
        notice = '<div class="alert alert-success mb-3">Синхронизация завершена успешно.</div>'
    if data.error_msg:
        notice = f'<div class="alert alert-danger mb-3">Ошибка: {_e(data.error_msg)}</div>'

    stat_cards = f"""
    <div class="prices-stats-grid">
      <div class="prices-stat-card">
        <div class="prices-stat-value">{stats.get("total", 0)}</div>
        <div class="prices-stat-label">Всего товаров</div>
      </div>
      <div class="prices-stat-card">
        <div class="prices-stat-value">{stats.get("with_price", 0)}</div>
        <div class="prices-stat-label">С ценой</div>
      </div>
      <div class="prices-stat-card prices-stat-card--wb">
        <div class="prices-stat-value">{stats.get("wb_products", 0)}</div>
        <div class="prices-stat-label">WB</div>
      </div>
      <div class="prices-stat-card prices-stat-card--ozon">
        <div class="prices-stat-value">{stats.get("ozon_products", 0)}</div>
        <div class="prices-stat-label">Ozon</div>
      </div>
      <div class="prices-stat-card prices-stat-card--warn">
        <div class="prices-stat-value">{stats.get("price_mismatch", 0)}</div>
        <div class="prices-stat-label">Расхождений</div>
      </div>
    </div>"""

    filters = _render_filters(data)
    toolbar = _render_toolbar(data)
    table = _render_table(data)
    pagination = _render_pagination(data)
    modals = _render_modals(data)

    return f"""
<div class="prices-page">
  {notice}
  {stat_cards}
  <div class="prices-main-card">
    {filters}
    {toolbar}
    {table}
    {pagination}
  </div>
  {modals}
</div>
{_prices_styles()}
{_prices_js()}"""


def _render_filters(data: PricesPageData) -> str:
    mp_opts = ""
    for val, label in [("", "Все маркетплейсы"), ("WB", "Wildberries"), ("OZON", "Ozon")]:
        sel = ' selected' if data.marketplace_filter == val else ''
        mp_opts += f'<option value="{val}"{sel}>{label}</option>'

    return f"""
  <form class="prices-filters" method="get" action="/web/prices" id="prices-filter-form">
    <div class="prices-filter-row">
      <input class="prices-search-input" type="text" name="search"
             placeholder="Поиск: артикул, название, ID..."
             value="{_e(data.search)}">
      <select class="prices-filter-select" name="mp" onchange="this.form.submit()">
        {mp_opts}
      </select>
      <button class="btn btn-primary btn-sm" type="submit">Найти</button>
      {'<a class="btn btn-ghost btn-sm" href="/web/prices">Сбросить</a>' if data.search or data.marketplace_filter else ''}
    </div>
  </form>"""


def _render_toolbar(data: PricesPageData) -> str:
    return """
  <div class="prices-toolbar">
    <div class="prices-toolbar-left">
      <button class="btn btn-ghost btn-sm" type="button" id="btn-select-all">
        Выбрать всё
      </button>
      <button class="btn btn-secondary btn-sm" type="button" id="btn-bulk-open" disabled>
        Массовое изменение
      </button>
    </div>
    <div class="prices-toolbar-right">
      <form method="post" action="/web/prices/sync-wb" style="display:inline">
        <button class="btn btn-ghost btn-sm" type="submit">↻ Синхр. WB</button>
      </form>
      <form method="post" action="/web/prices/sync-ozon" style="display:inline">
        <button class="btn btn-ghost btn-sm" type="submit">↻ Синхр. Ozon</button>
      </form>
      <a class="btn btn-ghost btn-sm" href="/web/prices/history">История цен</a>
    </div>
  </div>"""


def _render_table(data: PricesPageData) -> str:
    if not data.rows:
        return '<div class="prices-empty">Товары не найдены. Измените параметры поиска.</div>'

    def _th(label: str, key: str) -> str:
        icon = ""
        if data.sort_by == key:
            icon = " ↑" if data.sort_dir == "asc" else " ↓"
        sd = "desc" if (data.sort_by == key and data.sort_dir == "asc") else "asc"
        q = f"?sort={key}&dir={sd}&search={escape(data.search)}&mp={data.marketplace_filter}&page={data.page}"
        return f'<th class="prices-th"><a href="/web/prices{q}">{label}{icon}</a></th>'

    header = f"""
    <thead>
      <tr>
        <th class="prices-th prices-th-check"><input type="checkbox" id="check-all" title="Выбрать всё"></th>
        <th class="prices-th">Фото</th>
        {_th("Артикул", "article")}
        {_th("Название", "title")}
        {_th("Бренд", "brand")}
        {_th("Категория", "category")}
        <th class="prices-th">МП</th>
        <th class="prices-th">Цена WB</th>
        <th class="prices-th">Скидка WB</th>
        <th class="prices-th">Цена Ozon</th>
        <th class="prices-th">МРЦ</th>
        <th class="prices-th">Мин. цена</th>
        <th class="prices-th">Себест.</th>
        <th class="prices-th">Прибыль</th>
        <th class="prices-th">Маржа</th>
        <th class="prices-th">Остаток</th>
        <th class="prices-th">Изм. цены</th>
        <th class="prices-th">Действия</th>
      </tr>
    </thead>"""

    rows_html = ""
    for r in data.rows:
        p = r.product
        mp_badge = '<span class="badge badge-wb">WB</span>' if p.marketplace == Marketplace.WB else '<span class="badge badge-ozon">Ozon</span>'
        img = f'<img class="prices-thumb" src="{_e(p.image_url)}" alt="" loading="lazy">' if p.image_url else '<div class="prices-thumb-placeholder"></div>'
        wb_price_cell = f'<span class="{r.wb_indicator}">{_fmt(r.wb_discounted_price or r.wb_price)}</span>' if (r.wb_price or r.wb_discounted_price) else '—'
        wb_discount_cell = f'{r.wb_discount}%' if r.wb_discount else '—'
        ozon_price_cell = f'<span class="{r.ozon_indicator}">{_fmt(r.ozon_price)}</span>' if r.ozon_price else '—'
        mrc_cell = _fmt(p.mrc_price)
        min_cell = _fmt(p.min_price)

        mp_val = p.marketplace.value if p.marketplace else ""
        acct_id = p.marketplace_account_id

        rows_html += f"""
      <tr class="prices-row" data-product-id="{p.id}" data-mp="{mp_val}" data-account-id="{acct_id}">
        <td class="prices-td-check">
          <input type="checkbox" class="row-check" value="{p.id}" data-mp="{mp_val}" data-account-id="{acct_id}">
        </td>
        <td class="prices-td">{img}</td>
        <td class="prices-td prices-article">{_e(p.seller_article) or _e(p.external_product_id)}</td>
        <td class="prices-td prices-title" title="{_e(p.title)}">{_e(p.title or '')[:50]}</td>
        <td class="prices-td">{_e(p.brand or '—')}</td>
        <td class="prices-td">{_e(p.category or '—')}</td>
        <td class="prices-td">{mp_badge}</td>
        <td class="prices-td prices-price">{wb_price_cell}</td>
        <td class="prices-td">{wb_discount_cell}</td>
        <td class="prices-td prices-price">{ozon_price_cell}</td>
        <td class="prices-td prices-mrc">{mrc_cell}</td>
        <td class="prices-td">{min_cell}</td>
        <td class="prices-td">{_fmt(r.cost_price)}</td>
        <td class="prices-td prices-profit">{_fmt(r.profit)}</td>
        <td class="prices-td">{_pct(r.margin_pct)}</td>
        <td class="prices-td">{r.stock_quantity if r.stock_quantity is not None else '—'}</td>
        <td class="prices-td prices-date" title="{_e(r.last_price_source or '')}">{_e(r.last_price_change or '—')}</td>
        <td class="prices-td">
          <button class="btn btn-xs btn-accent prices-edit-btn"
                  data-product-id="{p.id}"
                  data-mp="{mp_val}"
                  data-account-id="{acct_id}"
                  data-article="{_e(p.seller_article or '')}"
                  data-title="{_e((p.title or '')[:40])}"
                  data-wb-price="{r.wb_discounted_price or r.wb_price or ''}"
                  data-ozon-price="{r.ozon_price or ''}"
                  data-min-price="{p.min_price or ''}"
                  data-max-price="{p.max_price or ''}">
            Изменить
          </button>
        </td>
      </tr>"""

    return f"""
  <div class="prices-table-wrap">
    <table class="prices-table">
      {header}
      <tbody>{rows_html}</tbody>
    </table>
  </div>"""


def _render_pagination(data: PricesPageData) -> str:
    if data.total_pages <= 1:
        return ""
    items = ""
    for p in range(1, data.total_pages + 1):
        active = ' pagination-active' if p == data.page else ''
        q = f"?page={p}&search={escape(data.search)}&mp={data.marketplace_filter}&sort={data.sort_by}&dir={data.sort_dir}"
        items += f'<a class="pagination-item{active}" href="/web/prices{q}">{p}</a>'
    info = f'Показано {(data.page - 1) * PAGE_SIZE + 1}–{min(data.page * PAGE_SIZE, data.total)} из {data.total}'
    return f'<div class="prices-pagination"><span class="pagination-info">{info}</span><div class="pagination-pages">{items}</div></div>'


def _render_modals(data: PricesPageData) -> str:
    bulk_op_opts = "".join(
        f'<option value="{k}">{v}</option>' for k, v in BULK_OP_LABELS.items()
    )
    return f"""
<div id="modal-edit" class="modal-overlay" hidden>
  <div class="modal-box">
    <div class="modal-header">
      <h3 class="modal-title">Изменить цену</h3>
      <button class="modal-close" type="button" data-close="modal-edit">✕</button>
    </div>
    <form method="post" action="/web/prices/edit-single" class="modal-form" id="edit-single-form">
      <input type="hidden" name="product_id" id="edit-product-id">
      <input type="hidden" name="marketplace" id="edit-marketplace">
      <input type="hidden" name="marketplace_account_id" id="edit-account-id">
      <div class="form-group">
        <label class="form-label">Товар</label>
        <div id="edit-product-info" class="form-hint"></div>
      </div>
      <div class="form-group">
        <label class="form-label">Текущая цена</label>
        <div id="edit-current-price" class="form-hint prices-current-price"></div>
      </div>
      <div class="form-group">
        <label class="form-label" for="edit-new-price">Новая цена <span class="required">*</span></label>
        <input class="form-input" type="number" id="edit-new-price" name="new_price" min="1" step="0.01" required>
        <div id="edit-price-hint" class="form-hint"></div>
      </div>
      <div class="form-group" id="edit-discount-group" hidden>
        <label class="form-label" for="edit-discount">Скидка WB %</label>
        <input class="form-input" type="number" id="edit-discount" name="new_discount" min="0" max="99">
      </div>
      <div class="form-group">
        <label class="form-label" for="edit-reason">Причина изменения</label>
        <select class="form-select" id="edit-reason" name="reason">
          <option value="">Не указана</option>
          <option value="price_correction">Коррекция цены</option>
          <option value="promo">Акционная цена</option>
          <option value="competitive">Конкурентная корректировка</option>
          <option value="cost_change">Изменение себестоимости</option>
          <option value="other">Другое</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label" for="edit-comment">Комментарий</label>
        <textarea class="form-input" id="edit-comment" name="comment" rows="2" placeholder="Необязательно"></textarea>
      </div>
      <div class="modal-actions">
        <button type="submit" class="btn btn-primary">Применить</button>
        <button type="button" class="btn btn-ghost" data-close="modal-edit">Отмена</button>
      </div>
    </form>
  </div>
</div>

<div id="modal-bulk" class="modal-overlay" hidden>
  <div class="modal-box modal-box-lg">
    <div class="modal-header">
      <h3 class="modal-title">Массовое изменение цен</h3>
      <button class="modal-close" type="button" data-close="modal-bulk">✕</button>
    </div>
    <div class="modal-body">
      <p id="bulk-selection-info" class="form-hint"></p>
      <div class="form-group">
        <label class="form-label">Операция</label>
        <select class="form-select" id="bulk-operation" onchange="updateBulkHint()">
          {bulk_op_opts}
        </select>
      </div>
      <div class="form-group">
        <label class="form-label" id="bulk-value-label">Значение</label>
        <input class="form-input" type="number" id="bulk-value" step="0.01" min="0" placeholder="0">
        <div id="bulk-hint" class="form-hint"></div>
      </div>
      <div class="form-group" id="bulk-round-group" hidden>
        <label class="form-label">Округлять до</label>
        <select class="form-select" id="bulk-round-to">
          <option value="1">1 ₽</option>
          <option value="5">5 ₽</option>
          <option value="10">10 ₽</option>
          <option value="50">50 ₽</option>
          <option value="100">100 ₽</option>
        </select>
      </div>
    </div>
    <div class="modal-actions">
      <button class="btn btn-primary" type="button" id="btn-bulk-preview">Предпросмотр</button>
      <button type="button" class="btn btn-ghost" data-close="modal-bulk">Отмена</button>
    </div>
  </div>
</div>"""


async def _render_history_page(
    session: AsyncSession,
    user_id: int,
    page_num: int,
    search: str,
    mp_filter: str,
) -> str:
    q = select(PriceChangeLog).where(PriceChangeLog.user_id == user_id)
    if mp_filter:
        q = q.where(PriceChangeLog.marketplace == mp_filter)
    if search:
        pattern = f"%{search}%"
        q = q.where(
            or_(
                PriceChangeLog.seller_article.ilike(pattern),
                PriceChangeLog.external_product_id.ilike(pattern),
            )
        )
    count_q = select(func.count()).select_from(q.subquery())
    total = (await session.execute(count_q)).scalar_one()
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    offset = (page_num - 1) * PAGE_SIZE
    q = q.order_by(PriceChangeLog.created_at.desc()).offset(offset).limit(PAGE_SIZE)
    logs = list((await session.execute(q)).scalars().all())

    rows_html = ""
    for log in logs:
        status_cls = {
            "applied": "badge badge-success",
            "failed": "badge badge-danger",
            "skipped": "badge badge-warning",
            "dry_run": "badge badge-info",
            "pending": "badge",
        }.get(log.status, "badge")
        mp_badge = f'<span class="badge badge-wb">WB</span>' if log.marketplace == "WB" else f'<span class="badge badge-ozon">Ozon</span>'
        old_p = _fmt(log.old_price)
        new_p = _fmt(log.new_price)
        change_pct = ""
        if log.old_price and log.old_price > 0 and log.new_price:
            pct = (log.new_price - log.old_price) / log.old_price * 100
            sign = "+" if pct >= 0 else ""
            cls = "text-success" if pct >= 0 else "text-danger"
            change_pct = f'<span class="{cls}">{sign}{pct:.1f}%</span>'
        created = format_datetime_for_user(log.created_at) if log.created_at else "—"
        rows_html += f"""
      <tr>
        <td class="prices-td">{created}</td>
        <td class="prices-td">{mp_badge}</td>
        <td class="prices-td">{_e(log.seller_article or log.external_product_id)}</td>
        <td class="prices-td prices-price">{old_p}</td>
        <td class="prices-td prices-price">{new_p}</td>
        <td class="prices-td">{change_pct}</td>
        <td class="prices-td">{_e(log.source)}</td>
        <td class="prices-td">{_e(log.reason or '—')}</td>
        <td class="prices-td"><span class="{status_cls}">{_e(log.status)}</span></td>
        <td class="prices-td" title="{_e(log.error or '')}">{_e((log.error or '')[:50]) or '—'}</td>
      </tr>"""

    mp_opts = ""
    for val, label in [("", "Все МП"), ("WB", "WB"), ("OZON", "Ozon")]:
        sel = ' selected' if mp_filter == val else ''
        mp_opts += f'<option value="{val}"{sel}>{label}</option>'

    pg_html = ""
    for p in range(1, total_pages + 1):
        active = ' pagination-active' if p == page_num else ''
        q_str = f"?page={p}&search={escape(search)}&mp={mp_filter}"
        pg_html += f'<a class="pagination-item{active}" href="/web/prices/history{q_str}">{p}</a>'

    return f"""
<div class="prices-page">
  <div class="prices-main-card">
    <div class="prices-history-header">
      <h2>История изменений цен</h2>
      <a class="btn btn-ghost btn-sm" href="/web/prices">← Назад к ценам</a>
    </div>
    <form class="prices-filters" method="get" action="/web/prices/history">
      <div class="prices-filter-row">
        <input class="prices-search-input" type="text" name="search"
               placeholder="Поиск по артикулу или ID..." value="{_e(search)}">
        <select class="prices-filter-select" name="mp" onchange="this.form.submit()">{mp_opts}</select>
        <button class="btn btn-primary btn-sm" type="submit">Найти</button>
      </div>
    </form>
    <div class="prices-table-wrap">
      <table class="prices-table">
        <thead>
          <tr>
            <th class="prices-th">Дата</th>
            <th class="prices-th">МП</th>
            <th class="prices-th">Артикул</th>
            <th class="prices-th">Старая цена</th>
            <th class="prices-th">Новая цена</th>
            <th class="prices-th">Изменение</th>
            <th class="prices-th">Источник</th>
            <th class="prices-th">Причина</th>
            <th class="prices-th">Статус</th>
            <th class="prices-th">Ошибка</th>
          </tr>
        </thead>
        <tbody>{rows_html or '<tr><td colspan="10" class="prices-empty">История пуста</td></tr>'}</tbody>
      </table>
    </div>
    <div class="prices-pagination">
      <span class="pagination-info">Всего: {total}</span>
      <div class="pagination-pages">{pg_html}</div>
    </div>
  </div>
</div>
{_prices_styles()}"""


def _render_bulk_preview(
    rows: list[BulkPricePreviewRow],
    params: BulkPriceParams,
    product_ids_str: str,
) -> str:
    rows_html = ""
    can_apply_ids = []
    for r in rows:
        status_cls = "text-success" if r.can_apply else "text-danger"
        status_txt = "✓" if r.can_apply else f"✗ {_e(r.error or '')}"
        if r.can_apply:
            can_apply_ids.append(str(r.product_id))
        rows_html += f"""
      <tr>
        <td class="prices-td">{_e(r.seller_article or str(r.product_id))}</td>
        <td class="prices-td">{_e(r.title or '')[:50]}</td>
        <td class="prices-td">{_e(r.marketplace)}</td>
        <td class="prices-td prices-price">{_fmt(r.current_price)}</td>
        <td class="prices-td prices-price"><strong>{_fmt(r.new_price)}</strong></td>
        <td class="prices-td {status_cls}">{status_txt}</td>
      </tr>"""

    can_count = len(can_apply_ids)
    return f"""
<div class="prices-page">
  <div class="prices-main-card">
    <div class="prices-history-header">
      <h2>Предпросмотр: {BULK_OP_LABELS.get(params.operation.value, params.operation.value)}</h2>
      <a class="btn btn-ghost btn-sm" href="/web/prices">← Назад</a>
    </div>
    <p>Готово к применению: <strong>{can_count}</strong> из {len(rows)} товаров.</p>
    <div class="prices-table-wrap">
      <table class="prices-table">
        <thead>
          <tr>
            <th class="prices-th">Артикул</th>
            <th class="prices-th">Название</th>
            <th class="prices-th">МП</th>
            <th class="prices-th">Текущая цена</th>
            <th class="prices-th">Новая цена</th>
            <th class="prices-th">Статус</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
    <form method="post" action="/web/prices/bulk-apply" class="mt-3">
      <input type="hidden" name="product_ids" value="{','.join(can_apply_ids)}">
      <input type="hidden" name="operation" value="{_e(params.operation.value)}">
      <input type="hidden" name="value" value="{params.value}">
      <input type="hidden" name="round_to" value="{params.round_to}">
      <input type="hidden" name="marketplace_account_id" value="0">
      <div class="form-group">
        <label class="form-label" for="bulk-reason-final">Причина</label>
        <input class="form-input" type="text" id="bulk-reason-final" name="reason" placeholder="Необязательно">
      </div>
      <div class="modal-actions">
        <button class="btn btn-primary" type="submit" {'disabled' if can_count == 0 else ''}>
          Применить к {can_count} товарам
        </button>
        <a class="btn btn-ghost" href="/web/prices">Отмена</a>
      </div>
    </form>
  </div>
</div>
{_prices_styles()}"""


def _prices_styles() -> str:
    return """<style>
.prices-page { padding: 0 0 2rem; }
.prices-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}
.prices-stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  text-align: center;
  box-shadow: var(--shadow-xs);
}
.prices-stat-card--wb { border-color: var(--wb-border); background: var(--wb-soft); }
.prices-stat-card--ozon { border-color: var(--ozon-border); background: var(--ozon-soft); }
.prices-stat-card--warn { border-color: var(--warning-border); background: var(--warning-soft); }
.prices-stat-value { font-size: 1.8rem; font-weight: 700; color: var(--text); line-height: 1; }
.prices-stat-label { font-size: 0.72rem; color: var(--text-secondary); margin-top: 4px; text-transform: uppercase; letter-spacing: .03em; }
.prices-main-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.prices-filters { padding: 16px 20px; border-bottom: 1px solid var(--border-light); background: var(--bg-muted); }
.prices-filter-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.prices-search-input {
  flex: 1; min-width: 200px;
  height: 34px; padding: 0 12px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  font-size: 13px; background: var(--bg-card); color: var(--text);
}
.prices-search-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.prices-filter-select {
  height: 34px; padding: 0 8px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  font-size: 13px; background: var(--bg-card); color: var(--text); cursor: pointer;
}
.prices-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 20px; border-bottom: 1px solid var(--border-light);
}
.prices-toolbar-left, .prices-toolbar-right { display: flex; gap: 8px; align-items: center; }
.prices-table-wrap { overflow-x: auto; }
.prices-table {
  width: 100%; border-collapse: collapse; font-size: 13px;
  min-width: 1200px;
}
.prices-th {
  padding: 10px 12px; text-align: left; font-weight: 600; font-size: 12px;
  color: var(--text-secondary); border-bottom: 2px solid var(--border);
  white-space: nowrap; background: var(--bg-muted); position: sticky; top: 0; z-index: 1;
}
.prices-th a { color: inherit; text-decoration: none; }
.prices-th a:hover { color: var(--accent); }
.prices-th-check { width: 36px; }
.prices-row:hover { background: var(--bg-hover); }
.prices-row.selected { background: var(--accent-bg); }
.prices-td {
  padding: 9px 12px; border-bottom: 1px solid var(--border-light);
  vertical-align: middle; white-space: nowrap;
}
.prices-td-check { width: 36px; padding: 9px 8px; }
.prices-article { font-family: var(--font-mono); font-size: 12px; color: var(--text-secondary); }
.prices-title { max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
.prices-price { font-weight: 600; text-align: right; }
.prices-mrc { color: var(--text-secondary); }
.prices-profit { color: var(--success); }
.prices-thumb { width: 40px; height: 40px; object-fit: cover; border-radius: 6px; }
.prices-thumb-placeholder { width: 40px; height: 40px; background: var(--bg-muted); border-radius: 6px; }
.price-indicator-ok { color: var(--success); }
.price-indicator-warn { color: var(--warning); }
.price-indicator-bad { color: var(--danger); font-weight: 700; }
.price-indicator-neutral { color: var(--text-secondary); }
.prices-empty { padding: 40px; text-align: center; color: var(--text-muted); font-size: 14px; }
.prices-pagination {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 20px; border-top: 1px solid var(--border-light);
}
.pagination-info { font-size: 13px; color: var(--text-secondary); }
.pagination-pages { display: flex; gap: 4px; flex-wrap: wrap; }
.pagination-item {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 32px; height: 32px; padding: 0 8px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  font-size: 13px; color: var(--text); text-decoration: none;
  transition: all var(--transition-fast);
}
.pagination-item:hover { border-color: var(--accent); color: var(--accent); }
.pagination-active { background: var(--accent); border-color: var(--accent); color: #fff !important; }
.badge-wb { background: var(--wb-soft); color: var(--wb); border: 1px solid var(--wb-border); }
.badge-ozon { background: var(--ozon-soft); color: var(--ozon); border: 1px solid var(--ozon-border); }
.prices-history-header { display: flex; justify-content: space-between; align-items: center; padding: 20px; border-bottom: 1px solid var(--border-light); }
.prices-history-header h2 { margin: 0; font-size: 1.1rem; }
.btn-xs { padding: 3px 10px; font-size: 12px; }
.btn-accent { background: var(--accent); color: #fff; border: none; cursor: pointer; border-radius: var(--radius-sm); transition: background var(--transition-fast); }
.btn-accent:hover { background: var(--accent-hover); }
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.45);
  z-index: 1000; display: flex; align-items: center; justify-content: center;
  padding: 20px;
}
.modal-overlay[hidden] { display: none; }
.modal-box {
  background: var(--bg-card); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg); width: 100%; max-width: 480px;
  max-height: 90vh; overflow-y: auto;
}
.modal-box-lg { max-width: 700px; }
.modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 20px 24px 16px; border-bottom: 1px solid var(--border-light);
}
.modal-title { margin: 0; font-size: 1.1rem; font-weight: 600; }
.modal-close { background: none; border: none; cursor: pointer; font-size: 18px; color: var(--text-muted); padding: 4px; border-radius: 4px; }
.modal-close:hover { color: var(--text); background: var(--bg-hover); }
.modal-form, .modal-body { padding: 20px 24px; }
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; padding: 16px 24px; border-top: 1px solid var(--border-light); }
.form-group { margin-bottom: 16px; }
.form-label { display: block; font-size: 13px; font-weight: 500; color: var(--text); margin-bottom: 6px; }
.form-input, .form-select {
  width: 100%; padding: 8px 12px; border: 1px solid var(--border);
  border-radius: var(--radius-sm); font-size: 13px; background: var(--bg-card); color: var(--text);
}
.form-input:focus, .form-select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
textarea.form-input { resize: vertical; }
.form-hint { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }
.prices-current-price { font-weight: 700; color: var(--accent); font-size: 15px; }
.required { color: var(--danger); }
.alert { padding: 12px 16px; border-radius: var(--radius-sm); font-size: 13px; margin-bottom: 16px; }
.alert-success { background: var(--success-soft); border: 1px solid var(--success-border); color: var(--success); }
.alert-danger { background: var(--danger-soft); border: 1px solid var(--danger-border); color: var(--danger); }
.text-success { color: var(--success); }
.text-danger { color: var(--danger); }
.mt-3 { margin-top: 16px; }
.mb-3 { margin-bottom: 16px; }
.prices-date { font-size: 11px; color: var(--text-secondary); white-space: nowrap; }
.analytics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}
.analytics-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 20px;
  box-shadow: var(--shadow-xs);
}
.analytics-card h3 { margin: 0 0 16px; font-size: 14px; color: var(--text-secondary); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
.analytics-chart-wrap { position: relative; height: 260px; }
</style>"""


def _prices_js() -> str:
    return """<script>
(function() {
  // ── Selection ──────────────────────────────────────────────────────────
  const checkAll = document.getElementById('check-all');
  const btnSelectAll = document.getElementById('btn-select-all');
  const btnBulkOpen = document.getElementById('btn-bulk-open');

  function getChecked() {
    return Array.from(document.querySelectorAll('.row-check:checked'));
  }
  function updateBulkBtn() {
    const checked = getChecked();
    if (btnBulkOpen) btnBulkOpen.disabled = checked.length === 0;
  }
  document.querySelectorAll('.row-check').forEach(cb => {
    cb.addEventListener('change', function() {
      if (this.closest('tr')) this.closest('tr').classList.toggle('selected', this.checked);
      updateBulkBtn();
    });
  });
  if (checkAll) {
    checkAll.addEventListener('change', function() {
      document.querySelectorAll('.row-check').forEach(cb => {
        cb.checked = this.checked;
        if (cb.closest('tr')) cb.closest('tr').classList.toggle('selected', this.checked);
      });
      updateBulkBtn();
    });
  }
  if (btnSelectAll) {
    btnSelectAll.addEventListener('click', function() {
      const allChecked = getChecked().length === document.querySelectorAll('.row-check').length;
      document.querySelectorAll('.row-check').forEach(cb => {
        cb.checked = !allChecked;
        if (cb.closest('tr')) cb.closest('tr').classList.toggle('selected', !allChecked);
      });
      if (checkAll) checkAll.checked = !allChecked;
      updateBulkBtn();
    });
  }

  // ── Modals ─────────────────────────────────────────────────────────────
  function openModal(id) {
    const m = document.getElementById(id);
    if (m) m.hidden = false;
  }
  function closeModal(id) {
    const m = document.getElementById(id);
    if (m) m.hidden = true;
  }
  document.querySelectorAll('[data-close]').forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.dataset.close));
  });
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', function(e) {
      if (e.target === this) closeModal(this.id);
    });
  });

  // ── Edit single ────────────────────────────────────────────────────────
  document.querySelectorAll('.prices-edit-btn').forEach(btn => {
    btn.addEventListener('click', function() {
      const mp = this.dataset.mp;
      document.getElementById('edit-product-id').value = this.dataset.productId;
      document.getElementById('edit-marketplace').value = mp;
      document.getElementById('edit-account-id').value = this.dataset.accountId;
      document.getElementById('edit-product-info').textContent =
        (this.dataset.article || this.dataset.productId) + (this.dataset.title ? ' — ' + this.dataset.title : '');
      const curPrice = (mp === 'WB' ? this.dataset.wbPrice : this.dataset.ozonPrice) || '';
      document.getElementById('edit-current-price').textContent = curPrice ? curPrice + ' ₽' : 'нет данных';
      document.getElementById('edit-new-price').value = curPrice;
      const hint = document.getElementById('edit-price-hint');
      const minP = parseFloat(this.dataset.minPrice), maxP = parseFloat(this.dataset.maxPrice);
      let hintTxt = '';
      if (minP) hintTxt += 'Мин: ' + minP + ' ₽  ';
      if (maxP) hintTxt += 'Макс: ' + maxP + ' ₽';
      hint.textContent = hintTxt;
      const discGroup = document.getElementById('edit-discount-group');
      if (discGroup) discGroup.hidden = mp !== 'WB';
      openModal('modal-edit');
    });
  });

  // ── Bulk modal ─────────────────────────────────────────────────────────
  if (btnBulkOpen) {
    btnBulkOpen.addEventListener('click', function() {
      const checked = getChecked();
      const infoEl = document.getElementById('bulk-selection-info');
      if (infoEl) infoEl.textContent = 'Выбрано товаров: ' + checked.length;
      openModal('modal-bulk');
    });
  }

  window.updateBulkHint = function() {
    const op = document.getElementById('bulk-operation')?.value;
    const label = document.getElementById('bulk-value-label');
    const hint = document.getElementById('bulk-hint');
    const roundGrp = document.getElementById('bulk-round-group');
    const hints = {
      'set': ['Установить цену (₽)', 'Новая единая цена для всех выбранных товаров'],
      'increase_percent': ['Процент увеличения (%)', 'Цена = текущая × (1 + X/100)'],
      'decrease_percent': ['Процент снижения (%)', 'Цена = текущая × (1 - X/100)'],
      'increase_fixed': ['Сумма увеличения (₽)', 'Цена = текущая + X'],
      'decrease_fixed': ['Сумма снижения (₽)', 'Цена = текущая − X'],
      'round': ['Шаг округления', 'Выберите шаг округления ниже'],
      'min_margin': ['Минимальная маржа (%)', 'Цена = себестоимость / (1 - X/100)'],
      'min_profit': ['Минимальная прибыль (₽)', 'Цена = себестоимость + X'],
    };
    if (label && hint) {
      const [l, h] = hints[op] || ['Значение', ''];
      label.textContent = l;
      hint.textContent = h;
    }
    if (roundGrp) roundGrp.hidden = op !== 'round';
  };
  updateBulkHint();

  const btnBulkPreview = document.getElementById('btn-bulk-preview');
  if (btnBulkPreview) {
    btnBulkPreview.addEventListener('click', function() {
      const checked = getChecked();
      if (!checked.length) { alert('Выберите товары'); return; }
      const ids = checked.map(cb => cb.value).join(',');
      const op = document.getElementById('bulk-operation')?.value;
      const val = document.getElementById('bulk-value')?.value;
      const rt = document.getElementById('bulk-round-to')?.value || '0';
      if (!val || isNaN(parseFloat(val))) { alert('Введите значение'); return; }
      const form = document.createElement('form');
      form.method = 'POST'; form.action = '/web/prices/bulk-preview';
      [['product_ids', ids], ['operation', op], ['value', val], ['round_to', rt]].forEach(([n, v]) => {
        const inp = document.createElement('input'); inp.type = 'hidden'; inp.name = n; inp.value = v;
        form.appendChild(inp);
      });
      document.body.appendChild(form);
      form.submit();
    });
  }
})();
</script>"""
