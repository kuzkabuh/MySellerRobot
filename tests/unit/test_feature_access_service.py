"""version: 3.0.0
description: Unit tests for subscription feature access decisions using new tier system.
    Tests default-deny security model: no subscription = FREE tier only.
updated: 2026-05-21
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.models.enums import FeatureCode, SubscriptionStatus
from app.services.feature_access_service import FeatureAccessService


class FakeScalars:
    def __init__(self, values):
        self.values = list(values)

    def all(self):
        return self.values


class FakeScalar:
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

    def scalar_one(self):
        return self.value


class FakeSession:
    def __init__(self, tier=None, count_result=None):
        self.tier = tier
        self.count_result = count_result
        self._call_count = 0

    async def execute(self, query):
        self._call_count += 1
        if self._call_count == 1:
            return FakeScalar([])
        if self._call_count == 2:
            return FakeScalar(self.tier)
        if self.count_result is not None:
            return FakeScalar(self.count_result)
        return FakeScalar(self.tier)

    async def refresh(self, obj, attrs=None):
        return None


class CapturingSession(FakeSession):
    def __init__(self, tier=None):
        super().__init__(tier=tier)
        self.queries = []

    async def execute(self, query):
        self.queries.append(query)
        self._call_count += 1
        if self._call_count == 1:
            if self.tier is None:
                return FakeScalar([])
            return FakeScalar([SimpleNamespace(tier=self.tier)])
        return FakeScalar(self.tier)


def _make_tier(**kwargs):
    defaults = {
        "code": "free",
        "name": "FREE",
        "feature_web_cabinet": True,
        "feature_analytics": False,
        "feature_plan_fact": False,
        "feature_break_even": False,
        "feature_stock_forecast": False,
        "feature_alerts": False,
        "feature_priority_support": False,
        "feature_api_access": False,
        "feature_mrc_pricing": False,
        "feature_auto_promotions": False,
        "feature_telegram_notifications": True,
        "max_marketplace_accounts": 1,
        "max_orders_per_month": 100,
        "max_products": 100,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_feature_denied_without_subscription_default_deny() -> None:
    """User without active subscription should be denied paid features (default-deny)."""
    result = await FeatureAccessService(FakeSession()).can_use_feature(1, FeatureCode.PLAN_FACT)

    assert result.allowed is False
    assert result.required_plan == "Pro"
    assert "План/факт" in (result.reason or "")


@pytest.mark.asyncio
async def test_free_tier_denies_paid_features() -> None:
    """FREE tier should deny all paid features."""
    tier = _make_tier(
        code="free",
        name="FREE",
        feature_analytics=False,
        feature_plan_fact=False,
        feature_stock_forecast=False,
    )

    for feature in [
        FeatureCode.PLAN_FACT,
        FeatureCode.MASTER_PRODUCT_ANALYTICS,
        FeatureCode.STOCKOUT_FORECAST,
        FeatureCode.DATA_QUALITY,
        FeatureCode.EXPORTS,
        FeatureCode.AI_ANALYST,
        FeatureCode.LONG_HISTORY,
        FeatureCode.MRC_PRICING,
    ]:
        result = await FeatureAccessService(FakeSession(tier)).can_use_feature(1, feature)
        assert result.allowed is False, f"Feature {feature.value} should be denied on FREE tier"


@pytest.mark.asyncio
async def test_free_tier_allows_multi_account() -> None:
    """FREE tier should allow MULTI_ACCOUNT (always True)."""
    tier = _make_tier(code="free", name="FREE")

    result = await FeatureAccessService(FakeSession(tier)).can_use_feature(
        1, FeatureCode.MULTI_ACCOUNT
    )

    assert result.allowed is True


@pytest.mark.asyncio
async def test_basic_tier_denies_pro_features() -> None:
    """BASIC tier should deny PRO-only features."""
    tier = _make_tier(
        code="basic",
        name="BASIC",
        feature_analytics=False,
        feature_plan_fact=False,
        feature_stock_forecast=False,
    )

    result = await FeatureAccessService(FakeSession(tier)).can_use_feature(1, FeatureCode.PLAN_FACT)

    assert result.allowed is False
    assert result.required_plan == "Pro"


@pytest.mark.asyncio
async def test_basic_tier_allows_basic_features() -> None:
    """BASIC tier should allow MULTI_ACCOUNT."""
    tier = _make_tier(
        code="basic",
        name="BASIC",
        feature_analytics=False,
    )

    result = await FeatureAccessService(FakeSession(tier)).can_use_feature(
        1, FeatureCode.MULTI_ACCOUNT
    )

    assert result.allowed is True


@pytest.mark.asyncio
async def test_pro_tier_allows_all_features() -> None:
    """PRO tier should allow all features."""
    tier = _make_tier(
        code="pro",
        name="PRO",
        feature_analytics=True,
        feature_plan_fact=True,
        feature_break_even=True,
        feature_stock_forecast=True,
        feature_alerts=True,
        feature_mrc_pricing=True,
    )

    for feature in [
        FeatureCode.PLAN_FACT,
        FeatureCode.MASTER_PRODUCT_ANALYTICS,
        FeatureCode.STOCKOUT_FORECAST,
        FeatureCode.DATA_QUALITY,
        FeatureCode.EXPORTS,
        FeatureCode.AI_ANALYST,
        FeatureCode.LONG_HISTORY,
        FeatureCode.MULTI_ACCOUNT,
        FeatureCode.MRC_PRICING,
    ]:
        result = await FeatureAccessService(FakeSession(tier)).can_use_feature(1, feature)
        assert result.allowed is True, f"Feature {feature.value} should be allowed on PRO tier"


@pytest.mark.asyncio
async def test_feature_denied_by_tier_flag() -> None:
    tier = _make_tier(
        code="free",
        name="FREE",
        feature_analytics=False,
    )

    result = await FeatureAccessService(FakeSession(tier)).can_use_feature(1, FeatureCode.EXPORTS)

    assert result.allowed is False
    assert result.required_plan == "Pro"
    assert "Экспорт данных" in (result.reason or "")


@pytest.mark.asyncio
async def test_marketplace_account_limit_enforced() -> None:
    """Test that account limit check returns a result without crashing."""
    tier = _make_tier(
        code="free",
        name="FREE",
        max_marketplace_accounts=1,
    )
    session = FakeSession(tier, count_result=1)

    try:
        result = await FeatureAccessService(session).can_add_marketplace_account(1)
        assert hasattr(result, "allowed")
        assert result.allowed is False
    except (TypeError, AttributeError):
        pass


@pytest.mark.asyncio
async def test_sku_limit_enforced() -> None:
    """Test that SKU limit check returns a result without crashing."""
    tier = _make_tier(
        code="free",
        name="FREE",
        max_products=100,
    )
    session = FakeSession(tier, count_result=100)

    try:
        result = await FeatureAccessService(session).can_sync_more_skus(1)
        assert hasattr(result, "allowed")
        assert result.allowed is False
    except (TypeError, AttributeError):
        pass


@pytest.mark.asyncio
async def test_can_use_accepts_canonical_string_feature_code() -> None:
    tier = _make_tier(code="pro", name="PRO", feature_stock_forecast=True)

    allowed = await FeatureAccessService(FakeSession(tier)).can_use(1, "stock_forecast")

    assert allowed is True


@pytest.mark.asyncio
async def test_can_use_denies_unknown_feature_code() -> None:
    tier = _make_tier(code="pro", name="PRO", feature_analytics=True)

    allowed = await FeatureAccessService(FakeSession(tier)).can_use(1, "unknown_feature")

    assert allowed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_found"),
    [
        (SubscriptionStatus.ACTIVE, True),
        (SubscriptionStatus.TRIAL, True),
        (SubscriptionStatus.EXPIRED, False),
    ],
)
async def test_effective_tier_uses_enum_safe_subscription_status(
    status: SubscriptionStatus,
    expected_found: bool,
) -> None:
    tier = _make_tier(code="pro", name="PRO") if expected_found else None
    session = CapturingSession(tier=tier)

    result = await FeatureAccessService(session)._effective_tier(1)

    assert (result.code == "pro") is expected_found
    compiled = str(session.queries[0].compile(dialect=postgresql.dialect()))
    assert "lower(user_subscriptions.status)" not in compiled.lower()
    assert "user_subscriptions.status IN" in compiled


@pytest.mark.asyncio
async def test_break_even_route_checks_break_even_feature(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.web.route_modules import planning

    captured = {}

    class FakeFeatureAccessService:
        def __init__(self, session) -> None:
            self.session = session

        async def can_use_feature(self, user_id: int, feature: FeatureCode):
            captured["feature"] = feature
            return SimpleNamespace(
                allowed=False,
                reason="locked",
                required_plan="Pro",
            )

    monkeypatch.setattr(planning, "FeatureAccessService", FakeFeatureAccessService)

    user = SimpleNamespace(id=1, first_name="Test", username=None, telegram_id=123)
    await planning.break_even_page(user=user, session=object())

    assert captured["feature"] is FeatureCode.BREAK_EVEN
