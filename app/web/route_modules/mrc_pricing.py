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
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy import Integer, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, Product, WbPromotion, WbPromotionNomenclature
from app.models.enums import Marketplace
from app.services.feature_access_service import FeatureAccessService, FeatureCode
from app.services.pricing.mrc_import_service import MrcImportService
from app.services.pricing.mrc_pricing_settings_service import MrcPricingSettingsService
from app.services.pricing.wb_auto_promo_price_service import (
    WbAutoPromoPriceService,
    STATUS_AUTO_SET_PRICE,
    STATUS_AUTO_PRICE_OK,
    STATUS_AUTO_PRICE_VIOLATION,
    STATUS_AUTO_MIN_PRICE_VIOLATION,
    STATUS_AUTO_REQUIRED_PRICE_UNKNOWN,
    STATUS_AUTO_WAITING_WB_SYNC,
)
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
    promo_type: str | None
    auto_promo_status: str | None = None
    auto_promo_reason: str | None = None
    auto_promo_required_price: Decimal | None = None
    auto_promo_recommended_price: Decimal | None = None
    wb_current_price: Decimal | None = None
    wb_current_discount: int | None = None
    wb_current_discounted_price: Decimal | None = None
    wb_prices_synced_at: str | None = None


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
    nomenclatures_synced: bool
    has_active_auto_promotions: bool
    active_promotions_count: int
    active_regular_promotions_count: int
    active_auto_promotions_count: int
    nomenclatures_count: int
    last_promotions_sync_at: str | None
    last_nomenclatures_sync_at: str | None
    has_sync_errors: bool
    auto_rec_set_price: int = 0
    auto_rec_price_ok: int = 0
    auto_rec_violation: int = 0
    auto_rec_min_violation: int = 0
    auto_rec_total: int = 0
    auto_conditions_count: int = 0
    wb_prices_synced: bool = False
    last_wb_prices_sync_at: str | None = None
    wb_prices_count: int = 0


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
                "active_promotions_count": data.active_promotions_count,
                "active_regular_promotions_count": data.active_regular_promotions_count,
                "active_auto_promotions_count": data.active_auto_promotions_count,
                "nomenclatures_count": data.nomenclatures_count,
                "last_promotions_sync_at": data.last_promotions_sync_at,
                "last_nomenclatures_sync_at": data.last_nomenclatures_sync_at,
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
    """Manually trigger WB promotions sync (allPromo=true)."""
    service = WbPromotionsSyncService(session)
    try:
        acquired, lock_msg = await service.try_acquire_sync_lock()
        if not acquired:
            return RedirectResponse(
                url=f"/web/mrc-pricing?sync_cooldown=1&message={lock_msg}",
                status_code=303,
            )
        try:
            stats = await service.sync_all_accounts(all_promo=True)
            await session.commit()
            return RedirectResponse(
                url=(
                    f"/web/mrc-pricing?sync_done=1&promos={stats.promotions_upserted}"
                    f"&nomenclatures={stats.nomenclatures_upserted}"
                    f"&raw_promos={stats.promotions_fetched}&all_promo=true"
                    f"&auto_skipped={stats.promotions_skipped_auto}"
                    f"&rate_limits={stats.rate_limit_hits}"
                    f"&regular_processed={stats.regular_promotions_processed}"
                    f"&regular_empty={stats.regular_nomenclatures_empty}"
                    f"&auto_details_failed={stats.auto_details_failed}"
                ),
                status_code=303,
            )
        finally:
            await service.release_sync_lock()
    except Exception:
        logger.exception("wb_promotions_manual_sync_failed")
        await session.rollback()
        try:
            await service.release_sync_lock()
        except Exception:
            pass
        return RedirectResponse(url="/web/mrc-pricing?sync_error=1", status_code=303)


@router.post("/mrc-pricing/sync-promotions-all")
async def trigger_promotions_sync_limited(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Manually trigger WB promotions sync (allPromo=false — only joinable promos)."""
    service = WbPromotionsSyncService(session)
    try:
        acquired, lock_msg = await service.try_acquire_sync_lock()
        if not acquired:
            return RedirectResponse(
                url=f"/web/mrc-pricing?sync_cooldown=1&message={lock_msg}",
                status_code=303,
            )
        try:
            stats = await service.sync_all_accounts(all_promo=False)
            await session.commit()
            return RedirectResponse(
                url=(
                    f"/web/mrc-pricing?sync_done=1&promos={stats.promotions_upserted}"
                    f"&nomenclatures={stats.nomenclatures_upserted}"
                    f"&raw_promos={stats.promotions_fetched}&all_promo=false"
                    f"&auto_skipped={stats.promotions_skipped_auto}"
                    f"&rate_limits={stats.rate_limit_hits}"
                    f"&regular_processed={stats.regular_promotions_processed}"
                    f"&regular_empty={stats.regular_nomenclatures_empty}"
                    f"&auto_details_failed={stats.auto_details_failed}"
                ),
                status_code=303,
            )
        finally:
            await service.release_sync_lock()
    except Exception:
        logger.exception("wb_promotions_manual_sync_limited_failed")
        await session.rollback()
        try:
            await service.release_sync_lock()
        except Exception:
            pass
        return RedirectResponse(url="/web/mrc-pricing?sync_error=1", status_code=303)


@router.post("/mrc-pricing/sync-wb-prices")
async def trigger_wb_prices_sync(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Manually trigger WB current prices sync."""
    from app.core.security import TokenCipher
    from app.services.wb.wb_current_prices_sync_service import WbCurrentPricesSyncService

    service = WbCurrentPricesSyncService(session, cipher=TokenCipher())
    try:
        stats = await service.sync_all_accounts()
        await session.commit()
        return RedirectResponse(
            url=(
                f"/web/mrc-pricing?prices_sync_done=1"
                f"&prices_fetched={stats.prices_fetched}"
                f"&prices_upserted={stats.prices_upserted}"
                f"&accounts_failed={stats.accounts_failed}"
            ),
            status_code=303,
        )
    except Exception:
        logger.exception("wb_prices_manual_sync_failed")
        await session.rollback()
        return RedirectResponse(url="/web/mrc-pricing?prices_sync_error=1", status_code=303)


@router.get("/mrc-pricing/settings", response_class=HTMLResponse)
async def mrc_settings_page(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    """MRC settings page."""
    try:
        access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.MRC_PRICING)
        if not access.allowed:
            return render_page(
                "Настройки МРЦ",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        settings_service = MrcPricingSettingsService(session)
        settings = await settings_service.get_settings(user_id=user.id)

        return render_page(
            "Настройки МРЦ и акций WB",
            user.first_name or user.username or str(user.telegram_id),
            _mrc_settings_content(settings),
            active_path="/web/mrc-pricing",
        )
    except Exception:
        logger.exception("mrc_settings_page_failed", extra={"user_id": user.id})
        return render_page(
            "Ошибка — Настройки МРЦ",
            user.first_name or user.username or str(user.telegram_id),
            '<div class="card"><h2>Не удалось загрузить настройки</h2>'
            '<p>Ошибка уже записана в лог. Попробуйте обновить страницу позже.</p>'
            '<p><a href="/web/mrc-pricing" class="button primary">Вернуться</a></p></div>',
            active_path="/web/mrc-pricing",
        )


@router.post("/mrc-pricing/settings", response_class=HTMLResponse)
async def save_mrc_settings(
    request: Request,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    """Save MRC settings."""
    try:
        access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.MRC_PRICING)
        if not access.allowed:
            return render_page(
                "Настройки МРЦ",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        form = await request.form()

        def _decimal_form(key: str, default: str) -> Decimal:
            val = form.get(key, default).strip().replace(",", ".")
            try:
                return Decimal(val)
            except Exception:
                return Decimal(default)

        def _bool_form(key: str) -> bool:
            return form.get(key, "off") == "on"

        default_discount = _decimal_form("default_discount_percent", "75")
        full_price_multiplier = _decimal_form("full_price_multiplier", "4")
        allowed_deviation = _decimal_form("allowed_action_price_deviation_percent", "10")
        auto_promo_check = _bool_form("auto_promo_check_enabled")
        auto_add = _bool_form("auto_add_to_promotions")
        auto_price = _bool_form("auto_price_for_auto_promotions")

        settings_service = MrcPricingSettingsService(session)
        errors = MrcPricingSettingsService.validate_settings(
            default_discount_percent=default_discount,
            full_price_multiplier=full_price_multiplier,
            allowed_action_price_deviation_percent=allowed_deviation,
        )

        if errors:
            settings = await settings_service.get_settings(user_id=user.id)
            return render_page(
                "Настройки МРЦ и акций WB",
                user.first_name or user.username or str(user.telegram_id),
                _mrc_settings_content(settings, errors=errors),
                active_path="/web/mrc-pricing",
            )

        await settings_service.update_settings(
            user_id=user.id,
            default_discount_percent=default_discount,
            full_price_multiplier=full_price_multiplier,
            allowed_action_price_deviation_percent=allowed_deviation,
            auto_promo_check_enabled=auto_promo_check,
            auto_add_to_promotions=auto_add,
            auto_price_for_auto_promotions=auto_price,
        )
        await session.commit()

        return RedirectResponse(url="/web/mrc-pricing/settings?saved=1", status_code=303)
    except Exception:
        logger.exception("mrc_settings_save_failed", extra={"user_id": user.id})
        return RedirectResponse(url="/web/mrc-pricing/settings?error=1", status_code=303)


@router.get("/mrc-pricing/export-template", response_model=None)
async def export_mrc_template(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
):
    """Download Excel template for MRC bulk import."""
    try:
        from app.services.pricing.mrc_import_service import MrcImportService
        from fastapi.responses import FileResponse

        access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.MRC_PRICING)
        if not access.allowed:
            return render_page(
                "Ошибка — МРЦ WB",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        service = MrcImportService(session)
        file_path = await service.generate_mrc_template(user.id)

        return FileResponse(
            path=str(file_path),
            filename=file_path.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception:
        logger.exception("mrc_export_template_failed", extra={"user_id": user.id})
        return render_page(
            "Ошибка — МРЦ WB",
            user.first_name or user.username or str(user.telegram_id),
            '<div class="card"><h2>Не удалось сформировать шаблон</h2>'
            '<p>Ошибка записана в лог. Попробуйте позже.</p>'
            '<p><a href="/web/mrc-pricing" class="button primary">Вернуться</a></p></div>',
            active_path="/web/mrc-pricing",
        )


@router.post("/mrc-pricing/import", response_class=HTMLResponse)
async def import_mrc_file(
    file: UploadFile,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    """Upload Excel file and show preview."""
    from app.services.pricing.mrc_import_service import MrcImportService

    access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.MRC_PRICING)
    if not access.allowed:
        return render_page(
            "Ошибка — МРЦ WB",
            user.first_name or user.username or str(user.telegram_id),
            _feature_locked_content(access),
            active_path="/web/mrc-pricing",
        )

    if not file.filename or not file.filename.endswith(".xlsx"):
        return render_page(
            "Ошибка — МРЦ WB",
            user.first_name or user.username or str(user.telegram_id),
            '<div class="card"><h2>Неверный формат</h2>'
            '<p>Загрузите файл <b>.xlsx</b>.</p>'
            '<p><a href="/web/mrc-pricing" class="button primary">Вернуться</a></p></div>',
            active_path="/web/mrc-pricing",
        )

    user_id = user.id

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        service = MrcImportService(session)
        preview = await service.create_preview(tmp_path, user_id, source="web", original_file_name=file.filename)
        rows = await service.get_import_rows(preview.import_id, user_id)

        return render_page(
            "Проверка импорта МРЦ",
            user.first_name or user.username or str(user.telegram_id),
            _import_preview_content(preview, rows, user.timezone),
            active_path="/web/mrc-pricing",
        )
    except ValueError as exc:
        logger.warning(
            "mrc_import_preview_validation_error",
            extra={"user_id": user_id, "error": str(exc)},
        )
        return render_page(
            "Ошибка — МРЦ WB",
            user.first_name or user.username or str(user.telegram_id),
            f'<div class="card"><h2>Не удалось обработать файл</h2>'
            f'<p>{escape(str(exc))}</p>'
            f'<p><a href="/web/mrc-pricing" class="button primary">Вернуться</a></p></div>',
            active_path="/web/mrc-pricing",
        )
    except Exception:
        await session.rollback()
        logger.exception("mrc_import_preview_failed", extra={"user_id": user_id})
        return render_page(
            "Ошибка — МРЦ WB",
            user.first_name or user.username or str(user.telegram_id),
            '<div class="card"><h2>Не удалось обработать файл</h2>'
            '<p>Ошибка записана в лог.</p>'
            '<p><a href="/web/mrc-pricing" class="button primary">Вернуться</a></p></div>',
            active_path="/web/mrc-pricing",
        )
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


@router.post("/mrc-pricing/import/confirm")
async def confirm_mrc_import(
    request: Request,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Confirm and apply MRC import."""
    user_id = user.id
    try:
        from app.services.pricing.mrc_import_service import MrcImportService

        form_data = await request.form()
        import_id = form_data.get("import_id", "")

        service = MrcImportService(session)
        result = await service.apply_mrc_import(int(import_id), user_id, source="web")

        return RedirectResponse(
            url=f"/web/mrc-pricing?import_done=1&updated={result.updated_count}&cleared={result.cleared_count}&errors={result.error_count}",
            status_code=303,
        )
    except ValueError as exc:
        logger.warning(
            "mrc_import_confirm_validation_error",
            extra={"user_id": user_id, "error": str(exc)},
        )
        return RedirectResponse(url=f"/web/mrc-pricing?import_error=1&error_msg={str(exc)}", status_code=303)
    except Exception:
        await session.rollback()
        logger.exception("mrc_import_confirm_failed", extra={"user_id": user_id})
        return RedirectResponse(url="/web/mrc-pricing?import_error=1", status_code=303)


@router.post("/mrc-pricing/import/cancel")
async def cancel_mrc_import(
    request: Request,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Cancel MRC import."""
    user_id = user.id
    try:
        from app.services.pricing.mrc_import_service import MrcImportService

        form_data = await request.form()
        import_id = form_data.get("import_id", "")

        service = MrcImportService(session)
        await service.cancel_import(int(import_id), user_id)
    except Exception:
        logger.exception("mrc_import_cancel_failed", extra={"user_id": user_id})

    return RedirectResponse(url="/web/mrc-pricing?import_cancelled=1", status_code=303)


@router.get("/auto-promo-prices", response_class=HTMLResponse)
async def auto_promo_prices_page(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    marketplace_account_id: int | None = Query(None),
) -> str:
    """Auto promotion price recommendations page."""
    try:
        access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.MRC_PRICING)
        if not access.allowed:
            return render_page(
                "Цены для автоакций WB",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        from app.services.pricing.wb_price_update_service import WbPriceUpdateService

        price_service = WbPriceUpdateService(session)

        if marketplace_account_id is None:
            first_account = await session.execute(
                select(MarketplaceAccount.id).where(
                    MarketplaceAccount.user_id == user.id,
                    MarketplaceAccount.marketplace == Marketplace.WB,
                    MarketplaceAccount.is_active.is_(True),
                ).limit(1)
            )
            marketplace_account_id = first_account.scalar_one_or_none()

        preview = []
        if marketplace_account_id:
            preview = await price_service.prepare_price_changes(
                user_id=user.id,
                marketplace_account_id=marketplace_account_id,
            )

        accounts_result = await session.execute(
            select(MarketplaceAccount.id, MarketplaceAccount.name).where(
                MarketplaceAccount.user_id == user.id,
                MarketplaceAccount.marketplace == Marketplace.WB,
                MarketplaceAccount.is_active.is_(True),
            )
        )
        accounts = list(accounts_result.all())

        return render_page(
            "Цены для автоакций WB",
            user.first_name or user.username or str(user.telegram_id),
            _auto_promo_prices_content(preview, accounts, marketplace_account_id),
            active_path="/web/mrc-pricing",
        )
    except Exception:
        logger.exception("auto_promo_prices_page_failed", extra={"user_id": user.id})
        return render_page(
            "Ошибка — Цены для автоакций",
            user.first_name or user.username or str(user.telegram_id),
            '<div class="card"><h2>Не удалось загрузить рекомендации</h2>'
            '<p>Ошибка записана в лог. Попробуйте позже.</p>'
            '<p><a href="/web/mrc-pricing" class="button primary">Вернуться</a></p></div>',
            active_path="/web/mrc-pricing",
        )


@router.post("/auto-promo-prices/apply", response_class=HTMLResponse)
async def auto_promo_prices_apply(
    request: Request,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    """Apply selected auto promo price changes."""
    try:
        access = await FeatureAccessService(session).can_use_feature(user.id, FeatureCode.MRC_PRICING)
        if not access.allowed:
            return render_page(
                "Цены для автоакций WB",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        form = await request.form()
        marketplace_account_id = int(form.get("marketplace_account_id", "0"))
        dry_run = form.get("dry_run", "on") == "on"

        selected_ids = form.getlist("product_ids")
        product_ids = [int(x) for x in selected_ids] if selected_ids else None

        wb_api_key = form.get("wb_api_key", "").strip()
        if not wb_api_key and not dry_run:
            return RedirectResponse(url="/web/auto-promo-prices?error=no_api_key", status_code=303)

        from app.services.pricing.wb_price_update_service import WbPriceUpdateService
        from app.core.security import decrypt_value

        price_service = WbPriceUpdateService(session)

        if not dry_run and wb_api_key:
            api_key_to_use = wb_api_key
        elif not dry_run:
            account_result = await session.execute(
                select(MarketplaceAccount.encrypted_api_key).where(
                    MarketplaceAccount.id == marketplace_account_id,
                )
            )
            encrypted_key = account_result.scalar_one_or_none()
            if encrypted_key:
                api_key_to_use = decrypt_value(encrypted_key)
            else:
                return RedirectResponse(url="/web/auto-promo-prices?error=no_api_key", status_code=303)
        else:
            api_key_to_use = "dry_run"

        results = await price_service.apply_price_changes(
            user_id=user.id,
            marketplace_account_id=marketplace_account_id,
            wb_api_key=api_key_to_use,
            product_ids=product_ids,
            dry_run=dry_run,
        )

        await session.commit()

        applied = sum(1 for r in results if r["status"] == "applied")
        dry_count = sum(1 for r in results if r["status"] == "dry_run")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        failed = sum(1 for r in results if r["status"] == "failed")

        msg_parts = []
        if dry_run:
            msg_parts.append(f"Preview: {len(results)} товаров")
        else:
            if applied:
                msg_parts.append(f"Применено: {applied}")
            if skipped:
                msg_parts.append(f"Пропущено: {skipped}")
            if failed:
                msg_parts.append(f"Ошибки: {failed}")

        query = f"result={'_'.join(msg_parts)}"
        return RedirectResponse(url=f"/web/auto-promo-prices?{query}", status_code=303)
    except Exception:
        logger.exception("auto_promo_prices_apply_failed", extra={"user_id": user.id})
        return RedirectResponse(url="/web/auto-promo-prices?error=apply_failed", status_code=303)


def _auto_promo_prices_content(
    preview: list[dict],
    accounts: list,
    selected_account_id: int | None,
) -> str:
    """Render auto promo prices page content."""
    parts = []
    parts.append('<div class="card">')
    parts.append("<h2>🤖 Рекомендации по ценам для автоакций WB</h2>")
    parts.append(
        '<p class="text-muted" style="margin-bottom:16px">'
        "Система проверяет активные автоакции WB и рассчитывает, нужно ли изменить цену товара "
        "для участия. Цена меняется только в пределах допустимого отклонения от МРЦ и не ниже minPrice."
        "</p>"
    )

    if not accounts:
        parts.append(
            '<div class="empty-state">'
            '<p>Нет активных аккаунтов WB.</p>'
            '<p><a href="/web/mrc-pricing" class="button primary">← Назад к МРЦ</a></p>'
            "</div>"
        )
        return "\n".join(parts)

    parts.append('<form method="get" action="/web/auto-promo-prices" style="margin-bottom:16px">')
    parts.append('<select name="marketplace_account_id" style="padding:6px 10px;border:1px solid var(--color-border);border-radius:6px">')
    for acct_id, acct_name in accounts:
        selected = "selected" if acct_id == selected_account_id else ""
        parts.append(f'<option value="{acct_id}" {selected}>{escape(acct_name or f"Аккаунт {acct_id}")}</option>')
    parts.append("</select>")
    parts.append('<button type="submit" class="button primary">Загрузить</button>')
    parts.append("</form>")

    if not preview:
        parts.append(
            '<div class="empty-state">'
            '<p>Нет рекомендаций по изменению цен.</p>'
            '<p class="text-muted">Это может означать, что:</p>'
            '<ul><li>Нет активных автоакций</li>'
            '<li>Цены уже подходят для автоакций</li>'
            '<li>Изменение цены нарушит МРЦ или minPrice</li>'
            '<li>Требуется синхронизация акций WB</li></ul>'
            '<p><a href="/web/mrc-pricing" class="button primary">← Назад к МРЦ</a></p>'
            "</div>"
        )
        parts.append("</div>")
        return "\n".join(parts)

    can_apply = any(p["can_change"] for p in preview)

    parts.append(
        f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px">'
        f'<div class="kpi-card"><div class="kpi-value">{len(preview)}</div>'
        '<div class="kpi-label">Всего рекомендаций</div></div>'
        f'<div class="kpi-card"><div class="kpi-value" style="color:#10b981">{sum(1 for p in preview if p["can_change"])}</div>'
        '<div class="kpi-label">Можно применить</div></div>'
        f'<div class="kpi-card"><div class="kpi-value" style="color:#ef4444">{sum(1 for p in preview if not p["can_change"])}</div>'
        '<div class="kpi-label">Пропущено</div></div>'
        "</div>"
    )

    parts.append(
        '<form method="post" action="/web/auto-promo-prices/apply" id="apply-form">'
        f'<input type="hidden" name="marketplace_account_id" value="{selected_account_id}">'
    )

    parts.append('<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">')
    parts.append(
        '<button type="submit" name="dry_run" value="on" class="button primary">🔍 Подготовить изменение цен</button>'
    )
    parts.append(
        '<button type="submit" name="dry_run" value="off" class="button" '
        'style="background:#ef4444;color:white" '
        'onclick="return confirm(\'Применить изменения цен в WB? Это действие нельзя отменить.\')">⚡ Применить выбранные</button>'
    )
    parts.append("</div>")

    parts.append('<div class="table-wrap">')
    parts.append("<table>")
    parts.append("<thead><tr>")
    parts.append("<th style='width:30px'><input type='checkbox' id='select-all'></th>")
    parts.append("<th>Товар</th>")
    parts.append("<th>nmID</th>")
    parts.append("<th>МРЦ</th>")
    parts.append("<th>Текущая цена</th>")
    parts.append("<th>Цена входа</th>")
    parts.append("<th>Границы МРЦ</th>")
    parts.append("<th>Рекомендуемая</th>")
    parts.append("<th>Статус</th>")
    parts.append("</tr></thead>")
    parts.append("<tbody>")

    for p in preview:
        parts.append("<tr>")
        checkbox_disabled = "" if p["can_change"] else "disabled"
        parts.append(
            f"<td><input type='checkbox' name='product_ids' value='{p['product_id']}' "
            f"class='product-checkbox' {checkbox_disabled}></td>"
        )
        title = escape((p.get("title") or "")[:50])
        article = escape(p.get("seller_article") or "")
        parts.append(f"<td>{title}<br><small class='text-muted'>{article}</small></td>")
        parts.append(f"<td>{p['wb_nm_id']}</td>")
        parts.append(f"<td>{p['mrc_price']:.0f} ₽</td>")
        parts.append(f"<td>{p['current_wb_price']:.0f} ₽" if p["current_wb_price"] else "<td>—")
        parts.append(f"</td><td>{p['recommended_price']:.0f} ₽</td>")
        parts.append(
            f"<td><small>{p['mrc_lower_bound']:.0f} — {p['mrc_upper_bound']:.0f} ₽</small></td>"
        )
        parts.append(f"<td><b>{p['recommended_price']:.0f} ₽</b></td>")

        if p["can_change"]:
            parts.append(
                '<td><span class="badge" style="background:#d1fae5;color:#065f46">✅ Можно</span></td>'
            )
        else:
            skip_reason = escape(p.get("skip_reason") or "Пропущено")
            parts.append(
                f'<td><span class="badge" style="background:#fee2e2;color:#991b1b">⚠️ {skip_reason}</span></td>'
            )

        parts.append("</tr>")

    parts.append("</tbody></table>")
    parts.append("</div>")
    parts.append("</form>")

    parts.append(
        '<p class="text-muted" style="margin-top:16px;font-size:13px">'
        "⚠️ Изменение цен отправляется в WB API. minPrice не меняется. "
        "Перед применением рекомендуется нажать «Подготовить изменение цен» для проверки."
        "</p>"
    )

    parts.append("</div>")

    parts.append("""
    <script>
    document.getElementById('select-all')?.addEventListener('change', function() {
        document.querySelectorAll('.product-checkbox:not([disabled])').forEach(cb => cb.checked = this.checked);
    });
    </script>
    """)

    return "\n".join(parts)


@router.get(
    "/mrc-pricing/auto-promotions/conditions",
    response_class=HTMLResponse,
)
async def auto_promo_conditions_page(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    marketplace_account_id: int | None = Query(None),
) -> str:
    """Auto promotion conditions import page (alias)."""
    return await auto_promo_import_page(
        user=user,
        session=session,
        marketplace_account_id=marketplace_account_id,
    )


@router.get("/auto-promo-import", response_class=HTMLResponse)
async def auto_promo_import_page(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    marketplace_account_id: int | None = Query(None),
) -> str:
    """Auto promotion conditions import page."""
    try:
        access = await FeatureAccessService(session).can_use_feature(
            user.id, FeatureCode.MRC_PRICING
        )
        if not access.allowed:
            return render_page(
                "Импорт условий автоакций WB",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        if marketplace_account_id is None:
            first_account = await session.execute(
                select(MarketplaceAccount.id).where(
                    MarketplaceAccount.user_id == user.id,
                    MarketplaceAccount.marketplace == Marketplace.WB,
                    MarketplaceAccount.is_active.is_(True),
                ).limit(1)
            )
            marketplace_account_id = first_account.scalar_one_or_none()

        accounts_result = await session.execute(
            select(MarketplaceAccount.id, MarketplaceAccount.name).where(
                MarketplaceAccount.user_id == user.id,
                MarketplaceAccount.marketplace == Marketplace.WB,
                MarketplaceAccount.is_active.is_(True),
            )
        )
        accounts = list(accounts_result.all())

        return render_page(
            "Импорт условий автоакций WB",
            user.first_name or user.username or str(user.telegram_id),
            _auto_promo_import_content(accounts, marketplace_account_id),
            active_path="/web/mrc-pricing",
        )
    except Exception:
        logger.exception(
            "auto_promo_import_page_failed",
            extra={"user_id": user.id},
        )
        return render_page(
            "Ошибка — Импорт условий",
            user.first_name or user.username or str(user.telegram_id),
            '<div class="card"><h2>Не удалось загрузить страницу</h2>'
            '<p>Ошибка записана в лог.</p>'
            '<p><a href="/web/mrc-pricing" class="button primary">Вернуться</a></p></div>',
            active_path="/web/mrc-pricing",
        )


@router.get("/auto-promo-import/template")
async def auto_promo_import_template(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
):
    """Download Excel template for auto promotion conditions."""
    try:
        access = await FeatureAccessService(session).can_use_feature(
            user.id, FeatureCode.MRC_PRICING
        )
        if not access.allowed:
            return render_page(
                "Ошибка",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        from app.services.pricing.wb_auto_promo_import_service import (
            WbAutoPromoImportService,
        )
        from fastapi.responses import FileResponse

        service = WbAutoPromoImportService(session)
        file_path = await service.generate_template(user.id)

        return FileResponse(
            path=str(file_path),
            filename=file_path.name,
            media_type=(
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            ),
        )
    except Exception:
        logger.exception(
            "auto_promo_import_template_failed",
            extra={"user_id": user.id},
        )
        return RedirectResponse(
            url="/web/auto-promo-import?error=template",
            status_code=303,
        )


@router.post("/mrc-pricing/auto-promotions/conditions/manual")
async def auto_promo_condition_manual(
    request: Request,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    """Manually set required_price for an auto promotion condition."""
    try:
        form = await request.form()
        wb_nm_id = form.get("wb_nm_id", "").strip()
        promotion_name = form.get("promotion_name", "").strip()
        required_price_str = form.get("required_price", "").strip()
        marketplace_account_id = int(form.get("marketplace_account_id", "0"))

        if not wb_nm_id or not required_price_str or not marketplace_account_id:
            return RedirectResponse(
                url="/web/mrc-pricing?error=manual_condition_missing_fields",
                status_code=303,
            )

        try:
            wb_nm_id_int = int(wb_nm_id)
            required_price = Decimal(required_price_str)
        except (ValueError, InvalidOperation):
            return RedirectResponse(
                url="/web/mrc-pricing?error=manual_condition_invalid_values",
                status_code=303,
            )

        from app.models.domain import WbAutoPromotionCondition

        now_utc = datetime.now(tz=UTC)

        existing_result = await session.execute(
            select(WbAutoPromotionCondition).where(
                WbAutoPromotionCondition.marketplace_account_id == marketplace_account_id,
                WbAutoPromotionCondition.wb_nm_id == wb_nm_id_int,
                WbAutoPromotionCondition.promotion_name == (promotion_name or None),
                WbAutoPromotionCondition.source == "manual",
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.required_price = required_price
            existing.synced_at = now_utc
        else:
            new_condition = WbAutoPromotionCondition(
                user_id=user.id,
                marketplace_account_id=marketplace_account_id,
                wb_nm_id=wb_nm_id_int,
                promotion_name=promotion_name or None,
                required_price=required_price,
                source="manual",
                synced_at=now_utc,
            )
            session.add(new_condition)

        await session.commit()

        logger.info(
            "auto_promo_condition_manual_set",
            extra={
                "user_id": user.id,
                "wb_nm_id": wb_nm_id_int,
                "required_price": str(required_price),
                "marketplace_account_id": marketplace_account_id,
            },
        )

        from app.services.pricing.wb_auto_promo_price_service import (
            WbAutoPromoPriceService,
        )

        price_service = WbAutoPromoPriceService(session)
        recs = await price_service.build_recommendations_for_conditions(
            user_id=user.id,
            marketplace_account_id=marketplace_account_id,
        )
        for rec in recs:
            await price_service.save_recommendation(
                rec=rec,
                user_id=user.id,
                marketplace_account_id=marketplace_account_id,
            )
        await session.commit()

        set_price = sum(1 for r in recs if r.status == STATUS_AUTO_SET_PRICE)
        price_ok = sum(1 for r in recs if r.status == STATUS_AUTO_PRICE_OK)

        return RedirectResponse(
            url=(
                f"/web/mrc-pricing/auto-promotions/recommendations"
                f"?marketplace_account_id={marketplace_account_id}"
                f"&condition_set=1"
                f"&wb_nm_id={wb_nm_id_int}"
                f"&required_price={required_price}"
                f"&rec_set_price={set_price}"
                f"&rec_price_ok={price_ok}"
            ),
            status_code=303,
        )
    except Exception:
        logger.exception("auto_promo_condition_manual_failed", extra={"user_id": user.id})
        await session.rollback()
        return RedirectResponse(
            url="/web/mrc-pricing?error=manual_condition_failed",
            status_code=303,
        )


@router.post("/auto-promo-import/preview", response_class=HTMLResponse)
async def auto_promo_import_preview(
    request: Request,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    marketplace_account_id: int = Form(...),
    file: UploadFile = Form(...),
) -> str:
    """Preview auto promotion conditions import."""
    try:
        access = await FeatureAccessService(session).can_use_feature(
            user.id, FeatureCode.MRC_PRICING
        )
        if not access.allowed:
            return render_page(
                "Ошибка",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        import tempfile
        from pathlib import Path

        from app.services.pricing.wb_auto_promo_import_service import (
            WbAutoPromoImportService,
        )

        content = await file.read()
        original_filename = file.filename or "upload.xlsx"
        suffix = Path(original_filename).suffix.lower()
        if suffix not in (".xlsx", ".xlsm", ".csv"):
            suffix = ".xlsx"
        with tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        service = WbAutoPromoImportService(session)
        preview, preview_rows = await service.create_preview(
            tmp_path,
            user.id,
            marketplace_account_id,
            original_file_name=file.filename,
        )

        return render_page(
            "Предпросмотр импорта условий автоакций",
            user.first_name or user.username or str(user.telegram_id),
            _auto_promo_import_preview_content(
                preview, preview_rows, marketplace_account_id
            ),
            active_path="/web/mrc-pricing",
        )
    except ValueError as exc:
        return render_page(
            "Ошибка импорта",
            user.first_name or user.username or str(user.telegram_id),
            f'<div class="card"><h2>Ошибка</h2>'
            f"<p>{escape(str(exc))}</p>"
            '<p><a href="/web/auto-promo-import" class="button primary">'
            "Назад</a></p></div>",
            active_path="/web/mrc-pricing",
        )
    except Exception:
        logger.exception(
            "auto_promo_import_preview_failed",
            extra={"user_id": user.id},
        )
        return RedirectResponse(
            url="/web/auto-promo-import?error=preview",
            status_code=303,
        )


@router.post("/auto-promo-import/apply", response_class=HTMLResponse)
async def auto_promo_import_apply(
    request: Request,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    marketplace_account_id: int = Form(...),
) -> str:
    """Apply auto promotion conditions import."""
    try:
        access = await FeatureAccessService(session).can_use_feature(
            user.id, FeatureCode.MRC_PRICING
        )
        if not access.allowed:
            return render_page(
                "Ошибка",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        from app.services.pricing.wb_auto_promo_import_service import (
            WbAutoPromoImportService,
        )

        form = await request.form()
        preview_rows_json = form.get("preview_rows", "[]")
        import json

        preview_rows = json.loads(preview_rows_json)

        service = WbAutoPromoImportService(session)
        saved = await service.apply_import(
            preview_rows, user.id, marketplace_account_id
        )
        await session.commit()

        return RedirectResponse(
            url=f"/web/auto-promo-import?saved={saved}",
            status_code=303,
        )
    except Exception:
        logger.exception(
            "auto_promo_import_apply_failed",
            extra={"user_id": user.id},
        )
        return RedirectResponse(
            url="/web/auto-promo-import?error=apply",
            status_code=303,
        )


@router.get(
    "/mrc-pricing/auto-promotions/recommendations",
    response_class=HTMLResponse,
)
async def auto_promo_recommendations_page(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    marketplace_account_id: int | None = Query(None),
    status_filter: str = Query("all"),
) -> str:
    """Auto promotion price recommendations page.

    GET only loads existing recommendations from DB.
    Use POST /recommendations/build to (re)build recommendations.
    """
    try:
        access = await FeatureAccessService(session).can_use_feature(
            user.id, FeatureCode.MRC_PRICING
        )
        if not access.allowed:
            return render_page(
                "Рекомендации по автоакциям WB",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        from app.services.pricing.wb_price_update_service import (
            WbPriceUpdateService,
        )

        if marketplace_account_id is None:
            first_account = await session.execute(
                select(MarketplaceAccount.id).where(
                    MarketplaceAccount.user_id == user.id,
                    MarketplaceAccount.marketplace == Marketplace.WB,
                    MarketplaceAccount.is_active.is_(True),
                ).limit(1)
            )
            marketplace_account_id = first_account.scalar_one_or_none()

        recommendations = []
        preview = []
        conditions_count = 0
        if marketplace_account_id:
            from app.models.domain import WbAutoPromotionCondition, WbAutoPromoPriceRecommendation

            cond_result = await session.execute(
                select(WbAutoPromotionCondition).where(
                    WbAutoPromotionCondition.marketplace_account_id == marketplace_account_id,
                    WbAutoPromotionCondition.required_price.isnot(None),
                )
            )
            conditions_count = len(list(cond_result.scalars().all()))

            recs_result = await session.execute(
                select(WbAutoPromoPriceRecommendation).where(
                    WbAutoPromoPriceRecommendation.marketplace_account_id == marketplace_account_id,
                ).order_by(WbAutoPromoPriceRecommendation.updated_at.desc())
            )
            db_recs = list(recs_result.scalars().all())

            for db_rec in db_recs:
                from app.services.pricing.wb_auto_promo_price_service import AutoPromoPriceRecommendation
                recommendations.append(AutoPromoPriceRecommendation(
                    product_id=db_rec.product_id,
                    wb_nm_id=db_rec.wb_nm_id,
                    wb_promotion_id=db_rec.wb_promotion_id,
                    promotion_name=db_rec.promotion_name,
                    mrc_price=db_rec.mrc_price,
                    current_wb_price=db_rec.current_wb_price,
                    required_price=db_rec.required_price,
                    recommended_price=db_rec.recommended_price,
                    min_price=db_rec.min_price,
                    mrc_lower_bound=db_rec.mrc_lower_bound,
                    mrc_upper_bound=db_rec.mrc_upper_bound,
                    status=db_rec.status,
                    reason=db_rec.reason,
                ))

            if recommendations:
                update_service = WbPriceUpdateService(session)
                preview = await update_service.prepare_price_changes(
                    user_id=user.id,
                    marketplace_account_id=marketplace_account_id,
                )

        await session.commit()

        accounts_result = await session.execute(
            select(MarketplaceAccount.id, MarketplaceAccount.name).where(
                MarketplaceAccount.user_id == user.id,
                MarketplaceAccount.marketplace == Marketplace.WB,
                MarketplaceAccount.is_active.is_(True),
            )
        )
        accounts = list(accounts_result.all())

        return render_page(
            "Рекомендации по автоакциям WB",
            user.first_name or user.username or str(user.telegram_id),
            _auto_promo_recommendations_content(
                recommendations, preview, accounts, marketplace_account_id, status_filter,
                conditions_count=conditions_count,
            ),
            active_path="/web/mrc-pricing",
        )
    except Exception:
        logger.exception(
            "auto_promo_recommendations_failed",
            extra={"user_id": user.id},
        )
        return render_page(
            "Ошибка — Рекомендации",
            user.first_name or user.username or str(user.telegram_id),
            '<div class="card"><h2>Не удалось загрузить рекомендации</h2>'
            '<p>Ошибка записана в лог.</p>'
            '<p><a href="/web/mrc-pricing" class="button primary">'
            "Вернуться</a></p></div>",
            active_path="/web/mrc-pricing",
        )


@router.post(
    "/mrc-pricing/auto-promotions/recommendations/build",
    response_class=HTMLResponse,
)
async def auto_promo_recommendations_build(
    request: Request,
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    marketplace_account_id: int = Form(...),
) -> str:
    """Generate recommendations for auto promotion conditions."""
    try:
        access = await FeatureAccessService(session).can_use_feature(
            user.id, FeatureCode.MRC_PRICING
        )
        if not access.allowed:
            return render_page(
                "Ошибка",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        from app.services.pricing.wb_auto_promo_price_service import (
            WbAutoPromoPriceService,
        )

        price_service = WbAutoPromoPriceService(session)
        recs = await price_service.build_recommendations_for_conditions(
            user_id=user.id,
            marketplace_account_id=marketplace_account_id,
        )

        total = len(recs)
        set_price = sum(1 for r in recs if r.status == STATUS_AUTO_SET_PRICE)
        price_ok = sum(1 for r in recs if r.status == STATUS_AUTO_PRICE_OK)
        violation = sum(1 for r in recs if r.status == STATUS_AUTO_PRICE_VIOLATION)
        min_violation = sum(1 for r in recs if r.status == STATUS_AUTO_MIN_PRICE_VIOLATION)
        unknown = sum(1 for r in recs if r.status == STATUS_AUTO_REQUIRED_PRICE_UNKNOWN)

        for rec in recs:
            await price_service.save_recommendation(
                rec=rec,
                user_id=user.id,
                marketplace_account_id=marketplace_account_id,
            )

        await session.commit()

        return RedirectResponse(
            url=(
                f"/web/mrc-pricing/auto-promotions/recommendations"
                f"?marketplace_account_id={marketplace_account_id}"
                f"&generated=1&total={total}&set_price={set_price}"
                f"&price_ok={price_ok}&violation={violation}"
                f"&min_violation={min_violation}&unknown={unknown}"
            ),
            status_code=303,
        )
    except Exception:
        logger.exception(
            "auto_promo_recommendations_build_failed",
            extra={"user_id": user.id},
        )
        return RedirectResponse(
            url="/web/mrc-pricing/auto-promotions/recommendations?error=build",
            status_code=303,
        )


@router.get(
    "/mrc-pricing/auto-promotions/recommendations/export",
    response_model=None,
)
async def auto_promo_recommendations_export(
    user=CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    marketplace_account_id: int | None = Query(None),
):
    """Export auto promotion recommendations to Excel."""
    try:
        access = await FeatureAccessService(session).can_use_feature(
            user.id, FeatureCode.MRC_PRICING
        )
        if not access.allowed:
            return render_page(
                "Ошибка",
                user.first_name or user.username or str(user.telegram_id),
                _feature_locked_content(access),
                active_path="/web/mrc-pricing",
            )

        import tempfile
        from openpyxl import Workbook
        from pathlib import Path

        from app.services.pricing.wb_auto_promo_price_service import (
            WbAutoPromoPriceService,
        )
        from app.services.pricing.wb_price_update_service import (
            WbPriceUpdateService,
        )

        if marketplace_account_id is None:
            first_account = await session.execute(
                select(MarketplaceAccount.id).where(
                    MarketplaceAccount.user_id == user.id,
                    MarketplaceAccount.marketplace == Marketplace.WB,
                    MarketplaceAccount.is_active.is_(True),
                ).limit(1)
            )
            marketplace_account_id = first_account.scalar_one_or_none()

        preview = []
        if marketplace_account_id:
            price_service = WbAutoPromoPriceService(session)
            recs = await price_service.build_recommendations_for_conditions(
                user_id=user.id,
                marketplace_account_id=marketplace_account_id,
            )
            for rec in recs:
                await price_service.save_recommendation(
                    rec=rec,
                    user_id=user.id,
                    marketplace_account_id=marketplace_account_id,
                )

            update_service = WbPriceUpdateService(session)
            preview = await update_service.prepare_price_changes(
                user_id=user.id,
                marketplace_account_id=marketplace_account_id,
            )

        await session.commit()

        wb = Workbook()
        ws = wb.active
        ws.title = "Рекомендации"

        headers = [
            "Товар", "nmID", "Артикул продавца", "Автоакция",
            "МРЦ", "Текущая цена WB", "Цена входа",
            "minPrice", "Нижняя граница МРЦ", "Верхняя граница МРЦ",
            "Рекомендуемая цена", "Статус", "Причина",
        ]
        ws.append(headers)

        for p in preview:
            ws.append([
                (p.get("title") or "")[:100],
                p.get("wb_nm_id", ""),
                p.get("seller_article") or "",
                p.get("promotion_name") or "",
                float(p["mrc_price"]) if p.get("mrc_price") else "",
                float(p["current_wb_price"]) if p.get("current_wb_price") else "",
                float(p["required_price"]) if p.get("required_price") else "",
                float(p["min_price"]) if p.get("min_price") else "",
                float(p["mrc_lower_bound"]) if p.get("mrc_lower_bound") else "",
                float(p["mrc_upper_bound"]) if p.get("mrc_upper_bound") else "",
                float(p["recommended_price"]) if p.get("recommended_price") else "",
                "Можно изменить" if p.get("can_change") else (p.get("skip_reason") or "Пропущено"),
                p.get("skip_reason") or "",
            ])

        tmp = Path(tempfile.gettempdir()) / f"auto_promo_recommendations_{user.id}.xlsx"
        wb.save(str(tmp))

        return FileResponse(
            path=str(tmp),
            filename=tmp.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception:
        logger.exception(
            "auto_promo_recommendations_export_failed",
            extra={"user_id": user.id},
        )
        return RedirectResponse(
            url="/web/mrc-pricing/auto-promotions/recommendations?error=export",
            status_code=303,
        )

        return render_page(
            "Рекомендации по автоакциям WB",
            user.first_name or user.username or str(user.telegram_id),
            _auto_promo_recommendations_content(
                recommendations, preview, accounts, marketplace_account_id
            ),
            active_path="/web/mrc-pricing",
        )
    except Exception:
        logger.exception(
            "auto_promo_recommendations_failed",
            extra={"user_id": user.id},
        )
        return render_page(
            "Ошибка — Рекомендации",
            user.first_name or user.username or str(user.telegram_id),
            '<div class="card"><h2>Не удалось загрузить рекомендации</h2>'
            '<p>Ошибка записана в лог.</p>'
            '<p><a href="/web/mrc-pricing" class="button primary">'
            "Вернуться</a></p></div>",
            active_path="/web/mrc-pricing",
        )


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

    # Safe defaults for all stats variables
    has_active_auto_promotions = False
    active_auto_promotions_count = 0
    active_regular_promotions_count = 0
    active_promotions_count = 0
    nomenclatures_count = 0
    last_nomenclatures_sync_at: str | None = None
    nomenclatures_synced = False
    has_sync_errors = False

    # Fetch promotion stats FIRST (needed before product enrichment)
    try:
        auto_promos_result = await session.execute(
            select(func.count(WbPromotion.id))
            .join(MarketplaceAccount, MarketplaceAccount.id == WbPromotion.marketplace_account_id)
            .where(MarketplaceAccount.user_id == user_id)
            .where(WbPromotion.promotion_type == "auto")
            .where(WbPromotion.start_datetime <= now_utc)
            .where(WbPromotion.end_datetime >= now_utc)
        )
        active_auto_promotions_count = int(auto_promos_result.scalar_one() or 0)
        has_active_auto_promotions = active_auto_promotions_count > 0
    except Exception:
        logger.exception("auto_promo_count_query_failed")

    try:
        regular_promos_result = await session.execute(
            select(func.count(WbPromotion.id))
            .join(MarketplaceAccount, MarketplaceAccount.id == WbPromotion.marketplace_account_id)
            .where(MarketplaceAccount.user_id == user_id)
            .where(WbPromotion.promotion_type != "auto")
            .where(WbPromotion.promotion_type != "")
            .where(WbPromotion.start_datetime <= now_utc)
            .where(WbPromotion.end_datetime >= now_utc)
        )
        active_regular_promotions_count = int(regular_promos_result.scalar_one() or 0)
    except Exception:
        logger.exception("regular_promo_count_query_failed")

    active_promotions_count = active_auto_promotions_count + active_regular_promotions_count

    try:
        nomenclatures_count_result = await session.execute(
            select(func.count(WbPromotionNomenclature.id))
            .join(MarketplaceAccount, MarketplaceAccount.id == WbPromotionNomenclature.marketplace_account_id)
            .where(MarketplaceAccount.user_id == user_id)
        )
        nomenclatures_count = int(nomenclatures_count_result.scalar_one() or 0)
        nomenclatures_synced = nomenclatures_count > 0
    except Exception:
        logger.exception("nomenclatures_count_query_failed")

    has_sync_errors = (
        active_regular_promotions_count > 0
        and nomenclatures_count == 0
    )

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

    # Single batch query for all promo nomenclatures (including auto promotions)
    promo_map: dict[tuple[int, int], tuple[WbPromotionNomenclature, str, datetime | None, str | None]] = {}
    if nm_ids_to_lookup:
        conditions = [
            (WbPromotionNomenclature.marketplace_account_id == acct_id)
            & (WbPromotionNomenclature.wb_nm_id == nm_id)
            for acct_id, nm_id in nm_ids_to_lookup
        ]
        nomenclature_query = (
            select(WbPromotionNomenclature, WbPromotion.name, WbPromotion.end_datetime, WbPromotion.promotion_type)
            .join(
                WbPromotion,
                (WbPromotion.wb_promotion_id == WbPromotionNomenclature.wb_promotion_id)
                & (WbPromotion.marketplace_account_id == WbPromotionNomenclature.marketplace_account_id),
            )
            .where(
                or_(*conditions),
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
        for nom, promo_name, promo_end_dt, promo_type in nomenclature_result.all():
            key = (nom.marketplace_account_id, nom.wb_nm_id)
            if key not in promo_map:
                promo_map[key] = (nom, promo_name or "", promo_end_dt, promo_type)

    # Batch lookup for wb_product_prices
    from app.models.domain import WbProductPrice

    wb_prices_map: dict[tuple[int, int], WbProductPrice] = {}
    if nm_ids_to_lookup:
        wb_prices_conditions = [
            (WbProductPrice.marketplace_account_id == acct_id)
            & (WbProductPrice.wb_nm_id == nm_id)
            for acct_id, nm_id in nm_ids_to_lookup
        ]
        wb_prices_query = (
            select(WbProductPrice)
            .where(or_(*wb_prices_conditions))
        )
        wb_prices_result = await session.execute(wb_prices_query)
        for wp in wb_prices_result.scalars().all():
            key = (wp.marketplace_account_id, wp.wb_nm_id)
            if key not in wb_prices_map:
                wb_prices_map[key] = wp

    # Enrich with MRC calculation and promo data
    rows = []
    products_with_promo = 0
    products_limited_by_mrc = 0
    products_limited_by_min = 0

    # Pre-load auto promo price service for products without nomenclature
    auto_price_service = WbAutoPromoPriceService(session)

    # Collect account IDs that have active auto promotions
    accounts_with_auto: dict[int, list[WbPromotion]] = {}
    if has_active_auto_promotions:
        auto_promos_result = await session.execute(
            select(WbPromotion).where(
                WbPromotion.marketplace_account_id.in_(
                    select(MarketplaceAccount.id).where(MarketplaceAccount.user_id == user_id)
                ),
                WbPromotion.promotion_type == "auto",
                WbPromotion.start_datetime <= now_utc,
                WbPromotion.end_datetime >= now_utc,
            )
        )
        for promo in auto_promos_result.scalars().all():
            accounts_with_auto.setdefault(promo.marketplace_account_id, []).append(promo)

    for product, account_name in product_rows:
        mrc_result = None
        has_active_promo = False
        promo_name = None
        promo_plan_price = None
        promo_end_date = None
        promo_in_action = None
        promo_type = None

        auto_promo_status: str | None = None
        auto_promo_reason: str | None = None
        auto_promo_required_price: Decimal | None = None
        auto_promo_recommended_price: Decimal | None = None

        wb_current_price: Decimal | None = None
        wb_current_discount: int | None = None
        wb_current_discounted_price: Decimal | None = None
        wb_prices_synced_at: str | None = None

        wb_nm_id_for_product = _extract_nm_id(product) if product.mrc_price and product.mrc_price > 0 else None
        if wb_nm_id_for_product:
            wb_key = (product.marketplace_account_id, wb_nm_id_for_product)
            wb_price_entry = wb_prices_map.get(wb_key)
            if wb_price_entry:
                wb_current_price = wb_price_entry.discounted_price
                wb_current_discount = wb_price_entry.discount
                wb_current_discounted_price = wb_price_entry.discounted_price
                if wb_price_entry.synced_at:
                    wb_prices_synced_at = format_datetime_for_user(wb_price_entry.synced_at, "Europe/Moscow", "%d.%m.%Y %H:%M")

        if product.mrc_price and product.mrc_price > 0:
            promo_data = product_nm_map.get(product.id)
            promo_nomenclature = None
            if promo_data and promo_data in promo_map:
                promo_nomenclature, promo_name, promo_end_dt, promo_type = promo_map[promo_data]

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

            # If no promo nomenclature found but auto promotions exist, compute auto promo status
            if not has_active_promo and has_active_auto_promotions:
                acct_auto_promos = accounts_with_auto.get(product.marketplace_account_id, [])
                if acct_auto_promos:
                    required_price = await _find_auto_promo_required_price(
                        session=session,
                        marketplace_account_id=product.marketplace_account_id,
                        wb_nm_id=wb_nm_id_for_product,
                        active_promos=acct_auto_promos,
                    )

                    auto_rec = await auto_price_service.build_recommendation(
                        product=product,
                        current_wb_price=wb_current_price,
                        required_price=required_price,
                    )
                    auto_promo_status = auto_rec.status
                    auto_promo_reason = auto_rec.reason
                    auto_promo_required_price = auto_rec.required_price
                    auto_promo_recommended_price = auto_rec.recommended_price

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
                promo_type=promo_type,
                auto_promo_status=auto_promo_status,
                auto_promo_reason=auto_promo_reason,
                auto_promo_required_price=auto_promo_required_price,
                auto_promo_recommended_price=auto_promo_recommended_price,
                wb_current_price=wb_current_price,
                wb_current_discount=wb_current_discount,
                wb_current_discounted_price=wb_current_discounted_price,
                wb_prices_synced_at=wb_prices_synced_at,
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

    # Last promotions sync time
    last_promo_sync_result = await session.execute(
        select(func.max(WbPromotion.synced_at))
        .join(MarketplaceAccount, MarketplaceAccount.id == WbPromotion.marketplace_account_id)
        .where(MarketplaceAccount.user_id == user_id)
    )
    last_promo_sync = last_promo_sync_result.scalar_one_or_none()
    last_promotions_sync_at = format_datetime_for_user(last_promo_sync, "Europe/Moscow") if last_promo_sync else None

    # Last nomenclatures sync time
    last_nom_sync_result = await session.execute(
        select(func.max(WbPromotionNomenclature.synced_at))
        .join(MarketplaceAccount, MarketplaceAccount.id == WbPromotionNomenclature.marketplace_account_id)
        .where(MarketplaceAccount.user_id == user_id)
    )
    last_nom_sync = last_nom_sync_result.scalar_one_or_none()
    last_nomenclatures_sync_at = format_datetime_for_user(last_nom_sync, "Europe/Moscow") if last_nom_sync else None

    # Auto promo recommendation counts
    auto_rec_set_price = 0
    auto_rec_price_ok = 0
    auto_rec_violation = 0
    auto_rec_min_violation = 0
    auto_rec_total = 0
    auto_conditions_count = 0

    if has_active_auto_promotions:
        account_ids = select(MarketplaceAccount.id).where(
            MarketplaceAccount.user_id == user_id,
            MarketplaceAccount.marketplace == Marketplace.WB,
            MarketplaceAccount.is_active.is_(True),
        )
        try:
            from app.models.domain import WbAutoPromoPriceRecommendation, WbAutoPromotionCondition

            rec_result = await session.execute(
                select(
                    func.count(WbAutoPromoPriceRecommendation.id),
                    func.sum(func.cast(
                        (WbAutoPromoPriceRecommendation.status == STATUS_AUTO_SET_PRICE), Integer
                    )),
                    func.sum(func.cast(
                        (WbAutoPromoPriceRecommendation.status == STATUS_AUTO_PRICE_OK), Integer
                    )),
                    func.sum(func.cast(
                        (WbAutoPromoPriceRecommendation.status == STATUS_AUTO_PRICE_VIOLATION), Integer
                    )),
                    func.sum(func.cast(
                        (WbAutoPromoPriceRecommendation.status == STATUS_AUTO_MIN_PRICE_VIOLATION), Integer
                    )),
                ).where(
                    WbAutoPromoPriceRecommendation.marketplace_account_id.in_(account_ids),
                )
            )
            rec_row = rec_result.one()
            auto_rec_total = int(rec_row[0] or 0)
            auto_rec_set_price = int(rec_row[1] or 0)
            auto_rec_price_ok = int(rec_row[2] or 0)
            auto_rec_violation = int(rec_row[3] or 0)
            auto_rec_min_violation = int(rec_row[4] or 0)

            cond_result = await session.execute(
                select(func.count(WbAutoPromotionCondition.id)).where(
                    WbAutoPromotionCondition.marketplace_account_id.in_(account_ids),
                )
            )
            auto_conditions_count = int(cond_result.scalar_one() or 0)
        except Exception:
            logger.exception("auto_promo_counts_query_failed")

    # WB prices sync stats
    wb_prices_synced = False
    last_wb_prices_sync_at: str | None = None
    wb_prices_count = 0
    try:
        from app.models.domain import WbProductPrice

        wb_prices_count_result = await session.execute(
            select(func.count(WbProductPrice.id))
            .join(MarketplaceAccount, MarketplaceAccount.id == WbProductPrice.marketplace_account_id)
            .where(MarketplaceAccount.user_id == user_id)
        )
        wb_prices_count = int(wb_prices_count_result.scalar_one() or 0)
        wb_prices_synced = wb_prices_count > 0

        if wb_prices_synced:
            last_wb_sync_result = await session.execute(
                select(func.max(WbProductPrice.synced_at))
                .join(MarketplaceAccount, MarketplaceAccount.id == WbProductPrice.marketplace_account_id)
                .where(MarketplaceAccount.user_id == user_id)
            )
            last_wb_sync = last_wb_sync_result.scalar_one_or_none()
            last_wb_prices_sync_at = format_datetime_for_user(last_wb_sync, "Europe/Moscow") if last_wb_sync else None
    except Exception:
        logger.exception("wb_prices_counts_query_failed")

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
        nomenclatures_synced=nomenclatures_synced,
        has_active_auto_promotions=has_active_auto_promotions,
        active_promotions_count=active_promotions_count,
        active_regular_promotions_count=active_regular_promotions_count,
        active_auto_promotions_count=active_auto_promotions_count,
        nomenclatures_count=nomenclatures_count,
        last_promotions_sync_at=last_promotions_sync_at,
        last_nomenclatures_sync_at=last_nomenclatures_sync_at,
        has_sync_errors=has_sync_errors,
        auto_rec_set_price=auto_rec_set_price,
        auto_rec_price_ok=auto_rec_price_ok,
        auto_rec_violation=auto_rec_violation,
        auto_rec_min_violation=auto_rec_min_violation,
        auto_rec_total=auto_rec_total,
        auto_conditions_count=auto_conditions_count,
        wb_prices_synced=wb_prices_synced,
        last_wb_prices_sync_at=last_wb_prices_sync_at,
        wb_prices_count=wb_prices_count,
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

        nm_id_subquery = (
            select(cast(WbPromotionNomenclature.wb_nm_id, String))
            .where(
                WbPromotionNomenclature.marketplace_account_id == promo.marketplace_account_id,
                WbPromotionNomenclature.wb_promotion_id == promo.wb_promotion_id,
            )
        )

        matched_result = await session.execute(
            select(func.count(Product.id)).where(
                Product.user_id == user_id,
                Product.marketplace == Marketplace.WB,
                Product.is_active.is_(True),
                Product.marketplace_account_id == promo.marketplace_account_id,
                or_(
                    Product.marketplace_article.in_(nm_id_subquery),
                    Product.external_product_id.in_(nm_id_subquery),
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


async def _find_auto_promo_required_price(
    session: AsyncSession,
    marketplace_account_id: int,
    wb_nm_id: int | None,
    active_promos: list[WbPromotion],
) -> Decimal | None:
    """Find the required price for a product from active auto promotions."""
    if wb_nm_id is None or not active_promos:
        return None

    # First check user-defined conditions (manual or import)
    from app.models.domain import WbAutoPromotionCondition

    cond_result = await session.execute(
        select(WbAutoPromotionCondition.required_price)
        .where(
            WbAutoPromotionCondition.marketplace_account_id == marketplace_account_id,
            WbAutoPromotionCondition.wb_nm_id == wb_nm_id,
            WbAutoPromotionCondition.required_price.isnot(None),
            WbAutoPromotionCondition.required_price > 0,
        )
        .limit(1)
    )
    cond_price = cond_result.scalar_one_or_none()
    if cond_price is not None:
        return cond_price

    # Fallback: check nomenclatures (for regular promotions that happen to be active)
    active_promo_ids = [p.wb_promotion_id for p in active_promos]

    result = await session.execute(
        select(WbPromotionNomenclature.plan_price)
        .where(
            WbPromotionNomenclature.marketplace_account_id == marketplace_account_id,
            WbPromotionNomenclature.wb_nm_id == wb_nm_id,
            WbPromotionNomenclature.wb_promotion_id.in_(active_promo_ids),
            WbPromotionNomenclature.plan_price.isnot(None),
            WbPromotionNomenclature.plan_price > 0,
        )
        .order_by(WbPromotionNomenclature.plan_price.asc())
        .limit(1)
    )
    price = result.scalar_one_or_none()
    if price is not None:
        return price

    for promo in active_promos:
        if promo.raw_payload and "_details" in promo.raw_payload:
            details = promo.raw_payload["_details"]
            for key in ("planPrice", "requiredPrice", "maxPrice"):
                val = details.get(key)
                if val is not None:
                    try:
                        return Decimal(str(val))
                    except Exception:
                        continue

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
        )
        if data.last_nomenclatures_sync_at:
            parts.append(
                f" | Товары акций: <b>{data.last_nomenclatures_sync_at}</b>"
            )
        if data.last_wb_prices_sync_at:
            parts.append(
                f" | Цены WB: <b>{data.last_wb_prices_sync_at}</b> ({data.wb_prices_count} товаров)"
            )
        parts.append("</p>")
    else:
        parts.append(
            '<p style="margin-bottom:12px;font-size:13px;color:#f59e0b">'
            "⚠️ Синхронизация акций ещё не запускалась"
            "</p>"
        )

    # WB prices not synced warning
    if not data.wb_prices_synced:
        parts.append(
            '<div style="padding:12px 16px;margin-bottom:16px;border-radius:8px;font-size:14px;'
            'background:#fef3c7;color:#92400e">'
            "⚠️ <b>Текущие цены WB не загружены</b><br>"
            "Нажмите «💰 Обновить цены WB» для загрузки текущих цен из Wildberries."
            "</div>"
        )

    # Warning if nomenclatures not synced
    if not data.nomenclatures_synced:
        if data.active_auto_promotions_count > 0 and data.active_regular_promotions_count == 0:
            parts.append(
                '<div style="padding:12px 16px;margin-bottom:16px;border-radius:8px;font-size:14px;'
                'background:#dbeafe;color:#1e40af">'
                f"ℹ️ <b>Автоакции WB найдены ({data.active_auto_promotions_count})</b><br>"
                "Товары автоматических акций загружаются. Если товары не отображаются, "
                "нажмите «Обновить акции WB» для обновления."
                "</div>"
            )
        elif data.active_promotions_count > 0:
            parts.append(
                '<div style="padding:12px 16px;margin-bottom:16px;border-radius:8px;font-size:14px;'
                'background:#fef3c7;color:#92400e">'
                f"⚠️ <b>Активных акций: {data.active_promotions_count}</b><br>"
                "Акции WB найдены, но список товаров внутри акций ещё не загружен. "
                "Нажмите «Обновить акции WB» для загрузки товаров."
                "</div>"
            )
        else:
            parts.append(
                '<div style="padding:12px 16px;margin-bottom:16px;border-radius:8px;font-size:14px;'
                'background:#fee2e2;color:#991b1b">'
                "⚠️ <b>Товары акций не синхронизированы</b><br>"
                "Нажмите «Обновить акции WB» для загрузки акций и товаров."
                "</div>"
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
        f'<div class="kpi-card"><div class="kpi-value" style="color:#8b5cf6">{data.active_promotions_count}</div>'
        '<div class="kpi-label">Активных акций</div></div>'
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
        '<button type="submit" class="button primary" title="allPromo=true — все акции включая уже участвующие">🔄 Обновить акции WB</button>'
        "</form>"
    )
    parts.append(
        '<form method="post" action="/web/mrc-pricing/sync-promotions-all" style="display:inline">'
        '<button type="submit" class="button" title="allPromo=false — только доступные для участия">🔍 Только доступные акции</button>'
        "</form>"
    )
    parts.append(
        '<form method="post" action="/web/mrc-pricing/sync-wb-prices" style="display:inline">'
        '<button type="submit" class="button" style="background:#e0f2fe;color:#0369a1" title="Обновить текущие цены WB из API">💰 Обновить цены WB</button>'
        "</form>"
    )
    parts.append(
        '<a href="/web/wb-promotions" class="button">🎯 Акции WB</a>'
    )
    if data.has_active_auto_promotions:
        parts.append(
            '<a href="/web/mrc-pricing/auto-promotions/conditions" '
            'class="button" style="background:#fef3c7;color:#92400e">'
            "📥 Условия автоакций</a>"
        )
        parts.append(
            '<a href="/web/mrc-pricing/auto-promotions/recommendations" '
            'class="button" style="background:#dbeafe;color:#1e40af">'
            "🤖 Рекомендации</a>"
        )
    parts.append(
        '<a href="/web/mrc-pricing/settings" class="button">⚙️ Настройки МРЦ</a>'
    )
    parts.append(
        '<a href="/web/mrc-pricing/export" class="button">📥 Скачать отчёт</a>'
    )
    parts.append("</div>")

    # Auto promo recommendations summary
    if data.has_active_auto_promotions and data.auto_rec_total > 0:
        parts.append(
            '<div class="card" style="margin-bottom:16px;background:#f0f9ff;'
            'border-left:4px solid #3b82f6">'
        )
        parts.append("<h3>🤖 Рекомендации автоакций</h3>")
        parts.append(
            '<p style="margin-bottom:12px">'
            f"Можно изменить цену: <b>{data.auto_rec_set_price}</b> | "
            f"Уже подходят: <b>{data.auto_rec_price_ok}</b> | "
            f"Нарушения МРЦ: <b>{data.auto_rec_violation}</b> | "
            f"Нарушения minPrice: <b>{data.auto_rec_min_violation}</b>"
            "</p>"
        )
        parts.append(
            '<a href="/web/mrc-pricing/auto-promotions/recommendations" '
            'class="button" style="background:#3b82f6;color:white">'
            "Открыть рекомендации</a>"
        )
        parts.append("</div>")
    elif data.has_active_auto_promotions and data.auto_conditions_count == 0:
        parts.append(
            '<div class="card" style="margin-bottom:16px;background:#dbeafe;'
            'border-left:4px solid #1e40af">'
        )
        parts.append(
            '<p style="margin:0">ℹ️ <b>Автоакции WB найдены</b> — нужна цена входа. '
            '<a href="/web/mrc-pricing/auto-promotions/conditions">Импортируйте условия</a> '
            "для управления ценами.</p>"
        )
        parts.append("</div>")

    # Mass import block
    parts.append('<div class="card" style="margin-bottom:16px;background:#f8fafc">')
    parts.append("<h3>📦 Массовая загрузка МРЦ</h3>")
    parts.append(
        '<p class="text-muted" style="margin-bottom:12px">'
        "Чтобы не заполнять МРЦ вручную по одному товару, скачайте Excel-шаблон, "
        "заполните колонку <b>new_mrc_price</b> и загрузите файл обратно."
        "</p>"
    )
    parts.append('<div style="display:flex;gap:8px;flex-wrap:wrap">')
    parts.append(
        '<a href="/web/mrc-pricing/export-template" class="button primary">📥 Скачать шаблон МРЦ</a>'
    )
    parts.append(
        '<form method="post" action="/web/mrc-pricing/import" enctype="multipart/form-data" style="display:inline">'
        '<input type="file" name="file" accept=".xlsx" style="padding:6px">'
        '<button type="submit" class="button">📤 Загрузить МРЦ из файла</button>'
        "</form>"
    )
    parts.append("</div></div>")

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
        parts.append("<th>Текущая цена WB</th>")
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

            # Current WB prices
            if row.wb_current_price is not None:
                wb_discount_str = f"{row.wb_current_discount}%" if row.wb_current_discount is not None else "—"
                wb_synced = row.wb_prices_synced_at or ""
                parts.append(
                    f"<td><small>"
                    f"<b>{row.wb_current_discounted_price:.0f} ₽</b> (скидка {wb_discount_str})<br>"
                    f"<span class='text-muted' style='font-size:11px'>обновлено: {wb_synced}</span>"
                    f"</small></td>"
                )
            else:
                parts.append(
                    "<td><small style='color:#f59e0b'>Цена WB не загружена<br>"
                    "<a href='#' onclick='document.querySelector(\"form[action*=sync-wb-prices]\")?.querySelector(\"button\")?.click();return false' style='font-size:11px'>Обновить цены WB</a>"
                    "</small></td>"
                )

            # Promo info
            if row.has_active_promo:
                promo_name = escape(row.promo_name or "Акция WB")
                promo_price = f"{row.promo_plan_price:.0f}" if row.promo_plan_price else "—"
                is_auto = row.promo_type and row.promo_type.lower() == "auto"
                if is_auto:
                    in_action_text = "Автоакция ✅"
                    parts.append(
                        f"<td><small>{promo_name}<br>{promo_price} ₽ ({in_action_text})</small></td>"
                    )
                else:
                    in_action_text = "Участвует" if row.promo_in_action else "Подходит"
                    parts.append(
                        f"<td><small>{promo_name}<br>{promo_price} ₽ ({in_action_text})</small></td>"
                    )
            elif row.auto_promo_status:
                # Auto promotion status computed
                if row.auto_promo_status == STATUS_AUTO_SET_PRICE:
                    rec_price = f"{row.auto_promo_recommended_price:.0f}" if row.auto_promo_recommended_price else "?"
                    parts.append(
                        f"<td><small style='color:#3b82f6'>Автоакция WB:<br>цена входа {rec_price} ₽</small></td>"
                    )
                elif row.auto_promo_status == STATUS_AUTO_PRICE_OK:
                    parts.append(
                        "<td><small style='color:#10b981'>Автоакция WB:<br>цена подходит</small></td>"
                    )
                elif row.auto_promo_status in (STATUS_AUTO_PRICE_VIOLATION, STATUS_AUTO_MIN_PRICE_VIOLATION):
                    parts.append(
                        "<td><small style='color:#ef4444'>Автоакция WB:<br>цена ниже допустимой</small></td>"
                    )
                elif row.auto_promo_status == STATUS_AUTO_REQUIRED_PRICE_UNKNOWN:
                    wb_nm_id_for_product = nm_id
                    if wb_nm_id_for_product:
                        parts.append(
                            f"<td><small style='color:#f59e0b'>Автоакции WB найдены,<br>нужна цена входа<br>"
                            f"<form method='post' action='/web/mrc-pricing/auto-promotions/conditions/manual' style='margin:4px 0'>"
                            f"<input type='hidden' name='wb_nm_id' value='{wb_nm_id_for_product}'>"
                            f"<input type='hidden' name='marketplace_account_id' value='{product.marketplace_account_id}'>"
                            f"<input type='hidden' name='promotion_name' value=''>"
                            f"<input type='number' name='required_price' step='1' min='1' placeholder='Цена' style='width:70px;padding:2px 4px;font-size:11px;border:1px solid #d1d5db;border-radius:4px'>"
                            f"<button type='submit' style='font-size:11px;padding:2px 6px;background:#f59e0b;color:white;border:none;border-radius:4px;cursor:pointer'>✓</button>"
                            f"</form>"
                            f"</small></td>"
                        )
                    else:
                        parts.append(
                            "<td><small style='color:#f59e0b'>Автоакции WB найдены,<br>нужна цена входа<br>"
                            "<span class='text-muted' style='font-size:11px'>nmID не найден</span>"
                            "</small></td>"
                        )
                else:
                    parts.append(
                        "<td><small class='text-muted'>Автоакция WB:<br>ожидание синхронизации</small></td>"
                    )
            else:
                # No promo nomenclature found for this product
                has_any_active_promo = data.active_promotions_count > 0
                has_regular_promo = data.active_regular_promotions_count > 0
                has_auto_promo = data.active_auto_promotions_count > 0
                noms_synced = data.nomenclatures_count > 0

                if not has_any_active_promo:
                    parts.append("<td><small class='text-muted'>Нет акции</small></td>")
                elif has_auto_promo and not noms_synced:
                    parts.append(
                        "<td><small class='text-muted'>Автоакции WB найдены,<br>участие уточняется</small></td>"
                    )
                elif has_auto_promo and noms_synced and not has_regular_promo:
                    parts.append(
                        "<td><small class='text-muted'>Автоакция WB:<br>требуется проверка цены</small></td>"
                    )
                elif has_regular_promo and not noms_synced:
                    parts.append(
                        "<td><small class='text-muted'>Товары акций не<br>синхронизированы</small></td>"
                    )
                elif has_regular_promo and noms_synced:
                    if has_auto_promo:
                        parts.append(
                            "<td><small class='text-muted'>Нет в регулярных;<br>автоакция уточняется</small></td>"
                        )
                    else:
                        parts.append("<td><small class='text-muted'>Нет акции</small></td>")
                else:
                    # Fallback
                    parts.append("<td><small class='text-muted'>Статус акции уточняется</small></td>")

            # Status badge
            is_auto_promo = row.promo_type and row.promo_type.lower() == "auto"
            if row.auto_promo_status == STATUS_AUTO_SET_PRICE:
                parts.append(
                    '<td><span class="badge" style="background:#dbeafe;color:#1e40af">🤖 Можно войти</span></td>'
                )
            elif row.auto_promo_status == STATUS_AUTO_PRICE_OK:
                parts.append(
                    '<td><span class="badge" style="background:#d1fae5;color:#065f46">🤖 В автоакции</span></td>'
                )
            elif row.auto_promo_status in (STATUS_AUTO_PRICE_VIOLATION, STATUS_AUTO_MIN_PRICE_VIOLATION):
                parts.append(
                    '<td><span class="badge" style="background:#fee2e2;color:#991b1b">🤖 Нарушение МРЦ</span></td>'
                )
            elif row.auto_promo_status == STATUS_AUTO_REQUIRED_PRICE_UNKNOWN:
                parts.append(
                    '<td><span class="badge" style="background:#fef3c7;color:#92400e">🤖 Нужна цена</span></td>'
                )
            elif row.mrc_result:
                if row.mrc_result.is_limited_by_min_price:
                    parts.append(
                        '<td><span class="badge" style="background:#fef3c7;color:#92400e">⚠️ minPrice</span></td>'
                    )
                elif row.mrc_result.is_limited_by_mrc_rule:
                    parts.append(
                        '<td><span class="badge" style="background:#fef3c7;color:#92400e">⚠️ 10% лимит</span></td>'
                    )
                elif row.mrc_result.is_promo_applied:
                    if is_auto_promo:
                        parts.append(
                            '<td><span class="badge" style="background:#dbeafe;color:#1e40af">🤖 Автоакция</span></td>'
                        )
                    else:
                        parts.append(
                            '<td><span class="badge" style="background:#d1fae5;color:#065f46">✅ Акция</span></td>'
                        )
                else:
                    if is_auto_promo:
                        parts.append(
                            '<td><span class="badge" style="background:#dbeafe;color:#1e40af">🤖 Автоакция</span></td>'
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
                    f'<tr><td colspan="11"><small style="color:#f59e0b">⚠️ {reason}</small></td></tr>'
                )

            # Auto promo recommendation row
            if row.auto_promo_status == STATUS_AUTO_SET_PRICE and row.auto_promo_reason:
                reason = escape(row.auto_promo_reason)
                parts.append(
                    f'<tr><td colspan="11"><small style="color:#3b82f6">🤖 {reason}</small></td></tr>'
                )
            elif row.auto_promo_status in (STATUS_AUTO_PRICE_VIOLATION, STATUS_AUTO_MIN_PRICE_VIOLATION) and row.auto_promo_reason:
                reason = escape(row.auto_promo_reason)
                parts.append(
                    f'<tr><td colspan="11"><small style="color:#ef4444">🤖 {reason}</small></td></tr>'
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

    # JavaScript for select all and sync button cooldown
    parts.append("""
    <script>
    document.getElementById('select-all')?.addEventListener('change', function() {
        document.querySelectorAll('.product-checkbox').forEach(cb => cb.checked = this.checked);
    });

    // Sync button cooldown
    (function() {
        const syncForms = document.querySelectorAll('form[action*="sync-promotions"]');
        syncForms.forEach(form => {
            const btn = form.querySelector('button[type="submit"]');
            if (!btn) return;
            form.addEventListener('submit', function() {
                btn.disabled = true;
                btn.textContent = '⏳ Синхронизация...';
                btn.style.opacity = '0.6';
                btn.style.cursor = 'not-allowed';
            });
        });
    })();
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
            const allPromo = params.get('all_promo') || 'true';
            const rawPromos = params.get('raw_promos') || '0';
            const promos = params.get('promos') || '0';
            const noms = params.get('nomenclatures') || '0';
            const autoSkipped = params.get('auto_skipped') || '0';
            const rateLimits = params.get('rate_limits') || '0';
            const regularProcessed = params.get('regular_processed') || '0';
            const regularEmpty = params.get('regular_empty') || '0';
            const autoDetailsFailed = params.get('auto_details_failed') || '0';
            const modeText = allPromo === 'true' ? 'все акции (allPromo=true)' : 'только доступные (allPromo=false)';
            msg = '✅ Синхронизация акций завершена (' + modeText + ')\\n'
                + 'WB вернул акций: ' + rawPromos
                + ' | Сохранено: ' + promos
                + ' | Автоакций: ' + autoSkipped
                + ' | Товаров в акциях: ' + noms
                + ' | Regular обработано: ' + regularProcessed
                + ' | Regular пустых: ' + regularEmpty
                + ' | Auto details ошибок: ' + autoDetailsFailed;
            if (rateLimits !== '0') {
                msg += '\\n⚠️ Rate limit срабатываний: ' + rateLimits;
            }
            if (rawPromos === '0' && allPromo === 'false') {
                msg += '\\n💡 WB вернул 0 доступных акций. Попробуйте основную синхронизацию allPromo=true.';
            }
            if (parseInt(autoSkipped) > 0 && parseInt(noms) === 0) {
                msg += '\\nℹ️ Автоакции найдены, но товары акций не загружены. Это нормально для auto promotions.';
            }
        }
        if (params.get('sync_cooldown') === '1') {
            const message = params.get('message') || 'Синхронизация уже запускалась. Подождите.';
            msg = '⏳ ' + message;
        }
        if (params.get('sync_error') === '1') msg = '❌ Ошибка синхронизации акций';
        if (params.get('condition_set') === '1') {
            const nmId = params.get('wb_nm_id') || '?';
            const price = params.get('required_price') || '?';
            msg = '✅ Цена входа установлена: nmID=' + nmId + ', цена=' + price + ' ₽';
        }
        if (params.get('prices_sync_done') === '1') {
            const fetched = params.get('prices_fetched') || '0';
            const upserted = params.get('prices_upserted') || '0';
            const failed = params.get('accounts_failed') || '0';
            if (parseInt(fetched) === 0) {
                msg = '⚠️ Цены WB не были загружены. Проверьте токен WB и endpoint Prices API.\\nЗагружено: ' + fetched + ' | Сохранено: ' + upserted + ' | Ошибок: ' + failed;
            } else {
                msg = '✅ Цены WB обновлены\\nЗагружено: ' + fetched + ' | Сохранено: ' + upserted + ' | Ошибок: ' + failed;
            }
        }
        if (params.get('prices_sync_error') === '1') msg = '❌ Ошибка синхронизации цен WB';
        if (params.get('error') === 'invalid_mrc') msg = '❌ МРЦ должна быть положительным числом';
        if (params.get('error') === 'no_products_selected') msg = '❌ Выберите товары для массового редактирования';
        if (params.get('export_coming_soon') === '1') msg = '📥 Выгрузка отчёта скоро будет доступна';
        if (params.get('import_done') === '1') {
            const updated = params.get('updated') || '0';
            const cleared = params.get('cleared') || '0';
            const errors = params.get('errors') || '0';
            msg = '✅ МРЦ импортированы\\nОбновлено: ' + updated + ' | Очищено: ' + cleared + ' | Ошибок: ' + errors;
        }
        if (params.get('import_error') === '1') msg = '❌ Ошибка импорта МРЦ';
        if (params.get('import_cancelled') === '1') msg = '❌ Импорт отменён';
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


def _import_preview_content(preview, rows, timezone: str = "Europe/Moscow") -> str:
    """Render MRC import preview page."""
    from app.models.domain import MrcImportRow

    parts = []
    parts.append('<div class="card">')
    parts.append("<h2>📤 Проверка файла МРЦ</h2>")

    updated_count = sum(1 for r in rows if r.status in ("valid", "warning"))
    cleared_count = sum(1 for r in rows if r.status == "valid_clear")
    skipped_count = sum(1 for r in rows if r.status.startswith("skipped"))
    warning_count = sum(1 for r in rows if r.status == "warning")
    error_count = sum(1 for r in rows if r.status == "error")

    parts.append(
        f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px">'
        f'<div class="kpi-card"><div class="kpi-value">{preview.total_rows}</div>'
        '<div class="kpi-label">Всего строк</div></div>'
        f'<div class="kpi-card"><div class="kpi-value" style="color:#10b981">{updated_count}</div>'
        '<div class="kpi-label">Будет обновлено</div></div>'
        f'<div class="kpi-card"><div class="kpi-value" style="color:#f59e0b">{cleared_count}</div>'
        '<div class="kpi-label">Будет очищено</div></div>'
        f'<div class="kpi-card"><div class="kpi-value" style="color:#6b7280">{skipped_count}</div>'
        '<div class="kpi-label">Пропущено</div></div>'
        f'<div class="kpi-card"><div class="kpi-value" style="color:#ef4444">{error_count}</div>'
        '<div class="kpi-label">Ошибок</div></div>'
        f'<div class="kpi-card"><div class="kpi-value" style="color:#f97316">{warning_count}</div>'
        '<div class="kpi-label">Предупреждений</div></div>'
        "</div>"
    )

    error_rows = [r for r in rows if r.status == "error"]
    if error_rows:
        parts.append('<div class="card" style="background:#fee2e2;margin-bottom:16px">')
        parts.append("<h3>⚠️ Ошибки</h3>")
        parts.append("<ul>")
        for row in error_rows[:20]:
            parts.append(f"<li>Строка {row.row_number}: {escape(row.message or '')}</li>")
        if error_count > 20:
            parts.append(f"<li>... и ещё {error_count - 20} ошибок</li>")
        parts.append("</ul></div>")

    warning_rows = [r for r in rows if r.status == "warning"]
    if warning_rows:
        parts.append('<div class="card" style="background:#fef3c7;margin-bottom:16px">')
        parts.append("<h3>⚡ Предупреждения</h3>")
        parts.append("<ul>")
        for row in warning_rows[:10]:
            parts.append(f"<li>Строка {row.row_number}: {escape(row.message or '')}</li>")
        if warning_count > 10:
            parts.append(f"<li>... и ещё {warning_count - 10} предупреждений</li>")
        parts.append("</ul></div>")

    parts.append(
        '<form method="post" action="/web/mrc-pricing/import/confirm" style="display:inline">'
        f'<input type="hidden" name="import_id" value="{preview.import_id}">'
    )
    if error_count == 0 or updated_count > 0 or cleared_count > 0:
        parts.append(
            '<button type="submit" class="button primary" '
            'onclick="return confirm(\'Сохранить МРЦ для выбранных товаров?\')">✅ Подтвердить импорт</button>'
        )
    parts.append("</form>")

    parts.append(
        f' <form method="post" action="/web/mrc-pricing/import/cancel" style="display:inline">'
        f'<input type="hidden" name="import_id" value="{preview.import_id}">'
        '<button type="submit" class="button">❌ Отмена</button>'
        "</form>"
    )

    parts.append(
        ' <a href="/web/mrc-pricing" class="button">⬅️ Вернуться</a>'
    )

    parts.append("</div>")
    return "\n".join(parts)


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


def _mrc_settings_content(
    settings,
    errors: list[str] | None = None,
) -> str:
    """Render MRC settings page."""
    parts = []
    parts.append('<div class="card">')
    parts.append("<h2>⚙️ Настройки МРЦ и акций WB</h2>")

    if errors:
        parts.append('<div class="card" style="background:#fee2e2;margin-bottom:16px">')
        parts.append("<h3>⚠️ Ошибки валидации</h3>")
        parts.append("<ul>")
        for err in errors:
            parts.append(f"<li>{escape(err)}</li>")
        parts.append("</ul></div>")

    parts.append(
        '<form method="post" action="/web/mrc-pricing/settings">'
    )

    # Discount percent
    parts.append('<div style="margin-bottom:16px">')
    parts.append(
        '<label style="display:block;font-weight:600;margin-bottom:4px">'
        "Процент скидки WB, %"
        "</label>"
    )
    parts.append(
        f'<input type="text" name="default_discount_percent" '
        f'value="{settings.default_discount_percent}" '
        'style="width:100px;padding:6px 10px;border:1px solid var(--color-border);border-radius:6px">'
    )
    parts.append(
        '<p class="text-muted" style="margin-top:4px;font-size:13px">'
        "Используется для расчёта скидки WB при формировании полной цены. Диапазон: 0–99."
        "</p>"
    )
    parts.append("</div>")

    # Full price multiplier
    parts.append('<div style="margin-bottom:16px">')
    parts.append(
        '<label style="display:block;font-weight:600;margin-bottom:4px">'
        "Коэффициент полной цены"
        "</label>"
    )
    parts.append(
        f'<input type="text" name="full_price_multiplier" '
        f'value="{settings.full_price_multiplier}" '
        'style="width:100px;padding:6px 10px;border:1px solid var(--color-border);border-radius:6px">'
    )
    parts.append(
        '<p class="text-muted" style="margin-top:4px;font-size:13px">'
        "Полная цена = МРЦ × коэффициент. Диапазон: 1–20."
        "</p>"
    )
    parts.append("</div>")

    # Allowed deviation
    parts.append('<div style="margin-bottom:16px">')
    parts.append(
        '<label style="display:block;font-weight:600;margin-bottom:4px">'
        "Допустимое отклонение цены в акции от МРЦ, %"
        "</label>"
    )
    parts.append(
        f'<input type="text" name="allowed_action_price_deviation_percent" '
        f'value="{settings.allowed_action_price_deviation_percent}" '
        'style="width:100px;padding:6px 10px;border:1px solid var(--color-border);border-radius:6px">'
    )
    parts.append(
        '<p class="text-muted" style="margin-top:4px;font-size:13px">'
        "Если цена в акции отличается от МРЦ больше чем на этот процент — товар требует внимания. Диапазон: 0–100."
        "</p>"
    )
    parts.append("</div>")

    # Auto promo check
    parts.append('<div style="margin-bottom:16px">')
    parts.append(
        '<label style="display:flex;align-items:center;gap:8px">'
        f'<input type="checkbox" name="auto_promo_check_enabled" '
        f'{"checked" if settings.auto_promo_check_enabled else ""}>'
        " Автоматически проверять участие в акциях WB"
        "</label>"
    )
    parts.append("</div>")

    # Auto add to promotions
    parts.append('<div style="margin-bottom:16px">')
    parts.append(
        '<label style="display:flex;align-items:center;gap:8px">'
        f'<input type="checkbox" name="auto_add_to_promotions" '
        f'{"checked" if settings.auto_add_to_promotions else ""}>'
        " Автоматически добавлять товары в подходящие акции WB"
        "</label>"
    )
    parts.append(
        '<p class="text-muted" style="margin-top:4px;font-size:13px">'
        "Товары с нарушением МРЦ не будут добавлены автоматически."
        "</p>"
    )
    parts.append("</div>")

    # Auto price for auto promotions
    parts.append('<div style="margin-bottom:16px;padding:12px;background:#fef3c7;border-radius:8px">')
    parts.append(
        '<label style="display:flex;align-items:center;gap:8px">'
        f'<input type="checkbox" name="auto_price_for_auto_promotions" '
        f'{"checked" if settings.auto_price_for_auto_promotions else ""}>'
        " <b>Автоматически менять цену для входа в автоакции WB</b>"
        "</label>"
    )
    parts.append(
        '<p class="text-muted" style="margin-top:4px;font-size:13px;color:#92400e">'
        "⚠️ Включая автоцену для автоакций WB, вы разрешаете сервису автоматически менять цены товаров, "
        "если новая цена не нарушает МРЦ, minPrice и заданный процент допуска."
        "</p>"
    )
    parts.append("</div>")

    # Buttons
    parts.append('<div style="display:flex;gap:8px;margin-top:24px">')
    parts.append('<button type="submit" class="button primary">💾 Сохранить настройки</button>')
    parts.append('<a href="/web/mrc-pricing" class="button">← Назад</a>')
    parts.append("</div>")

    parts.append("</form></div>")

    # Flash message
    parts.append("""
    <script>
    (function() {
        const params = new URLSearchParams(window.location.search);
        let msg = '';
        if (params.get('saved') === '1') msg = '✅ Настройки МРЦ сохранены';
        if (params.get('error') === '1') msg = '❌ Ошибка сохранения настроек';
        if (msg) {
            const div = document.createElement('div');
            let bgColor = 'background:#fee2e2;color:#991b1b';
            if (msg.startsWith('✅')) bgColor = 'background:#d1fae5;color:#065f46';
            else if (msg.startsWith('⚠️')) bgColor = 'background:#fef3c7;color:#92400e';
            div.style.cssText = 'padding:12px 16px;margin-bottom:16px;border-radius:8px;font-size:14px;white-space:pre-line;' + bgColor;
            div.textContent = msg;
            document.querySelector('.card')?.before(div);
        }
    })();
    </script>
    """)

    return "\n".join(parts)


def _auto_promo_import_content(
    accounts: list,
    selected_account_id: int | None,
) -> str:
    """Render auto promotion import page."""
    parts = []
    parts.append('<div class="card">')
    parts.append("<h2>📥 Импорт условий автоакций WB</h2>")
    parts.append(
        '<p class="text-muted" style="margin-bottom:16px">'
        "Загрузите Excel-файл с ценами входа в автоакции WB. "
        "Система проверит данные и покажет предпросмотр."
        "</p>"
    )

    if not accounts:
        parts.append(
            '<div class="empty-state">'
            '<p>Нет активных аккаунтов WB.</p>'
            "</div></div>"
        )
        return "\n".join(parts)

    parts.append(
        '<form method="post" action="/web/auto-promo-import/preview" '
        'enctype="multipart/form-data">'
    )
    parts.append('<div style="margin-bottom:16px">')
    parts.append(
        '<label style="display:block;font-weight:600;margin-bottom:4px">'
        "Аккаунт</label>"
    )
    parts.append(
        '<select name="marketplace_account_id" style="padding:6px 10px;'
        'border:1px solid var(--color-border);border-radius:6px">'
    )
    for acct_id, acct_name in accounts:
        sel = "selected" if acct_id == selected_account_id else ""
        parts.append(
            f'<option value="{acct_id}" {sel}>'
            f"{escape(acct_name or f'Аккаунт {acct_id}')}"
            f"</option>"
        )
    parts.append("</select></div>")

    parts.append('<div style="margin-bottom:16px">')
    parts.append(
        '<a href="/web/auto-promo-import/template" class="button primary">'
        "📥 Скачать шаблон Excel</a>"
    )
    parts.append(
        ' <a href="/web/mrc-pricing/auto-promotions/recommendations" '
        'class="button" style="background:#dbeafe;color:#1e40ab">'
        "🤖 Сформировать рекомендации</a>"
    )
    parts.append("</div>")

    parts.append('<div style="margin-bottom:16px">')
    parts.append(
        '<label style="display:block;font-weight:600;margin-bottom:4px">'
        "Файл</label>"
    )
    parts.append(
        '<input type="file" name="file" accept=".xlsx" '
        'style="padding:6px;border:1px solid var(--color-border);'
        'border-radius:6px">'
    )
    parts.append("</div>")

    parts.append(
        '<button type="submit" class="button primary">🔍 Предпросмотр</button>'
    )
    parts.append("</form></div>")

    return "\n".join(parts)


def _auto_promo_import_preview_content(
    preview,
    preview_rows: list[dict],
    marketplace_account_id: int,
) -> str:
    """Render import preview."""
    import json

    parts = []
    parts.append('<div class="card">')
    parts.append("<h2>Предпросмотр импорта</h2>")

    parts.append(
        '<div style="display:flex;gap:12px;flex-wrap:wrap;'
        'margin-bottom:16px">'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value">'
        f"{preview.total_rows}</div>"
        '<div class="kpi-label">Всего строк</div></div>'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value" '
        f'style="color:#10b981">{preview.valid_rows}</div>'
        '<div class="kpi-label">Найдены в базе</div></div>'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value" '
        f'style="color:#f59e0b">{preview.warning_rows}</div>'
        '<div class="kpi-label">Предупреждения</div></div>'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value" '
        f'style="color:#ef4444">{preview.error_rows}</div>'
        '<div class="kpi-label">Ошибки</div></div>'
    )
    parts.append("</div>")

    parts.append(
        '<form method="post" action="/web/auto-promo-import/apply">'
        f'<input type="hidden" name="marketplace_account_id" '
        f'value="{marketplace_account_id}">'
        f'<input type="hidden" name="preview_rows" '
        f'value="{escape(json.dumps(preview_rows, default=str))}">'
    )

    parts.append('<div class="table-wrap">')
    parts.append("<table>")
    parts.append("<thead><tr>")
    for th in ["Строка", "nmID", "Артикул", "Автоакция",
               "Цена входа", "Текущая цена", "Статус"]:
        parts.append(f"<th>{th}</th>")
    parts.append("</tr></thead>")
    parts.append("<tbody>")

    for row in preview_rows:
        if row["status"] == "valid":
            bg, tc = "#d1fae5", "#065f46"
        elif row["status"] == "warning":
            bg, tc = "#fef3c7", "#92400e"
        else:
            bg, tc = "#fee2e2", "#991b1b"
        parts.append("<tr>")
        parts.append(f"<td>{row['row_num']}</td>")
        parts.append(f"<td>{row.get('wb_nm_id') or '—'}</td>")
        parts.append(
            f"<td>{escape(row.get('seller_article') or '—')}</td>"
        )
        parts.append(
            f"<td>{escape(row.get('promotion_name') or '—')}</td>"
        )
        rp = row.get("required_price")
        parts.append(f"<td>{rp:.0f} ₽</td>" if rp else "<td>—</td>")
        cp = row.get("current_wb_price")
        parts.append(f"<td>{cp:.0f} ₽</td>" if cp else "<td>—</td>")
        msg = escape(row.get("message") or row["status"])
        parts.append(
            f'<td><span class="badge" style="background:{bg};'
            f'color:{tc}">{msg}</span></td>'
        )
        parts.append("</tr>")

    parts.append("</tbody></table></div>")

    if preview.error_rows == 0:
        parts.append(
            '<button type="submit" class="button primary" '
            'style="margin-top:16px">✅ Подтвердить импорт</button>'
        )
    parts.append("</form>")
    parts.append(
        '<p style="margin-top:12px">'
        '<a href="/web/auto-promo-import" class="button">← Назад</a>'
        "</p>"
    )
    parts.append("</div>")

    return "\n".join(parts)


def _auto_promo_recommendations_content(
    recommendations: list,
    preview: list[dict],
    accounts: list,
    selected_account_id: int | None,
    status_filter: str = "all",
    conditions_count: int = 0,
) -> str:
    """Render recommendations page."""
    parts = []
    parts.append('<div class="card">')
    parts.append("<h2>🤖 Рекомендации по ценам для автоакций WB</h2>")
    parts.append(
        '<p class="text-muted" style="margin-bottom:16px">'
        "Система проверяет условия автоакций и рассчитывает, "
        "нужно ли изменить цену. Цена меняется в пределах допуска "
        "от МРЦ и не ниже minPrice."
        "</p>"
    )

    if not accounts:
        parts.append(
            '<div class="empty-state">'
            '<p>Нет активных аккаунтов WB.</p></div></div>'
        )
        return "\n".join(parts)

    parts.append(
        '<form method="get" action="/web/mrc-pricing/auto-promotions/'
        'recommendations" style="margin-bottom:16px">'
    )
    parts.append(
        '<select name="marketplace_account_id" style="padding:6px 10px;'
        'border:1px solid var(--color-border);border-radius:6px">'
    )
    for acct_id, acct_name in accounts:
        sel = "selected" if acct_id == selected_account_id else ""
        parts.append(
            f'<option value="{acct_id}" {sel}>'
            f"{escape(acct_name or f'Аккаунт {acct_id}')}"
            f"</option>"
        )
    parts.append("</select>")

    parts.append(
        '<select name="status_filter" style="padding:6px 10px;'
        'border:1px solid var(--color-border);border-radius:6px">'
    )
    filter_options = [
        ("all", "Все"),
        ("set_price", "Можно изменить цену"),
        ("price_ok", "Уже подходит"),
        ("violation", "Нарушение МРЦ"),
        ("min_violation", "Нарушение minPrice"),
        ("unknown", "Нет цены входа"),
    ]
    for val, label in filter_options:
        sel = "selected" if status_filter == val else ""
        parts.append(f'<option value="{val}" {sel}>{label}</option>')
    parts.append("</select>")

    parts.append(
        '<button type="submit" class="button">'
        "Фильтр</button>"
    )
    parts.append("</form>")

    parts.append(
        '<form method="post" action="/web/mrc-pricing/auto-promotions/'
        'recommendations/build" style="margin-bottom:16px">'
    )
    parts.append(
        f'<input type="hidden" name="marketplace_account_id" '
        f'value="{selected_account_id}">'
    )
    parts.append(
        '<button type="submit" class="button primary">'
        "🔄 Сформировать рекомендации</button>"
    )
    parts.append("</form>")

    if not preview and not recommendations:
        parts.append('<div class="empty-state">')
        if conditions_count == 0:
            parts.append(
                '<p><b>Нет условий автоакций.</b></p>'
                '<p>Укажите цену входа для товаров или загрузите файл условий.</p>'
            )
            parts.append(
                '<p><a href="/web/mrc-pricing" '
                'class="button primary">📥 Указать цену входа</a></p>'
            )
            parts.append(
                '<p><a href="/web/auto-promo-import" '
                'class="button">📄 Загрузить условия автоакций</a></p>'
            )
        else:
            parts.append(
                f'<p>Условий автоакций: <b>{conditions_count}</b>. '
                'Нажмите «Сформировать рекомендации» для расчёта.</p>'
            )
        parts.append(
            '<p><a href="/web/mrc-pricing" class="button">'
            "← Назад к МРЦ</a></p></div></div>"
        )
        return "\n".join(parts)

    # Summary counts
    total = len(preview)
    can_count = sum(1 for p in preview if p.get("can_change"))
    set_price_count = sum(1 for p in preview if p.get("can_change"))
    skip_count = total - can_count
    price_ok_count = sum(
        1 for p in preview
        if not p.get("can_change") and "уже равна" in (p.get("skip_reason") or "")
    )
    mrc_violation_count = sum(
        1 for p in preview
        if not p.get("can_change") and "МРЦ" in (p.get("skip_reason") or "")
    )
    min_violation_count = sum(
        1 for p in preview
        if not p.get("can_change") and "minPrice" in (p.get("skip_reason") or "")
    )
    cooldown_count = sum(
        1 for p in preview
        if not p.get("can_change") and "6ч" in (p.get("skip_reason") or "")
    )

    parts.append(
        '<div style="display:flex;gap:12px;flex-wrap:wrap;'
        'margin-bottom:16px">'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value">'
        f'{total}</div>'
        '<div class="kpi-label">Всего</div></div>'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value" '
        f'style="color:#10b981">{set_price_count}</div>'
        '<div class="kpi-label">Можно изменить</div></div>'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value" '
        f'style="color:#3b82f6">{price_ok_count}</div>'
        '<div class="kpi-label">Уже подходят</div></div>'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value" '
        f'style="color:#ef4444">{mrc_violation_count}</div>'
        '<div class="kpi-label">Нарушения МРЦ</div></div>'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value" '
        f'style="color:#f97316">{min_violation_count}</div>'
        '<div class="kpi-label">Нарушения minPrice</div></div>'
    )
    parts.append(
        f'<div class="kpi-card"><div class="kpi-value" '
        f'style="color:#6b7280">{cooldown_count}</div>'
        '<div class="kpi-label">Кулдаун</div></div>'
    )
    parts.append("</div>")

    # Filter preview rows
    filtered_preview = preview
    if status_filter == "set_price":
        filtered_preview = [p for p in preview if p.get("can_change")]
    elif status_filter == "price_ok":
        filtered_preview = [
            p for p in preview
            if not p.get("can_change") and "уже равна" in (p.get("skip_reason") or "")
        ]
    elif status_filter == "violation":
        filtered_preview = [
            p for p in preview
            if not p.get("can_change") and "МРЦ" in (p.get("skip_reason") or "")
        ]
    elif status_filter == "min_violation":
        filtered_preview = [
            p for p in preview
            if not p.get("can_change") and "minPrice" in (p.get("skip_reason") or "")
        ]
    elif status_filter == "unknown":
        filtered_preview = [
            p for p in preview
            if not p.get("can_change") and (
                "нужна цена" in (p.get("skip_reason") or "").lower()
                or "не найдена" in (p.get("skip_reason") or "").lower()
            )
        ]

    # Action buttons
    parts.append(
        '<form method="post" action="/web/auto-promo-prices/apply">'
        f'<input type="hidden" name="marketplace_account_id" '
        f'value="{selected_account_id}">'
    )

    parts.append(
        '<div style="display:flex;gap:8px;flex-wrap:wrap;'
        'margin-bottom:16px">'
    )
    parts.append(
        '<button type="submit" name="dry_run" value="on" '
        'class="button primary">🔍 Подготовить</button>'
    )
    parts.append(
        '<button type="submit" name="dry_run" value="off" '
        'class="button" style="background:#ef4444;color:white" '
        'onclick="return confirm(\'Применить?\')">⚡ Применить</button>'
    )
    parts.append(
        f'<a href="/web/mrc-pricing/auto-promotions/recommendations/export?'
        f'marketplace_account_id={selected_account_id}" '
        'class="button">📥 Скачать Excel</a>'
    )
    parts.append("</div>")
    parts.append("</form>")

    parts.append('<div class="table-wrap">')
    parts.append("<table>")
    parts.append("<thead><tr>")
    parts.append(
        "<th style='width:30px'>"
        "<input type='checkbox' id='select-all'></th>"
    )
    for th in ["Товар", "nmID", "Автоакция", "МРЦ", "Границы МРЦ",
               "minPrice", "Текущая", "Цена входа", "Рекоменд.", "Статус"]:
        parts.append(f"<th>{th}</th>")
    parts.append("</tr></thead>")
    parts.append("<tbody>")

    for p in filtered_preview:
        parts.append("<tr>")
        dis = "" if p.get("can_change") else "disabled"
        parts.append(
            f"<td><input type='checkbox' name='product_ids' "
            f"value='{p['product_id']}' class='product-checkbox' "
            f"{dis}></td>"
        )
        title = escape((p.get("title") or "")[:50])
        art = escape(p.get("seller_article") or "")
        parts.append(
            f"<td>{title}<br><small class='text-muted'>{art}</small></td>"
        )
        parts.append(f"<td>{p['wb_nm_id']}</td>")
        promo_name = escape(p.get("promotion_name") or "—")
        parts.append(f"<td><small>{promo_name}</small></td>")
        parts.append(f"<td>{p['mrc_price']:.0f} ₽</td>")
        parts.append(
            f"<td><small>{p['mrc_lower_bound']:.0f} — "
            f"{p['mrc_upper_bound']:.0f} ₽</small></td>"
        )
        mp = p.get("min_price")
        parts.append(f"<td>{mp:.0f} ₽</td>" if mp else "<td>—</td>")
        cp = p.get("current_wb_price")
        parts.append(f"<td>{cp:.0f} ₽</td>" if cp else "<td>—</td>")
        rp = p.get("required_price") or p.get("recommended_price")
        parts.append(f"<td>{rp:.0f} ₽</td>" if rp else "<td>—</td>")
        rec_p = p.get("recommended_price")
        parts.append(
            f"<td><b>{rec_p:.0f} ₽</b></td>" if rec_p else "<td>—</td>"
        )

        if p.get("can_change"):
            parts.append(
                '<td><span class="badge" style="background:#d1fae5;'
                'color:#065f46">✅ Можно</span></td>'
            )
        else:
            skip = escape(p.get("skip_reason") or "—")
            parts.append(
                f'<td><span class="badge" style="background:#fee2e2;'
                f'color:#991b1b">⚠️ {skip}</span></td>'
            )
        parts.append("</tr>")

    parts.append("</tbody></table></div>")

    parts.append(
        '<p class="text-muted" style="margin-top:16px;font-size:13px">'
        "⚠️ Изменение цен отправляется в WB API. minPrice не меняется. "
        "Перед применением рекомендуется нажать «Подготовить» для проверки."
        "</p>"
    )

    parts.append("</div>")

    # Flash messages for generate result
    parts.append("""
    <script>
    (function() {
        const params = new URLSearchParams(window.location.search);
        let msg = '';
        if (params.get('generated') === '1') {
            const total = params.get('total') || '0';
            const setPrice = params.get('set_price') || '0';
            const priceOk = params.get('price_ok') || '0';
            const violation = params.get('violation') || '0';
            const minViolation = params.get('min_violation') || '0';
            const unknown = params.get('unknown') || '0';
            msg = '✅ Рекомендации сформированы\\n'
                + 'Всего условий: ' + total
                + ' | Можно изменить: ' + setPrice
                + ' | Уже подходят: ' + priceOk
                + ' | Нарушения МРЦ: ' + violation
                + ' | Нарушения minPrice: ' + minViolation
                + ' | Нет цены входа: ' + unknown;
        }
        if (params.get('error') === 'generate' || params.get('error') === 'build') msg = '❌ Ошибка формирования рекомендаций';
        if (params.get('error') === 'export') msg = '❌ Ошибка экспорта';
        if (params.get('condition_set') === '1') {
            const nmId = params.get('wb_nm_id') || '?';
            const reqPrice = params.get('required_price') || '?';
            const setPrice = params.get('rec_set_price') || '0';
            const priceOk = params.get('rec_price_ok') || '0';
            msg = '✅ Цена входа сохранена: nmID ' + nmId + ' = ' + reqPrice + ' ₽\\n'
                + 'Можно изменить: ' + setPrice + ' | Уже подходят: ' + priceOk;
        }
        if (msg) {
            const div = document.createElement('div');
            div.style.cssText = 'padding:12px 16px;margin-bottom:16px;border-radius:8px;font-size:14px;white-space:pre-line;' +
                (msg.startsWith('✅') ? 'background:#d1fae5;color:#065f46' : 'background:#fee2e2;color:#991b1b');
            div.textContent = msg;
            document.querySelector('.card')?.before(div);
        }
    })();
    </script>
    """)

    parts.append("""
    <script>
    document.getElementById('select-all')?.addEventListener('change',
    function() {
        document.querySelectorAll('.product-checkbox:not([disabled])')
        .forEach(cb => cb.checked = this.checked);
    });
    </script>
    """)

    return "\n".join(parts)
