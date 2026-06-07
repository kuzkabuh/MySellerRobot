"""version: 3.2.0
description: Feature access checks using new subscription tier system.
    Implements default-deny: no active subscription = FREE tier permissions only.
    Tier codes are normalized to lowercase for case-insensitive comparison.
updated: 2026-06-07
"""

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, Product
from app.models.enums import FeatureCode
from app.models.subscriptions import SubscriptionTier
from app.services.subscription_service import SubscriptionService, default_free_tier

logger = logging.getLogger(__name__)

__all__ = ["FeatureAccessResult", "FeatureAccessService", "FeatureCode"]

_TIER_HIERARCHY: dict[str, int] = {
    "free": 0,
    "basic": 1,
    "pro": 2,
    "business": 3,
    "enterprise": 4,
}

_FEATURE_MIN_TIER: dict[FeatureCode, str] = {
    FeatureCode.WEB_DASHBOARD: "free",
    FeatureCode.ADVANCED_ANALYTICS: "pro",
    FeatureCode.PLAN_FACT: "pro",
    FeatureCode.BREAK_EVEN: "pro",
    FeatureCode.MASTER_PRODUCT_ANALYTICS: "pro",
    FeatureCode.STOCKOUT_FORECAST: "pro",
    FeatureCode.STOCK_FORECAST: "pro",
    FeatureCode.DATA_QUALITY: "pro",
    FeatureCode.EXPORTS: "pro",
    FeatureCode.AI_ANALYST: "pro",
    FeatureCode.LONG_HISTORY: "pro",
    FeatureCode.MULTI_ACCOUNT: "free",
    FeatureCode.MRC_PRICING: "pro",
    FeatureCode.ALERTS: "pro",
    FeatureCode.API_ACCESS: "business",
    FeatureCode.AUTO_PROMOTIONS: "pro",
    FeatureCode.PRICE_MANAGEMENT: "pro",
}

_FEATURE_DISPLAY_NAME: dict[FeatureCode, str] = {
    FeatureCode.WEB_DASHBOARD: "Web-кабинет",
    FeatureCode.ADVANCED_ANALYTICS: "Расширенная аналитика",
    FeatureCode.PLAN_FACT: "План/факт",
    FeatureCode.BREAK_EVEN: "Безубыточность",
    FeatureCode.MASTER_PRODUCT_ANALYTICS: "Аналитика товаров",
    FeatureCode.STOCKOUT_FORECAST: "Прогноз остатков",
    FeatureCode.DATA_QUALITY: "Качество данных",
    FeatureCode.EXPORTS: "Экспорт данных",
    FeatureCode.AI_ANALYST: "AI-аналитик",
    FeatureCode.LONG_HISTORY: "Длинная история",
    FeatureCode.MULTI_ACCOUNT: "Мульти-аккаунт",
    FeatureCode.MRC_PRICING: "МРЦ и акции WB",
    FeatureCode.ALERTS: "Алерты",
    FeatureCode.API_ACCESS: "API-доступ",
    FeatureCode.AUTO_PROMOTIONS: "Автоакции WB",
    FeatureCode.PRICE_MANAGEMENT: "Управление ценами",
}


@dataclass(frozen=True, slots=True)
class FeatureAccessResult:
    allowed: bool
    reason: str | None = None
    required_plan: str | None = None
    current_tier: str | None = None


_FREE_FEATURES: set[FeatureCode] = set()

_BASIC_FEATURES: set[FeatureCode] = {
    FeatureCode.WEB_DASHBOARD,
    FeatureCode.MULTI_ACCOUNT,
}

_PRO_FEATURES: set[FeatureCode] = {
    FeatureCode.ADVANCED_ANALYTICS,
    FeatureCode.PLAN_FACT,
    FeatureCode.BREAK_EVEN,
    FeatureCode.MASTER_PRODUCT_ANALYTICS,
    FeatureCode.STOCKOUT_FORECAST,
    FeatureCode.STOCK_FORECAST,
    FeatureCode.DATA_QUALITY,
    FeatureCode.EXPORTS,
    FeatureCode.AI_ANALYST,
    FeatureCode.LONG_HISTORY,
    FeatureCode.MRC_PRICING,
    FeatureCode.ALERTS,
    FeatureCode.AUTO_PROMOTIONS,
    FeatureCode.PRICE_MANAGEMENT,
}


_FEATURE_ALIASES: dict[str, FeatureCode] = {item.value.lower(): item for item in FeatureCode}
_FEATURE_ALIASES.update(
    {
        "plan_fact": FeatureCode.PLAN_FACT,
        "master_product_analytics": FeatureCode.MASTER_PRODUCT_ANALYTICS,
        "stockout_forecast": FeatureCode.STOCKOUT_FORECAST,
        "mrc_pricing": FeatureCode.MRC_PRICING,
    }
)


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

    async def can_use(self, user_id: int, feature_code: str | FeatureCode) -> bool:
        """Return a plain boolean for the canonical feature access check."""
        feature = self._normalize_feature(feature_code)
        if feature is None:
            logger.info(
                "feature_access_denied",
                extra={"user_id": user_id, "feature_code": str(feature_code), "reason": "unknown"},
            )
            return False
        result = await self.can_use_feature(user_id, feature)
        return result.allowed

    async def can_use_feature(self, user_id: int, feature: FeatureCode) -> FeatureAccessResult:
        feature = self._normalize_feature(feature) or feature
        tier = await self._effective_tier(user_id)
        normalized_code = _normalize_tier_code(tier.code)

        feature_attr = {
            FeatureCode.WEB_DASHBOARD: tier.feature_web_cabinet,
            FeatureCode.ADVANCED_ANALYTICS: tier.feature_analytics,
            FeatureCode.PLAN_FACT: tier.feature_plan_fact,
            FeatureCode.BREAK_EVEN: tier.feature_break_even,
            FeatureCode.MASTER_PRODUCT_ANALYTICS: tier.feature_analytics,
            FeatureCode.STOCKOUT_FORECAST: tier.feature_stock_forecast,
            FeatureCode.STOCK_FORECAST: tier.feature_stock_forecast,
            FeatureCode.DATA_QUALITY: tier.feature_analytics,
            FeatureCode.EXPORTS: tier.feature_analytics,
            FeatureCode.AI_ANALYST: tier.feature_analytics,
            FeatureCode.MULTI_ACCOUNT: True,
            FeatureCode.LONG_HISTORY: tier.feature_analytics,
            FeatureCode.MRC_PRICING: tier.feature_mrc_pricing,
            FeatureCode.ALERTS: tier.feature_alerts,
            FeatureCode.API_ACCESS: tier.feature_api_access,
            FeatureCode.AUTO_PROMOTIONS: tier.feature_auto_promotions,
            FeatureCode.PRICE_MANAGEMENT: tier.feature_mrc_pricing,
        }
        allowed = feature_attr.get(feature, False)

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
                    "source": "db_flag",
                    "reason": "feature_flag_disabled",
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
        """Return the same effective tier shown in web and Telegram subscription screens."""
        return await SubscriptionService(self.session).get_user_tier(user_id)

    async def _free_tier(self) -> SubscriptionTier:
        """Backward-compatible helper for older tests and callers."""
        result = await self.session.execute(
            select(SubscriptionTier).where(func.lower(SubscriptionTier.code) == "free")
        )
        tier = result.scalar_one_or_none()
        if tier is None:
            return default_free_tier()
        return tier

    @staticmethod
    def _normalize_feature(feature_code: str | FeatureCode) -> FeatureCode | None:
        if isinstance(feature_code, FeatureCode):
            return feature_code
        return _FEATURE_ALIASES.get(str(feature_code).strip().lower())

    @staticmethod
    def _required_plan_for_feature(feature: FeatureCode) -> str:
        min_tier = _FEATURE_MIN_TIER.get(feature)
        if min_tier:
            return min_tier.capitalize()
        if feature in _PRO_FEATURES:
            return "Pro"
        if feature in _BASIC_FEATURES:
            return "Basic"
        return "Pro"
