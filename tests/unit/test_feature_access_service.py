"""version: 1.0.0
description: Unit tests for subscription feature access decisions.
updated: 2026-05-15
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


class FakeSession:
    def __init__(self, plan=None):
        self.plan = plan

    async def execute(self, query):  # type: ignore[no-untyped-def]
        return FakeScalar(self.plan)


@pytest.mark.asyncio
async def test_feature_allowed_without_subscription_plan() -> None:
    result = await FeatureAccessService(FakeSession()).can_use_feature(1, FeatureCode.PLAN_FACT)

    assert result.allowed is True


@pytest.mark.asyncio
async def test_feature_denied_by_plan_flag() -> None:
    plan = SimpleNamespace(title="Free", features={FeatureCode.EXPORTS.value: False})

    result = await FeatureAccessService(FakeSession(plan)).can_use_feature(1, FeatureCode.EXPORTS)

    assert result.allowed is False
    assert result.required_plan == "Pro"
    assert "Функция будет доступна" in (result.reason or "")
