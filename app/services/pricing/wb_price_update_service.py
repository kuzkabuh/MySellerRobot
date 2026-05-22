"""version: 1.0.0
description: WB price update service for auto promotions.
    Safely changes product prices with MRC/minPrice validation and dry_run.
updated: 2026-05-22
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.wb import WildberriesClient
from app.models.domain import (
    Product,
    WbAutoPromoPriceRecommendation,
    WbPriceChangeHistory,
)

logger = logging.getLogger(__name__)

REASON_AUTO_PROMOTION = "auto_promotion"
SOURCE_MANUAL = "manual"
SOURCE_AUTO = "auto"
STATUS_PENDING = "pending"
STATUS_APPLIED = "applied"
STATUS_FAILED = "failed"
STATUS_DRY_RUN = "dry_run"
STATUS_SKIPPED = "skipped"

MIN_PRICE_CHANGE_INTERVAL_SECONDS = 6 * 3600


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
                "can_change": can_change,
                "skip_reason": skip_reason,
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

        for rec in recommendations:
            product_result = await self.session.execute(
                select(Product).where(Product.id == rec.product_id)
            )
            product = product_result.scalar_one_or_none()
            if product is None:
                continue

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
                    old_price=None,
                    new_price=rec.recommended_price,
                    status=STATUS_SKIPPED,
                    error=skip_reason,
                    dry_run=dry_run,
                    source=source,
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

            current_price = await self._get_current_wb_price(product)

            if dry_run:
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
                )
                results.append({
                    "product_id": product.id,
                    "wb_nm_id": rec.wb_nm_id,
                    "status": STATUS_DRY_RUN,
                    "old_price": current_price,
                    "new_price": rec.recommended_price,
                })
                continue

            try:
                client = WildberriesClient(api_key=wb_api_key)
                await client.upload_prices_discounts(items=[{
                    "id": rec.wb_nm_id,
                    "price": int(rec.recommended_price),
                    "discount": 0,
                }])

                await self._record_history(
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    product_id=product.id,
                    wb_nm_id=rec.wb_nm_id,
                    old_price=current_price,
                    new_price=rec.recommended_price,
                    status=STATUS_APPLIED,
                    dry_run=False,
                    source=source,
                )
                logger.info(
                    "wb_auto_promo_price_update_applied",
                    extra={
                        "product_id": product.id,
                        "wb_nm_id": rec.wb_nm_id,
                        "old_price": str(current_price),
                        "new_price": str(rec.recommended_price),
                    },
                )
                results.append({
                    "product_id": product.id,
                    "wb_nm_id": rec.wb_nm_id,
                    "status": STATUS_APPLIED,
                    "old_price": current_price,
                    "new_price": rec.recommended_price,
                })
            except Exception as exc:
                await self._record_history(
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    product_id=product.id,
                    wb_nm_id=rec.wb_nm_id,
                    old_price=current_price,
                    new_price=rec.recommended_price,
                    status=STATUS_FAILED,
                    error=str(exc),
                    dry_run=False,
                    source=source,
                )
                logger.exception(
                    "wb_auto_promo_price_update_failed",
                    extra={
                        "product_id": product.id,
                        "wb_nm_id": rec.wb_nm_id,
                    },
                )
                results.append({
                    "product_id": product.id,
                    "wb_nm_id": rec.wb_nm_id,
                    "status": STATUS_FAILED,
                    "error": str(exc),
                })

        return results

    async def _can_change_price(
        self,
        product: Product,
        new_price: Decimal,
        rec: WbAutoPromoPriceRecommendation,
    ) -> tuple[bool, str | None]:
        """Check if price can be changed safely."""
        if new_price <= 0:
            return False, "Цена должна быть больше 0"

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

        if rec.min_price and new_price < rec.min_price:
            return False, f"Цена {new_price} ниже minPrice ({rec.min_price})"

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
        """Get current WB price from product data."""
        return None

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
    ) -> None:
        """Record a price change in history."""
        record = WbPriceChangeHistory(
            user_id=user_id,
            marketplace_account_id=marketplace_account_id,
            product_id=product_id,
            wb_nm_id=wb_nm_id,
            old_price=old_price,
            new_price=new_price,
            reason=REASON_AUTO_PROMOTION,
            source=source,
            status=status,
            error=error,
            dry_run=dry_run,
        )
        self.session.add(record)
        await self.session.flush()
