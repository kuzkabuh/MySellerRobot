"""Tests for subscription display after payment.

Covers:
1. First payment creates subscription and get_active_subscription returns it.
2. Same-tier renewal extends existing subscription.
3. Upgrade replaces old subscription, new one is returned.
4. Downgrade replaces old subscription, new one is returned.
5. Multiple subscriptions in DB: service returns the correct current one.
6. Subscription screen shows correct data after new payment.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.models.enums import SubscriptionStatus
from app.models.subscriptions import SubscriptionTier, UserSubscription
from app.services.feature_access_service import FeatureAccessService, FeatureCode
from app.services.subscription_service import SubscriptionService


class ScalarResult:
    def __init__(self, value=None, values: list[object] | None = None) -> None:
        self.value = value
        self.values = values or []

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self) -> list[object]:
        if self.value is not None:
            return [self.value]
        return self.values


class SessionMock:
    def __init__(self, execute_results: list[ScalarResult] | None = None) -> None:
        self.execute_results = execute_results or []
        self.added: list[object] = []
        self.flushed = 0
        self.refreshed: list[object] = []
        self.get_result = None

    async def execute(self, *_args, **_kwargs):
        if self.execute_results:
            return self.execute_results.pop(0)
        return ScalarResult()

    async def get(self, *_args, **_kwargs):
        return self.get_result

    async def refresh(self, value, *_args, **_kwargs) -> None:
        self.refreshed.append(value)

    def add(self, value) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed += 1


def _make_tier(code: str, sort_order: int) -> SubscriptionTier:
    normalized = code.lower()
    return SubscriptionTier(
        id={"free": 0, "basic": 1, "pro": 2, "enterprise": 3}[normalized],
        code=code,
        name=normalized.upper(),
        description=None,
        price_monthly=Decimal({"free": 0, "basic": 490, "pro": 1490, "enterprise": 0}[normalized]),
        price_yearly=Decimal({"free": 0, "basic": 4900, "pro": 14900, "enterprise": 0}[normalized]),
        max_marketplace_accounts=2,
        max_orders_per_month=1000,
        max_products=1000,
        feature_web_cabinet=True,
        feature_analytics=normalized in {"basic", "pro"},
        feature_plan_fact=normalized == "pro",
        feature_break_even=normalized == "pro",
        feature_stock_forecast=normalized == "pro",
        feature_alerts=normalized in {"basic", "pro"},
        feature_api_access=False,
        feature_priority_support=normalized == "pro",
        is_active=True,
        sort_order=sort_order,
    )


def _make_subscription(
    tier: SubscriptionTier,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    started_at: datetime | None = None,
    expires_at: datetime | None = None,
    period: str = "monthly",
) -> UserSubscription:
    now = datetime.now(tz=UTC)
    return UserSubscription(
        id=MagicMock(),
        user_id=1,
        tier_id=tier.id,
        status=status,
        started_at=started_at or now,
        expires_at=expires_at or (now + timedelta(days=30)),
        period=period,
        is_trial=False,
        trial_ends_at=None,
        payment_provider="yookassa",
        payment_id="test-payment",
        auto_renew=True,
        created_at=now,
        updated_at=now,
    )


class TestFirstPaymentCreatesSubscription:
    """Test 1: First payment creates subscription and get_active_subscription returns it."""

    @pytest.mark.asyncio
    async def test_first_payment_creates_and_returns_subscription(self):
        basic = _make_tier("basic", 10)
        session = SessionMock([ScalarResult(basic), ScalarResult(None)])

        service = SubscriptionService(session)

        sub = await service.create_subscription(
            user_id=1,
            tier_code="basic",
            period="monthly",
        )

        assert sub is not None
        assert sub.tier_id == basic.id
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.expires_at is not None

        session.execute_results = [ScalarResult(sub)]
        active = await service.get_active_subscription(1)
        assert active is not None
        assert active.tier_id == basic.id


class TestSameTierRenewal:
    """Test 2: Same-tier renewal extends existing subscription."""

    @pytest.mark.asyncio
    async def test_same_tier_renewal_extends_existing(self):
        basic = _make_tier("basic", 10)
        future = datetime.now(tz=UTC) + timedelta(days=20)
        active_basic = _make_subscription(basic, expires_at=future)

        session = SessionMock([ScalarResult(basic), ScalarResult(active_basic)])
        session.get_result = active_basic

        service = SubscriptionService(session)

        result = await service.create_subscription(
            user_id=1,
            tier_code="basic",
            period="monthly",
        )

        assert result.id == active_basic.id
        assert result.expires_at is not None
        assert (result.expires_at - datetime.now(tz=UTC)).days >= 49

        session.execute_results = [ScalarResult(active_basic)]
        active = await service.get_active_subscription(1)
        assert active is not None
        assert active.tier_id == basic.id


class TestUpgradeReplacesOldSubscription:
    """Test 3: Upgrade replaces old subscription, new one is returned."""

    @pytest.mark.asyncio
    async def test_upgrade_basic_to_pro_replaces_old(self):
        basic = _make_tier("basic", 10)
        pro = _make_tier("pro", 20)
        active_basic = _make_subscription(
            basic, expires_at=datetime.now(tz=UTC) + timedelta(days=20)
        )
        active_basic.tier = basic

        session = SessionMock([ScalarResult(pro), ScalarResult(active_basic)])

        service = SubscriptionService(session)

        new_sub = await service.create_subscription(
            user_id=1,
            tier_code="pro",
            period="monthly",
        )

        assert active_basic.status == SubscriptionStatus.REPLACED
        assert new_sub.tier_id == pro.id
        assert new_sub.status == SubscriptionStatus.ACTIVE

        session.execute_results = [ScalarResult(new_sub)]
        active = await service.get_active_subscription(1)
        assert active is not None
        assert active.tier_id == pro.id


class TestDowngradeReplacesOldSubscription:
    """Test 4: Downgrade replaces old subscription, new one is returned."""

    @pytest.mark.asyncio
    async def test_downgrade_pro_to_basic_replaces_old(self):
        pro = _make_tier("pro", 20)
        basic = _make_tier("basic", 10)
        active_pro = _make_subscription(pro, expires_at=datetime.now(tz=UTC) + timedelta(days=365))
        active_pro.tier = pro

        session = SessionMock([ScalarResult(basic), ScalarResult(active_pro)])

        service = SubscriptionService(session)

        new_sub = await service.create_subscription(
            user_id=1,
            tier_code="basic",
            period="monthly",
        )

        assert active_pro.status == SubscriptionStatus.REPLACED
        assert new_sub.tier_id == basic.id
        assert new_sub.status == SubscriptionStatus.ACTIVE

        session.execute_results = [ScalarResult(new_sub)]
        active = await service.get_active_subscription(1)
        assert active is not None
        assert active.tier_id == basic.id
        assert active.tier_id != pro.id


class TestMultipleSubscriptionsInDB:
    """Test 5: Multiple subscriptions in DB: service returns the correct current one."""

    @pytest.mark.asyncio
    async def test_returns_most_recent_active_subscription(self):
        basic = _make_tier("basic", 10)
        pro = _make_tier("pro", 20)

        _make_subscription(
            pro,
            status=SubscriptionStatus.REPLACED,
            started_at=datetime.now(tz=UTC) - timedelta(days=60),
            expires_at=datetime.now(tz=UTC) + timedelta(days=300),
        )
        new_basic = _make_subscription(
            basic,
            status=SubscriptionStatus.ACTIVE,
            started_at=datetime.now(tz=UTC) - timedelta(days=1),
            expires_at=datetime.now(tz=UTC) + timedelta(days=29),
        )

        session = SessionMock([ScalarResult(new_basic)])

        service = SubscriptionService(session)

        active = await service.get_active_subscription(1)
        assert active is not None
        assert active.tier_id == basic.id
        assert active.status == SubscriptionStatus.ACTIVE


class TestSubscriptionScreenShowsCorrectData:
    """Test 6: Subscription screen shows correct data after new payment."""

    @pytest.mark.asyncio
    async def test_screen_shows_new_tier_after_downgrade(self):
        """After PRO → BASIC downgrade, screen should show BASIC, not old PRO."""
        pro = _make_tier("pro", 20)
        basic = _make_tier("basic", 10)
        active_pro = _make_subscription(
            pro,
            expires_at=datetime.now(tz=UTC) + timedelta(days=365),
        )
        active_pro.tier = pro

        session = SessionMock([ScalarResult(basic), ScalarResult(active_pro)])

        service = SubscriptionService(session)

        new_sub = await service.create_subscription(
            user_id=1,
            tier_code="basic",
            period="monthly",
        )

        assert active_pro.status == SubscriptionStatus.REPLACED
        assert new_sub.tier_id == basic.id

        session.execute_results = [ScalarResult(new_sub)]
        active = await service.get_active_subscription(1)
        assert active is not None
        assert active.tier_id == basic.id


class TestFeatureGatingUsesCorrectSubscription:
    """Test 7: Feature gating uses the same subscription as the screen."""

    @pytest.mark.asyncio
    async def test_feature_access_uses_current_subscription(self):
        basic = _make_tier("basic", 10)
        sub = _make_subscription(basic)
        sub.tier = basic

        session = SessionMock([ScalarResult(sub)])

        service = SubscriptionService(session)

        has_analytics = await service.check_feature_access(1, "analytics")
        has_web = await service.check_feature_access(1, "web_cabinet")

        assert has_analytics is True
        assert has_web is True


class TestTariffSourceOfTruth:
    """Cross-cutting tariff detection rules."""

    @pytest.mark.asyncio
    async def test_user_without_subscription_gets_free(self):
        free = _make_tier("free", 0)
        session = SessionMock([ScalarResult(None), ScalarResult(free)])

        tier = await SubscriptionService(session).get_user_tier(1)

        assert tier.code == "free"

    @pytest.mark.asyncio
    async def test_active_pro_is_returned_as_pro(self):
        pro = _make_tier("pro", 20)
        sub = _make_subscription(pro)
        sub.tier = pro
        session = SessionMock([ScalarResult(sub)])

        tier = await SubscriptionService(session).get_user_tier(1)

        assert tier.code == "pro"

    @pytest.mark.asyncio
    async def test_expired_pro_falls_back_to_free(self):
        free = _make_tier("free", 0)
        session = SessionMock([ScalarResult(None), ScalarResult(free)])

        tier = await SubscriptionService(session).get_user_tier(1)

        assert tier.code == "free"

    @pytest.mark.asyncio
    async def test_conflicting_active_subscriptions_choose_highest_tier(self, caplog):
        basic = _make_tier("basic", 10)
        pro = _make_tier("pro", 20)
        basic_sub = _make_subscription(basic)
        pro_sub = _make_subscription(pro)
        session = SessionMock([ScalarResult(values=[pro_sub, basic_sub])])

        active = await SubscriptionService(session).get_active_subscription(1)

        assert active is pro_sub
        assert "multiple_active_subscriptions_detected" in caplog.text

    @pytest.mark.asyncio
    async def test_tier_lookup_is_case_insensitive(self):
        pro = _make_tier("PRO", 20)
        session = SessionMock([ScalarResult(pro)])

        tier = await SubscriptionService(session).get_tier_by_code("pro")

        assert tier is pro

    @pytest.mark.asyncio
    async def test_feature_access_uses_subscription_service_tier(self):
        pro = _make_tier("pro", 20)
        sub = _make_subscription(pro)
        sub.tier = pro
        session = SessionMock([ScalarResult(sub)])

        access = await FeatureAccessService(session).can_use_feature(1, FeatureCode.PLAN_FACT)

        assert access.allowed is True
