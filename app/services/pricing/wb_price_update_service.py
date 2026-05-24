"""version: 2.0.0
description: WB price update service for auto promotions.
    Safely changes product prices with MRC/minPrice validation,
    calculates price/discount payload for WB /api/v2/upload/task,
    checks upload status, and handles quarantine detection.
updated: 2026-05-23
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.wb import WildberriesClient
from app.models.domain import (
    Product,
    WbAutoPromoPriceRecommendation,
    WbPriceChangeHistory,
    WbProductPrice,
    WbPromotionNomenclature,
)

logger = logging.getLogger(__name__)

REASON_AUTO_PROMOTION = "auto_promotion"
SOURCE_MANUAL = "manual"
SOURCE_AUTO = "auto"
STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_UPLOAD_ERROR = "upload_error"
STATUS_STATUS_PENDING = "status_pending"
STATUS_APPLIED = "applied"
STATUS_QUARANTINE = "quarantine"
STATUS_FAILED = "failed"
STATUS_DRY_RUN = "dry_run"
STATUS_SKIPPED = "skipped"

MIN_PRICE_CHANGE_INTERVAL_SECONDS = 6 * 3600
QUARANTINE_THRESHOLD = Decimal("3")
MAX_UPLOAD_ITEMS = 1000
UPLOAD_STATUS_POLL_ATTEMPTS = 10
UPLOAD_STATUS_POLL_INTERVAL = 15

WB_UPLOAD_STATUS_MAP = {
    3: "processed_success",
    4: "cancelled",
    5: "processed_partial",
    6: "processed_all_errors",
}


@dataclass(slots=True)
class WbPricePayload:
    """Calculated price/discount payload for WB upload."""
    nm_id: int
    price: int
    discount: int
    final_discounted_price: Decimal
    target_discounted_price: Decimal


def calculate_wb_price_payload_for_target(
    target_discounted_price: Decimal,
    discount_percent: Decimal = Decimal("75"),
    nm_id: int = 0,
) -> WbPricePayload:
    """Calculate WB price and discount to achieve target discounted price.

    Formula:
        price_before_discount = ceil(target / (1 - discount/100))
        final_price = price_before_discount * (1 - discount/100)

    If final_price > target due to rounding, reduce price_before_discount by 1.
    """
    discount_factor = Decimal("1") - discount_percent / Decimal("100")
    if discount_factor <= 0:
        discount_factor = Decimal("0.25")

    price_before_discount = (target_discounted_price / discount_factor).to_integral_value(rounding=ROUND_CEILING)
    price_int = int(price_before_discount)

    final_price = Decimal(str(price_int)) * discount_factor

    if final_price > target_discounted_price and price_int > 1:
        price_int -= 1
        final_price = Decimal(str(price_int)) * discount_factor

    return WbPricePayload(
        nm_id=nm_id,
        price=price_int,
        discount=int(discount_percent),
        final_discounted_price=final_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        target_discounted_price=target_discounted_price,
    )


def is_quarantine_risk(
    old_discounted_price: Decimal | None,
    target_discounted_price: Decimal,
) -> bool:
    """Check if new price is 3x or more lower than old price (quarantine risk)."""
    if old_discounted_price is None or old_discounted_price <= 0:
        return False
    return target_discounted_price <= old_discounted_price / QUARANTINE_THRESHOLD


class WbPriceUpdateService:
    """Safely update WB product prices for auto promotion entry."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def prepare_price_changes(
        self,
        user_id: int,
        marketplace_account_id: int,
        status_filter: str = "AUTO_PROMOTION_SET_PRICE",
    ) -> list[dict]:
        """Prepare a preview of price changes without applying them."""
        from app.services.pricing.mrc_pricing_settings_service import MrcPricingSettingsService

        settings_service = MrcPricingSettingsService(self.session)
        settings = await settings_service.get_settings(
            user_id=user_id,
            marketplace_account_id=marketplace_account_id,
        )
        discount_percent = settings.default_discount_percent or Decimal("75")

        logger.info(
            "wb_auto_promo_price_update_preview_created",
            extra={
                "user_id": user_id,
                "marketplace_account_id": marketplace_account_id,
                "status_filter": status_filter,
            },
        )

        recs_result = await self.session.execute(
            select(WbAutoPromoPriceRecommendation).where(
                WbAutoPromoPriceRecommendation.user_id == user_id,
                WbAutoPromoPriceRecommendation.marketplace_account_id == marketplace_account_id,
                WbAutoPromoPriceRecommendation.status == status_filter,
                WbAutoPromoPriceRecommendation.recommended_price.isnot(None),
            )
        )
        recommendations = list(recs_result.scalars().all())

        preview: list[dict] = []
        for rec in recommendations:
            product_result = await self.session.execute(
                select(Product).where(Product.id == rec.product_id)
            )
            product = product_result.scalar_one_or_none()
            if product is None:
                continue

            current_price = await self._get_current_wb_price(product)
            can_change, skip_reason = await self._can_change_price(
                product=product,
                new_price=rec.recommended_price,
                rec=rec,
            )

            payload = calculate_wb_price_payload_for_target(
                target_discounted_price=rec.recommended_price,
                discount_percent=discount_percent,
                nm_id=rec.wb_nm_id,
            )

            quarantine_risk = is_quarantine_risk(current_price, rec.recommended_price)

            preview.append({
                "product_id": product.id,
                "wb_nm_id": rec.wb_nm_id,
                "seller_article": product.seller_article,
                "title": product.title,
                "promotion_name": rec.promotion_name,
                "mrc_price": rec.mrc_price,
                "current_wb_price": current_price,
                "required_price": rec.required_price,
                "recommended_price": rec.recommended_price,
                "min_price": rec.min_price,
                "mrc_lower_bound": rec.mrc_lower_bound,
                "mrc_upper_bound": rec.mrc_upper_bound,
                "can_change": can_change and not quarantine_risk,
                "skip_reason": "Карантин WB: новая цена в 3+ раза ниже старой" if quarantine_risk else skip_reason,
                "quarantine_risk": quarantine_risk,
                "wb_price": payload.price,
                "wb_discount": payload.discount,
                "final_discounted_price": payload.final_discounted_price,
                "recommendation_id": rec.id,
            })

        return preview

    async def apply_price_changes(
        self,
        user_id: int,
        marketplace_account_id: int,
        wb_api_key: str,
        product_ids: list[int] | None = None,
        dry_run: bool = True,
        source: str = SOURCE_MANUAL,
    ) -> list[dict]:
        """Apply price changes for selected products."""
        from app.services.pricing.mrc_pricing_settings_service import MrcPricingSettingsService

        settings_service = MrcPricingSettingsService(self.session)
        settings = await settings_service.get_settings(
            user_id=user_id,
            marketplace_account_id=marketplace_account_id,
        )
        discount_percent = settings.default_discount_percent or Decimal("75")

        query = (
            select(WbAutoPromoPriceRecommendation)
            .where(
                WbAutoPromoPriceRecommendation.user_id == user_id,
                WbAutoPromoPriceRecommendation.marketplace_account_id
                == marketplace_account_id,
                WbAutoPromoPriceRecommendation.status == "AUTO_PROMOTION_SET_PRICE",
                WbAutoPromoPriceRecommendation.recommended_price.isnot(None),
            )
        )
        if product_ids:
            query = query.where(
                WbAutoPromoPriceRecommendation.product_id.in_(product_ids)
            )

        recs_result = await self.session.execute(query)
        recommendations = list(recs_result.scalars().all())

        results: list[dict] = []
        upload_items: list[dict] = []
        upload_context: list[dict] = []

        for rec in recommendations:
            product_result = await self.session.execute(
                select(Product).where(Product.id == rec.product_id)
            )
            product = product_result.scalar_one_or_none()
            if product is None:
                continue

            current_price = await self._get_current_wb_price(product)
            can_change, skip_reason = await self._can_change_price(
                product=product,
                new_price=rec.recommended_price,
                rec=rec,
            )

            if not can_change:
                await self._record_history(
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    product_id=product.id,
                    wb_nm_id=rec.wb_nm_id,
                    old_price=current_price,
                    new_price=rec.recommended_price,
                    status=STATUS_SKIPPED,
                    error=skip_reason,
                    dry_run=dry_run,
                    source=source,
                    min_price=rec.min_price,
                    mrc_lower_bound=rec.mrc_lower_bound,
                    mrc_upper_bound=rec.mrc_upper_bound,
                )
                logger.info(
                    "wb_auto_promo_price_update_skipped",
                    extra={
                        "product_id": product.id,
                        "wb_nm_id": rec.wb_nm_id,
                        "reason": skip_reason,
                    },
                )
                results.append({
                    "product_id": product.id,
                    "wb_nm_id": rec.wb_nm_id,
                    "status": STATUS_SKIPPED,
                    "reason": skip_reason,
                })
                continue

            quarantine_risk = is_quarantine_risk(current_price, rec.recommended_price)
            if quarantine_risk and source == SOURCE_AUTO:
                skip_reason = "Карантин WB: новая цена в 3+ раза ниже старой"
                await self._record_history(
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    product_id=product.id,
                    wb_nm_id=rec.wb_nm_id,
                    old_price=current_price,
                    new_price=rec.recommended_price,
                    status=STATUS_QUARANTINE,
                    error=skip_reason,
                    dry_run=dry_run,
                    source=source,
                    min_price=rec.min_price,
                    mrc_lower_bound=rec.mrc_lower_bound,
                    mrc_upper_bound=rec.mrc_upper_bound,
                )
                results.append({
                    "product_id": product.id,
                    "wb_nm_id": rec.wb_nm_id,
                    "status": STATUS_QUARANTINE,
                    "reason": skip_reason,
                })
                continue

            if dry_run:
                payload = calculate_wb_price_payload_for_target(
                    target_discounted_price=rec.recommended_price,
                    discount_percent=discount_percent,
                    nm_id=rec.wb_nm_id,
                )
                await self._record_history(
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    product_id=product.id,
                    wb_nm_id=rec.wb_nm_id,
                    old_price=current_price,
                    new_price=rec.recommended_price,
                    status=STATUS_DRY_RUN,
                    dry_run=True,
                    source=source,
                    min_price=rec.min_price,
                    mrc_lower_bound=rec.mrc_lower_bound,
                    mrc_upper_bound=rec.mrc_upper_bound,
                    wb_price=payload.price,
                    wb_discount=payload.discount,
                    final_discounted_price=payload.final_discounted_price,
                    target_discounted_price=rec.recommended_price,
                )
                results.append({
                    "product_id": product.id,
                    "wb_nm_id": rec.wb_nm_id,
                    "status": STATUS_DRY_RUN,
                    "old_price": current_price,
                    "new_price": rec.recommended_price,
                    "wb_price": payload.price,
                    "wb_discount": payload.discount,
                })
                continue

            payload = calculate_wb_price_payload_for_target(
                target_discounted_price=rec.recommended_price,
                discount_percent=discount_percent,
                nm_id=rec.wb_nm_id,
            )

            logger.info(
                "wb_price_payload_calculated",
                extra={
                    "wb_nm_id": rec.wb_nm_id,
                    "target_price": str(rec.recommended_price),
                    "wb_price": payload.price,
                    "wb_discount": payload.discount,
                    "final_price": str(payload.final_discounted_price),
                },
            )

            upload_items.append({
                "nmID": rec.wb_nm_id,
                "price": payload.price,
                "discount": payload.discount,
            })
            upload_context.append({
                "product_id": product.id,
                "wb_nm_id": rec.wb_nm_id,
                "old_price": current_price,
                "target_discounted_price": rec.recommended_price,
                "wb_price": payload.price,
                "wb_discount": payload.discount,
                "final_discounted_price": payload.final_discounted_price,
                "min_price": rec.min_price,
                "mrc_lower_bound": rec.mrc_lower_bound,
                "mrc_upper_bound": rec.mrc_upper_bound,
            })

            if len(upload_items) >= MAX_UPLOAD_ITEMS:
                batch_results = await self._execute_upload(
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    wb_api_key=wb_api_key,
                    upload_items=upload_items,
                    upload_context=upload_context,
                    source=source,
                )
                results.extend(batch_results)
                upload_items = []
                upload_context = []

        if upload_items and not dry_run:
            batch_results = await self._execute_upload(
                user_id=user_id,
                marketplace_account_id=marketplace_account_id,
                wb_api_key=wb_api_key,
                upload_items=upload_items,
                upload_context=upload_context,
                source=source,
            )
            results.extend(batch_results)

        return results

    async def _execute_upload(
        self,
        user_id: int,
        marketplace_account_id: int,
        wb_api_key: str,
        upload_items: list[dict],
        upload_context: list[dict],
        source: str,
    ) -> list[dict]:
        """Execute a batch upload to WB /api/v2/upload/task."""
        client = WildberriesClient(api_key=wb_api_key)
        results: list[dict] = []

        logger.info(
            "wb_price_upload_started",
            extra={
                "marketplace_account_id": marketplace_account_id,
                "items_count": len(upload_items),
            },
        )

        try:
            response = await client.upload_task_prices_discounts(items=upload_items)
            raw_response = response

            error = response.get("error", False)
            error_text = response.get("errorText", "")
            data = response.get("data", {})
            upload_id = data.get("id") if isinstance(data, dict) else None
            already_exists = data.get("alreadyExists", False) if isinstance(data, dict) else False

            if error:
                logger.warning(
                    "wb_price_upload_failed",
                    extra={
                        "marketplace_account_id": marketplace_account_id,
                        "error_text": error_text,
                        "raw_response": str(raw_response)[:500],
                    },
                )
                for ctx in upload_context:
                    await self._record_history(
                        user_id=user_id,
                        marketplace_account_id=marketplace_account_id,
                        product_id=ctx["product_id"],
                        wb_nm_id=ctx["wb_nm_id"],
                        old_price=ctx["old_price"],
                        new_price=ctx["target_discounted_price"],
                        status=STATUS_UPLOAD_ERROR,
                        error=error_text,
                        dry_run=False,
                        source=source,
                        min_price=ctx["min_price"],
                        mrc_lower_bound=ctx["mrc_lower_bound"],
                        mrc_upper_bound=ctx["mrc_upper_bound"],
                        wb_price=ctx["wb_price"],
                        wb_discount=ctx["wb_discount"],
                        final_discounted_price=ctx["final_discounted_price"],
                        target_discounted_price=ctx["target_discounted_price"],
                        wb_upload_id=upload_id,
                        raw_payload=upload_items,
                        raw_response=raw_response,
                    )
                    results.append({
                        "product_id": ctx["product_id"],
                        "wb_nm_id": ctx["wb_nm_id"],
                        "status": STATUS_UPLOAD_ERROR,
                        "error": error_text,
                    })
                return results

            logger.info(
                "wb_price_upload_completed",
                extra={
                    "marketplace_account_id": marketplace_account_id,
                    "upload_id": upload_id,
                    "already_exists": already_exists,
                    "items_count": len(upload_items),
                },
            )

            if upload_id:
                upload_status = await self._check_upload_status(
                    client=client,
                    upload_id=upload_id,
                )
            else:
                upload_status = "sent"

            for ctx in upload_context:
                await self._record_history(
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    product_id=ctx["product_id"],
                    wb_nm_id=ctx["wb_nm_id"],
                    old_price=ctx["old_price"],
                    new_price=ctx["target_discounted_price"],
                    status=STATUS_APPLIED if upload_status == "processed_success" else upload_status,
                    dry_run=False,
                    source=source,
                    min_price=ctx["min_price"],
                    mrc_lower_bound=ctx["mrc_lower_bound"],
                    mrc_upper_bound=ctx["mrc_upper_bound"],
                    wb_price=ctx["wb_price"],
                    wb_discount=ctx["wb_discount"],
                    final_discounted_price=ctx["final_discounted_price"],
                    target_discounted_price=ctx["target_discounted_price"],
                    wb_upload_id=upload_id,
                    raw_payload=upload_items,
                    raw_response=raw_response,
                )
                results.append({
                    "product_id": ctx["product_id"],
                    "wb_nm_id": ctx["wb_nm_id"],
                    "status": STATUS_APPLIED if upload_status == "processed_success" else upload_status,
                    "upload_id": upload_id,
                    "old_price": ctx["old_price"],
                    "new_price": ctx["target_discounted_price"],
                    "wb_price": ctx["wb_price"],
                    "wb_discount": ctx["wb_discount"],
                })

        except Exception as exc:
            logger.exception(
                "wb_price_upload_failed",
                extra={
                    "marketplace_account_id": marketplace_account_id,
                },
            )
            for ctx in upload_context:
                await self._record_history(
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    product_id=ctx["product_id"],
                    wb_nm_id=ctx["wb_nm_id"],
                    old_price=ctx["old_price"],
                    new_price=ctx["target_discounted_price"],
                    status=STATUS_FAILED,
                    error=str(exc),
                    dry_run=False,
                    source=source,
                    min_price=ctx["min_price"],
                    mrc_lower_bound=ctx["mrc_lower_bound"],
                    mrc_upper_bound=ctx["mrc_upper_bound"],
                    wb_price=ctx["wb_price"],
                    wb_discount=ctx["wb_discount"],
                    final_discounted_price=ctx["final_discounted_price"],
                    target_discounted_price=ctx["target_discounted_price"],
                    raw_payload=upload_items,
                )
                results.append({
                    "product_id": ctx["product_id"],
                    "wb_nm_id": ctx["wb_nm_id"],
                    "status": STATUS_FAILED,
                    "error": str(exc),
                })

        return results

    async def _check_upload_status(
        self,
        client: WildberriesClient,
        upload_id: int,
    ) -> str:
        """Check upload status with polling."""
        import asyncio

        for attempt in range(UPLOAD_STATUS_POLL_ATTEMPTS):
            try:
                status_response = await client.get_price_upload_status(upload_id)
                data = status_response.get("data", {})
                if isinstance(data, list) and data:
                    status_code = data[0].get("status")
                elif isinstance(data, dict):
                    status_code = data.get("status")
                else:
                    status_code = None

                if status_code is not None:
                    status_text = WB_UPLOAD_STATUS_MAP.get(int(status_code), "unknown")
                    logger.info(
                        "wb_price_upload_status_checked",
                        extra={
                            "upload_id": upload_id,
                            "status_code": status_code,
                            "status_text": status_text,
                            "attempt": attempt + 1,
                        },
                    )
                    if status_text in ("processed_success", "processed_partial", "processed_all_errors"):
                        return status_text

                await asyncio.sleep(UPLOAD_STATUS_POLL_INTERVAL)
            except Exception:
                logger.warning(
                    "wb_price_upload_status_check_failed",
                    extra={"upload_id": upload_id, "attempt": attempt + 1},
                )
                await asyncio.sleep(UPLOAD_STATUS_POLL_INTERVAL)

        return STATUS_STATUS_PENDING

    async def _can_change_price(
        self,
        product: Product,
        new_price: Decimal,
        rec: WbAutoPromoPriceRecommendation,
    ) -> tuple[bool, str | None]:
        """Check if price can be changed safely."""
        if new_price <= 0:
            return False, "Цена должна быть больше 0"

        if rec.min_price and new_price < rec.min_price:
            return False, f"Цена {new_price} ниже minPrice ({rec.min_price})"

        if rec.mrc_lower_bound and new_price < rec.mrc_lower_bound:
            return False, (
                f"Цена {new_price} ниже нижней границы МРЦ "
                f"({rec.mrc_lower_bound})"
            )

        if rec.mrc_upper_bound and new_price > rec.mrc_upper_bound:
            return False, (
                f"Цена {new_price} выше верхней границы МРЦ "
                f"({rec.mrc_upper_bound})"
            )

        last_change = await self._get_last_price_change(
            product.marketplace_account_id,
            rec.wb_nm_id,
        )
        if last_change:
            elapsed = (datetime.now(tz=UTC) - last_change).total_seconds()
            if elapsed < MIN_PRICE_CHANGE_INTERVAL_SECONDS:
                hours = int(elapsed / 3600)
                return False, f"Цена менялась {hours}ч назад, подождите 6ч"

        current_price = await self._get_current_wb_price(product)
        if current_price is not None and current_price == new_price:
            return False, "Цена уже равна рекомендуемой"

        return True, None

    async def _get_current_wb_price(self, product: Product) -> Decimal | None:
        """Get current WB price from wb_product_prices first, then nomenclatures or conditions."""
        nm_id_str = product.external_product_id or product.marketplace_article
        if not nm_id_str or not nm_id_str.isdigit():
            return None
        wb_nm_id = int(nm_id_str)

        result = await self.session.execute(
            select(WbProductPrice.discounted_price)
            .where(
                WbProductPrice.marketplace_account_id == product.marketplace_account_id,
                WbProductPrice.wb_nm_id == wb_nm_id,
                WbProductPrice.discounted_price.isnot(None),
                WbProductPrice.discounted_price > 0,
            )
            .order_by(WbProductPrice.synced_at.desc())
            .limit(1)
        )
        price = result.scalar_one_or_none()
        if price is not None:
            return price

        result = await self.session.execute(
            select(WbPromotionNomenclature.current_price)
            .where(
                WbPromotionNomenclature.marketplace_account_id == product.marketplace_account_id,
                WbPromotionNomenclature.wb_nm_id == wb_nm_id,
                WbPromotionNomenclature.current_price.isnot(None),
                WbPromotionNomenclature.current_price > 0,
            )
            .order_by(WbPromotionNomenclature.synced_at.desc())
            .limit(1)
        )
        price = result.scalar_one_or_none()
        if price is not None:
            return price

        from app.models.domain import WbAutoPromotionCondition

        cond_result = await self.session.execute(
            select(WbAutoPromotionCondition.current_wb_price)
            .where(
                WbAutoPromotionCondition.marketplace_account_id == product.marketplace_account_id,
                WbAutoPromotionCondition.wb_nm_id == wb_nm_id,
                WbAutoPromotionCondition.current_wb_price.isnot(None),
                WbAutoPromotionCondition.current_wb_price > 0,
            )
            .limit(1)
        )
        return cond_result.scalar_one_or_none()

    async def _get_last_price_change(
        self,
        marketplace_account_id: int,
        wb_nm_id: int,
    ) -> datetime | None:
        """Get the last price change time for a product."""
        result = await self.session.execute(
            select(WbPriceChangeHistory.created_at)
            .where(
                WbPriceChangeHistory.marketplace_account_id
                == marketplace_account_id,
                WbPriceChangeHistory.wb_nm_id == wb_nm_id,
                WbPriceChangeHistory.status.in_([STATUS_APPLIED, STATUS_DRY_RUN]),
            )
            .order_by(WbPriceChangeHistory.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _record_history(
        self,
        user_id: int,
        marketplace_account_id: int,
        product_id: int,
        wb_nm_id: int,
        old_price: Decimal | None,
        new_price: Decimal,
        status: str,
        error: str | None = None,
        dry_run: bool = True,
        source: str = SOURCE_MANUAL,
        min_price: Decimal | None = None,
        mrc_lower_bound: Decimal | None = None,
        mrc_upper_bound: Decimal | None = None,
        wb_upload_id: int | None = None,
        wb_price: int | None = None,
        wb_discount: int | None = None,
        final_discounted_price: Decimal | None = None,
        target_discounted_price: Decimal | None = None,
        raw_payload: dict | None = None,
        raw_response: dict | None = None,
    ) -> None:
        """Record a price change in history."""
        record = WbPriceChangeHistory(
            user_id=user_id,
            marketplace_account_id=marketplace_account_id,
            product_id=product_id,
            wb_nm_id=wb_nm_id,
            old_price=old_price,
            new_price=new_price,
            min_price=min_price,
            mrc_lower_bound=mrc_lower_bound,
            mrc_upper_bound=mrc_upper_bound,
            reason=REASON_AUTO_PROMOTION,
            source=source,
            status=status,
            error=error,
            dry_run=dry_run,
            wb_upload_id=wb_upload_id,
            wb_price=wb_price,
            wb_discount=wb_discount,
            final_discounted_price=final_discounted_price,
            target_discounted_price=target_discounted_price,
            raw_payload=raw_payload,
            raw_response=raw_response,
        )
        self.session.add(record)
        await self.session.flush()
