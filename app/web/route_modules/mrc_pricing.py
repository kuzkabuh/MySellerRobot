"""MRC (recommended retail price) management routes for web cabinet.

Full-featured MRC pricing management with:
- Product table with inline MRC editing
- Filters (with MRC, without MRC, with promo, limited, etc.)
- Search by article, nmID, title
- Bulk MRC update
- Promotions list and detail
- Manual sync trigger
- Feature gating by subscription tier
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import Integer, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, Product, WbPromotion, WbPromotionNomenclature
from app.models.enums import Marketplace
from app.services.feature_access_service import FeatureAccessService, FeatureCode
from app.services.pricing.wb_mrc_price_service import WbMrcPriceResult, WbMrcPriceService
from app.services.wb.wb_promotions_sync_service import WbPromotionsSyncService
from app.utils.datetime import format_datetime_for_user
from app.web.dependencies import (
    CURRENT_WEB_USER_DEPENDENCY,
    SESSION_DEPENDENCY,
)
from app.web.rendering import page as render_page

logger = logging.getLogger(__name__)
router = APIRouter()

PAGE_SIZE = 50


@dataclass(slots=True)
class MrcProductRow:
    product: Product
    account_name: str
    mrc_result: WbMrcPriceResult | None
    has_active_promo: bool
    promo_name: str | None
    promo_plan_price: Decimal | None
    promo_end_date: str | None
    promo_in_action: bool | None


@dataclass(slots=True)
class MrcPageData:
    rows: list[MrcProductRow]
    total_products: int
    products_with_mrc: int
    products_without_mrc: int
    products_with_promo: int
    products_limited_by_mrc: int
    products_limited_by_min: int
    page: int
    page_size: int
    total_pages: int
    filters: dict[str, str]
    last_sync_status: str
    last_sync_time: str | None
    last_sync_error: str | None


@dataclass(slots=True)
class PromoRow:
    promotion: WbPromotion
    total_items: int
    items_in_action: int
    items_not_in_action: int
    matched_products: int


@dataclass(slots=True)
class PromoDetailData:
    promotion: WbPromotion
    rows: list[dict[str, Any]]
    total_items: int
    page: int
    page_size: int
    total_pages: int


@router.get("/mrc-pricing", response_class=HTMLResponse)
async def mrc_pricing_page(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    page_number: int = Query(1, ge=1),
    filter_type: str = Query("all"),
    search: str = Query(""),
) -> str:
    """MRC pricing management page."""
    try:
        access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.MRC_PRICING)
        if not access.allowed:
            return render_page(
                "МРЦ WB — Управление ценами",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        data = await _load_mrc_page_data(session, user.id, page_number, filter_type, search)

        # Resolve actual tier code for logging
        tier_code = access.current_tier
        if not tier_code:
            tier_code = await _resolve_user_tier_code(session, user.id)

        logger.info(
            "mrc_pricing_page_opened",
            extra={
                "user_id": user.id,
                "tier_code": tier_code,
                "products_count": data.total_products,
                "products_with_mrc_count": data.products_with_mrc,
                "active_promotions_count": data.products_with_promo,
                "last_promotions_sync_at": data.last_sync_time,
                "render_mode": "server",
                "source": "web",
            },
        )

        return render_page(
            "МРЦ WB — Управление ценами",
            user.first_name or user.username or str(user.telegram_id),
            _mrc_pricing_content(data, user.timezone),
            active_path="/web/mrc-pricing",
        )
    except Exception:
        logger.exception("mrc_pricing_page_failed", extra={"user_id": user.id})
        return render_page(
            "Ошибка — МРЦ WB",
            user.first_name or user.username or str(user.telegram_id),
            '<div class="card"><h2>Не удалось загрузить раздел МРЦ</h2>'
            '<p>Ошибка уже записана в лог. Попробуйте обновить страницу позже.</p>'
            '<p><a href="/web/" class="button primary">Вернуться на главную</a></p></div>',
            active_path="/web/mrc-pricing",
        )


async def _resolve_user_tier_code(session: AsyncSession, user_id: int) -> str:
    """Resolve the actual tier code for a user for logging purposes."""
    from datetime import UTC, datetime
    from app.models.subscriptions import SubscriptionTier, UserSubscription

    now = datetime.now(tz=UTC)
    result = await session.execute(
        select(SubscriptionTier.code)
        .join(UserSubscription, UserSubscription.tier_id == SubscriptionTier.id)
        .where(UserSubscription.user_id == user_id)
        .where(UserSubscription.status.in_(["ACTIVE", "TRIAL"]))
        .where((UserSubscription.expires_at.is_(None)) | (UserSubscription.expires_at > now))
        .where(SubscriptionTier.is_active.is_(True))
        .order_by(UserSubscription.started_at.desc())
        .limit(1)
    )
    code = result.scalar_one_or_none()
    if code:
        return str(code).strip().lower()
    return "free"


@router.post("/mrc-pricing/products/{product_id}")
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

    old_mrc = product.mrc_price
    if mrc_value:
        try:
            mrc_decimal = Decimal(mrc_value.replace(",", "."))
            if mrc_decimal <= 0:
                raise ValueError
            product.mrc_price = mrc_decimal.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return RedirectResponse(
                url=f"/web/mrc-pricing?error=invalid_mrc&product_id={product_id}",
                status_code=303,
            )
    else:
        product.mrc_price = None

    logger.info(
        "mrc_price_updated",
        extra={
            "user_id": user.id,
            "product_id": product_id,
            "wb_nm_id": _extract_nm_id(product),
            "old_mrc_price": str(old_mrc),
            "new_mrc_price": str(product.mrc_price),
            "source": "web",
        },
    )

    await session.commit()
    return RedirectResponse(url=f"/web/mrc-pricing?mrc_saved=1&product_id={product_id}", status_code=303)


@router.post("/mrc-pricing/products/{product_id}/clear")
async def clear_mrc_price(
    product_id: int,
    request: Request,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Clear MRC price for a product."""
    product = await session.get(Product, product_id)
    if product is None or product.user_id != user.id:
        raise HTTPException(status_code=404, detail="Товар не найден")

    old_mrc = product.mrc_price
    product.mrc_price = None

    logger.info(
        "mrc_price_cleared",
        extra={
            "user_id": user.id,
            "product_id": product_id,
            "wb_nm_id": _extract_nm_id(product),
            "old_mrc_price": str(old_mrc),
            "source": "web",
        },
    )

    await session.commit()
    return RedirectResponse(url="/web/mrc-pricing?saved=1", status_code=303)


@router.post("/mrc-pricing/bulk-update")
async def bulk_update_mrc(
    request: Request,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Bulk update MRC for selected products."""
    form = await _urlencoded_form(request)
    product_ids = form.get("product_ids", [])
    mrc_value = _form_value(form, "bulk_mrc", "").strip()
    action = _form_value(form, "bulk_action", "")

    if not product_ids:
        return RedirectResponse(url="/web/mrc-pricing?error=no_products_selected", status_code=303)

    if action == "clear":
        for pid in product_ids:
            try:
                product = await session.get(Product, int(pid))
                if product and product.user_id == user.id and product.marketplace == Marketplace.WB:
                    product.mrc_price = None
            except (ValueError, TypeError):
                continue
        await session.commit()
        return RedirectResponse(url="/web/mrc-pricing?saved=1&bulk=cleared", status_code=303)

    if not mrc_value:
        return RedirectResponse(url="/web/mrc-pricing?error=invalid_mrc", status_code=303)

    try:
        mrc_decimal = Decimal(mrc_value.replace(",", "."))
        if mrc_decimal <= 0:
            raise ValueError
        mrc_decimal = mrc_decimal.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return RedirectResponse(url="/web/mrc-pricing?error=invalid_mrc", status_code=303)

    updated = 0
    for pid in product_ids:
        try:
            product = await session.get(Product, int(pid))
            if product and product.user_id == user.id and product.marketplace == Marketplace.WB:
                product.mrc_price = mrc_decimal
                updated += 1
        except (ValueError, TypeError):
            continue

    await session.commit()
    return RedirectResponse(url=f"/web/mrc-pricing?saved=1&bulk={updated}", status_code=303)


@router.post("/mrc-pricing/sync-promotions")
async def trigger_promotions_sync(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Manually trigger WB promotions sync (allPromo=false)."""
    service = WbPromotionsSyncService(session)
    try:
        stats = await service.sync_all_accounts(all_promo=False)
        await session.commit()
        return RedirectResponse(
            url=(
                f"/web/mrc-pricing?sync_done=1&promos={stats.promotions_upserted}"
                f"&nomenclatures={stats.nomenclatures_upserted}"
                f"&raw_promos={stats.promotions_fetched}&all_promo=false"
                f"&auto_skipped={stats.promotions_skipped_auto}"
            ),
            status_code=303,
        )
    except Exception:
        logger.exception("wb_promotions_manual_sync_failed")
        await session.rollback()
        return RedirectResponse(url="/web/mrc-pricing?sync_error=1", status_code=303)


@router.post("/mrc-pricing/sync-promotions-all")
async def trigger_promotions_sync_all(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Manually trigger WB promotions sync (allPromo=true)."""
    service = WbPromotionsSyncService(session)
    try:
        stats = await service.sync_all_accounts(all_promo=True)
        await session.commit()
        return RedirectResponse(
            url=(
                f"/web/mrc-pricing?sync_done=1&promos={stats.promotions_upserted}"
                f"&nomenclatures={stats.nomenclatures_upserted}"
                f"&raw_promos={stats.promotions_fetched}&all_promo=true"
                f"&auto_skipped={stats.promotions_skipped_auto}"
            ),
            status_code=303,
        )
    except Exception:
        logger.exception("wb_promotions_manual_sync_all_failed")
        await session.rollback()
        return RedirectResponse(url="/web/mrc-pricing?sync_error=1", status_code=303)


@router.get("/mrc-pricing/export")
async def export_mrc_report(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Export MRC report (placeholder — redirects back with notice)."""
    return RedirectResponse(url="/web/mrc-pricing?export_coming_soon=1", status_code=303)


@router.get("/wb-promotions", response_class=HTMLResponse)
async def wb_promotions_page(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    """List of WB promotions for today."""
    access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.MRC_PRICING)
    if not access.allowed:
        return render_page(
            "Акции WB",
            user.first_name or user.username or str(user.telegram_id),
            _feature_locked_content(access),
            active_path="/web/wb-promotions",
        )

    data = await _load_promotions_page_data(session, user.id)
    return render_page(
        "Акции Wildberries",
        user.first_name or user.username or str(user.telegram_id),
        _wb_promotions_content(data, user.timezone),
        active_path="/web/wb-promotions",
    )


@router.get("/wb-promotions/{promotion_id}", response_class=HTMLResponse)
async def wb_promotion_detail_page(
    promotion_id: int,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    page_number: int = Query(1, ge=1),
    filter_type: str = Query("all"),
) -> str:
    """Detail page for a WB promotion with products."""
    access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.MRC_PRICING)
    if not access.allowed:
        return render_page(
            "Акция WB",
            user.first_name or user.username or str(user.telegram_id),
            _feature_locked_content(access),
            active_path="/web/wb-promotions",
        )

    data = await _load_promotion_detail_data(session, user.id, promotion_id, page_number, filter_type)
    if data is None:
        raise HTTPException(status_code=404, detail="Акция не найдена")

    return render_page(
        f"Акция: {data.promotion.name or 'Без названия'}",
        user.first_name or user.username or str(user.telegram_id),
        _wb_promotion_detail_content(data, user.timezone),
        active_path="/web/wb-promotions",
    )


async def _load_mrc_page_data(
    session: AsyncSession,
    user_id: int,
    page_num: int,
    filter_type: str,
    search: str,
) -> MrcPageData:
    """Load MRC pricing page data with filters and pagination.

    Uses batch queries for promo lookups to avoid N+1 problem.
    """
    from datetime import UTC, datetime

    now_utc = datetime.now(tz=UTC)
    mrc_service = WbMrcPriceService()

    # Base query
    base_query = (
        select(Product, MarketplaceAccount.name)
        .join(MarketplaceAccount, MarketplaceAccount.id == Product.marketplace_account_id)
        .where(Product.user_id == user_id)
        .where(Product.marketplace == Marketplace.WB)
        .where(Product.is_active.is_(True))
    )

    # Apply filters
    if filter_type == "with_mrc":
        base_query = base_query.where(Product.mrc_price.isnot(None)).where(Product.mrc_price > 0)
    elif filter_type == "without_mrc":
        base_query = base_query.where(
            (Product.mrc_price.is_(None)) | (Product.mrc_price <= 0)
        )

    # Search
    if search.strip():
        pattern = f"%{search.strip()}%"
        base_query = base_query.where(
            or_(
                Product.seller_article.ilike(pattern),
                Product.marketplace_article.ilike(pattern),
                Product.external_product_id.ilike(pattern),
                Product.title.ilike(pattern),
            )
        )

    # Total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await session.execute(count_query)
    total = int(total_result.scalar_one() or 0)

    # Pagination
    offset = (page_num - 1) * PAGE_SIZE
    query = base_query.order_by(Product.seller_article).offset(offset).limit(PAGE_SIZE)
    result = await session.execute(query)
    product_rows = result.all()

    # Batch promo lookup: collect all (account_id, nm_id) pairs
    nm_ids_to_lookup: list[tuple[int, int]] = []
    product_nm_map: dict[int, tuple[int, int]] = {}
    for product, _ in product_rows:
        if product.mrc_price and product.mrc_price > 0:
            wb_nm_id = _extract_nm_id(product)
            if wb_nm_id:
                key = (product.marketplace_account_id, wb_nm_id)
                product_nm_map[product.id] = key
                if key not in nm_ids_to_lookup:
                    nm_ids_to_lookup.append(key)

    # Single batch query for all promo nomenclatures
    promo_map: dict[tuple[int, int], WbPromotionNomenclature] = {}
    if nm_ids_to_lookup:
        conditions = [
            (WbPromotionNomenclature.marketplace_account_id == acct_id)
            & (WbPromotionNomenclature.wb_nm_id == nm_id)
            for acct_id, nm_id in nm_ids_to_lookup
        ]
        nomenclature_query = (
            select(WbPromotionNomenclature, WbPromotion.name, WbPromotion.end_datetime)
            .join(
                WbPromotion,
                (WbPromotion.wb_promotion_id == WbPromotionNomenclature.wb_promotion_id)
                & (WbPromotion.marketplace_account_id == WbPromotionNomenclature.marketplace_account_id),
            )
            .where(
                or_(*conditions),
                WbPromotion.is_active_today.is_(True),
                WbPromotion.start_datetime <= now_utc,
                WbPromotion.end_datetime >= now_utc,
                WbPromotionNomenclature.plan_price.isnot(None),
                WbPromotionNomenclature.plan_price > 0,
            )
            .order_by(
                WbPromotionNomenclature.marketplace_account_id,
                WbPromotionNomenclature.wb_nm_id,
                WbPromotionNomenclature.plan_price.asc(),
                WbPromotion.end_datetime.asc(),
            )
        )
        nomenclature_result = await session.execute(nomenclature_query)
        for nom, promo_name, promo_end in nomenclature_result.all():
            key = (nom.marketplace_account_id, nom.wb_nm_id)
            if key not in promo_map:
                promo_map[key] = (nom, promo_name, promo_end)

    # Enrich with MRC calculation and promo data
    rows = []
    products_with_promo = 0
    products_limited_by_mrc = 0
    products_limited_by_min = 0

    for product, account_name in product_rows:
        mrc_result = None
        has_active_promo = False
        promo_name = None
        promo_plan_price = None
        promo_end_date = None
        promo_in_action = None

        if product.mrc_price and product.mrc_price > 0:
            promo_data = product_nm_map.get(product.id)
            promo_nomenclature = None
            if promo_data and promo_data in promo_map:
                promo_nomenclature, promo_name, promo_end_dt = promo_map[promo_data]

            promo_required_price = None
            if promo_nomenclature and promo_nomenclature.plan_price:
                promo_required_price = promo_nomenclature.plan_price
                has_active_promo = True
                promo_plan_price = promo_nomenclature.plan_price
                promo_in_action = promo_nomenclature.in_action
                products_with_promo += 1
                if promo_end_dt:
                    promo_end_date = promo_end_dt.strftime("%d.%m.%Y")

            try:
                mrc_result = mrc_service.calculate(
                    mrc_price=product.mrc_price,
                    promo_required_price=promo_required_price,
                )
                if mrc_result.is_limited_by_mrc_rule:
                    products_limited_by_mrc += 1
                elif mrc_result.is_limited_by_min_price:
                    products_limited_by_min += 1
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
                promo_in_action=promo_in_action,
            )
        )

    # Stats
    all_products_result = await session.execute(
        select(Product.mrc_price)
        .where(Product.user_id == user_id)
        .where(Product.marketplace == Marketplace.WB)
        .where(Product.is_active.is_(True))
    )
    all_products = all_products_result.scalars().all()
    products_with_mrc = sum(1 for mrc in all_products if mrc and mrc > 0)
    products_without_mrc = len(all_products) - products_with_mrc

    # Last sync status
    last_sync_result = await session.execute(
        select(WbPromotion.synced_at)
        .join(MarketplaceAccount, MarketplaceAccount.id == WbPromotion.marketplace_account_id)
        .where(MarketplaceAccount.user_id == user_id)
        .where(WbPromotion.synced_at.isnot(None))
        .order_by(WbPromotion.synced_at.desc())
        .limit(1)
    )
    last_sync = last_sync_result.scalar_one_or_none()
    last_sync_time = format_datetime_for_user(last_sync, "Europe/Moscow") if last_sync else None

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return MrcPageData(
        rows=rows,
        total_products=len(all_products),
        products_with_mrc=products_with_mrc,
        products_without_mrc=products_without_mrc,
        products_with_promo=products_with_promo,
        products_limited_by_mrc=products_limited_by_mrc,
        products_limited_by_min=products_limited_by_min,
        page=page_num,
        page_size=PAGE_SIZE,
        total_pages=total_pages,
        filters={"filter_type": filter_type, "search": search},
        last_sync_status="ok",
        last_sync_time=last_sync_time,
        last_sync_error=None,
    )


async def _load_promotions_page_data(
    session: AsyncSession,
    user_id: int,
) -> dict[str, Any]:
    """Load promotions list page data."""
    from datetime import UTC, datetime

    now_utc = datetime.now(tz=UTC)

    result = await session.execute(
        select(WbPromotion, MarketplaceAccount.name)
        .join(MarketplaceAccount, MarketplaceAccount.id == WbPromotion.marketplace_account_id)
        .where(MarketplaceAccount.user_id == user_id)
        .where(WbPromotion.is_active_today.is_(True))
        .where(WbPromotion.start_datetime <= now_utc)
        .where(WbPromotion.end_datetime >= now_utc)
        .order_by(WbPromotion.start_datetime)
    )
    promo_rows = result.all()

    promo_data = []
    for promo, account_name in promo_rows:
        items_result = await session.execute(
            select(
                func.count(WbPromotionNomenclature.id),
                func.sum(func.cast(WbPromotionNomenclature.in_action, Integer)),
            ).where(
                WbPromotionNomenclature.marketplace_account_id == promo.marketplace_account_id,
                WbPromotionNomenclature.wb_promotion_id == promo.wb_promotion_id,
            )
        )
        total_items, in_action_count = items_result.one()
        in_action_count = in_action_count or 0

        matched_result = await session.execute(
            select(func.count(Product.id)).where(
                Product.user_id == user_id,
                Product.marketplace == Marketplace.WB,
                Product.is_active.is_(True),
                Product.marketplace_account_id == promo.marketplace_account_id,
                or_(
                    Product.marketplace_article.in_(
                        select(WbPromotionNomenclature.wb_nm_id).where(
                            WbPromotionNomenclature.marketplace_account_id == promo.marketplace_account_id,
                            WbPromotionNomenclature.wb_promotion_id == promo.wb_promotion_id,
                        )
                    ),
                    Product.external_product_id.in_(
                        select(WbPromotionNomenclature.wb_nm_id).where(
                            WbPromotionNomenclature.marketplace_account_id == promo.marketplace_account_id,
                            WbPromotionNomenclature.wb_promotion_id == promo.wb_promotion_id,
                        )
                    ),
                ),
            )
        )
        matched_count = int(matched_result.scalar_one() or 0)

        promo_data.append({
            "promotion": promo,
            "account_name": account_name,
            "total_items": total_items or 0,
            "items_in_action": in_action_count,
            "items_not_in_action": (total_items or 0) - in_action_count,
            "matched_products": matched_count,
        })

    last_sync_result = await session.execute(
        select(WbPromotion.synced_at)
        .join(MarketplaceAccount, MarketplaceAccount.id == WbPromotion.marketplace_account_id)
        .where(MarketplaceAccount.user_id == user_id)
        .where(WbPromotion.synced_at.isnot(None))
        .order_by(WbPromotion.synced_at.desc())
        .limit(1)
    )
    last_sync = last_sync_result.scalar_one_or_none()

    return {
        "promotions": promo_data,
        "last_sync_time": format_datetime_for_user(last_sync, "Europe/Moscow") if last_sync else None,
    }


async def _load_promotion_detail_data(
    session: AsyncSession,
    user_id: int,
    promotion_id: int,
    page_num: int,
    filter_type: str,
) -> PromoDetailData | None:
    """Load promotion detail with products."""
    promo_result = await session.execute(
        select(WbPromotion).where(WbPromotion.wb_promotion_id == promotion_id)
    )
    promotion = promo_result.scalar_one_or_none()
    if promotion is None:
        return None

    # Build query for nomenclatures
    base_query = (
        select(WbPromotionNomenclature)
        .where(WbPromotionNomenclature.wb_promotion_id == promotion_id)
    )

    if filter_type == "in_action":
        base_query = base_query.where(WbPromotionNomenclature.in_action.is_(True))
    elif filter_type == "not_in_action":
        base_query = base_query.where(WbPromotionNomenclature.in_action.is_(False))
    elif filter_type == "matched":
        base_query = base_query.where(
            WbPromotionNomenclature.wb_nm_id.in_(
                select(Product.marketplace_article).where(
                    Product.user_id == user_id,
                    Product.marketplace == Marketplace.WB,
                    Product.is_active.is_(True),
                    Product.marketplace_account_id == promotion.marketplace_account_id,
                    Product.marketplace_article.isnot(None),
                )
            )
            | WbPromotionNomenclature.wb_nm_id.in_(
                select(Product.external_product_id).where(
                    Product.user_id == user_id,
                    Product.marketplace == Marketplace.WB,
                    Product.is_active.is_(True),
                    Product.marketplace_account_id == promotion.marketplace_account_id,
                    Product.external_product_id.isnot(None),
                )
            )
        )
    elif filter_type == "with_mrc":
        base_query = base_query.where(
            WbPromotionNomenclature.wb_nm_id.in_(
                select(Product.marketplace_article).where(
                    Product.user_id == user_id,
                    Product.marketplace == Marketplace.WB,
                    Product.is_active.is_(True),
                    Product.mrc_price.isnot(None),
                    Product.mrc_price > 0,
                )
            )
        )

    # Total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await session.execute(count_query)
    total = int(total_result.scalar_one() or 0)

    # Pagination
    offset = (page_num - 1) * PAGE_SIZE
    query = base_query.order_by(WbPromotionNomenclature.wb_nm_id).offset(offset).limit(PAGE_SIZE)
    result = await session.execute(query)
    nomenclatures = result.scalars().all()

    # Enrich with product data and MRC calculation
    mrc_service = WbMrcPriceService()
    rows = []
    for nom in nomenclatures:
        product_result = await session.execute(
            select(Product).where(
                Product.marketplace_account_id == promotion.marketplace_account_id,
                or_(
                    Product.marketplace_article == str(nom.wb_nm_id),
                    Product.external_product_id == str(nom.wb_nm_id),
                ),
            )
        )
        product = product_result.scalar_one_or_none()

        mrc_result = None
        can_participate = None
        if product and product.mrc_price and product.mrc_price > 0:
            try:
                mrc_result = mrc_service.calculate(
                    mrc_price=product.mrc_price,
                    promo_required_price=nom.plan_price if nom.plan_price else None,
                )
                can_participate = not mrc_result.is_limited_by_mrc_rule
            except Exception:
                pass

        rows.append({
            "nomenclature": nom,
            "product": product,
            "mrc_result": mrc_result,
            "can_participate": can_participate,
        })

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return PromoDetailData(
        promotion=promotion,
        rows=rows,
        total_items=total,
        page=page_num,
        page_size=PAGE_SIZE,
        total_pages=total_pages,
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


def _feature_locked_content(access) -> str:
    """Render feature locked message."""
    return f"""
    <div class="card">
        <h2>🔒 Функция недоступна</h2>
        <p>{escape(access.reason)}</p>
        <p>Для управления МРЦ и акциями WB нужен тариф: <b>{escape(access.required_plan or "Pro")}</b></p>
        <p><a href="/web/subscription" class="button primary">Перейти к подписке</a></p>
    </div>
    """


def _mrc_pricing_content(data: MrcPageData, timezone: str = "Europe/Moscow") -> str:
    """Render MRC pricing page content."""
    parts = []

    # Flash messages
    parts.append(_flash_messages())

    # Header
    parts.append('<div class="card">')
    parts.append("<h2>Управление МРЦ Wildberries</h2>")
    parts.append(
        '<p class="text-muted" style="margin-bottom:16px">'
        "МРЦ — это целевая цена со скидкой на Wildberries. "
        "Цена продавца до скидки рассчитывается автоматически: <b>МРЦ × 4</b>. "
        "Если товар участвует в подходящей акции WB, цена может быть снижена, но не более чем на 10% от МРЦ."
        "</p>"
    )

    # Sync status
    if data.last_sync_time:
        parts.append(
            f'<p style="margin-bottom:12px;font-size:13px;color:#64748b">'
            f"📡 Последняя синхронизация акций: <b>{data.last_sync_time}</b>"
            f"</p>"
        )
    else:
        parts.append(
            '<p style="margin-bottom:12px;font-size:13px;color:#f59e0b">'
            "⚠️ Синхронизация акций ещё не запускалась"
            "</p>"
        )

    # Stats bar
    parts.append('<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px">')
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value">{data.total_products}</div>'
        '<div class="kpi-label">Всего товаров WB</div></div>'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value" style="color:#10b981">{data.products_with_mrc}</div>'
        '<div class="kpi-label">С МРЦ</div></div>'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value" style="color:#f59e0b">{data.products_without_mrc}</div>'
        '<div class="kpi-label">Без МРЦ</div></div>'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value" style="color:#3b82f6">{data.products_with_promo}</div>'
        '<div class="kpi-label">С акцией WB</div></div>'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value" style="color:#ef4444">{data.products_limited_by_mrc + data.products_limited_by_min}</div>'
        '<div class="kpi-label">С ограничениями</div></div>'
    )
    parts.append("</div>")

    # Action buttons
    parts.append('<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">')
    parts.append(
        '<form method="post" action="/web/mrc-pricing/sync-promotions" style="display:inline">'
        '<button type="submit" class="button">🔄 Синхронизировать акции WB</button>'
        "</form>"
    )
    parts.append(
        '<form method="post" action="/web/mrc-pricing/sync-promotions-all" style="display:inline">'
        '<button type="submit" class="button" title="allPromo=true — показать все акции">🔍 Расширенная проверка</button>'
        "</form>"
    )
    parts.append(
        '<a href="/web/wb-promotions" class="button">🎯 Акции WB</a>'
    )
    parts.append(
        '<a href="/web/mrc-pricing/export" class="button">📥 Скачать отчёт</a>'
    )
    parts.append("</div>")

    # Filters
    parts.append('<form method="get" action="/web/mrc-pricing" class="filters" style="margin-bottom:16px">')
    parts.append(
        '<select name="filter_type" style="padding:6px 10px;border:1px solid var(--color-border);border-radius:6px">'
    )
    filter_options = [
        ("all", "Все товары"),
        ("with_mrc", "С МРЦ"),
        ("without_mrc", "Без МРЦ"),
    ]
    for val, label in filter_options:
        selected = "selected" if data.filters.get("filter_type") == val else ""
        parts.append(f'<option value="{val}" {selected}>{label}</option>')
    parts.append("</select>")

    parts.append(
        '<input type="text" name="search" placeholder="Поиск по артикулу, nmID, названию" '
        f'value="{escape(data.filters.get("search", ""))}" '
        'style="flex:1;padding:6px 10px;border:1px solid var(--color-border);border-radius:6px">'
    )
    parts.append('<button type="submit" class="button primary">Найти</button>')
    parts.append("</form>")

    # Bulk operations form
    parts.append(
        '<form method="post" action="/web/mrc-pricing/bulk-update" id="bulk-form" style="margin-bottom:16px">'
    )
    parts.append('<div style="display:flex;gap:8px;align-items:center">')
    parts.append(
        '<input type="text" name="bulk_mrc" placeholder="Новая МРЦ" '
        'style="width:100px;padding:6px 10px;border:1px solid var(--color-border);border-radius:6px">'
    )
    parts.append(
        '<button type="submit" name="bulk_action" value="set" class="button primary">Установить МРЦ</button>'
    )
    parts.append(
        '<button type="submit" name="bulk_action" value="clear" class="button" '
        'onclick="return confirm(\'Очистить МРЦ у выбранных товаров?\')">Очистить МРЦ</button>'
    )
    parts.append("</div></form>")

    # Products table
    if not data.rows:
        parts.append(
            '<div class="empty-state">'
            '<p>Товары Wildberries не найдены.</p>'
            "</div>"
        )
    else:
        parts.append('<div class="table-wrap">')
        parts.append("<table>")
        parts.append("<thead><tr>")
        parts.append("<th style='width:30px'><input type='checkbox' id='select-all'></th>")
        parts.append("<th>Товар</th>")
        parts.append("<th>Артикул</th>")
        parts.append("<th>nmID</th>")
        parts.append("<th>МРЦ</th>")
        parts.append("<th>Цена со скидкой</th>")
        parts.append("<th>Цена до скидки</th>")
        parts.append("<th>Акция WB</th>")
        parts.append("<th>Статус</th>")
        parts.append("<th>Действие</th>")
        parts.append("</tr></thead>")
        parts.append("<tbody>")

        for row in data.rows:
            product = row.product
            nm_id = _extract_nm_id(product)
            article = escape(product.seller_article or "—")
            title = escape(product.title or "—")[:50]

            parts.append("<tr>")
            parts.append(
                f"<td><input type='checkbox' name='product_ids' value='{product.id}' class='product-checkbox'></td>"
            )
            parts.append(f"<td>{title}</td>")
            parts.append(f"<td>{article}</td>")
            parts.append(f"<td>{nm_id or '—'}</td>")

            # MRC edit form
            mrc_value = str(product.mrc_price) if product.mrc_price else ""
            parts.append(
                f'<td><form method="post" action="/web/mrc-pricing/products/{product.id}" '
                'style="display:flex;gap:4px;align-items:center">'
                f'<input type="text" name="mrc_price" value="{mrc_value}" '
                'placeholder="—" style="width:80px;padding:4px 8px;border:1px solid var(--color-border);border-radius:6px">'
                '<button type="submit" class="button" style="padding:4px 8px;font-size:12px">💾</button>'
                "</form></td>"
            )

            # Calculated prices
            if row.mrc_result:
                parts.append(f"<td><b>{row.mrc_result.final_discounted_price:.0f} ₽</b></td>")
                parts.append(f"<td>{row.mrc_result.price_before_discount:.0f} ₽</td>")
            else:
                parts.append("<td>—</td>")
                parts.append("<td>—</td>")

            # Promo info
            if row.has_active_promo:
                promo_name = escape(row.promo_name or "Акция WB")
                promo_price = f"{row.promo_plan_price:.0f}" if row.promo_plan_price else "—"
                in_action_text = "Участвует" if row.promo_in_action else "Подходит"
                parts.append(
                    f"<td><small>{promo_name}<br>{promo_price} ₽ ({in_action_text})</small></td>"
                )
            else:
                parts.append("<td><small class='text-muted'>Нет акции</small></td>")

            # Status badge
            if row.mrc_result:
                if row.mrc_result.is_limited_by_min_price:
                    parts.append(
                        '<td><span class="badge" style="background:#fef3c7;color:#92400e">⚠️ minPrice</span></td>'
                    )
                elif row.mrc_result.is_limited_by_mrc_rule:
                    parts.append(
                        '<td><span class="badge" style="background:#fef3c7;color:#92400e">⚠️ 10% лимит</span></td>'
                    )
                elif row.mrc_result.is_promo_applied:
                    parts.append(
                        '<td><span class="badge" style="background:#d1fae5;color:#065f46">✅ Акция</span></td>'
                    )
                else:
                    parts.append(
                        '<td><span class="badge" style="background:#dbeafe;color:#1e40af">ℹ️ МРЦ</span></td>'
                    )
            else:
                if product.mrc_price and product.mrc_price > 0:
                    parts.append(
                        '<td><span class="badge" style="background:#dbeafe;color:#1e40af">ℹ️ МРЦ</span></td>'
                    )
                else:
                    parts.append(
                        '<td><span class="badge" style="background:#f3f4f6;color:#6b7280">— Без МРЦ</span></td>'
                    )

            # Clear button
            parts.append(
                f'<td><form method="post" action="/web/mrc-pricing/products/{product.id}/clear" style="display:inline">'
                '<button type="submit" class="button" style="padding:2px 6px;font-size:11px" '
                'onclick="return confirm(\'Очистить МРЦ?\')">✕</button>'
                "</form></td>"
            )

            parts.append("</tr>")

            # Warning message row
            if row.mrc_result and (
                row.mrc_result.is_limited_by_mrc_rule
                or row.mrc_result.is_limited_by_min_price
            ):
                reason = escape(row.mrc_result.reason)
                parts.append(
                    f'<tr><td colspan="10"><small style="color:#f59e0b">⚠️ {reason}</small></td></tr>'
                )

        parts.append("</tbody></table>")
        parts.append("</div>")

        # Pagination
        if data.total_pages > 1:
            parts.append('<div style="display:flex;gap:8px;justify-content:center;margin-top:16px">')
            for p in range(1, data.total_pages + 1):
                if p == data.page:
                    parts.append(f'<span class="button primary" style="padding:4px 10px">{p}</span>')
                else:
                    filter_q = f"filter_type={data.filters.get('filter_type', 'all')}" if data.filters.get('filter_type') != 'all' else ""
                    search_q = f"search={data.filters.get('search', '')}" if data.filters.get('search') else ""
                    qs = "&".join(q for q in [filter_q, search_q] if q)
                    parts.append(
                        f'<a href="/web/mrc-pricing?page={p}&{qs}" class="button" style="padding:4px 10px">{p}</a>'
                    )
            parts.append("</div>")

    # Help section
    parts.append('<div class="card" style="margin-top:16px">')
    parts.append("<h3>Как работает расчёт МРЦ</h3>")
    parts.append("<ul>")
    parts.append("<li><b>МРЦ</b> — целевая цена продажи со скидкой на Wildberries.</li>")
    parts.append("<li><b>Цена до скидки</b> = МРЦ × 4. WB показывает скидку 75% от этой цены.</li>")
    parts.append("<li><b>Без акции</b>: цена со скидкой = МРЦ, цена до скидки = МРЦ × 4.</li>")
    parts.append(
        "<li><b>С акцией</b>: если цена акции (planPrice) в пределах 10% от МРЦ, "
        "используется цена акции. Иначе — минимально допустимая цена (МРЦ − 10%, округление вверх).</li>"
    )
    parts.append("<li><b>minPrice</b>: рассчитанная цена не может быть ниже minPrice товара.</li>")
    parts.append("</ul>")
    parts.append("</div>")

    # JavaScript for select all
    parts.append("""
    <script>
    document.getElementById('select-all')?.addEventListener('change', function() {
        document.querySelectorAll('.product-checkbox').forEach(cb => cb.checked = this.checked);
    });
    </script>
    """)

    parts.append("</div>")
    return "\n".join(parts)


def _flash_messages() -> str:
    """Render flash messages from query params."""
    return """
    <script>
    (function() {
        const params = new URLSearchParams(window.location.search);
        let msg = '';
        if (params.get('mrc_saved') === '1') {
            const productId = params.get('product_id');
            msg = '✅ МРЦ сохранена' + (productId ? ' (товар #' + productId + ')' : '');
        }
        if (params.get('saved') === '1') {
            const bulk = params.get('bulk');
            if (bulk === 'cleared') msg = '✅ МРЦ очищена у выбранных товаров';
            else if (bulk) msg = '✅ МРЦ обновлена для ' + bulk + ' товаров';
            else if (!msg) msg = '✅ МРЦ сохранена';
        }
        if (params.get('sync_done') === '1') {
            const allPromo = params.get('all_promo') || 'false';
            const rawPromos = params.get('raw_promos') || '0';
            const promos = params.get('promos') || '0';
            const noms = params.get('nomenclatures') || '0';
            const autoSkipped = params.get('auto_skipped') || '0';
            msg = '✅ Синхронизация акций завершена (allPromo=' + allPromo + ')\\n'
                + 'WB вернул акций: ' + rawPromos
                + ' | Сохранено: ' + promos
                + ' | Автоакций пропущено: ' + autoSkipped
                + ' | Товаров в акциях: ' + noms;
            if (rawPromos === '0' && allPromo === 'false') {
                msg += '\\n💡 WB вернул 0 доступных акций. Попробуйте расширенную проверку allPromo=true.';
            }
        }
        if (params.get('sync_error') === '1') msg = '❌ Ошибка синхронизации акций';
        if (params.get('error') === 'invalid_mrc') msg = '❌ МРЦ должна быть положительным числом';
        if (params.get('error') === 'no_products_selected') msg = '❌ Выберите товары для массового редактирования';
        if (params.get('export_coming_soon') === '1') msg = '📥 Выгрузка отчёта скоро будет доступна';
        if (msg) {
            const div = document.createElement('div');
            div.style.cssText = 'padding:12px 16px;margin-bottom:16px;border-radius:8px;font-size:14px;white-space:pre-line;' +
                (msg.startsWith('✅') ? 'background:#d1fae5;color:#065f46' : 'background:#fee2e2;color:#991b1b');
            div.textContent = msg;
            document.querySelector('.card')?.before(div);
        }
    })();
    </script>
    """


def _wb_promotions_content(data: dict, timezone: str = "Europe/Moscow") -> str:
    """Render WB promotions list page."""
    parts = []
    parts.append('<div class="card">')
    parts.append("<h2>🎯 Акции Wildberries</h2>")

    if data.get("last_sync_time"):
        parts.append(
            f'<p style="margin-bottom:16px;font-size:13px;color:#64748b">'
            f"Последняя синхронизация: <b>{data['last_sync_time']}</b>"
            f"</p>"
        )

    promotions = data.get("promotions", [])
    if not promotions:
        parts.append(
            '<div class="empty-state">'
            '<p>Активных акций WB на сегодня не найдено.</p>'
            '<p><a href="/web/mrc-pricing" class="button primary">Синхронизировать акции</a></p>'
            "</div>"
        )
    else:
        parts.append('<div class="table-wrap">')
        parts.append("<table>")
        parts.append("<thead><tr>")
        parts.append("<th>Название</th>")
        parts.append("<th>ID</th>")
        parts.append("<th>Тип</th>")
        parts.append("<th>Начало</th>")
        parts.append("<th>Окончание</th>")
        parts.append("<th>Товаров</th>")
        parts.append("<th>Участвуют</th>")
        parts.append("<th>Подходят</th>")
        parts.append("<th>Наши товары</th>")
        parts.append("<th></th>")
        parts.append("</tr></thead>")
        parts.append("<tbody>")

        for pd in promotions:
            promo = pd["promotion"]
            start_str = format_datetime_for_user(promo.start_datetime, "Europe/Moscow", "%d.%m.%Y") if promo.start_datetime else "—"
            end_str = format_datetime_for_user(promo.end_datetime, "Europe/Moscow", "%d.%m.%Y") if promo.end_datetime else "—"
            is_auto = promo.promotion_type and promo.promotion_type.lower() == "auto"
            promo_type = "Авто" if is_auto else "Обычная"

            parts.append("<tr>")
            parts.append(f"<td><b>{escape(promo.name or 'Без названия')}</b></td>")
            parts.append(f"<td>{promo.wb_promotion_id}</td>")
            parts.append(f"<td>{promo_type}</td>")
            parts.append(f"<td>{start_str}</td>")
            parts.append(f"<td>{end_str}</td>")

            if is_auto:
                parts.append(
                    '<td colspan="4"><small style="color:#64748b">Автоакция. Список товаров через WB API не запрашивается.</small></td>'
                )
            else:
                parts.append(f"<td>{pd['total_items']}</td>")
                parts.append(f"<td>{pd['items_in_action']}</td>")
                parts.append(f"<td>{pd['items_not_in_action']}</td>")
                parts.append(f"<td>{pd['matched_products']}</td>")

            parts.append(
                f'<td><a href="/web/wb-promotions/{promo.wb_promotion_id}" class="button" style="padding:2px 8px;font-size:12px">Открыть</a></td>'
            )
            parts.append("</tr>")

        parts.append("</tbody></table>")
        parts.append("</div>")

    parts.append("</div>")
    return "\n".join(parts)


def _wb_promotion_detail_content(data: PromoDetailData, timezone: str = "Europe/Moscow") -> str:
    """Render WB promotion detail page."""
    parts = []
    parts.append('<div class="card">')

    promo = data.promotion
    start_str = format_datetime_for_user(promo.start_datetime, "Europe/Moscow", "%d.%m.%Y %H:%M") if promo.start_datetime else "—"
    end_str = format_datetime_for_user(promo.end_datetime, "Europe/Moscow", "%d.%m.%Y %H:%M") if promo.end_datetime else "—"
    promo_type = "Авто" if promo.promotion_type and promo.promotion_type.lower() == "auto" else "Обычная"

    parts.append(
        f'<h2>🎯 {escape(promo.name or "Без названия")}</h2>'
        f'<p style="margin-bottom:16px">'
        f"ID: {promo.wb_promotion_id} | Тип: {promo_type}<br>"
        f"Период: {start_str} — {end_str}<br>"
        f"Всего товаров в акции: <b>{data.total_items}</b>"
        f"</p>"
    )

    # Filters
    parts.append('<form method="get" class="filters" style="margin-bottom:16px">')
    parts.append(
        '<select name="filter_type" style="padding:6px 10px;border:1px solid var(--color-border);border-radius:6px">'
    )
    filter_options = [
        ("all", "Все товары"),
        ("in_action", "Участвуют в акции"),
        ("not_in_action", "Подходят для участия"),
        ("matched", "Наши товары"),
        ("with_mrc", "С МРЦ"),
    ]
    for val, label in filter_options:
        parts.append(f'<option value="{val}">{label}</option>')
    parts.append("</select>")
    parts.append('<button type="submit" class="button primary">Применить</button>')
    parts.append("</form>")

    # Products table
    if not data.rows:
        parts.append(
            '<div class="empty-state">'
            '<p>Товары не найдены.</p>'
            "</div>"
        )
    else:
        parts.append('<div class="table-wrap">')
        parts.append("<table>")
        parts.append("<thead><tr>")
        parts.append("<th>Товар</th>")
        parts.append("<th>Артикул</th>")
        parts.append("<th>nmID</th>")
        parts.append("<th>Участвует</th>")
        parts.append("<th>Текущая цена</th>")
        parts.append("<th>Цена акции</th>")
        parts.append("<th>МРЦ</th>")
        parts.append("<th>Итоговая цена</th>")
        parts.append("<th>Статус</th>")
        parts.append("</tr></thead>")
        parts.append("<tbody>")

        for row in data.rows:
            nom = row["nomenclature"]
            product = row["product"]
            mrc_result = row["mrc_result"]

            in_action_text = "Да" if nom.in_action else "Нет"
            current_price = f"{nom.current_price:.0f}" if nom.current_price else "—"
            plan_price = f"{nom.plan_price:.0f}" if nom.plan_price else "—"
            mrc_val = f"{product.mrc_price:.0f}" if product and product.mrc_price else "—"
            final_price = f"{mrc_result.final_discounted_price:.0f}" if mrc_result else "—"

            product_title = escape((product.title or "—")[:40]) if product else "Не найден в базе"
            article = escape(product.seller_article or "—") if product else "—"
            nm_id = str(nom.wb_nm_id)

            # Status
            if mrc_result:
                if mrc_result.is_limited_by_mrc_rule:
                    status = '<span class="badge" style="background:#fef3c7;color:#92400e">⚠️ Ограничено 10%</span>'
                elif mrc_result.is_limited_by_min_price:
                    status = '<span class="badge" style="background:#fef3c7;color:#92400e">⚠️ minPrice</span>'
                else:
                    status = '<span class="badge" style="background:#d1fae5;color:#065f46">✅ Можно участвовать</span>'
            else:
                status = '<span class="badge" style="background:#f3f4f6;color:#6b7280">МРЦ не задана</span>'

            parts.append("<tr>")
            parts.append(f"<td>{product_title}</td>")
            parts.append(f"<td>{article}</td>")
            parts.append(f"<td>{nm_id}</td>")
            parts.append(f"<td>{in_action_text}</td>")
            parts.append(f"<td>{current_price} ₽</td>")
            parts.append(f"<td><b>{plan_price} ₽</b></td>")
            parts.append(f"<td>{mrc_val} ₽</td>")
            parts.append(f"<td>{final_price} ₽</td>")
            parts.append(f"<td>{status}</td>")
            parts.append("</tr>")

        parts.append("</tbody></table>")
        parts.append("</div>")

        # Pagination
        if data.total_pages > 1:
            parts.append('<div style="display:flex;gap:8px;justify-content:center;margin-top:16px">')
            for p in range(1, data.total_pages + 1):
                if p == data.page:
                    parts.append(f'<span class="button primary" style="padding:4px 10px">{p}</span>')
                else:
                    parts.append(
                        f'<a href="/web/wb-promotions/{promo.wb_promotion_id}?page={p}" class="button" style="padding:4px 10px">{p}</a>'
                    )
            parts.append("</div>")

    parts.append(
        f'<p style="margin-top:16px"><a href="/web/wb-promotions" class="button">← Назад к акциям</a></p>'
    )
    parts.append("</div>")
    return "\n".join(parts)


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
