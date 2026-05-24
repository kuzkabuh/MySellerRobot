"""Automatic WB auto-promotion participation pricing service."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.integrations.wb import WildberriesClient
from app.models.domain import (
    MarketplaceAccount,
    Product,
    WbAutoPromoPriceRecommendation,
    WbAutoPromotionCondition,
    WbPriceChangeHistory,
    WbProductPrice,
)
from app.models.enums import Marketplace
from app.services.pricing.mrc_pricing_settings_service import MrcPricingSettingsService
from app.services.pricing.wb_auto_promo_condition_resolver import WbAutoPromoConditionResolver
from app.services.pricing.wb_price_apply_service import WbPriceApplyPayload, WbPriceApplyService

logger = logging.getLogger(__name__)

STATUS_CAN_APPLY = "CAN_APPLY"
STATUS_ALREADY_ELIGIBLE = "ALREADY_ELIGIBLE"
STATUS_BLOCKED_BY_MRC = "BLOCKED_BY_MRC"
STATUS_BLOCKED_BY_MIN_PRICE = "BLOCKED_BY_MIN_PRICE"
STATUS_NO_AUTO_PROMO_PRICE = "NO_AUTO_PROMO_PRICE"
STATUS_NO_CURRENT_PRICE = "NO_CURRENT_PRICE"
STATUS_NO_MRC_PRICE = "NO_MRC_PRICE"
STATUS_WAITING_WB_SYNC = "WAITING_WB_SYNC"
STATUS_APPLIED = "APPLIED"
STATUS_FAILED = "FAILED"
STATUS_SAFE_PRICE_RESTORE = "AUTO_PROMO_NOT_AVAILABLE_SAFE_PRICE_RESTORE"


@dataclass(slots=True)
class AutoPromoParticipationRecommendation:
    product_id: int
    wb_nm_id: int
    wb_promotion_id: int | None
    promotion_name: str | None
    mrc_price: Decimal | None
    current_full_price: Decimal | None
    current_discount: int | None
    current_discounted_price: Decimal | None
    max_auto_promo_price: Decimal | None
    wb_condition_discount_percent: Decimal | None
    candidate_discounted_price: Decimal | None
    recommended_discounted_price: Decimal | None
    recommended_full_price: Decimal | None
    recommended_discount: int | None
    safe_discounted_price: Decimal | None
    safe_full_price: Decimal | None
    safe_discount: int | None
    min_price: Decimal | None
    mrc_lower_bound: Decimal | None
    mrc_upper_bound: Decimal | None
    status: str
    reason: str
    condition_type: str = "unknown"
    source: str = "wb_api"
    raw_payload: dict[str, Any] | None = None


class WbAutoPromoParticipationService:
    """Resolve WB auto-promo prices, validate MRC/minPrice, and apply WB payloads."""

    def __init__(
        self,
        session: AsyncSession,
        cipher: TokenCipher | None = None,
    ) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()

    async def sync_auto_promo_conditions(
        self,
        account_id: int,
    ) -> list[Any]:
        account = await self._get_account(account_id)
        return await WbAutoPromoConditionResolver().resolve_for_account(
            self.session,
            user_id=account.user_id,
            marketplace_account_id=account.id,
        )

    async def calculate_participation_recommendations(
        self,
        account_id: int,
        *,
        commit: bool = True,
    ) -> list[AutoPromoParticipationRecommendation]:
        account = await self._get_account(account_id)
        settings = await MrcPricingSettingsService(self.session).get_settings(
            user_id=account.user_id,
            marketplace_account_id=account.id,
        )
        products = list(
            (
                await self.session.execute(
                    select(Product).where(
                        Product.marketplace_account_id == account.id,
                        Product.marketplace == Marketplace.WB,
                        Product.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        result: list[AutoPromoParticipationRecommendation] = []
        for product in products:
            nm_id = self._extract_nm_id(product)
            if nm_id is None:
                continue
            condition = await self._get_condition(account.id, nm_id)
            current_price = await self._get_current_price(account.id, nm_id)
            current_full_price = (
                condition.current_full_price
                if condition and condition.current_full_price is not None
                else current_price.price if current_price else None
            )
            current_discount = (
                condition.current_discount
                if condition and condition.current_discount is not None
                else current_price.discount if current_price else None
            )
            current_discounted_price = (
                condition.current_discounted_price
                if condition and condition.current_discounted_price is not None
                else (
                    current_price.discounted_price
                    or current_price.club_discounted_price
                    or current_price.price
                    if current_price
                    else None
                )
            )
            rec = self.calculate(
                product_id=product.id,
                wb_nm_id=nm_id,
                wb_promotion_id=condition.wb_promotion_id if condition else None,
                promotion_name=condition.promotion_name if condition else None,
                mrc_price=product.mrc_price,
                current_full_price=current_full_price,
                current_discount=current_discount,
                current_discounted_price=current_discounted_price,
                max_auto_promo_price=(
                    condition.max_auto_promo_price or condition.required_price
                    if condition and condition.condition_type == "max_price"
                    else None
                ),
                wb_condition_discount_percent=(
                    condition.wb_condition_discount_percent if condition else None
                ),
                condition_type=condition.condition_type if condition else "unknown",
                min_price=self._extract_min_price(
                    current_price.raw_payload if current_price else None
                ),
                allowed_deviation_percent=settings.allowed_action_price_deviation_percent,
                discount=settings.default_discount_percent,
                raw_payload=condition.raw_payload if condition else None,
            )
            await self._save_recommendation(account, rec)
            result.append(rec)
        if commit:
            await self.session.commit()
        return result

    @staticmethod
    def calculate(
        *,
        product_id: int = 0,
        wb_nm_id: int = 0,
        wb_promotion_id: int | None = None,
        promotion_name: str | None = None,
        mrc_price: Decimal | None,
        current_full_price: Decimal | None,
        current_discount: int | None,
        current_discounted_price: Decimal | None,
        max_auto_promo_price: Decimal | None,
        wb_condition_discount_percent: Decimal | None = None,
        condition_type: str = "unknown",
        min_price: Decimal | None = None,
        allowed_deviation_percent: Decimal = Decimal("10"),
        discount: Decimal = Decimal("75"),
        raw_payload: dict[str, Any] | None = None,
    ) -> AutoPromoParticipationRecommendation:
        if mrc_price is None or mrc_price <= 0:
            return AutoPromoParticipationRecommendation(
                product_id=product_id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_full_price=current_full_price,
                current_discount=current_discount,
                current_discounted_price=current_discounted_price,
                max_auto_promo_price=max_auto_promo_price,
                wb_condition_discount_percent=wb_condition_discount_percent,
                candidate_discounted_price=None,
                recommended_discounted_price=None,
                recommended_full_price=None,
                recommended_discount=None,
                safe_discounted_price=None,
                safe_full_price=None,
                safe_discount=None,
                min_price=min_price,
                mrc_lower_bound=None,
                mrc_upper_bound=None,
                status=STATUS_NO_MRC_PRICE,
                reason="МРЦ товара не задана.",
                condition_type=condition_type,
                raw_payload=raw_payload,
            )

        lower_bound = mrc_price * (Decimal("1") - allowed_deviation_percent / Decimal("100"))
        upper_bound = mrc_price * (Decimal("1") + allowed_deviation_percent / Decimal("100"))
        safe_payload = WbPriceApplyService.build_payload(
            nm_id=wb_nm_id,
            recommended_price=mrc_price,
            discount=discount,
            max_discounted_price=mrc_price,
        )
        safe_full_price = Decimal(safe_payload.price)
        safe_discount = safe_payload.discount

        if current_discounted_price is None and current_full_price is None:
            return AutoPromoParticipationRecommendation(
                product_id=product_id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_full_price=current_full_price,
                current_discount=current_discount,
                current_discounted_price=None,
                max_auto_promo_price=max_auto_promo_price,
                wb_condition_discount_percent=wb_condition_discount_percent,
                candidate_discounted_price=None,
                recommended_discounted_price=None,
                recommended_full_price=None,
                recommended_discount=None,
                safe_discounted_price=mrc_price,
                safe_full_price=safe_full_price,
                safe_discount=safe_discount,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_NO_CURRENT_PRICE,
                reason="Текущая цена WB ещё не загружена.",
                condition_type=condition_type,
                raw_payload=raw_payload,
            )

        candidate = WbAutoPromoParticipationService._candidate_price(
            max_auto_promo_price=max_auto_promo_price,
            current_full_price=current_full_price,
            wb_condition_discount_percent=wb_condition_discount_percent,
        )
        resolved_condition_type = condition_type
        if max_auto_promo_price is not None:
            resolved_condition_type = "max_price"
        elif candidate is not None:
            resolved_condition_type = "discount_projection"

        if candidate is None:
            return AutoPromoParticipationRecommendation(
                product_id=product_id,
                wb_nm_id=wb_nm_id,
                wb_promotion_id=wb_promotion_id,
                promotion_name=promotion_name,
                mrc_price=mrc_price,
                current_full_price=current_full_price,
                current_discount=current_discount,
                current_discounted_price=current_discounted_price,
                max_auto_promo_price=None,
                wb_condition_discount_percent=wb_condition_discount_percent,
                candidate_discounted_price=None,
                recommended_discounted_price=None,
                recommended_full_price=None,
                recommended_discount=None,
                safe_discounted_price=mrc_price,
                safe_full_price=safe_full_price,
                safe_discount=safe_discount,
                min_price=min_price,
                mrc_lower_bound=lower_bound,
                mrc_upper_bound=upper_bound,
                status=STATUS_NO_AUTO_PROMO_PRICE,
                reason=(
                    "WB API не вернул максимальную цену для входа в автоакцию. "
                    "Откройте диагностику raw_payload."
                ),
                condition_type=resolved_condition_type,
                raw_payload=raw_payload,
            )

        if candidate <= 0:
            status = STATUS_NO_AUTO_PROMO_PRICE
            reason = "WB API вернул некорректное условие автоакции."
            rec_price = None
            payload = None
        elif candidate < lower_bound:
            status = STATUS_BLOCKED_BY_MRC
            reason = "Цена входа WB ниже минимально допустимой цены по МРЦ."
            rec_price = None
            payload = None
        elif min_price is not None and candidate < min_price:
            status = STATUS_BLOCKED_BY_MIN_PRICE
            reason = "Цена входа WB ниже minPrice продавца."
            rec_price = None
            payload = None
        elif current_discounted_price is not None and current_discounted_price <= candidate:
            status = STATUS_ALREADY_ELIGIBLE
            reason = "Текущая цена уже подходит для автоакции."
            rec_price = None
            payload = None
        else:
            payload = WbPriceApplyService.build_payload(
                nm_id=wb_nm_id,
                recommended_price=candidate,
                discount=discount,
                min_price=min_price,
                max_discounted_price=candidate,
            )
            status = STATUS_CAN_APPLY
            reason = "Можно применить цену входа WB для автоакции."
            rec_price = candidate

        return AutoPromoParticipationRecommendation(
            product_id=product_id,
            wb_nm_id=wb_nm_id,
            wb_promotion_id=wb_promotion_id,
            promotion_name=promotion_name,
            mrc_price=mrc_price,
            current_full_price=current_full_price,
            current_discount=current_discount,
            current_discounted_price=current_discounted_price,
            max_auto_promo_price=max_auto_promo_price,
            wb_condition_discount_percent=wb_condition_discount_percent,
            candidate_discounted_price=candidate,
            recommended_discounted_price=rec_price,
            recommended_full_price=Decimal(payload.price) if payload else None,
            recommended_discount=payload.discount if payload else None,
            safe_discounted_price=mrc_price,
            safe_full_price=safe_full_price,
            safe_discount=safe_discount,
            min_price=min_price,
            mrc_lower_bound=lower_bound,
            mrc_upper_bound=upper_bound,
            status=status,
            reason=reason,
            condition_type=resolved_condition_type,
            raw_payload=raw_payload,
        )

    async def prepare_price_payload(self, recommendation_id: int) -> WbPriceApplyPayload:
        rec = await self._get_recommendation(recommendation_id)
        if rec.recommended_discounted_price is None:
            raise ValueError("recommendation has no discounted price to apply")
        return WbPriceApplyService.build_payload(
            nm_id=rec.wb_nm_id,
            recommended_price=rec.recommended_discounted_price,
            discount=Decimal(str(rec.recommended_discount or 75)),
            min_price=rec.min_price,
            max_discounted_price=rec.candidate_discounted_price or rec.max_auto_promo_price,
        )

    async def apply_recommendations(
        self,
        account_id: int,
        recommendation_ids: list[int],
        dry_run: bool = True,
    ) -> list[dict[str, Any]]:
        account = await self._get_account(account_id)
        api_key = self.cipher.decrypt(account.encrypted_api_key)
        results: list[dict[str, Any]] = []
        upload_items: list[dict[str, int]] = []
        recs: list[WbAutoPromoPriceRecommendation] = []

        for recommendation_id in recommendation_ids:
            rec = await self._get_recommendation(recommendation_id)
            if rec.marketplace_account_id != account.id:
                continue
            validated = self.calculate(
                product_id=rec.product_id,
                wb_nm_id=rec.wb_nm_id,
                wb_promotion_id=rec.wb_promotion_id,
                promotion_name=rec.promotion_name,
                mrc_price=rec.mrc_price,
                current_full_price=rec.current_full_price,
                current_discount=rec.current_discount,
                current_discounted_price=rec.current_discounted_price,
                max_auto_promo_price=rec.max_auto_promo_price,
                wb_condition_discount_percent=rec.wb_condition_discount_percent,
                condition_type=rec.condition_type,
                min_price=rec.min_price,
                raw_payload=rec.raw_payload,
            )
            if validated.status != STATUS_CAN_APPLY:
                rec.status = validated.status
                rec.reason = validated.reason
                await self._record_history(account, rec, None, dry_run, validated.status, None)
                results.append({"recommendation_id": rec.id, "status": rec.status})
                continue
            payload = await self.prepare_price_payload(rec.id)
            upload_items.append(payload.as_wb_item())
            recs.append(rec)
            results.append(
                {
                    "recommendation_id": rec.id,
                    "status": "dry_run" if dry_run else "prepared",
                    "payload": payload.as_wb_item(),
                }
            )

        response: dict[str, Any] | None = None
        if upload_items and not dry_run:
            response = await WildberriesClient(
                api_key=api_key
            ).upload_task_prices_discounts(upload_items)

        for rec in recs:
            status = STATUS_APPLIED if not dry_run else "dry_run"
            rec.status = STATUS_APPLIED if not dry_run else rec.status
            rec.applied_at = datetime.now(tz=UTC) if not dry_run else None
            await self._record_history(account, rec, response, dry_run, status, None)

        await self.session.commit()
        return results

    async def _save_recommendation(
        self,
        account: MarketplaceAccount,
        rec: AutoPromoParticipationRecommendation,
    ) -> WbAutoPromoPriceRecommendation:
        result = await self.session.execute(
            select(WbAutoPromoPriceRecommendation).where(
                WbAutoPromoPriceRecommendation.marketplace_account_id == account.id,
                WbAutoPromoPriceRecommendation.product_id == rec.product_id,
                WbAutoPromoPriceRecommendation.wb_nm_id == rec.wb_nm_id,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = WbAutoPromoPriceRecommendation(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                product_id=rec.product_id,
                wb_nm_id=rec.wb_nm_id,
                mrc_price=rec.mrc_price or Decimal("0"),
                mrc_lower_bound=rec.mrc_lower_bound or Decimal("0"),
                mrc_upper_bound=rec.mrc_upper_bound or Decimal("0"),
                status=rec.status,
            )
            self.session.add(record)
        record.wb_promotion_id = rec.wb_promotion_id
        record.promotion_name = rec.promotion_name
        record.mrc_price = rec.mrc_price or Decimal("0")
        record.current_wb_price = rec.current_discounted_price
        record.required_price = rec.max_auto_promo_price
        record.recommended_price = rec.recommended_discounted_price
        record.current_full_price = rec.current_full_price
        record.current_discount = rec.current_discount
        record.current_discounted_price = rec.current_discounted_price
        record.max_auto_promo_price = rec.max_auto_promo_price
        record.wb_condition_discount_percent = rec.wb_condition_discount_percent
        record.candidate_discounted_price = rec.candidate_discounted_price
        record.recommended_discounted_price = rec.recommended_discounted_price
        record.recommended_full_price = rec.recommended_full_price
        record.recommended_discount = rec.recommended_discount
        record.safe_discounted_price = rec.safe_discounted_price
        record.safe_full_price = rec.safe_full_price
        record.safe_discount = rec.safe_discount
        record.condition_type = rec.condition_type
        record.min_price = rec.min_price
        record.mrc_lower_bound = rec.mrc_lower_bound or Decimal("0")
        record.mrc_upper_bound = rec.mrc_upper_bound or Decimal("0")
        record.status = rec.status
        record.reason = rec.reason
        record.source = rec.source
        record.raw_payload = rec.raw_payload
        await self.session.flush()
        return record

    async def _record_history(
        self,
        account: MarketplaceAccount,
        rec: WbAutoPromoPriceRecommendation,
        response: dict[str, Any] | None,
        dry_run: bool,
        status: str,
        error: str | None,
    ) -> None:
        history = WbPriceChangeHistory(
            user_id=account.user_id,
            marketplace_account_id=account.id,
            product_id=rec.product_id,
            wb_nm_id=rec.wb_nm_id,
            old_price=rec.current_discounted_price,
            new_price=(
                rec.recommended_discounted_price
                or rec.current_discounted_price
                or Decimal("0")
            ),
            target_discounted_price=rec.recommended_discounted_price,
            wb_price=int(rec.recommended_full_price) if rec.recommended_full_price else None,
            wb_discount=rec.recommended_discount,
            final_discounted_price=rec.recommended_discounted_price,
            min_price=rec.min_price,
            mrc_lower_bound=rec.mrc_lower_bound,
            mrc_upper_bound=rec.mrc_upper_bound,
            reason="auto_promo_participation",
            source="wb_api",
            dry_run=dry_run,
            status=status,
            error=error,
            raw_payload={
                "promotion_id": rec.wb_promotion_id,
                "promotion_name": rec.promotion_name,
                "old_full_price": str(rec.current_full_price)
                if rec.current_full_price is not None
                else None,
                "old_discount": rec.current_discount,
                "condition_type": rec.condition_type,
                "wb_condition_discount_percent": str(rec.wb_condition_discount_percent)
                if rec.wb_condition_discount_percent is not None
                else None,
                "candidate_discounted_price": str(rec.candidate_discounted_price)
                if rec.candidate_discounted_price is not None
                else None,
                "new_full_price": str(rec.recommended_full_price)
                if rec.recommended_full_price is not None
                else None,
                "new_discount": rec.recommended_discount,
                "payload": {
                    "nmID": rec.wb_nm_id,
                    "price": int(rec.recommended_full_price)
                    if rec.recommended_full_price is not None
                    else None,
                    "discount": rec.recommended_discount,
                },
            },
            raw_response=response,
        )
        self.session.add(history)
        await self.session.flush()

    async def _get_account(self, account_id: int) -> MarketplaceAccount:
        account = await self.session.get(MarketplaceAccount, account_id)
        if account is None:
            raise ValueError(f"WB account {account_id} not found")
        return account

    async def _get_recommendation(self, recommendation_id: int) -> WbAutoPromoPriceRecommendation:
        rec = await self.session.get(WbAutoPromoPriceRecommendation, recommendation_id)
        if rec is None:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        return rec

    async def _get_condition(
        self,
        account_id: int,
        wb_nm_id: int,
    ) -> WbAutoPromotionCondition | None:
        result = await self.session.execute(
            select(WbAutoPromotionCondition)
            .where(
                WbAutoPromotionCondition.marketplace_account_id == account_id,
                WbAutoPromotionCondition.wb_nm_id == wb_nm_id,
                WbAutoPromotionCondition.source.in_(("wb_file", "wb_api", "file_import")),
            )
            .order_by(
                WbAutoPromotionCondition.required_price.is_(None),
                (WbAutoPromotionCondition.source == "wb_file").desc(),
                WbAutoPromotionCondition.synced_at.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_current_price(
        self,
        account_id: int,
        wb_nm_id: int,
    ) -> WbProductPrice | None:
        result = await self.session.execute(
            select(WbProductPrice)
            .where(
                WbProductPrice.marketplace_account_id == account_id,
                WbProductPrice.wb_nm_id == wb_nm_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _extract_min_price(raw_payload: dict[str, Any] | None) -> Decimal | None:
        if not raw_payload:
            return None
        for key in ("minPrice", "minPriceForNm"):
            value = raw_payload.get(key)
            if value not in (None, ""):
                return Decimal(str(value))
        return None

    @staticmethod
    def _candidate_price(
        *,
        max_auto_promo_price: Decimal | None,
        current_full_price: Decimal | None,
        wb_condition_discount_percent: Decimal | None,
    ) -> Decimal | None:
        if max_auto_promo_price is not None:
            return max_auto_promo_price
        if current_full_price is None or wb_condition_discount_percent is None:
            return None
        if current_full_price <= 0:
            return None
        if wb_condition_discount_percent < 0 or wb_condition_discount_percent >= 100:
            return None
        return current_full_price * (
            Decimal("1") - wb_condition_discount_percent / Decimal("100")
        )

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
