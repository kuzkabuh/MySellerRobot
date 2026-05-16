"""version: 1.0.0
description: Subscription service with tier limits, feature access, and safe FREE fallback.
updated: 2026-05-17
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, User
from app.models.enums import SubscriptionStatus
from app.models.subscriptions import SubscriptionTier, UserSubscription

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


class SubscriptionService:
    """Manage user subscriptions and feature access."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_subscription(self, user_id: int) -> UserSubscription | None:
        """Get user's active subscription."""
        result = await self.session.execute(
            select(UserSubscription)
            .where(UserSubscription.user_id == user_id)
            .where(UserSubscription.status == SubscriptionStatus.ACTIVE)
            .order_by(UserSubscription.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_user_tier(self, user_id: int) -> SubscriptionTier:
        """Get user's current subscription tier (or FREE if none)."""
        subscription = await self.get_active_subscription(user_id)
        if subscription:
            await self.session.refresh(subscription, ["tier"])
            return subscription.tier

        # Return FREE tier by default
        result = await self.session.execute(
            select(SubscriptionTier).where(SubscriptionTier.code == "free")
        )
        tier = result.scalar_one_or_none()
        if not tier:
            logger.warning("free_tier_missing_using_safe_fallback", extra={"user_id": user_id})
            return default_free_tier()
        return tier

    async def create_subscription(
        self,
        *,
        user_id: int,
        tier_code: str,
        is_trial: bool = False,
        trial_days: int = 14,
        payment_provider: str | None = None,
        payment_id: str | None = None,
    ) -> UserSubscription:
        """Create new subscription for user."""
        tier = await self.get_tier_by_code(tier_code)
        if not tier:
            raise ValueError(f"Tier {tier_code} not found")

        now = datetime.now(tz=UTC)
        expires_at = now + timedelta(days=30)  # Default 1 month
        trial_ends_at = now + timedelta(days=trial_days) if is_trial else None

        subscription = UserSubscription(
            user_id=user_id,
            tier_id=tier.id,
            status=SubscriptionStatus.TRIAL if is_trial else SubscriptionStatus.ACTIVE,
            started_at=now,
            expires_at=expires_at,
            is_trial=is_trial,
            trial_ends_at=trial_ends_at,
            payment_provider=payment_provider,
            payment_id=payment_id,
            auto_renew=True,
        )
        self.session.add(subscription)
        await self.session.flush()

        logger.info(
            "subscription_created",
            extra={
                "user_id": user_id,
                "tier_code": tier_code,
                "is_trial": is_trial,
                "subscription_id": subscription.id,
            },
        )
        return subscription

    async def cancel_subscription(self, subscription_id: int) -> UserSubscription:
        """Cancel user subscription."""
        subscription = await self.session.get(UserSubscription, subscription_id)
        if not subscription:
            raise ValueError(f"Subscription {subscription_id} not found")

        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = datetime.now(tz=UTC)
        subscription.auto_renew = False

        await self.session.flush()

        logger.info(
            "subscription_cancelled",
            extra={"subscription_id": subscription_id, "user_id": subscription.user_id},
        )
        return subscription

    async def renew_subscription(
        self,
        subscription_id: int,
        *,
        payment_id: str | None = None,
    ) -> UserSubscription:
        """Renew expired subscription."""
        subscription = await self.session.get(UserSubscription, subscription_id)
        if not subscription:
            raise ValueError(f"Subscription {subscription_id} not found")

        now = datetime.now(tz=UTC)
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.expires_at = now + timedelta(days=30)
        subscription.payment_id = payment_id

        await self.session.flush()

        logger.info(
            "subscription_renewed",
            extra={"subscription_id": subscription_id, "user_id": subscription.user_id},
        )
        return subscription

    async def check_feature_access(self, user_id: int, feature: str) -> bool:
        """Check if user has access to specific feature."""
        tier = await self.get_user_tier(user_id)
        feature_attr = f"feature_{feature}"
        return getattr(tier, feature_attr, False)

    async def check_account_limit(self, user_id: int) -> tuple[int, int]:
        """Check marketplace account limit.

        Returns (current_count, max_allowed).
        """
        tier = await self.get_user_tier(user_id)
        user = await self.session.get(User, user_id)
        if not user:
            return (0, 0)

        result = await self.session.execute(
            select(func.count(MarketplaceAccount.id))
            .where(MarketplaceAccount.user_id == user_id)
            .where(MarketplaceAccount.is_active.is_(True))
        )
        current_count = int(result.scalar_one() or 0)
        max_allowed = tier.max_marketplace_accounts

        return (current_count, max_allowed)

    async def can_add_account(self, user_id: int) -> bool:
        """Check if user can add another marketplace account."""
        current, max_allowed = await self.check_account_limit(user_id)
        return current < max_allowed

    async def get_all_tiers(self) -> list[SubscriptionTier]:
        """Get all active subscription tiers."""
        result = await self.session.execute(
            select(SubscriptionTier)
            .where(SubscriptionTier.is_active.is_(True))
            .order_by(SubscriptionTier.sort_order)
        )
        return list(result.scalars().all())

    async def get_tier_by_code(self, code: str) -> SubscriptionTier | None:
        """Get tier by code (public method)."""
        result = await self.session.execute(
            select(SubscriptionTier).where(SubscriptionTier.code == code)
        )
        return result.scalar_one_or_none()

    async def assign_admin_subscription(
        self,
        *,
        user_id: int,
        tier_code: str,
        days: int | None = None,
        admin_user_id: int,
    ) -> UserSubscription | None:
        """Assign a subscription to a user via admin action.

        Args:
            user_id: Target user database ID.
            tier_code: Tier code (free, basic, pro, enterprise).
            days: Duration in days. None for FREE or ENTERPRISE (indefinite).
            admin_user_id: Admin user database ID (for logging).

        Returns:
            The new UserSubscription if created, or None for FREE tier.

        Raises:
            ValueError: If tier not found or invalid configuration.
        """
        tier = await self.get_tier_by_code(tier_code)
        if not tier:
            raise ValueError(f"Tier {tier_code} not found")

        user = await self.session.get(User, user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        now = datetime.now(tz=UTC)
        old_tier_name = "FREE"

        active_sub = await self.get_active_subscription(user_id)
        if active_sub:
            await self.session.refresh(active_sub, ["tier"])
            old_tier_name = active_sub.tier.name
            await self.cancel_subscription(active_sub.id)
            logger.info(
                "admin_tariff_replaced_active",
                extra={
                    "admin_user_id": admin_user_id,
                    "target_user_id": user_id,
                    "old_tier": old_tier_name,
                    "new_tier": tier_code,
                },
            )

        if tier_code == "free":
            logger.info(
                "admin_tariff_changed",
                extra={
                    "admin_user_id": admin_user_id,
                    "target_user_id": user_id,
                    "old_tier": old_tier_name,
                    "new_tier": "free",
                    "expires_at": None,
                },
            )
            return None

        if tier_code == "enterprise":
            expires_at = None
        elif days is not None:
            expires_at = now + timedelta(days=days)
        else:
            expires_at = now + timedelta(days=30)

        subscription = UserSubscription(
            user_id=user_id,
            tier_id=tier.id,
            status=SubscriptionStatus.ACTIVE,
            started_at=now,
            expires_at=expires_at,
            is_trial=False,
            trial_ends_at=None,
            payment_provider="admin_manual",
            payment_id=None,
            auto_renew=False,
        )
        self.session.add(subscription)
        await self.session.flush()

        logger.info(
            "admin_tariff_changed",
            extra={
                "admin_user_id": admin_user_id,
                "target_user_id": user_id,
                "old_tier": old_tier_name,
                "new_tier": tier_code,
                "expires_at": str(expires_at) if expires_at else "indefinite",
                "subscription_id": subscription.id,
            },
        )

        return subscription


def default_free_tier() -> SubscriptionTier:
    """Return a read-only FREE tier fallback for stable web rendering.

    The real catalog should still be seeded in subscription_tiers. This fallback keeps
    FREE users from receiving a 500 if a deployment serves web before the seed migration
    has populated the tariff catalog.
    """

    return SubscriptionTier(
        id=0,
        code="free",
        name="FREE",
        description="Бесплатный тариф для знакомства с MP Control.",
        price_monthly=ZERO,
        price_yearly=ZERO,
        max_marketplace_accounts=1,
        max_orders_per_month=100,
        max_products=None,
        feature_web_cabinet=True,
        feature_analytics=False,
        feature_plan_fact=False,
        feature_break_even=False,
        feature_stock_forecast=False,
        feature_alerts=False,
        feature_priority_support=False,
        feature_api_access=False,
        is_active=True,
        sort_order=0,
    )
