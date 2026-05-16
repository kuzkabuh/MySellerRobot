"""version: 1.0.0
description: Subscription and feature access checks for future monetization.
updated: 2026-05-15
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, Product, Subscription, SubscriptionPlan
from app.models.enums import FeatureCode


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
        plan = await self._active_plan(user_id)
        if plan is None:
            return FeatureAccessResult(allowed=True)
        value = (plan.features or {}).get(feature.value, True)
        if value is False:
            return FeatureAccessResult(
                allowed=False,
                reason=f"Функция будет доступна на тарифе выше текущего: {plan.title}.",
                required_plan="Pro",
            )
        return FeatureAccessResult(allowed=True)

    async def can_add_marketplace_account(self, user_id: int) -> FeatureAccessResult:
        plan = await self._active_plan(user_id)
        if plan is None:
            return FeatureAccessResult(allowed=True)
        result = await self.session.execute(
            select(func.count(MarketplaceAccount.id)).where(MarketplaceAccount.user_id == user_id)
        )
        count = int(result.scalar_one() or 0)
        if count >= plan.marketplace_limit:
            return FeatureAccessResult(
                allowed=False,
                reason="Превышен лимит кабинетов текущего тарифа.",
                required_plan="Pro",
            )
        return FeatureAccessResult(allowed=True)

    async def can_sync_more_skus(self, user_id: int) -> FeatureAccessResult:
        plan = await self._active_plan(user_id)
        if plan is None:
            return FeatureAccessResult(allowed=True)
        result = await self.session.execute(
            select(func.count(Product.id)).where(Product.user_id == user_id)
        )
        count = int(result.scalar_one() or 0)
        if count >= plan.sku_limit:
            return FeatureAccessResult(
                allowed=False,
                reason="Превышен лимит товаров текущего тарифа.",
                required_plan="Pro",
            )
        return FeatureAccessResult(allowed=True)

    async def _active_plan(self, user_id: int) -> SubscriptionPlan | None:
        now = datetime.now(tz=UTC)
        result = await self.session.execute(
            select(SubscriptionPlan)
            .join(Subscription, Subscription.plan_id == SubscriptionPlan.id)
            .where(Subscription.user_id == user_id)
            .where(Subscription.status == "ACTIVE")
            .where((Subscription.expires_at.is_(None)) | (Subscription.expires_at > now))
            .where(SubscriptionPlan.is_active.is_(True))
            .order_by(Subscription.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
