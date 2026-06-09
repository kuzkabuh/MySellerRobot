"""version: 1.0.0
description: Tests for subscription lifecycle release 1.6.3.
updated: 2026-05-17
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.enums import SubscriptionStatus
from app.models.subscriptions import SubscriptionTier, UserSubscription
from app.services.subscriptions.subscription_service import SubscriptionService


class ScalarResult:
    def __init__(self, value=None, values: list[object] | None = None) -> None:  # type: ignore[no-untyped-def]
        self.value = value
        self.values = values or []

    def scalar_one_or_none(self):  # type: ignore[no-untyped-def]
        return self.value

    def scalars(self):  # type: ignore[no-untyped-def]
        return self

    def all(self) -> list[object]:
        return self.values


class LifecycleSession:
    def __init__(self, execute_results: list[ScalarResult] | None = None) -> None:
        self.execute_results = execute_results or []
        self.added: list[object] = []
        self.flushed = 0
        self.refreshed: list[object] = []
        self.get_result = None

    async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        if self.execute_results:
            return self.execute_results.pop(0)
        return ScalarResult()

    async def get(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return self.get_result

    async def refresh(self, value, *_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        self.refreshed.append(value)

    def add(self, value) -> None:  # type: ignore[no-untyped-def]
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed += 1


def tier(code: str, tier_id: int) -> SubscriptionTier:
    return SubscriptionTier(
        id=tier_id,
        code=code,
        name=code.upper(),
        description=None,
        price_monthly=Decimal("490"),
        price_yearly=Decimal("4900"),
        max_marketplace_accounts=2,
        max_orders_per_month=1000,
        max_products=1000,
        feature_web_cabinet=True,
        feature_analytics=code in {"basic", "pro"},
        feature_plan_fact=code == "pro",
        feature_break_even=code == "pro",
        feature_stock_forecast=code == "pro",
        feature_alerts=code in {"basic", "pro"},
        feature_api_access=False,
        feature_priority_support=code == "pro",
        is_active=True,
        sort_order={"free": 0, "basic": 10, "pro": 20}.get(code, 0),
    )


def subscription(
    *,
    tier_obj: SubscriptionTier,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    expires_at: datetime | None = None,
    is_trial: bool = False,
) -> UserSubscription:
    row = UserSubscription(
        id=10,
        user_id=1,
        tier_id=tier_obj.id,
        status=status,
        started_at=datetime.now(tz=UTC),
        expires_at=expires_at,
        period="monthly",
        is_trial=is_trial,
        trial_ends_at=expires_at if is_trial else None,
        payment_provider="yookassa",
        payment_id="payment-id",
        auto_renew=True,
    )
    row.tier = tier_obj
    return row


@pytest.mark.asyncio
async def test_monthly_subscription_creates_30_day_period() -> None:
    session = LifecycleSession([ScalarResult(tier("basic", 2)), ScalarResult(None)])

    row = await SubscriptionService(session).create_subscription(
        user_id=1,
        tier_code="basic",
        period="monthly",
    )

    assert row.period == "monthly"
    assert row.expires_at is not None
    assert 29 <= (row.expires_at - datetime.now(tz=UTC)).days <= 30


@pytest.mark.asyncio
async def test_yearly_subscription_creates_365_day_period() -> None:
    session = LifecycleSession([ScalarResult(tier("pro", 3)), ScalarResult(None)])

    row = await SubscriptionService(session).create_subscription(
        user_id=1,
        tier_code="pro",
        period="yearly",
    )

    assert row.period == "yearly"
    assert row.expires_at is not None
    assert 364 <= (row.expires_at - datetime.now(tz=UTC)).days <= 365


@pytest.mark.asyncio
async def test_renew_before_expiration_adds_days_to_current_expires_at() -> None:
    current = subscription(
        tier_obj=tier("basic", 2),
        expires_at=datetime.now(tz=UTC) + timedelta(days=10),
    )
    session = LifecycleSession()
    session.get_result = current

    renewed = await SubscriptionService(session).renew_subscription(
        current.id,
        period="monthly",
        payment_id="renew-payment",
    )

    assert renewed.expires_at is not None
    assert 39 <= (renewed.expires_at - datetime.now(tz=UTC)).days <= 40
    assert renewed.payment_id == "renew-payment"


@pytest.mark.asyncio
async def test_renew_after_expiration_counts_from_now() -> None:
    current = subscription(
        tier_obj=tier("basic", 2),
        expires_at=datetime.now(tz=UTC) - timedelta(days=3),
    )
    session = LifecycleSession()
    session.get_result = current

    renewed = await SubscriptionService(session).renew_subscription(current.id, period="monthly")

    assert renewed.expires_at is not None
    assert 29 <= (renewed.expires_at - datetime.now(tz=UTC)).days <= 30


@pytest.mark.asyncio
async def test_upgrade_basic_to_pro_replaces_old_subscription() -> None:
    basic = tier("basic", 2)
    pro = tier("pro", 3)
    active_basic = subscription(
        tier_obj=basic,
        expires_at=datetime.now(tz=UTC) + timedelta(days=20),
    )
    session = LifecycleSession([ScalarResult(pro), ScalarResult(active_basic)])

    new_subscription = await SubscriptionService(session).create_subscription(
        user_id=1,
        tier_code="pro",
        period="monthly",
    )

    assert active_basic.status == SubscriptionStatus.REPLACED
    assert active_basic.auto_renew is False
    assert new_subscription.tier_id == pro.id
    assert new_subscription.status == SubscriptionStatus.ACTIVE


@pytest.mark.asyncio
async def test_trial_is_active_and_can_be_used_once() -> None:
    session = LifecycleSession([ScalarResult(tier("pro", 3)), ScalarResult(None)])

    trial = await SubscriptionService(session).start_trial(user_id=1)

    assert trial.status == SubscriptionStatus.TRIAL
    assert trial.is_trial is True
    assert trial.period == "trial"
    assert trial.trial_ends_at == trial.expires_at


@pytest.mark.asyncio
async def test_trial_cannot_be_used_twice() -> None:
    old_trial = subscription(
        tier_obj=tier("pro", 3),
        status=SubscriptionStatus.EXPIRED,
        expires_at=datetime.now(tz=UTC) - timedelta(days=1),
        is_trial=True,
    )
    session = LifecycleSession([ScalarResult(tier("pro", 3)), ScalarResult(old_trial.id)])

    with pytest.raises(ValueError, match="already used trial"):
        await SubscriptionService(session).start_trial(user_id=1)


@pytest.mark.asyncio
async def test_expired_subscription_returns_free_tier() -> None:
    free = tier("free", 1)
    session = LifecycleSession([ScalarResult(None), ScalarResult(free)])

    current_tier = await SubscriptionService(session).get_user_tier(1)

    assert current_tier.code == "free"


@pytest.mark.asyncio
async def test_expire_outdated_subscriptions_marks_active_and_trial_expired() -> None:
    active = subscription(
        tier_obj=tier("basic", 2),
        expires_at=datetime.now(tz=UTC) - timedelta(days=1),
    )
    trial = subscription(
        tier_obj=tier("pro", 3),
        status=SubscriptionStatus.TRIAL,
        expires_at=datetime.now(tz=UTC) - timedelta(hours=1),
        is_trial=True,
    )
    session = LifecycleSession([ScalarResult(values=[active, trial])])

    count = await SubscriptionService(session).expire_outdated_subscriptions()

    assert count == 2
    assert active.status == SubscriptionStatus.EXPIRED
    assert trial.status == SubscriptionStatus.EXPIRED
    assert active.auto_renew is False
    assert trial.auto_renew is False
