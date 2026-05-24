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
    WbProductPrice,
    WbPromotion,
)
from app.models.enums import Marketplace
from app.services.pricing.mrc_pricing_settings_service import (
    MrcPricingSettingsService,
)

logger = logging.getLogger(__name__)

STATUS_NO_PROMOTION = "NO_PROMOTION"
STATUS_REGULAR_PROMOTION_ACTIVE = "REGULAR_PROMOTION_ACTIVE"
STATUS_REGULAR_PROMOTION_AVAILABLE = "REGULAR_PROMOTION_AVAILABLE"
STATUS_AUTO_REQUIRED_PRICE_UNKNOWN = "AUTO_PROMOTION_REQUIRED_PRICE_UNKNOWN"
STATUS_AUTO_PRICE_OK = "AUTO_PROMOTION_PRICE_OK"
STATUS_AUTO_SET_PRICE = "AUTO_PROMOTION_SET_PRICE"
STATUS_AUTO_PRICE_VIOLATION = "AUTO_PROMOTION_PRICE_VIOLATION"
STATUS_AUTO_MIN_PRICE_VIOLATION = "AUTO_PROMOTION_MIN_PRICE_VIOLATION"
STATUS_AUTO_WAITING_WB_SYNC = "AUTO_PROMOTION_WAITING_WB_SYNC"


@dataclass(slots=True)
class AutoPromoPriceRecommendation:
    product_id: int
    wb_nm_id: int
    wb_promotion_id: int | None
    promotion_name: str | None
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
        condition: WbAutoPromotionCondition | None = None,
        current_wb_price: Decimal | None = None,
        min_price: Decimal | None = None,
        required_price: Decimal | None = None,
    ) -> AutoPromoPriceRecommendation:
        """Build a price recommendation for a product in an auto promotion.

        Priority for required_price:
        1. Explicit required_price parameter
        2. condition.required_price
        3. None -> AUTO_PROMOTION_REQUIRED_PRICE_UNKNOWN
        """
        mrc_price = product.mrc_price or Decimal("0")
        wb_nm_id = _extract_nm_id(product)
        if wb_nm_id is None:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=0,
                wb_promotion_id=None,
                promotion_name=None,
                mrc_price=mrc_price,
                current_wb_price=current_wb_price,
                required_price=None,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=Decimal("0"),
                mrc_upper_bound=Decimal("0"),
                status=STATUS_AUTO_WAITING_WB_SYNC,
                reason="Нет nmID WB",
            )

        settings = await self._settings_service.get_settings(
            user_id=product.user_id,
            marketplace_account_id=product.marketplace_account_id,
        )

        deviation = settings.allowed_action_price_deviation_percent
        lower_bound = mrc_price * (Decimal("1") - deviation / Decimal("100"))
        upper_bound = mrc_price * (Decimal("1") + deviation / Decimal("100"))

        eff_required = required_price
        if eff_required is None and condition is not None:
            eff_required = condition.required_price

        promotion_name = None
        wb_promotion_id = None
        if condition is not None:
            promotion_name = condition.promotion_name
            wb_promotion_id = condition.wb_promotion_id

        eff_current = current_wb_price
        if eff_current is None and condition is not None:
            eff_current = condition.current_wb_price

        if eff_required is None:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_wb_price=eff_current,
                required_price=None,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_AUTO_REQUIRED_PRICE_UNKNOWN,
                reason="Автоакции WB найдены, нужна цена входа",
            )

        if eff_current is not None and eff_current <= eff_required:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_wb_price=eff_current,
                required_price=eff_required,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_AUTO_PRICE_OK,
                reason="Цена подходит для автоакции",
            )

        candidate_price = eff_required

        if candidate_price <= 0:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_wb_price=eff_current,
                required_price=eff_required,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_AUTO_PRICE_VIOLATION,
                reason="Цена автоакции некорректна (<=0)",
            )

        if min_price is not None and candidate_price < min_price:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_wb_price=eff_current,
                required_price=eff_required,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_AUTO_MIN_PRICE_VIOLATION,
                reason=f"Цена входа ниже minPrice ({min_price})",
            )

        if candidate_price < lower_bound:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_wb_price=eff_current,
                required_price=eff_required,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_AUTO_PRICE_VIOLATION,
                reason="Цена входа ниже допустимой цены по МРЦ",
            )

        if candidate_price > upper_bound:
            return AutoPromoPriceRecommendation(
                product_id=product.id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_wb_price=eff_current,
                required_price=eff_required,
                recommended_price=None,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_AUTO_PRICE_VIOLATION,
                reason="Цена автоакции выше допустимого отклонения от МРЦ",
            )

        return AutoPromoPriceRecommendation(
            product_id=product.id,
            wb_nm_id=wb_nm_id,
            wb_promotion_id=wb_promotion_id,
            promotion_name=promotion_name,
            mrc_price=mrc_price,
            current_wb_price=eff_current,
            required_price=eff_required,
            recommended_price=candidate_price,
            min_price=min_price,
            mrc_lower_bound=lower_bound,
            mrc_upper_bound=upper_bound,
            status=STATUS_AUTO_SET_PRICE,
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
        record.promotion_name = rec.promotion_name
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

    async def build_recommendations_for_conditions(
        self,
        user_id: int,
        marketplace_account_id: int,
    ) -> list[AutoPromoPriceRecommendation]:
        """Build recommendations for products matching imported conditions."""
        conditions_result = await self.session.execute(
            select(WbAutoPromotionCondition).where(
                WbAutoPromotionCondition.marketplace_account_id == marketplace_account_id,
                WbAutoPromotionCondition.required_price.isnot(None),
            )
        )
        conditions = list(conditions_result.scalars().all())

        if not conditions:
            return []

        recommendations: list[AutoPromoPriceRecommendation] = []

        for condition in conditions:
            product_result = await self.session.execute(
                select(Product).where(
                    Product.marketplace_account_id == marketplace_account_id,
                    Product.marketplace == Marketplace.WB,
                    (Product.external_product_id == str(condition.wb_nm_id))
                    | (Product.marketplace_article == str(condition.wb_nm_id)),
                ).limit(1)
            )
            product = product_result.scalar_one_or_none()
            if product is None or product.mrc_price is None:
                continue

            current_wb_price = await self._get_current_wb_price_from_db(
                marketplace_account_id, condition.wb_nm_id,
            )

            rec = await self.build_recommendation(
                product=product,
                condition=condition,
                current_wb_price=current_wb_price,
            )
            recommendations.append(rec)

            logger.info(
                "wb_auto_promo_recommendation_created",
                extra={
                    "product_id": product.id,
                    "wb_nm_id": condition.wb_nm_id,
                    "status": rec.status,
                    "required_price": str(rec.required_price),
                    "recommended_price": str(rec.recommended_price),
                },
            )

        return recommendations

    async def _get_current_wb_price_from_db(
        self,
        marketplace_account_id: int,
        wb_nm_id: int,
    ) -> Decimal | None:
        """Get current WB price from wb_product_prices, then nomenclatures, then conditions."""
        result = await self.session.execute(
            select(WbProductPrice.discounted_price)
            .where(
                WbProductPrice.marketplace_account_id == marketplace_account_id,
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

        from app.models.domain import WbPromotionNomenclature

        result = await self.session.execute(
            select(WbPromotionNomenclature.current_price)
            .where(
                WbPromotionNomenclature.marketplace_account_id == marketplace_account_id,
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

        cond_result = await self.session.execute(
            select(WbAutoPromotionCondition.current_wb_price)
            .where(
                WbAutoPromotionCondition.marketplace_account_id == marketplace_account_id,
                WbAutoPromotionCondition.wb_nm_id == wb_nm_id,
                WbAutoPromotionCondition.current_wb_price.isnot(None),
                WbAutoPromotionCondition.current_wb_price > 0,
            )
            .limit(1)
        )
        return cond_result.scalar_one_or_none()

    async def build_recommendations_for_active_auto_promos(
        self,
        user_id: int,
        marketplace_account_id: int,
    ) -> list[AutoPromoPriceRecommendation]:
        """Build recommendations for all products with MRC when auto promos active."""
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

            required_price = await self._find_required_price(
                marketplace_account_id=marketplace_account_id,
                wb_nm_id=wb_nm_id,
            )

            current_wb_price = await self._get_current_wb_price_from_db(
                marketplace_account_id=marketplace_account_id,
                wb_nm_id=wb_nm_id,
            )

            rec = await self.build_recommendation(
                product=product,
                current_wb_price=current_wb_price,
                required_price=required_price,
            )
            if active_auto_promos:
                rec.wb_promotion_id = active_auto_promos[0].wb_promotion_id
            recommendations.append(rec)

        return recommendations

    async def _find_required_price(
        self,
        marketplace_account_id: int,
        wb_nm_id: int,
    ) -> Decimal | None:
        """Find required price from conditions first, then nomenclatures.

        Priority:
        1. wb_auto_promotion_conditions (file_import or manual)
        2. wb_promotion_nomenclatures plan_price
        """
        cond_result = await self.session.execute(
            select(WbAutoPromotionCondition.required_price)
            .where(
                WbAutoPromotionCondition.marketplace_account_id == marketplace_account_id,
                WbAutoPromotionCondition.wb_nm_id == wb_nm_id,
                WbAutoPromotionCondition.required_price.isnot(None),
                WbAutoPromotionCondition.required_price > 0,
            )
            .limit(1)
        )
        price = cond_result.scalar_one_or_none()
        if price is not None:
            return price

        from app.models.domain import WbPromotionNomenclature

        result = await self.session.execute(
            select(WbPromotionNomenclature.plan_price)
            .where(
                WbPromotionNomenclature.marketplace_account_id == marketplace_account_id,
                WbPromotionNomenclature.wb_nm_id == wb_nm_id,
                WbPromotionNomenclature.plan_price.isnot(None),
                WbPromotionNomenclature.plan_price > 0,
            )
            .order_by(WbPromotionNomenclature.plan_price.asc())
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
