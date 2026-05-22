"""version: 1.0.0
description: WB promotion recommendations engine.
    Determines product status for regular and auto promotions.
updated: 2026-05-22
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, Product, WbPromotion, WbPromotionNomenclature
from app.models.enums import Marketplace
from app.services.pricing.mrc_pricing_settings_service import MrcPricingSettingsService, MrcSettingsResult
from app.services.pricing.wb_mrc_price_service import WbMrcPriceService
from app.services.wb.wb_promotions_sync_service import WbPromotionsSyncService

logger = logging.getLogger(__name__)

# Regular promotion statuses
STATUS_OK = "OK"
STATUS_NOT_IN_ACTION = "NOT_IN_ACTION"
STATUS_RECOMMEND_ADD = "RECOMMEND_ADD"
STATUS_VIOLATION = "VIOLATION"
STATUS_NO_NM_ID = "NO_NM_ID"
STATUS_NO_MRC = "NO_MRC"

# Auto promotion statuses
STATUS_AUTO_ALREADY_IN_ACTION = "AUTO_PROMO_ALREADY_IN_ACTION"
STATUS_AUTO_SET_PRICE = "AUTO_PROMO_SET_PRICE"
STATUS_AUTO_PRICE_VIOLATION = "AUTO_PROMO_PRICE_VIOLATION"
STATUS_AUTO_PRICE_ALREADY_OK = "AUTO_PROMO_PRICE_ALREADY_OK_WAITING_SYNC"
STATUS_AUTO_UNSUPPORTED_DATA = "AUTO_PROMO_UNSUPPORTED_DATA"
STATUS_AUTO_PRICE_UPDATED = "AUTO_PROMO_PRICE_UPDATED_WAITING_WB_SYNC"


@dataclass(slots=True)
class PromotionRecommendation:
    product: Product
    wb_nm_id: int | None
    mrc_price: Decimal | None
    current_price: Decimal | None
    promotion_id: int | None
    promotion_name: str | None
    promotion_type: str | None
    is_auto_promo: bool
    in_action: bool
    plan_price: Decimal | None
    status: str
    reason: str
    recommended_price: Decimal | None
    lower_bound: Decimal | None
    upper_bound: Decimal | None


class PromotionRecommendationsService:
    """Build recommendations for products regarding WB promotions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_recommendations_for_user(
        self,
        user_id: int,
        marketplace_account_id: int | None = None,
    ) -> list[PromotionRecommendation]:
        """Get recommendations for all WB products with MRC."""
        query = (
            select(Product)
            .join(MarketplaceAccount, MarketplaceAccount.id == Product.marketplace_account_id)
            .where(Product.user_id == user_id)
            .where(Product.marketplace == Marketplace.WB)
            .where(Product.is_active.is_(True))
            .where(Product.mrc_price.isnot(None))
            .where(Product.mrc_price > 0)
        )
        if marketplace_account_id is not None:
            query = query.where(Product.marketplace_account_id == marketplace_account_id)

        result = await self.session.execute(query.order_by(Product.seller_article))
        products = list(result.scalars().all())

        if not products:
            return []

        settings_service = MrcPricingSettingsService(self.session)
        sync_service = WbPromotionsSyncService(self.session)
        recommendations: list[PromotionRecommendation] = []

        for product in products:
            wb_nm_id = _extract_nm_id(product)
            if wb_nm_id is None:
                recommendations.append(PromotionRecommendation(
                    product=product,
                    wb_nm_id=None,
                    mrc_price=product.mrc_price,
                    current_price=None,
                    promotion_id=None,
                    promotion_name=None,
                    promotion_type=None,
                    is_auto_promo=False,
                    in_action=False,
                    plan_price=None,
                    status=STATUS_NO_NM_ID,
                    reason="Нет nmID WB",
                    recommended_price=None,
                    lower_bound=None,
                    upper_bound=None,
                ))
                continue

            settings = await settings_service.get_settings(
                user_id=user_id,
                marketplace_account_id=product.marketplace_account_id,
            )

            promo_nomenclature = await sync_service.get_actual_promo_for_product(
                marketplace_account_id=product.marketplace_account_id,
                wb_nm_id=wb_nm_id,
            )

            rec = await self._build_recommendation(
                product=product,
                wb_nm_id=wb_nm_id,
                promo_nomenclature=promo_nomenclature,
                settings=settings,
            )
            recommendations.append(rec)

        return recommendations

    async def _build_recommendation(
        self,
        product: Product,
        wb_nm_id: int,
        promo_nomenclature: WbPromotionNomenclature | None,
        settings: MrcSettingsResult,
    ) -> PromotionRecommendation:
        """Build a single recommendation for a product."""
        mrc_price = product.mrc_price

        if promo_nomenclature is None:
            return PromotionRecommendation(
                product=product,
                wb_nm_id=wb_nm_id,
                mrc_price=mrc_price,
                current_price=None,
                promotion_id=None,
                promotion_name=None,
                promotion_type=None,
                is_auto_promo=False,
                in_action=False,
                plan_price=None,
                status=STATUS_NOT_IN_ACTION,
                reason="Нет подходящих акций",
                recommended_price=None,
                lower_bound=None,
                upper_bound=None,
            )

        # Get promotion details
        promo_result = await self.session.execute(
            select(WbPromotion).where(
                WbPromotion.marketplace_account_id == promo_nomenclature.marketplace_account_id,
                WbPromotion.wb_promotion_id == promo_nomenclature.wb_promotion_id,
            )
        )
        promotion = promo_result.scalar_one_or_none()

        promotion_type = promotion.promotion_type if promotion else ""
        is_auto = promotion_type and promotion_type.lower() == "auto"
        plan_price = promo_nomenclature.plan_price
        in_action = promo_nomenclature.in_action

        # Calculate bounds
        deviation = settings.allowed_action_price_deviation_percent
        lower_bound = mrc_price * (Decimal("1") - deviation / Decimal("100"))
        upper_bound = mrc_price * (Decimal("1") + deviation / Decimal("100"))

        if is_auto:
            return self._build_auto_recommendation(
                product=product,
                wb_nm_id=wb_nm_id,
                mrc_price=mrc_price,
                plan_price=plan_price,
                in_action=in_action,
                promotion=promotion,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                settings=settings,
            )

        return self._build_regular_recommendation(
            product=product,
            wb_nm_id=wb_nm_id,
            mrc_price=mrc_price,
            plan_price=plan_price,
            in_action=in_action,
            promotion=promotion,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        )

    def _build_regular_recommendation(
        self,
        product: Product,
        wb_nm_id: int,
        mrc_price: Decimal,
        plan_price: Decimal | None,
        in_action: bool,
        promotion: WbPromotion | None,
        lower_bound: Decimal,
        upper_bound: Decimal,
    ) -> PromotionRecommendation:
        """Build recommendation for a regular (non-auto) promotion."""
        if in_action:
            if plan_price and plan_price > 0:
                if lower_bound <= plan_price <= upper_bound:
                    return PromotionRecommendation(
                        product=product,
                        wb_nm_id=wb_nm_id,
                        mrc_price=mrc_price,
                        current_price=None,
                        promotion_id=promotion.wb_promotion_id if promotion else None,
                        promotion_name=promotion.name if promotion else None,
                        promotion_type=promotion.promotion_type if promotion else None,
                        is_auto_promo=False,
                        in_action=True,
                        plan_price=plan_price,
                        status=STATUS_OK,
                        reason="Товар участвует в акции, цена в допустимом диапазоне",
                        recommended_price=None,
                        lower_bound=lower_bound,
                        upper_bound=upper_bound,
                    )
                else:
                    return PromotionRecommendation(
                        product=product,
                        wb_nm_id=wb_nm_id,
                        mrc_price=mrc_price,
                        current_price=None,
                        promotion_id=promotion.wb_promotion_id if promotion else None,
                        promotion_name=promotion.name if promotion else None,
                        promotion_type=promotion.promotion_type if promotion else None,
                        is_auto_promo=False,
                        in_action=True,
                        plan_price=plan_price,
                        status=STATUS_VIOLATION,
                        reason="Цена в акции отличается от МРЦ больше допустимого процента",
                        recommended_price=None,
                        lower_bound=lower_bound,
                        upper_bound=upper_bound,
                    )

        # Not in action but available
        if plan_price and plan_price > 0:
            if lower_bound <= plan_price <= upper_bound:
                return PromotionRecommendation(
                    product=product,
                    wb_nm_id=wb_nm_id,
                    mrc_price=mrc_price,
                    current_price=None,
                    promotion_id=promotion.wb_promotion_id if promotion else None,
                    promotion_name=promotion.name if promotion else None,
                    promotion_type=promotion.promotion_type if promotion else None,
                    is_auto_promo=False,
                    in_action=False,
                    plan_price=plan_price,
                    status=STATUS_RECOMMEND_ADD,
                    reason="Рекомендовано добавить в акцию",
                    recommended_price=plan_price,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                )
            else:
                return PromotionRecommendation(
                    product=product,
                    wb_nm_id=wb_nm_id,
                    mrc_price=mrc_price,
                    current_price=None,
                    promotion_id=promotion.wb_promotion_id if promotion else None,
                    promotion_name=promotion.name if promotion else None,
                    promotion_type=promotion.promotion_type if promotion else None,
                    is_auto_promo=False,
                    in_action=False,
                    plan_price=plan_price,
                    status=STATUS_VIOLATION,
                    reason="Цена акции нарушает МРЦ — не добавлять",
                    recommended_price=None,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                )

        return PromotionRecommendation(
            product=product,
            wb_nm_id=wb_nm_id,
            mrc_price=mrc_price,
            current_price=None,
            promotion_id=promotion.wb_promotion_id if promotion else None,
            promotion_name=promotion.name if promotion else None,
            promotion_type=promotion.promotion_type if promotion else None,
            is_auto_promo=False,
            in_action=False,
            plan_price=plan_price,
            status=STATUS_NOT_IN_ACTION,
            reason="Нет данных о цене для участия",
            recommended_price=None,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        )

    def _build_auto_recommendation(
        self,
        product: Product,
        wb_nm_id: int,
        mrc_price: Decimal,
        plan_price: Decimal | None,
        in_action: bool,
        promotion: WbPromotion | None,
        lower_bound: Decimal,
        upper_bound: Decimal,
        settings: MrcSettingsResult,
    ) -> PromotionRecommendation:
        """Build recommendation for an auto promotion."""
        if in_action:
            return PromotionRecommendation(
                product=product,
                wb_nm_id=wb_nm_id,
                mrc_price=mrc_price,
                current_price=None,
                promotion_id=promotion.wb_promotion_id if promotion else None,
                promotion_name=promotion.name if promotion else None,
                promotion_type=promotion.promotion_type if promotion else None,
                is_auto_promo=True,
                in_action=True,
                plan_price=plan_price,
                status=STATUS_AUTO_ALREADY_IN_ACTION,
                reason="Товар уже участвует в автоакции WB",
                recommended_price=None,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
            )

        # Not in action — check if we can set a price
        required_price = self._determine_required_auto_price(plan_price, promotion)
        if required_price is None:
            return PromotionRecommendation(
                product=product,
                wb_nm_id=wb_nm_id,
                mrc_price=mrc_price,
                current_price=None,
                promotion_id=promotion.wb_promotion_id if promotion else None,
                promotion_name=promotion.name if promotion else None,
                promotion_type=promotion.promotion_type if promotion else None,
                is_auto_promo=True,
                in_action=False,
                plan_price=plan_price,
                status=STATUS_AUTO_UNSUPPORTED_DATA,
                reason="WB не вернул требуемую цену для автоакции",
                recommended_price=None,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
            )

        # Check if current price already meets requirement
        # We don't have current_price from nomenclature directly, use plan_price as reference
        if plan_price and plan_price <= required_price:
            return PromotionRecommendation(
                product=product,
                wb_nm_id=wb_nm_id,
                mrc_price=mrc_price,
                current_price=plan_price,
                promotion_id=promotion.wb_promotion_id if promotion else None,
                promotion_name=promotion.name if promotion else None,
                promotion_type=promotion.promotion_type if promotion else None,
                is_auto_promo=True,
                in_action=False,
                plan_price=plan_price,
                status=STATUS_AUTO_PRICE_ALREADY_OK,
                reason="Цена уже соответствует условию автоакции, ожидается обновление статуса WB",
                recommended_price=None,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
            )

        # Check if required price passes MRC bounds
        if required_price < lower_bound:
            return PromotionRecommendation(
                product=product,
                wb_nm_id=wb_nm_id,
                mrc_price=mrc_price,
                current_price=None,
                promotion_id=promotion.wb_promotion_id if promotion else None,
                promotion_name=promotion.name if promotion else None,
                promotion_type=promotion.promotion_type if promotion else None,
                is_auto_promo=True,
                in_action=False,
                plan_price=plan_price,
                status=STATUS_AUTO_PRICE_VIOLATION,
                reason="Цена автоакции ниже допустимой МРЦ",
                recommended_price=None,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
            )

        if required_price > upper_bound:
            return PromotionRecommendation(
                product=product,
                wb_nm_id=wb_nm_id,
                mrc_price=mrc_price,
                current_price=None,
                promotion_id=promotion.wb_promotion_id if promotion else None,
                promotion_name=promotion.name if promotion else None,
                promotion_type=promotion.promotion_type if promotion else None,
                is_auto_promo=True,
                in_action=False,
                plan_price=plan_price,
                status=STATUS_AUTO_PRICE_VIOLATION,
                reason="Цена автоакции выше допустимого отклонения от МРЦ",
                recommended_price=None,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
            )

        # Price is within bounds — recommend setting it
        return PromotionRecommendation(
            product=product,
            wb_nm_id=wb_nm_id,
            mrc_price=mrc_price,
            current_price=None,
            promotion_id=promotion.wb_promotion_id if promotion else None,
            promotion_name=promotion.name if promotion else None,
            promotion_type=promotion.promotion_type if promotion else None,
            is_auto_promo=True,
            in_action=False,
            plan_price=plan_price,
            status=STATUS_AUTO_SET_PRICE,
            reason=f"Можно изменить цену до {required_price:.0f} ₽ для входа в автоакцию",
            recommended_price=required_price,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        )

    @staticmethod
    def _determine_required_auto_price(
        plan_price: Decimal | None,
        promotion: WbPromotion | None,
    ) -> Decimal | None:
        """Determine required price for auto promotion participation."""
        if plan_price and plan_price > 0:
            return plan_price

        if promotion and promotion.raw_payload:
            raw = promotion.raw_payload
            for key in ("planPrice", "requiredPrice", "maxPrice", "price"):
                val = raw.get(key)
                if val is not None:
                    try:
                        return Decimal(str(val))
                    except Exception:
                        continue

        return None


def _extract_nm_id(product: Product) -> int | None:
    """Extract WB nmID from product."""
    if product.marketplace_article and product.marketplace_article.isdigit():
        return int(product.marketplace_article)
    if product.external_product_id and product.external_product_id.isdigit():
        return int(product.external_product_id)
    return None
