"""version: 1.0.0
description: Stability tests for subscription service fallbacks and async-safe limits.
updated: 2026-05-17
"""

from app.services.subscription_service import SubscriptionService


class EmptyResult:
    def scalar_one_or_none(self):  # type: ignore[no-untyped-def]
        return None

    def scalar_one(self) -> int:
        return 0


class EmptySubscriptionSession:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.get_calls = 0

    async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        self.execute_calls += 1
        return EmptyResult()

    async def get(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        self.get_calls += 1
        return None


async def test_get_user_tier_uses_safe_free_fallback_when_catalog_missing() -> None:
    session = EmptySubscriptionSession()

    tier = await SubscriptionService(session).get_user_tier(1)  # type: ignore[arg-type]

    assert tier.code == "free"
    assert tier.name == "FREE"
    assert tier.feature_web_cabinet is True
    assert tier.max_marketplace_accounts == 1


async def test_check_account_limit_counts_accounts_without_lazy_relationships() -> None:
    class ExistingUserSession(EmptySubscriptionSession):
        async def get(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            self.get_calls += 1
            return object()

    session = ExistingUserSession()

    current, max_allowed = await SubscriptionService(session).check_account_limit(1)  # type: ignore[arg-type]

    assert (current, max_allowed) == (0, 1)
    assert session.get_calls == 1
    assert session.execute_calls == 3
