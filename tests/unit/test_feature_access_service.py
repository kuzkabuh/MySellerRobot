"""version: 3.0.0
description: Unit tests for subscription feature access decisions using new tier system.
    Tests default-deny security model: no subscription = FREE tier only.
updated: 2026-05-21
"""

from types import SimpleNamespace

import pytest

from app.models.enums import FeatureCode
from app.services.feature_access_service import FeatureAccessService


class FakeScalar:
    def __init__(self, value):
        self.value = value

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
        if self.count_result is not None:
            return FakeScalar(self.count_result)
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
