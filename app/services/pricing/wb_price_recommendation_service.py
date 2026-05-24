"""Build WB auto-promotion price recommendations from MRC and API conditions."""

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    Product,
    WbAutoPromoPriceRecommendation,
    WbAutoPromotionCondition,
    WbProductPrice,
)
from app.models.enums import Marketplace
from app.services.pricing.mrc_pricing_settings_service import MrcPricingSettingsService
from app.services.pricing.wb_price_apply_service import WbPriceApplyService

logger = logging.getLogger(__name__)

STATUS_NO_REQUIRED_PRICE = "NO_REQUIRED_PRICE"
STATUS_ALREADY_OK = "ALREADY_OK"
STATUS_BLOCKED_BY_MRC = "BLOCKED_BY_MRC"
STATUS_BLOCKED_BY_MIN_PRICE = "BLOCKED_BY_MIN_PRICE"
STATUS_CAN_APPLY = "CAN_APPLY"


@dataclass(slots=True)
class WbPriceRecommendation:
    product_id: int
    wb_nm_id: int
    wb_promotion_id: int | None
    promotion_name: str | None
    mrc_price: Decimal
    current_wb_price: Decimal | None
    required_price: Decimal | None
    lower_bound: Decimal
    upper_bound: Decimal
    recommended_price: Decimal | None
    min_price: Decimal | None
    full_wb_price: int | None
    discount: int | None
    status: str
    reason: str


class WbPriceRecommendationService:
    """Recommendation calculation kept separate from WB sync and upload."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    @staticmethod
    def calculate(
        *,
        product_id: int = 0,
        wb_nm_id: int = 0,
        mrc_price: Decimal,
        current_wb_price: Decimal | None,
        required_price: Decimal | None,
        allowed_deviation_percent: Decimal = Decimal("10"),
        min_price: Decimal | None = None,
        discount: Decimal = Decimal("75"),
        wb_promotion_id: int | None = None,
        promotion_name: str | None = None,
    ) -> WbPriceRecommendation:
        lower_bound = mrc_price * (Decimal("1") - allowed_deviation_percent / Decimal("100"))
        upper_bound = mrc_price * (Decimal("1") + allowed_deviation_percent / Decimal("100"))

        if required_price is None:
            return WbPriceRecommendation(
                product_id=product_id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_wb_price=current_wb_price,
                required_price=None,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                recommended_price=None,
                min_price=min_price,
                full_wb_price=None,
                discount=None,
                status=STATUS_NO_REQUIRED_PRICE,
                reason="WB API не отдал цену входа. Откройте диагностику raw_payload.",
            )

        if current_wb_price is not None and current_wb_price <= required_price:
            return WbPriceRecommendation(
                product_id=product_id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_wb_price=current_wb_price,
                required_price=required_price,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                recommended_price=None,
                min_price=min_price,
                full_wb_price=None,
                discount=None,
                status=STATUS_ALREADY_OK,
                reason="Текущая цена WB уже подходит для автоакции.",
            )

        if required_price < lower_bound or required_price > upper_bound:
            return WbPriceRecommendation(
                product_id=product_id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_wb_price=current_wb_price,
                required_price=required_price,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                recommended_price=None,
                min_price=min_price,
                full_wb_price=None,
                discount=None,
                status=STATUS_BLOCKED_BY_MRC,
                reason="Цена входа автоакции вне допустимых границ МРЦ.",
            )

        if min_price is not None and required_price < min_price:
            return WbPriceRecommendation(
                product_id=product_id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_wb_price=current_wb_price,
                required_price=required_price,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                recommended_price=None,
                min_price=min_price,
                full_wb_price=None,
                discount=None,
                status=STATUS_BLOCKED_BY_MIN_PRICE,
                reason="Цена входа ниже minPrice WB.",
            )

        payload = WbPriceApplyService.build_payload(
            nm_id=wb_nm_id,
            recommended_price=required_price,
            discount=discount,
            min_price=min_price,
        )
        return WbPriceRecommendation(
            product_id=product_id,
            wb_nm_id=wb_nm_id,
            wb_promotion_id=wb_promotion_id,
            promotion_name=promotion_name,
            mrc_price=mrc_price,
            current_wb_price=current_wb_price,
            required_price=required_price,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            recommended_price=required_price,
            min_price=min_price,
            full_wb_price=payload.price,
            discount=payload.discount,
            status=STATUS_CAN_APPLY,
            reason="Можно применить цену входа автоакции.",
        )

    async def build_for_account(
        self,
        *,
        user_id: int,
        marketplace_account_id: int,
    ) -> list[WbPriceRecommendation]:
        if self.session is None:
            raise RuntimeError("session is required for DB-backed recommendations")

        settings = await MrcPricingSettingsService(self.session).get_settings(
            user_id=user_id,
            marketplace_account_id=marketplace_account_id,
        )
        products_result = await self.session.execute(
            select(Product).where(
                Product.user_id == user_id,
                Product.marketplace_account_id == marketplace_account_id,
                Product.marketplace == Marketplace.WB,
                Product.mrc_price.isnot(None),
                Product.mrc_price > 0,
            )
        )

        recommendations: list[WbPriceRecommendation] = []
        for product in products_result.scalars().all():
            wb_nm_id = self._extract_nm_id(product)
            if wb_nm_id is None:
                continue
            condition = await self._get_condition(marketplace_account_id, wb_nm_id)
            current_price, min_price = await self._get_current_prices(
                marketplace_account_id,
                wb_nm_id,
            )
            recommendations.append(
                self.calculate(
                    product_id=product.id,
                    wb_nm_id=wb_nm_id,
                    wb_promotion_id=condition.wb_promotion_id if condition else None,
                    promotion_name=condition.promotion_name if condition else None,
                    mrc_price=product.mrc_price,
                    current_wb_price=current_price,
                    required_price=condition.required_price if condition else None,
                    allowed_deviation_percent=settings.allowed_action_price_deviation_percent,
                    min_price=min_price,
                    discount=settings.default_discount_percent,
                )
            )
        return recommendations

    async def save_for_account(
        self,
        *,
        user_id: int,
        marketplace_account_id: int,
        commit: bool = True,
    ) -> list[WbPriceRecommendation]:
        recommendations = await self.build_for_account(
            user_id=user_id,
            marketplace_account_id=marketplace_account_id,
        )
        for rec in recommendations:
            await self._save(rec, user_id, marketplace_account_id)
        if self.session is not None and commit:
            await self.session.commit()
        return recommendations

    async def _save(
        self,
        rec: WbPriceRecommendation,
        user_id: int,
        marketplace_account_id: int,
    ) -> None:
        assert self.session is not None
        result = await self.session.execute(
            select(WbAutoPromoPriceRecommendation).where(
                WbAutoPromoPriceRecommendation.marketplace_account_id == marketplace_account_id,
                WbAutoPromoPriceRecommendation.product_id == rec.product_id,
                WbAutoPromoPriceRecommendation.wb_nm_id == rec.wb_nm_id,
            )
        )
        record = result.scalar_one_or_none()
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
        record.mrc_lower_bound = rec.lower_bound
        record.mrc_upper_bound = rec.upper_bound
        record.status = rec.status
        record.reason = rec.reason
        record.source = "wb_api"
        await self.session.flush()

    async def _get_condition(
        self,
        marketplace_account_id: int,
        wb_nm_id: int,
    ) -> WbAutoPromotionCondition | None:
        assert self.session is not None
        result = await self.session.execute(
            select(WbAutoPromotionCondition)
            .where(
                WbAutoPromotionCondition.marketplace_account_id == marketplace_account_id,
                WbAutoPromotionCondition.wb_nm_id == wb_nm_id,
                WbAutoPromotionCondition.source == "wb_api",
            )
            .order_by(
                WbAutoPromotionCondition.required_price.is_(None),
                WbAutoPromotionCondition.synced_at.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_current_prices(
        self,
        marketplace_account_id: int,
        wb_nm_id: int,
    ) -> tuple[Decimal | None, Decimal | None]:
        assert self.session is not None
        result = await self.session.execute(
            select(WbProductPrice)
            .where(
                WbProductPrice.marketplace_account_id == marketplace_account_id,
                WbProductPrice.wb_nm_id == wb_nm_id,
            )
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None, None
        current = row.discounted_price or row.club_discounted_price or row.price
        raw = row.raw_payload or {}
        min_price = self._money(raw.get("minPrice") or raw.get("minPriceForNm"))
        return current, min_price

    @staticmethod
    def _extract_nm_id(product: Product) -> int | None:
        for value in (product.external_product_id, product.marketplace_article):
            if value is None:
                continue
            try:
                return int(str(value).strip())
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _money(value: object) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None
