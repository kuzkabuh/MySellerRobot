"""version: 3.1.0
description: Feature access checks using new subscription tier system.
    Implements default-deny: no active subscription = FREE tier permissions only.
    Tier codes are normalized to lowercase for case-insensitive comparison.
updated: 2026-05-21
"""

from dataclasses import dataclass
from datetime import UTC, datetime
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, Product
from app.models.enums import FeatureCode
from app.models.subscriptions import SubscriptionTier, UserSubscription
from app.services.subscription_service import default_free_tier

logger = logging.getLogger(__name__)

_TIER_HIERARCHY: dict[str, int] = {
    "free": 0,
    "basic": 1,
    "pro": 2,
    "business": 3,
    "enterprise": 4,
}

_FEATURE_MIN_TIER: dict[FeatureCode, str] = {
    FeatureCode.PLAN_FACT: "pro",
    FeatureCode.MASTER_PRODUCT_ANALYTICS: "pro",
    FeatureCode.STOCKOUT_FORECAST: "pro",
    FeatureCode.DATA_QUALITY: "pro",
    FeatureCode.EXPORTS: "pro",
    FeatureCode.AI_ANALYST: "pro",
    FeatureCode.LONG_HISTORY: "pro",
    FeatureCode.MULTI_ACCOUNT: "free",
    FeatureCode.MRC_PRICING: "pro",
}

_FEATURE_DISPLAY_NAME: dict[FeatureCode, str] = {
    FeatureCode.PLAN_FACT: "План/факт",
    FeatureCode.MASTER_PRODUCT_ANALYTICS: "Аналитика товаров",
    FeatureCode.STOCKOUT_FORECAST: "Прогноз остатков",
    FeatureCode.DATA_QUALITY: "Качество данных",
    FeatureCode.EXPORTS: "Экспорт данных",
    FeatureCode.AI_ANALYST: "AI-аналитик",
    FeatureCode.LONG_HISTORY: "Длинная история",
    FeatureCode.MULTI_ACCOUNT: "Мульти-аккаунт",
    FeatureCode.MRC_PRICING: "МРЦ и акции WB",
}


@dataclass(frozen=True, slots=True)
class FeatureAccessResult:
    allowed: bool
    reason: str | None = None
    required_plan: str | None = None
    current_tier: str | None = None


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


def _normalize_tier_code(code: str) -> str:
    """Normalize tier code to lowercase for case-insensitive comparison."""
    return code.strip().lower() if code else ""


def _tier_level(code: str) -> int:
    """Return numeric level for a tier code. Unknown tiers get level 0."""
    return _TIER_HIERARCHY.get(_normalize_tier_code(code), 0)


class FeatureAccessService:
    """Check whether a user can access a feature or add more marketplace data.

    Security model: default-deny.
    - No active subscription → FREE tier (only FREE features allowed).
    - Active subscription → tier features enforced.
    - Unknown features → denied by default.
    - Tier codes are compared case-insensitively.
    - Falls back to tier hierarchy if feature flag is not set in DB.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def can_use_feature(self, user_id: int, feature: FeatureCode) -> FeatureAccessResult:
        tier = await self._effective_tier(user_id)
        normalized_code = _normalize_tier_code(tier.code)
        tier_level = _tier_level(tier.code)

        # Check explicit feature flag on tier first
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
        flag_allowed = feature_attr.get(feature, False)

        # Fallback: check tier hierarchy if flag is not set
        min_tier_code = _FEATURE_MIN_TIER.get(feature, "pro")
        min_tier_level = _tier_level(min_tier_code)
        hierarchy_allowed = tier_level >= min_tier_level

        allowed = flag_allowed or hierarchy_allowed

        if not allowed:
            display_name = _FEATURE_DISPLAY_NAME.get(feature, feature.value)
            required_plan = self._required_plan_for_feature(feature)
            reason = (
                f"🔒 Функция «{display_name}» недоступна на вашем тарифе.\n"
                f"Ваш тариф: {tier.name}\n"
                f"Нужный тариф: {required_plan} или выше."
            )
            logger.info(
                "feature_access_denied",
                extra={
                    "user_id": user_id,
                    "current_tier_code": tier.code,
                    "normalized_current_tier_code": normalized_code,
                    "feature_code": feature.value,
                    "required_tier": required_plan,
                    "source": "unknown",
                    "reason": "tier_level_insufficient",
                },
            )
            return FeatureAccessResult(
                allowed=False,
                reason=reason,
                required_plan=required_plan,
                current_tier=tier.name,
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
