"""version: 2.0.0
description: Feature access checks using new subscription tier system.
updated: 2026-05-16
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, Product
from app.models.enums import FeatureCode
from app.models.subscriptions import SubscriptionTier, UserSubscription


@dataclass(frozen=True, slots=True)
class FeatureAccessResult:
    allowed: bool
    reason: str | None = None
    required_plan: str | None = None


class FeatureAccessService:
    """Check whether a user can access a feature or add more marketplace data."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def can_use_feature(self, user_id: int, feature: FeatureCode) -> FeatureAccessResult:
        tier = await self._active_tier(user_id)
        if not tier:
            return FeatureAccessResult(allowed=True)

        feature_attr = {
            FeatureCode.PLAN_FACT: tier.feature_plan_fact,
            FeatureCode.MASTER_PRODUCT_ANALYTICS: tier.feature_analytics,
            FeatureCode.STOCKOUT_FORECAST: tier.feature_stock_forecast,
            FeatureCode.DATA_QUALITY: tier.feature_analytics,
            FeatureCode.EXPORTS: tier.feature_analytics,
            FeatureCode.AI_ANALYST: tier.feature_analytics,
            FeatureCode.MULTI_ACCOUNT: True,
            FeatureCode.LONG_HISTORY: tier.feature_analytics,
        }
        allowed = feature_attr.get(feature, True)
        if not allowed:
            return FeatureAccessResult(
                allowed=False,
                reason=f"Функция {feature.value} недоступна на тарифе {tier.name}.",
                required_plan="Pro",
            )
        return FeatureAccessResult(allowed=True)

    async def can_add_marketplace_account(self, user_id: int) -> FeatureAccessResult:
        tier = await self._active_tier(user_id)
        if not tier:
            return FeatureAccessResult(allowed=True)

        result = await self.session.execute(
            select(func.count(MarketplaceAccount.id)).where(MarketplaceAccount.user_id == user_id)
        )
        count = int(result.scalar_one() or 0)
        if count >= tier.max_marketplace_accounts:
            return FeatureAccessResult(
                allowed=False,
                reason=(
                    f"Превышен лимит кабинетов ({tier.max_marketplace_accounts}) "
                    f"тарифа {tier.name}."
                ),
                required_plan="Pro",
            )
        return FeatureAccessResult(allowed=True)

    async def can_sync_more_skus(self, user_id: int) -> FeatureAccessResult:
        tier = await self._active_tier(user_id)
        if not tier:
            return FeatureAccessResult(allowed=True)

        result = await self.session.execute(
            select(func.count(Product.id)).where(Product.user_id == user_id)
        )
        count = int(result.scalar_one() or 0)
        if tier.max_products is not None and count >= tier.max_products:
            return FeatureAccessResult(
                allowed=False,
                reason=f"Превышен лимит товаров ({tier.max_products}) тарифа {tier.name}.",
                required_plan="Pro",
            )
        return FeatureAccessResult(allowed=True)

    async def _active_tier(self, user_id: int) -> SubscriptionTier | None:
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
        return result.scalar_one_or_none()
