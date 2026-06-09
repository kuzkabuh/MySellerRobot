"""Test subscription service with PostgreSQL enum."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User
from app.models.enums import SubscriptionStatus
from app.models.subscriptions import SubscriptionTier, UserSubscription
from app.services.subscriptions.subscription_service import SubscriptionService


class FakeScalars:
    def __init__(self, values):
        self.values = list(values)

    def all(self):
        return self.values


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        if isinstance(self.value, list):
            return FakeScalars(self.value)
        if self.value is None:
            return FakeScalars([])
        return FakeScalars([self.value])

    def scalar_one_or_none(self):
        return self.value


class FakeDbSession:
    def __init__(self):
        self.objects = []
        self._next_id = 1
        self._execute_count = 0

    def add(self, obj):
        self.objects.append(obj)

    async def flush(self):
        for obj in self.objects:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1
        self._link_subscription_tiers()

    async def commit(self):
        await self.flush()

    async def refresh(self, obj, attrs=None):
        self._link_subscription_tiers()

    async def execute(self, query):
        self._execute_count += 1
        subscriptions = [
            obj
            for obj in self.objects
            if isinstance(obj, UserSubscription)
            and obj.status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL}
        ]
        if self._execute_count == 1:
            return FakeResult(subscriptions[:2])
        tier = next(
            (
                obj
                for obj in self.objects
                if isinstance(obj, SubscriptionTier) and obj.code == "free"
            ),
            None,
        )
        return FakeResult(tier)

    def _link_subscription_tiers(self):
        tiers = {
            obj.id: obj
            for obj in self.objects
            if isinstance(obj, SubscriptionTier) and getattr(obj, "id", None) is not None
        }
        for obj in self.objects:
            if isinstance(obj, UserSubscription):
                obj.tier = tiers.get(obj.tier_id)


@pytest.fixture
def db_session() -> FakeDbSession:
    return FakeDbSession()


@pytest.mark.asyncio
async def test_get_active_subscription_with_enum(db_session: AsyncSession):
    """Test that get_active_subscription works with PostgreSQL enum without lower()."""
    # Create a test user
    user = User(telegram_id=999999, username="test_user")
    db_session.add(user)
    await db_session.flush()

    # Create a test tier
    tier = SubscriptionTier(
        code="test_tier",
        name="Test Tier",
        price_monthly=100,
        max_marketplace_accounts=1,
        sync_interval_minutes=60,
        analytics_depth_days=30,
    )
    db_session.add(tier)
    await db_session.flush()

    # Create an active subscription
    subscription = UserSubscription(
        user_id=user.id,
        tier_id=tier.id,
        status=SubscriptionStatus.ACTIVE,
        started_at=datetime.now(UTC),
        expires_at=None,
        period="monthly",
        is_trial=False,
    )
    db_session.add(subscription)
    await db_session.commit()

    # Test get_active_subscription
    service = SubscriptionService(db_session)
    active_sub = await service.get_active_subscription(user.id)

    assert active_sub is not None
    assert active_sub.status == SubscriptionStatus.ACTIVE
    assert active_sub.user_id == user.id


@pytest.mark.asyncio
async def test_get_active_subscription_with_trial(db_session: AsyncSession):
    """Test that get_active_subscription works with TRIAL status."""
    # Create a test user
    from app.models.domain import User

    user = User(telegram_id=888888, username="test_user_trial")
    db_session.add(user)
    await db_session.flush()

    # Create a test tier
    tier = SubscriptionTier(
        code="test_tier_trial",
        name="Test Tier Trial",
        price_monthly=100,
        max_marketplace_accounts=1,
        sync_interval_minutes=60,
        analytics_depth_days=30,
    )
    db_session.add(tier)
    await db_session.flush()

    # Create a trial subscription
    subscription = UserSubscription(
        user_id=user.id,
        tier_id=tier.id,
        status=SubscriptionStatus.TRIAL,
        started_at=datetime.now(UTC),
        expires_at=None,
        period="trial",
        is_trial=True,
    )
    db_session.add(subscription)
    await db_session.commit()

    # Test get_active_subscription
    service = SubscriptionService(db_session)
    active_sub = await service.get_active_subscription(user.id)

    assert active_sub is not None
    assert active_sub.status == SubscriptionStatus.TRIAL
    assert active_sub.is_trial is True


@pytest.mark.asyncio
async def test_get_user_tier_with_active_subscription(db_session: AsyncSession):
    """Test that get_user_tier works with active subscription."""
    # Create a test user
    from app.models.domain import User

    user = User(telegram_id=777777, username="test_user_tier")
    db_session.add(user)
    await db_session.flush()

    # Create a test tier
    tier = SubscriptionTier(
        code="premium",
        name="Premium Tier",
        price_monthly=500,
        max_marketplace_accounts=5,
        sync_interval_minutes=30,
        analytics_depth_days=90,
    )
    db_session.add(tier)
    await db_session.flush()

    # Create an active subscription
    subscription = UserSubscription(
        user_id=user.id,
        tier_id=tier.id,
        status=SubscriptionStatus.ACTIVE,
        started_at=datetime.now(UTC),
        expires_at=None,
        period="monthly",
        is_trial=False,
    )
    db_session.add(subscription)
    await db_session.commit()

    # Test get_user_tier
    service = SubscriptionService(db_session)
    user_tier = await service.get_user_tier(user.id)

    assert user_tier is not None
    assert user_tier.code == "premium"
    assert user_tier.name == "Premium Tier"
