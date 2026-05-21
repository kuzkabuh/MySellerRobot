"""MRC (recommended retail price) management routes for web cabinet."""

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, Product, WbPromotion, WbPromotionNomenclature
from app.models.enums import Marketplace
from app.services.pricing.wb_mrc_price_service import WbMrcPriceService, WbMrcPriceResult
from app.services.web_auth_service import WebAuthService
from app.web.dependencies import (
    CURRENT_WEB_USER_DEPENDENCY,
    SESSION_DEPENDENCY,
    WEB_DASHBOARD_PATH,
)
from app.web.rendering import page

logger = logging.getLogger(__name__)
router = APIRouter()


@dataclass(slots=True)
class MrcProductRow:
    product: Product
    account_name: str
    mrc_result: WbMrcPriceResult | None
    has_active_promo: bool
    promo_name: str | None
    promo_plan_price: Decimal | None
    promo_end_date: str | None


@dataclass(slots=True)
class MrcPageData:
    rows: list[MrcProductRow]
    total_products: int
    products_with_mrc: int
    products_without_mrc: int
    products_with_promo: int
    last_sync_status: str


@router.get("/mrc-pricing", response_class=HTMLResponse)
async def mrc_pricing_page(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    account_id: int | None = Query(None),
) -> str:
    """MRC pricing management page."""
    data = await _load_mrc_page_data(session, user.id, account_id)
    return page(
        "МРЦ WB — Управление ценами",
        user.first_name or user.username or str(user.telegram_id),
        _mrc_pricing_content(data, user.timezone),
        active_path="/web/mrc-pricing",
    )


@router.post("/mrc-pricing/{product_id}")
async def save_mrc_price(
    product_id: int,
    request: Request,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Save MRC price for a product."""
    form = await _urlencoded_form(request)
    mrc_value = _form_value(form, "mrc_price", "").strip()

    product = await session.get(Product, product_id)
    if product is None or product.user_id != user.id:
        raise HTTPException(status_code=404, detail="Товар не найден")

    if product.marketplace != Marketplace.WB:
        raise HTTPException(status_code=400, detail="МРЦ поддерживается только для Wildberries")

    if mrc_value:
        try:
            mrc_decimal = Decimal(mrc_value.replace(",", "."))
            if mrc_decimal <= 0:
                raise ValueError
            product.mrc_price = mrc_decimal.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            raise HTTPException(
                status_code=400,
                detail="МРЦ должна быть положительным числом",
            ) from None
    else:
        product.mrc_price = None

    await session.commit()
    return RedirectResponse(url="/web/mrc-pricing?saved=1", status_code=303)


@router.post("/mrc-pricing/sync-promotions")
async def trigger_promotions_sync(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Manually trigger WB promotions sync."""
    from app.core.security import TokenCipher
    from app.services.wb.wb_promotions_sync_service import WbPromotionsSyncService

    service = WbPromotionsSyncService(session, cipher=TokenCipher())
    try:
        stats = await service.sync_all_accounts()
        await session.commit()
        return RedirectResponse(
            url=f"/web/mrc-pricing?sync_done=1&promos={stats.promotions_upserted}&nomenclatures={stats.nomenclatures_upserted}",
            status_code=303,
        )
    except Exception:
        logger.exception("wb_promotions_manual_sync_failed")
        await session.rollback()
        return RedirectResponse(
            url="/web/mrc-pricing?sync_error=1",
            status_code=303,
        )


async def _load_mrc_page_data(
    session: AsyncSession,
    user_id: int,
    account_id: int | None = None,
) -> MrcPageData:
    """Load MRC pricing page data."""
    query = (
        select(Product, MarketplaceAccount.name)
        .join(MarketplaceAccount, MarketplaceAccount.id == Product.marketplace_account_id)
        .where(Product.user_id == user_id)
        .where(Product.marketplace == Marketplace.WB)
        .where(Product.is_active.is_(True))
        .order_by(Product.seller_article)
        .limit(500)
    )
    if account_id is not None:
        query = query.where(Product.marketplace_account_id == account_id)

    result = await session.execute(query)
    product_rows = result.all()

    mrc_service = WbMrcPriceService()
    rows = []
    products_with_promo = 0

    for product, account_name in product_rows:
        mrc_result = None
        has_active_promo = False
        promo_name = None
        promo_plan_price = None
        promo_end_date = None

        if product.mrc_price and product.mrc_price > 0:
            # Get actual promo for this product
            wb_nm_id = _extract_nm_id(product)
            promo_nomenclature = None
            if wb_nm_id:
                promo_nomenclature = await _get_actual_promo(
                    session, product.marketplace_account_id, wb_nm_id
                )

            promo_required_price = None
            if promo_nomenclature and promo_nomenclature.plan_price:
                promo_required_price = promo_nomenclature.plan_price
                has_active_promo = True
                promo_plan_price = promo_nomenclature.plan_price
                products_with_promo += 1

                # Get promotion name
                promo_result = await session.execute(
                    select(WbPromotion.name, WbPromotion.end_datetime).where(
                        WbPromotion.marketplace_account_id == product.marketplace_account_id,
                        WbPromotion.wb_promotion_id == promo_nomenclature.wb_promotion_id,
                    )
                )
                promo_row = promo_result.one_or_none()
                if promo_row:
                    promo_name = promo_row[0]
                    if promo_row[1]:
                        promo_end_date = promo_row[1].strftime("%d.%m.%Y")

            try:
                mrc_result = mrc_service.calculate(
                    mrc_price=product.mrc_price,
                    promo_required_price=promo_required_price,
                    min_price=None,
                )
            except Exception:
                logger.exception("mrc_calculation_failed", extra={"product_id": product.id})

        rows.append(
            MrcProductRow(
                product=product,
                account_name=str(account_name),
                mrc_result=mrc_result,
                has_active_promo=has_active_promo,
                promo_name=promo_name,
                promo_plan_price=promo_plan_price,
                promo_end_date=promo_end_date,
            )
        )

    total = len(rows)
    with_mrc = sum(1 for r in rows if r.product.mrc_price and r.product.mrc_price > 0)

    return MrcPageData(
        rows=rows,
        total_products=total,
        products_with_mrc=with_mrc,
        products_without_mrc=total - with_mrc,
        products_with_promo=products_with_promo,
        last_sync_status="ok",
    )


async def _get_actual_promo(
    session: AsyncSession,
    marketplace_account_id: int,
    wb_nm_id: int,
) -> WbPromotionNomenclature | None:
    """Get the best active promo for a product."""
    from datetime import UTC, datetime

    now_utc = datetime.now(tz=UTC)

    result = await session.execute(
        select(WbPromotionNomenclature)
        .join(
            WbPromotion,
            (WbPromotion.wb_promotion_id == WbPromotionNomenclature.wb_promotion_id)
            & (WbPromotion.marketplace_account_id == WbPromotionNomenclature.marketplace_account_id),
        )
        .where(
            WbPromotionNomenclature.marketplace_account_id == marketplace_account_id,
            WbPromotionNomenclature.wb_nm_id == wb_nm_id,
            WbPromotion.is_active_today.is_(True),
            WbPromotion.start_datetime <= now_utc,
            WbPromotion.end_datetime >= now_utc,
            WbPromotionNomenclature.plan_price.isnot(None),
            WbPromotionNomenclature.plan_price > 0,
        )
        .order_by(
            WbPromotionNomenclature.plan_price.asc(),
            WbPromotion.end_datetime.asc(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


def _extract_nm_id(product: Product) -> int | None:
    """Extract WB nmID from product."""
    if product.marketplace_article and product.marketplace_article.isdigit():
        return int(product.marketplace_article)
    if product.external_product_id and product.external_product_id.isdigit():
        return int(product.external_product_id)
    return None


def _mrc_pricing_content(data: MrcPageData, timezone: str = "Europe/Moscow") -> str:
    """Render MRC pricing page content."""
    from html import escape

    html_parts = []

    # Header with stats
    html_parts.append('<div class="card">')
    html_parts.append("<h2>Управление МРЦ Wildberries</h2>")
    html_parts.append(
        '<p class="text-muted" style="margin-bottom:16px">'
        "МРЦ — это целевая цена со скидкой на Wildberries. "
        "Цена продавца до скидки будет рассчитана автоматически как МРЦ × 4."
        "</p>"
    )

    # Stats bar
    html_parts.append('<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:20px">')
    html_parts.append(
        f'<div class="kpi-card"><div class="kpi-value">{data.total_products}</div>'
        '<div class="kpi-label">Всего товаров WB</div></div>'
    )
    html_parts.append(
        f'<div class="kpi-card"><div class="kpi-value">{data.products_with_mrc}</div>'
        '<div class="kpi-label">С заполненной МРЦ</div></div>'
    )
    html_parts.append(
        f'<div class="kpi-card"><div class="kpi-value">{data.products_without_mrc}</div>'
        '<div class="kpi-label">Без МРЦ</div></div>'
    )
    html_parts.append(
        f'<div class="kpi-card"><div class="kpi-value">{data.products_with_promo}</div>'
        '<div class="kpi-label">Участвуют в акциях</div></div>'
    )
    html_parts.append("</div>")

    # Sync button
    html_parts.append(
        '<form method="post" action="/web/mrc-pricing/sync-promotions" style="margin-bottom:20px">'
        '<button type="submit" class="btn btn-secondary">🔄 Синхронизировать акции WB</button>'
        "</form>"
    )

    # Products table
    if not data.rows:
        html_parts.append('<p class="text-muted">Товары Wildberries не найдены.</p>')
    else:
        html_parts.append('<div class="table-wrap">')
        html_parts.append("<table>")
        html_parts.append("<thead><tr>")
        html_parts.append("<th>Товар</th>")
        html_parts.append("<th>Артикул</th>")
        html_parts.append("<th>nmID</th>")
        html_parts.append("<th>МРЦ</th>")
        html_parts.append("<th>Цена со скидкой</th>")
        html_parts.append("<th>Цена до скидки</th>")
        html_parts.append("<th>Акция WB</th>")
        html_parts.append("<th>Статус</th>")
        html_parts.append("<th>Действие</th>")
        html_parts.append("</tr></thead>")
        html_parts.append("<tbody>")

        for row in data.rows:
            product = row.product
            nm_id = _extract_nm_id(product)
            article = escape(product.seller_article or "—")
            title = escape(product.title or "—")[:60]

            html_parts.append("<tr>")
            html_parts.append(f"<td>{title}</td>")
            html_parts.append(f"<td>{article}</td>")
            html_parts.append(f"<td>{nm_id or '—'}</td>")

            # MRC edit form
            mrc_value = str(product.mrc_price) if product.mrc_price else ""
            html_parts.append(
                f'<td><form method="post" action="/web/mrc-pricing/{product.id}" '
                'style="display:flex;gap:4px;align-items:center">'
                f'<input type="text" name="mrc_price" value="{mrc_value}" '
                'placeholder="—" style="width:80px;padding:4px 8px;border:1px solid var(--color-border);border-radius:6px">'
                '<button type="submit" class="btn btn-sm btn-primary">💾</button>'
                "</form></td>"
            )

            # Calculated prices
            if row.mrc_result:
                html_parts.append(f"<td>{row.mrc_result.final_discounted_price:.0f} ₽</td>")
                html_parts.append(f"<td>{row.mrc_result.price_before_discount:.0f} ₽</td>")
            else:
                html_parts.append("<td>—</td>")
                html_parts.append("<td>—</td>")

            # Promo info
            if row.has_active_promo:
                promo_name = escape(row.promo_name or "Акция WB")
                promo_price = f"{row.promo_plan_price:.0f}" if row.promo_plan_price else "—"
                promo_end = escape(row.promo_end_date or "")
                html_parts.append(
                    f"<td>{promo_name}<br><small>{promo_price} ₽"
                    f"{' до ' + promo_end if promo_end else ''}</small></td>"
                )
            else:
                html_parts.append("<td><small class='text-muted'>Нет акции</small></td>")

            # Status
            if row.mrc_result:
                if row.mrc_result.is_limited_by_min_price:
                    html_parts.append(
                        '<td><span class="badge badge-warning">⚠️ Ограничено minPrice</span></td>'
                    )
                elif row.mrc_result.is_limited_by_mrc_rule:
                    html_parts.append(
                        '<td><span class="badge badge-warning">⚠️ Ограничено 10% от МРЦ</span></td>'
                    )
                elif row.mrc_result.is_promo_applied:
                    html_parts.append(
                        '<td><span class="badge badge-success">✅ Акция применена</span></td>'
                    )
                else:
                    html_parts.append(
                        '<td><span class="badge badge-info">ℹ️ Цена = МРЦ</span></td>'
                    )
            else:
                if product.mrc_price and product.mrc_price > 0:
                    html_parts.append(
                        '<td><span class="badge badge-info">ℹ️ МРЦ задана</span></td>'
                    )
                else:
                    html_parts.append(
                        '<td><span class="badge badge-muted">— Без МРЦ</span></td>'
                    )

            # Warning message
            if row.mrc_result and (
                row.mrc_result.is_limited_by_mrc_rule
                or row.mrc_result.is_limited_by_min_price
            ):
                reason = escape(row.mrc_result.reason)
                html_parts.append(
                    f'<td colspan="2"><small class="text-warning">{reason}</small></td>'
                )
            else:
                html_parts.append("<td></td>")

            html_parts.append("</tr>")

        html_parts.append("</tbody></table>")
        html_parts.append("</div>")

    html_parts.append("</div>")

    # Help section
    html_parts.append('<div class="card" style="margin-top:16px">')
    html_parts.append("<h3>Как работает расчёт МРЦ</h3>")
    html_parts.append("<ul>")
    html_parts.append(
        "<li><b>МРЦ</b> — целевая цена продажи со скидкой на Wildberries.</li>"
    )
    html_parts.append(
        "<li><b>Цена до скидки</b> = МРЦ × 4. WB показывает скидку 75% от этой цены.</li>"
    )
    html_parts.append(
        "<li><b>Без акции</b>: цена со скидкой = МРЦ, цена до скидки = МРЦ × 4.</li>"
    )
    html_parts.append(
        "<li><b>С акцией</b>: если цена акции (planPrice) в пределах 10% от МРЦ, "
        "используется цена акции. Иначе — минимально допустимая цена (МРЦ − 10%, округление вверх).</li>"
    )
    html_parts.append(
        "<li><b>minPrice</b>: рассчитанная цена не может быть ниже minPrice товара.</li>"
    )
    html_parts.append("</ul>")
    html_parts.append("</div>")

    return "\n".join(html_parts)


async def _urlencoded_form(request: Request) -> dict[str, list[str]]:
    body = await request.body()
    text = body.decode("utf-8")
    from urllib.parse import parse_qs

    return parse_qs(text)


def _form_value(form: dict[str, list[str]], key: str, default: str) -> str:
    values = form.get(key)
    if not values:
        return default
    return values[0]
