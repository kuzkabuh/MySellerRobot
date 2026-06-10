"""Tariff-based limits for manual sync period selection in Sync Center."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.subscriptions.subscription_service import SubscriptionService


@dataclass(frozen=True, slots=True)
class ManualSyncPeriodLimits:
    max_days_back: int
    max_range_days: int
    tariff_code: str
    tariff_name: str


_MANUAL_SYNC_LIMITS: dict[str, ManualSyncPeriodLimits] = {
    "free": ManualSyncPeriodLimits(7, 7, "free", "Free"),
    "basic": ManualSyncPeriodLimits(30, 30, "basic", "Basic"),
    "pro": ManualSyncPeriodLimits(90, 90, "pro", "Pro"),
    "business": ManualSyncPeriodLimits(180, 180, "business", "Business"),
    "enterprise": ManualSyncPeriodLimits(365, 365, "enterprise", "Enterprise"),
}


async def get_manual_sync_period_limits(
    session: AsyncSession, user_id: int
) -> ManualSyncPeriodLimits:
    tier = await SubscriptionService(session).get_user_tier(user_id)
    return _MANUAL_SYNC_LIMITS.get(tier.code, _MANUAL_SYNC_LIMITS["free"])


def get_period_supported_sync_types() -> list[str]:
    return [
        "orders", "sales", "returns", "stocks",
        "finances", "wb_financial_details", "ozon_finances",
    ]


def parse_period_preset(preset: str) -> int | None:
    mapping = {
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "180d": 180,
        "365d": 365,
    }
    return mapping.get(preset)
