"""version: 1.0.0
description: Тесты backend-gate для платных web-мутаций.
updated: 2026-06-07
"""

import pytest
from fastapi import HTTPException

from app.models.enums import FeatureCode
from app.services.subscriptions.feature_access_service import FeatureAccessResult
from app.web.route_modules import mrc_pricing, planning


class _FeatureAccessService:
    def __init__(self, session) -> None:
        self.session = session

    async def can_use_feature(self, user_id: int, feature: FeatureCode) -> FeatureAccessResult:
        if user_id == 1:
            return FeatureAccessResult(allowed=True)
        return FeatureAccessResult(
            allowed=False,
            reason=f"Нет доступа к {feature.value}",
            required_plan="Pro",
            current_tier="Free",
        )


@pytest.mark.asyncio
async def test_plan_fact_post_gate_allows_paid_user(monkeypatch) -> None:
    monkeypatch.setattr(planning, "FeatureAccessService", _FeatureAccessService)

    await planning._ensure_plan_fact_access(object(), 1)


@pytest.mark.asyncio
async def test_plan_fact_post_gate_rejects_free_user(monkeypatch) -> None:
    monkeypatch.setattr(planning, "FeatureAccessService", _FeatureAccessService)

    with pytest.raises(HTTPException) as exc_info:
        await planning._ensure_plan_fact_access(object(), 2)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_mrc_post_gate_allows_paid_user(monkeypatch) -> None:
    monkeypatch.setattr(mrc_pricing, "FeatureAccessService", _FeatureAccessService)

    await mrc_pricing._ensure_mrc_access(object(), 1)


@pytest.mark.asyncio
async def test_mrc_post_gate_rejects_free_user(monkeypatch) -> None:
    monkeypatch.setattr(mrc_pricing, "FeatureAccessService", _FeatureAccessService)

    with pytest.raises(HTTPException) as exc_info:
        await mrc_pricing._ensure_mrc_access(object(), 2)

    assert exc_info.value.status_code == 403
