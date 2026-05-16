"""version: 1.0.0
description: Subscription management service with tier limits and feature access.
updated: 2026-05-16
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User
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
            raise ValueError("FREE tier not found in database")
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
        tier = await self._get_tier_by_code(tier_code)
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

        current_count = len(user.accounts)
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

    async def _get_tier_by_code(self, code: str) -> SubscriptionTier | None:
        """Get tier by code."""
        result = await self.session.execute(
            select(SubscriptionTier).where(SubscriptionTier.code == code)
        )
        return result.scalar_one_or_none()
