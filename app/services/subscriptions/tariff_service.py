"""version: 1.0.0
description: Tariff management service for admin CRUD and feature access queries.
updated: 2026-05-31
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SubscriptionStatus
from app.models.subscriptions import SubscriptionTier, UserSubscription

logger = logging.getLogger(__name__)

TARIFF_FEATURE_FIELDS: list[tuple[str, str]] = [
    ("feature_web_cabinet", "Web-кабинет"),
    ("feature_analytics", "Расширенная аналитика"),
    ("feature_plan_fact", "План/факт"),
    ("feature_break_even", "Безубыточность"),
    ("feature_stock_forecast", "Прогноз остатков"),
    ("feature_alerts", "Алерты"),
    ("feature_api_access", "API-доступ"),
    ("feature_priority_support", "Приоритетная поддержка"),
    ("feature_mrc_pricing", "МРЦ и акции WB"),
    ("feature_auto_promotions", "Автоакции WB"),
    ("feature_telegram_notifications", "Telegram-уведомления"),
]


class TariffService:
    """CRUD and query operations for subscription tariffs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_all_tariffs(self) -> list[SubscriptionTier]:
        result = await self.session.execute(
            select(SubscriptionTier).order_by(SubscriptionTier.sort_order)
        )
        return list(result.scalars().all())

    async def get_public_active_tariffs(self) -> list[SubscriptionTier]:
        result = await self.session.execute(
            select(SubscriptionTier)
            .where(SubscriptionTier.is_active.is_(True))
            .where(SubscriptionTier.is_public.is_(True))
            .order_by(SubscriptionTier.sort_order)
        )
        return list(result.scalars().all())

    async def get_tariff_by_id(self, tariff_id: int) -> SubscriptionTier | None:
        return await self.session.get(SubscriptionTier, tariff_id)

    async def get_tariff_by_code(self, code: str) -> SubscriptionTier | None:
        result = await self.session.execute(
            select(SubscriptionTier).where(SubscriptionTier.code == code)
        )
        return result.scalar_one_or_none()

    async def create_tariff(self, **kwargs: Any) -> SubscriptionTier:
        tariff = SubscriptionTier(**kwargs)
        self.session.add(tariff)
        await self.session.flush()
        logger.info(
            "tariff_created",
            extra={"tariff_id": tariff.id, "tariff_code": tariff.code},
        )
        return tariff

    async def update_tariff(self, tariff_id: int, **kwargs: Any) -> SubscriptionTier | None:
        tariff = await self.session.get(SubscriptionTier, tariff_id)
        if not tariff:
            return None
        old_values: dict[str, Any] = {}
        for key, value in kwargs.items():
            if hasattr(tariff, key):
                old_value = getattr(tariff, key)
                if old_value != value:
                    old_values[key] = str(old_value)
                setattr(tariff, key, value)
        await self.session.flush()
        logger.info(
            "tariff_updated",
            extra={
                "tariff_id": tariff.id,
                "tariff_code": tariff.code,
                "changed_fields": list(old_values.keys()),
            },
        )
        return tariff

    async def toggle_tariff(self, tariff_id: int) -> SubscriptionTier | None:
        tariff = await self.session.get(SubscriptionTier, tariff_id)
        if not tariff:
            return None
        tariff.is_active = not tariff.is_active
        await self.session.flush()
        logger.info(
            "tariff_toggled",
            extra={
                "tariff_id": tariff.id,
                "tariff_code": tariff.code,
                "is_active": tariff.is_active,
            },
        )
        return tariff

    async def get_tariff_user_count(self, tariff_id: int) -> int:
        now = datetime.now(tz=UTC)
        result = await self.session.execute(
            select(func.count(UserSubscription.id))
            .where(UserSubscription.tier_id == tariff_id)
            .where(
                UserSubscription.status.in_(
                    [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.TRIAL.value]
                )
            )
            .where((UserSubscription.expires_at.is_(None)) | (UserSubscription.expires_at > now))
        )
        return int(result.scalar_one() or 0)

    async def get_all_tariffs_with_user_counts(self) -> list[tuple[SubscriptionTier, int]]:
        tariffs = await self.get_all_tariffs()
        result: list[tuple[SubscriptionTier, int]] = []
        for tariff in tariffs:
            count = await self.get_tariff_user_count(tariff.id)
            result.append((tariff, count))
        return result

    async def code_exists(self, code: str, exclude_id: int | None = None) -> bool:
        query = select(SubscriptionTier.id).where(SubscriptionTier.code == code)
        if exclude_id is not None:
            query = query.where(SubscriptionTier.id != exclude_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None

    async def has_active_subscribers(self, tariff_id: int) -> bool:
        count = await self.get_tariff_user_count(tariff_id)
        return count > 0

    @staticmethod
    def get_feature_flags(tariff: SubscriptionTier) -> dict[str, bool]:
        return {field: bool(getattr(tariff, field, False)) for field, _ in TARIFF_FEATURE_FIELDS}

    @staticmethod
    def get_limits(tariff: SubscriptionTier) -> dict[str, Any]:
        return {
            "max_marketplace_accounts": tariff.max_marketplace_accounts,
            "max_orders_per_month": tariff.max_orders_per_month,
            "max_products": tariff.max_products,
            "max_users": tariff.max_users,
            "sync_interval_minutes": tariff.sync_interval_minutes,
            "analytics_depth_days": tariff.analytics_depth_days,
        }

    @staticmethod
    def get_available_periods(tariff: SubscriptionTier) -> dict[str, Decimal]:
        periods: dict[str, Decimal] = {}
        if tariff.price_monthly is not None and tariff.price_monthly > 0:
            periods["monthly"] = tariff.price_monthly
        if tariff.price_3_months is not None and tariff.price_3_months > 0:
            periods["3_months"] = tariff.price_3_months
        if tariff.price_6_months is not None and tariff.price_6_months > 0:
            periods["6_months"] = tariff.price_6_months
        if tariff.price_yearly is not None and tariff.price_yearly > 0:
            periods["yearly"] = tariff.price_yearly
        return periods

    @staticmethod
    def check_feature_access(tariff: SubscriptionTier, feature_field: str) -> bool:
        return bool(getattr(tariff, feature_field, False))
