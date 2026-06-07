"""version: 1.3.0
description: Subscription lifecycle service with trial, upgrade, admin assignment, and expiration.
updated: 2026-06-07
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import MarketplaceAccount, User
from app.models.enums import SubscriptionStatus
from app.models.subscriptions import SubscriptionTier, UserSubscription

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
SUBSCRIPTION_ACTIVE_STATUSES = (SubscriptionStatus.ACTIVE.value, SubscriptionStatus.TRIAL.value)
SUBSCRIPTION_PERIOD_DAYS = {
    "monthly": 30,
    "3_months": 90,
    "6_months": 180,
    "yearly": 365,
}
TRIAL_PERIOD = "trial"


class SubscriptionService:
    """Manage user subscriptions and feature access."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_subscription(self, user_id: int) -> UserSubscription | None:
        """Get user's active non-expired subscription, including trial.

        This is the source of truth for current paid/trial tariff detection across web,
        Telegram, API guards, and background services. If data drift leaves several active
        subscriptions, the highest tier wins; ties use the latest start date.
        """
        now = datetime.now(tz=UTC)
        result = await self.session.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.tier))
            .join(SubscriptionTier, UserSubscription.tier_id == SubscriptionTier.id)
            .where(UserSubscription.user_id == user_id)
            .where(UserSubscription.status.in_(SUBSCRIPTION_ACTIVE_STATUSES))
            .where((UserSubscription.expires_at.is_(None)) | (UserSubscription.expires_at > now))
            .where(SubscriptionTier.is_active.is_(True))
            .order_by(SubscriptionTier.sort_order.desc(), UserSubscription.started_at.desc())
            .limit(2)
        )
        subscriptions = list(result.scalars().all())
        if len(subscriptions) > 1:
            logger.warning(
                "multiple_active_subscriptions_detected",
                extra={
                    "user_id": user_id,
                    "selected_subscription_id": subscriptions[0].id,
                    "selected_tier_id": subscriptions[0].tier_id,
                    "conflicting_subscription_id": subscriptions[1].id,
                    "conflicting_tier_id": subscriptions[1].tier_id,
                },
            )
        return subscriptions[0] if subscriptions else None

    async def get_user_tier(self, user_id: int) -> SubscriptionTier:
        """Get user's current subscription tier (or FREE if none)."""
        subscription = await self.get_active_subscription(user_id)
        if subscription:
            await self.session.refresh(subscription, ["tier"])
            return subscription.tier

        # Return FREE tier by default
        result = await self.session.execute(select(SubscriptionTier).where(_tier_code_is("free")))
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
        period: str = "monthly",
        is_trial: bool = False,
        trial_days: int = 14,
        payment_provider: str | None = None,
        payment_id: str | None = None,
    ) -> UserSubscription:
        """Create, renew, or upgrade a user subscription."""
        tier = await self.get_tier_by_code(tier_code)
        if not tier:
            raise ValueError(f"Tier {tier_code} not found")

        now = datetime.now(tz=UTC)
        if is_trial:
            if await self.has_used_trial(user_id):
                raise ValueError(f"User {user_id} has already used trial")
            expires_at = now + timedelta(days=trial_days)
            trial_ends_at = expires_at
            subscription_period = TRIAL_PERIOD
        else:
            subscription_period = normalize_subscription_period(period)
            active_subscription = await self.get_active_subscription(user_id)
            if active_subscription:
                await self.session.refresh(active_subscription, ["tier"])
                active_tier = active_subscription.tier
                if active_subscription.tier_id == tier.id:
                    return await self.renew_subscription(
                        active_subscription.id,
                        period=subscription_period,
                        payment_id=payment_id,
                    )
                active_subscription.status = SubscriptionStatus.REPLACED
                active_subscription.cancelled_at = now
                active_subscription.auto_renew = False
                if _tier_rank(tier) > _tier_rank(active_tier):
                    log_event = "subscription_replaced_by_upgrade"
                else:
                    log_event = "subscription_replaced_by_downgrade"
                logger.info(
                    log_event,
                    extra={
                        "user_id": user_id,
                        "old_tier": active_tier.code,
                        "new_tier": tier_code,
                        "old_subscription_id": active_subscription.id,
                    },
                )
            expires_at = now + timedelta(days=subscription_period_days(subscription_period))
            trial_ends_at = None

        subscription = UserSubscription(
            user_id=user_id,
            tier_id=tier.id,
            status=SubscriptionStatus.TRIAL if is_trial else SubscriptionStatus.ACTIVE,
            started_at=now,
            expires_at=expires_at,
            period=subscription_period,
            is_trial=is_trial,
            trial_ends_at=trial_ends_at,
            payment_provider=payment_provider,
            payment_id=payment_id,
            auto_renew=True,
            created_at=now,
            updated_at=now,
        )
        self.session.add(subscription)
        await self.session.flush()

        logger.info(
            "subscription_created",
            extra={
                "user_id": user_id,
                "tier_code": tier_code,
                "period": subscription_period,
                "is_trial": is_trial,
                "expires_at": expires_at.isoformat() if expires_at else None,
                "subscription_id": subscription.id,
            },
        )
        return subscription

    async def create_bonus_subscription(
        self,
        *,
        user_id: int,
        tier_code: str,
        days: int,
        payment_provider: str | None = None,
        payment_id: str | None = None,
    ) -> UserSubscription:
        """Create a promo-funded subscription for an arbitrary number of days."""
        if days < 1:
            raise ValueError("Bonus subscription days must be positive")

        tier = await self.get_tier_by_code(tier_code)
        if not tier:
            raise ValueError(f"Tier {tier_code} not found")

        now = datetime.now(tz=UTC)
        active_subscription = await self.get_active_subscription(user_id)
        if active_subscription:
            active_subscription.status = SubscriptionStatus.REPLACED
            active_subscription.cancelled_at = now
            active_subscription.auto_renew = False

        subscription = UserSubscription(
            user_id=user_id,
            tier_id=tier.id,
            status=SubscriptionStatus.ACTIVE,
            started_at=now,
            expires_at=now + timedelta(days=days),
            period="bonus",
            is_trial=False,
            trial_ends_at=None,
            payment_provider=payment_provider,
            payment_id=payment_id,
            auto_renew=False,
            created_at=now,
            updated_at=now,
        )
        self.session.add(subscription)
        await self.session.flush()

        logger.info(
            "bonus_subscription_created",
            extra={
                "user_id": user_id,
                "tier_code": tier_code,
                "days": days,
                "subscription_id": subscription.id,
            },
        )
        return subscription

    async def start_trial(
        self,
        *,
        user_id: int,
        tier_code: str = "pro",
        trial_days: int = 14,
    ) -> UserSubscription:
        """Start a one-time trial subscription for a user."""
        return await self.create_subscription(
            user_id=user_id,
            tier_code=tier_code,
            is_trial=True,
            trial_days=trial_days,
            payment_provider="trial",
            payment_id=None,
        )

    async def has_used_trial(self, user_id: int) -> bool:
        """Return true if user already had any trial subscription."""
        result = await self.session.execute(
            select(UserSubscription.id)
            .where(UserSubscription.user_id == user_id)
            .where(UserSubscription.is_trial.is_(True))
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

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
        period: str = "monthly",
        payment_id: str | None = None,
    ) -> UserSubscription:
        """Renew subscription from current expiration if it is still active."""
        subscription = await self.session.get(UserSubscription, subscription_id)
        if not subscription:
            raise ValueError(f"Subscription {subscription_id} not found")

        now = datetime.now(tz=UTC)
        subscription_period = normalize_subscription_period(period)
        base = (
            subscription.expires_at
            if subscription.expires_at and subscription.expires_at > now
            else now
        )
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.expires_at = base + timedelta(
            days=subscription_period_days(subscription_period)
        )
        subscription.period = subscription_period
        subscription.is_trial = False
        subscription.trial_ends_at = None
        subscription.payment_id = payment_id

        await self.session.flush()

        logger.info(
            "subscription_renewed",
            extra={
                "subscription_id": subscription_id,
                "user_id": subscription.user_id,
                "period": subscription_period,
                "expires_at": subscription.expires_at.isoformat(),
            },
        )
        return subscription

    async def expire_outdated_subscriptions(self, user_id: int | None = None) -> int:
        """Mark active/trial subscriptions with expired end date as EXPIRED."""
        now = datetime.now(tz=UTC)
        statement = (
            select(UserSubscription)
            .where(UserSubscription.status.in_(SUBSCRIPTION_ACTIVE_STATUSES))
            .where(UserSubscription.expires_at.is_not(None))
            .where(UserSubscription.expires_at <= now)
        )
        if user_id is not None:
            statement = statement.where(UserSubscription.user_id == user_id)

        result = await self.session.execute(statement)
        subscriptions = list(result.scalars().all())
        for subscription in subscriptions:
            subscription.status = SubscriptionStatus.EXPIRED
            subscription.auto_renew = False
        if subscriptions:
            await self.session.flush()
            logger.info(
                "subscriptions_expired",
                extra={"count": len(subscriptions), "user_id": user_id},
            )
        return len(subscriptions)

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
            .where(SubscriptionTier.is_public.is_(True))
            .order_by(SubscriptionTier.sort_order)
        )
        return list(result.scalars().all())

    async def get_tier_by_code(self, code: str) -> SubscriptionTier | None:
        """Get tier by code (public method)."""
        result = await self.session.execute(select(SubscriptionTier).where(_tier_code_is(code)))
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
            created_at=now,
            updated_at=now,
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
        price_3_months=None,
        price_6_months=None,
        price_yearly=ZERO,
        currency="RUB",
        max_marketplace_accounts=1,
        max_orders_per_month=100,
        max_products=None,
        max_users=None,
        sync_interval_minutes=180,
        analytics_depth_days=30,
        feature_web_cabinet=True,
        feature_analytics=False,
        feature_plan_fact=False,
        feature_break_even=False,
        feature_stock_forecast=False,
        feature_alerts=False,
        feature_priority_support=False,
        feature_api_access=False,
        feature_mrc_pricing=False,
        feature_auto_promotions=False,
        feature_telegram_notifications=True,
        is_active=True,
        is_public=True,
        sort_order=0,
    )


def normalize_subscription_period(period: str) -> str:
    """Normalize and validate paid subscription period."""
    normalized = period.lower().strip()
    if normalized not in SUBSCRIPTION_PERIOD_DAYS:
        raise ValueError(f"Unsupported subscription period: {period}")
    return normalized


def subscription_period_days(period: str) -> int:
    """Return duration in days for a paid subscription period."""
    return SUBSCRIPTION_PERIOD_DAYS[normalize_subscription_period(period)]


def _tier_rank(tier: SubscriptionTier) -> int:
    """Return tier ordering rank for upgrade decisions."""
    rank_by_code = {"free": 0, "basic": 10, "pro": 20, "business": 25, "enterprise": 30}
    code = _normalize_tier_code(tier.code)
    if code in rank_by_code:
        return rank_by_code[code]
    return int(tier.sort_order or 0)


def _normalize_tier_code(code: str) -> str:
    return code.strip().lower()


def _tier_code_is(code: str):
    return func.lower(SubscriptionTier.code) == _normalize_tier_code(code)
