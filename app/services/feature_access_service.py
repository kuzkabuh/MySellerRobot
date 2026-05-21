"""version: 3.0.0
description: Feature access checks using new subscription tier system.
    Implements default-deny: no active subscription = FREE tier permissions only.
updated: 2026-05-21
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, Product
from app.models.enums import FeatureCode
from app.models.subscriptions import SubscriptionTier, UserSubscription
from app.services.subscription_service import default_free_tier


@dataclass(frozen=True, slots=True)
class FeatureAccessResult:
    allowed: bool
    reason: str | None = None
    required_plan: str | None = None


_FREE_FEATURES: set[FeatureCode] = set()

_BASIC_FEATURES: set[FeatureCode] = {
    FeatureCode.MULTI_ACCOUNT,
}

_PRO_FEATURES: set[FeatureCode] = {
    FeatureCode.PLAN_FACT,
    FeatureCode.MASTER_PRODUCT_ANALYTICS,
    FeatureCode.STOCKOUT_FORECAST,
    FeatureCode.DATA_QUALITY,
    FeatureCode.EXPORTS,
    FeatureCode.AI_ANALYST,
    FeatureCode.LONG_HISTORY,
    FeatureCode.MRC_PRICING,
}


class FeatureAccessService:
    """Check whether a user can access a feature or add more marketplace data.

    Security model: default-deny.
    - No active subscription → FREE tier (only FREE features allowed).
    - Active subscription → tier features enforced.
    - Unknown features → denied by default.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def can_use_feature(self, user_id: int, feature: FeatureCode) -> FeatureAccessResult:
        tier = await self._effective_tier(user_id)

        feature_attr = {
            FeatureCode.PLAN_FACT: tier.feature_plan_fact,
            FeatureCode.MASTER_PRODUCT_ANALYTICS: tier.feature_analytics,
            FeatureCode.STOCKOUT_FORECAST: tier.feature_stock_forecast,
            FeatureCode.DATA_QUALITY: tier.feature_analytics,
            FeatureCode.EXPORTS: tier.feature_analytics,
            FeatureCode.AI_ANALYST: tier.feature_analytics,
            FeatureCode.MULTI_ACCOUNT: True,
            FeatureCode.LONG_HISTORY: tier.feature_analytics,
            FeatureCode.MRC_PRICING: tier.feature_mrc_pricing,
        }
        allowed = feature_attr.get(feature, False)
        if not allowed:
            return FeatureAccessResult(
                allowed=False,
                reason=f"Функция «{feature.value}» недоступна на тарифе {tier.name}. "
                f"Для доступа оформите подписку с нужным тарифом.",
                required_plan=self._required_plan_for_feature(feature),
            )
        return FeatureAccessResult(allowed=True)

    async def can_add_marketplace_account(self, user_id: int) -> FeatureAccessResult:
        tier = await self._effective_tier(user_id)

        result = await self.session.execute(
            select(func.count(MarketplaceAccount.id)).where(MarketplaceAccount.user_id == user_id)
        )
        count = int(result.scalar_one() or 0)
        if count >= tier.max_marketplace_accounts:
            return FeatureAccessResult(
                allowed=False,
                reason=(
                    f"Превышен лимит кабинетов ({tier.max_marketplace_accounts}) "
                    f"тарифа {tier.name}. Для увеличения лимита оформите подписку."
                ),
                required_plan="Pro",
            )
        return FeatureAccessResult(allowed=True)

    async def can_sync_more_skus(self, user_id: int) -> FeatureAccessResult:
        tier = await self._effective_tier(user_id)

        result = await self.session.execute(
            select(func.count(Product.id)).where(Product.user_id == user_id)
        )
        count = int(result.scalar_one() or 0)
        if tier.max_products is not None and count >= tier.max_products:
            return FeatureAccessResult(
                allowed=False,
                reason=f"Превышен лимит товаров ({tier.max_products}) тарифа {tier.name}. "
                f"Для увеличения лимита оформите подписку.",
                required_plan="Pro",
            )
        return FeatureAccessResult(allowed=True)

    async def _effective_tier(self, user_id: int) -> SubscriptionTier:
        """Return the effective tier for a user.

        If there is an active paid/trial subscription, return its tier.
        Otherwise return the FREE tier (default-deny).
        """
        now = datetime.now(tz=UTC)
        result = await self.session.execute(
            select(SubscriptionTier)
            .join(UserSubscription, UserSubscription.tier_id == SubscriptionTier.id)
            .where(UserSubscription.user_id == user_id)
            .where(UserSubscription.status.in_(["ACTIVE", "TRIAL"]))
            .where((UserSubscription.expires_at.is_(None)) | (UserSubscription.expires_at > now))
            .where(SubscriptionTier.is_active.is_(True))
            .order_by(UserSubscription.started_at.desc())
            .limit(1)
        )
        tier = result.scalar_one_or_none()
        if tier is not None:
            return tier
        return await self._free_tier()

    async def _free_tier(self) -> SubscriptionTier:
        result = await self.session.execute(
            select(SubscriptionTier).where(SubscriptionTier.code == "free")
        )
        tier = result.scalar_one_or_none()
        if tier is None:
            return default_free_tier()
        return tier

    @staticmethod
    def _required_plan_for_feature(feature: FeatureCode) -> str:
        if feature in _PRO_FEATURES:
            return "Pro"
        if feature in _BASIC_FEATURES:
            return "Basic"
        return "Pro"
