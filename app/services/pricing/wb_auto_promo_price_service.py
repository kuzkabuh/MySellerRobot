"""version: 1.0.0
description: WB auto promotion price control service.
    Calculates price recommendations for auto promotions based on MRC rules.
updated: 2026-05-22
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    Product,
    WbAutoPromoPriceRecommendation,
    WbAutoPromotionCondition,
    WbPromotion,
)
from app.services.pricing.mrc_pricing_settings_service import MrcPricingSettingsService

logger = logging.getLogger(__name__)

STATUS_AUTO_PROMO_PRICE_OK = "AUTO_PROMO_PRICE_OK"
STATUS_AUTO_PROMO_SET_PRICE = "AUTO_PROMO_SET_PRICE"
STATUS_AUTO_PROMO_PRICE_VIOLATION = "AUTO_PROMO_PRICE_VIOLATION"
STATUS_AUTO_PROMO_REQUIRED_PRICE_UNKNOWN = "AUTO_PROMO_REQUIRED_PRICE_UNKNOWN"
STATUS_AUTO_PROMO_MIN_PRICE_VIOLATION = "AUTO_PROMO_MIN_PRICE_VIOLATION"
STATUS_AUTO_PROMO_WAITING_WB_SYNC = "AUTO_PROMO_WAITING_WB_SYNC"


@dataclass(slots=True)
class AutoPromoPriceRecommendation:
    product_id: int
    wb_nm_id: int
    wb_promotion_id: int | None
    mrc_price: Decimal
    current_wb_price: Decimal | None
    required_price: Decimal | None
    recommended_price: Decimal | None
    min_price: Decimal | None
    mrc_lower_bound: Decimal
    mrc_upper_bound: Decimal
    status: str
    reason: str


class WbAutoPromoPriceService:
    """Calculate price recommendations for WB auto promotions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._settings_service = MrcPricingSettingsService(session)

    async def build_recommendation(
        self,
        product: Product,
        current_wb_price: Decimal | None,
        required_price: Decimal | None,
        min_price: Decimal | None = None,
    ) -> AutoPromoPriceRecommendation:
        """Build a price recommendation for a product in an auto promotion.

        Rules:
        1. If required_price is None: AUTO_PROMO_REQUIRED_PRICE_UNKNOWN
        2. If current_wb_price <= required_price: AUTO_PROMO_PRICE_OK
        3. If current_wb_price > required_price: check if candidate_price passes MRC bounds
        4. candidate_price = required_price
           - candidate_price >= lower_bound
           - candidate_price <= upper_bound
           - candidate_price >= min_price (if set)
           - candidate_price > 0
        """
        mrc_price = product.mrc_price or Decimal("0")
        wb_nm_id = _extract_nm_id(product)
        if wb_nm_id is None:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=0,
                wb_promotion_id=None,
                mrc_price=mrc_price,
                current_wb_price=current_wb_price,
                required_price=None,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=Decimal("0"),
                mrc_upper_bound=Decimal("0"),
                status=STATUS_AUTO_PROMO_WAITING_WB_SYNC,
                reason="Нет nmID WB",
            )

        settings = await self._settings_service.get_settings(
            user_id=product.user_id,
            marketplace_account_id=product.marketplace_account_id,
        )

        deviation = settings.allowed_action_price_deviation_percent
        lower_bound = mrc_price * (Decimal("1") - deviation / Decimal("100"))
        upper_bound = mrc_price * (Decimal("1") + deviation / Decimal("100"))

        if required_price is None:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=None,
                mrc_price=mrc_price,
                current_wb_price=current_wb_price,
                required_price=None,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_AUTO_PROMO_REQUIRED_PRICE_UNKNOWN,
                reason="Автоакции WB найдены, требуется цена входа",
            )

        if current_wb_price is not None and current_wb_price <= required_price:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=None,
                mrc_price=mrc_price,
                current_wb_price=current_wb_price,
                required_price=required_price,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_AUTO_PROMO_PRICE_OK,
                reason="Цена подходит для автоакции",
            )

        candidate_price = required_price

        if candidate_price <= 0:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=None,
                mrc_price=mrc_price,
                current_wb_price=current_wb_price,
                required_price=required_price,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_AUTO_PROMO_PRICE_VIOLATION,
                reason="Цена автоакции некорректна (<=0)",
            )

        if candidate_price < lower_bound:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=None,
                mrc_price=mrc_price,
                current_wb_price=current_wb_price,
                required_price=required_price,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_AUTO_PROMO_PRICE_VIOLATION,
                reason="Цена автоакции ниже допустимой МРЦ",
            )

        if candidate_price > upper_bound:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=None,
                mrc_price=mrc_price,
                current_wb_price=current_wb_price,
                required_price=required_price,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_AUTO_PROMO_PRICE_VIOLATION,
                reason="Цена автоакции выше допустимого отклонения от МРЦ",
            )

        if min_price is not None and candidate_price < min_price:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=None,
                mrc_price=mrc_price,
                current_wb_price=current_wb_price,
                required_price=required_price,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_AUTO_PROMO_MIN_PRICE_VIOLATION,
                reason=f"Цена автоакции ниже minPrice ({min_price})",
            )

        return AutoPromoPriceRecommendation(
            product_id=product.id,
            wb_nm_id=wb_nm_id,
            wb_promotion_id=None,
            mrc_price=mrc_price,
            current_wb_price=current_wb_price,
            required_price=required_price,
            recommended_price=candidate_price,
            min_price=min_price,
            mrc_lower_bound=lower_bound,
            mrc_upper_bound=upper_bound,
            status=STATUS_AUTO_PROMO_SET_PRICE,
            reason=f"Можно изменить цену до {candidate_price:.0f} ₽ для входа в автоакцию",
        )

    async def save_recommendation(
        self,
        rec: AutoPromoPriceRecommendation,
        user_id: int,
        marketplace_account_id: int,
    ) -> WbAutoPromoPriceRecommendation:
        """Save or update a price recommendation in the database."""
        existing = await self.session.execute(
            select(WbAutoPromoPriceRecommendation).where(
                WbAutoPromoPriceRecommendation.product_id == rec.product_id,
                WbAutoPromoPriceRecommendation.marketplace_account_id == marketplace_account_id,
            )
        )
        record = existing.scalar_one_or_none()

        if record is None:
            record = WbAutoPromoPriceRecommendation(
                user_id=user_id,
                marketplace_account_id=marketplace_account_id,
                product_id=rec.product_id,
                wb_nm_id=rec.wb_nm_id,
            )
            self.session.add(record)

        record.wb_promotion_id = rec.wb_promotion_id
        record.mrc_price = rec.mrc_price
        record.current_wb_price = rec.current_wb_price
        record.required_price = rec.required_price
        record.recommended_price = rec.recommended_price
        record.min_price = rec.min_price
        record.mrc_lower_bound = rec.mrc_lower_bound
        record.mrc_upper_bound = rec.mrc_upper_bound
        record.status = rec.status
        record.reason = rec.reason

        await self.session.flush()
        return record

    async def get_recommendations_for_account(
        self,
        user_id: int,
        marketplace_account_id: int,
        status_filter: str | None = None,
    ) -> list[WbAutoPromoPriceRecommendation]:
        """Get latest recommendations for an account."""
        query = (
            select(WbAutoPromoPriceRecommendation)
            .where(
                WbAutoPromoPriceRecommendation.user_id == user_id,
                WbAutoPromoPriceRecommendation.marketplace_account_id == marketplace_account_id,
            )
            .order_by(WbAutoPromoPriceRecommendation.updated_at.desc())
        )
        if status_filter:
            query = query.where(WbAutoPromoPriceRecommendation.status == status_filter)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def build_recommendations_for_active_auto_promos(
        self,
        user_id: int,
        marketplace_account_id: int,
    ) -> list[AutoPromoPriceRecommendation]:
        """Build recommendations for all products with MRC when auto promotions are active."""
        now_utc = datetime.now(tz=UTC)

        active_auto_promos_result = await self.session.execute(
            select(WbPromotion).where(
                WbPromotion.marketplace_account_id == marketplace_account_id,
                WbPromotion.promotion_type == "auto",
                WbPromotion.start_datetime <= now_utc,
                WbPromotion.end_datetime >= now_utc,
            )
        )
        active_auto_promos = list(active_auto_promos_result.scalars().all())

        if not active_auto_promos:
            return []

        products_result = await self.session.execute(
            select(Product).where(
                Product.user_id == user_id,
                Product.marketplace_account_id == marketplace_account_id,
                Product.mrc_price.isnot(None),
                Product.mrc_price > 0,
            )
        )
        products = list(products_result.scalars().all())

        recommendations: list[AutoPromoPriceRecommendation] = []

        for product in products:
            wb_nm_id = _extract_nm_id(product)
            if wb_nm_id is None:
                continue

            required_price = await self._find_required_price_for_product(
                marketplace_account_id=marketplace_account_id,
                wb_nm_id=wb_nm_id,
                active_promos=active_auto_promos,
            )

            rec = await self.build_recommendation(
                product=product,
                current_wb_price=None,
                required_price=required_price,
            )
            if active_auto_promos:
                rec.wb_promotion_id = active_auto_promos[0].wb_promotion_id
            recommendations.append(rec)

        return recommendations

    async def _find_required_price_for_product(
        self,
        marketplace_account_id: int,
        wb_nm_id: int,
        active_promos: list[WbPromotion],
    ) -> Decimal | None:
        """Find the required price for a product from nomenclatures or promotion conditions."""

        from app.models.domain import WbPromotionNomenclature

        active_promo_ids = [p.wb_promotion_id for p in active_promos]
        if not active_promo_ids:
            return None

        result = await self.session.execute(
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

        conditions_result = await self.session.execute(
            select(WbAutoPromotionCondition.required_price)
            .where(
                WbAutoPromotionCondition.marketplace_account_id == marketplace_account_id,
                WbAutoPromotionCondition.wb_nm_id == wb_nm_id,
                WbAutoPromotionCondition.required_price.isnot(None),
            )
            .limit(1)
        )
        return conditions_result.scalar_one_or_none()


def _extract_nm_id(product: Product) -> int | None:
    """Extract WB nmID from product."""
    if product.marketplace_article and product.marketplace_article.isdigit():
        return int(product.marketplace_article)
    if product.external_product_id and product.external_product_id.isdigit():
        return int(product.external_product_id)
    return None
