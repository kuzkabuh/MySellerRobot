"""version: 2.0.0
description: Сервис управления тарифами — CRUD, статистика биллинга, дублирование, порядок.
updated: 2026-06-12
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

# Список (поле_модели, читаемое_название) для рендера чекбоксов функций
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

_ACTIVE_STATUSES = [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.TRIAL.value]


class TariffService:
    """CRUD и query-операции для тарифных планов подписки."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Чтение ────────────────────────────────────────────────────────────────

    async def get_all_tariffs(self) -> list[SubscriptionTier]:
        result = await self.session.execute(
            select(SubscriptionTier).order_by(SubscriptionTier.sort_order, SubscriptionTier.id)
        )
        return list(result.scalars().all())

    async def get_public_active_tariffs(self) -> list[SubscriptionTier]:
        result = await self.session.execute(
            select(SubscriptionTier)
            .where(SubscriptionTier.is_active.is_(True))
            .where(SubscriptionTier.is_public.is_(True))
            .order_by(SubscriptionTier.sort_order, SubscriptionTier.id)
        )
        return list(result.scalars().all())

    async def get_tariff_by_id(self, tariff_id: int) -> SubscriptionTier | None:
        return await self.session.get(SubscriptionTier, tariff_id)

    async def get_tariff_by_code(self, code: str) -> SubscriptionTier | None:
        result = await self.session.execute(
            select(SubscriptionTier).where(SubscriptionTier.code == code)
        )
        return result.scalar_one_or_none()

    async def get_tariff_user_count(self, tariff_id: int) -> int:
        now = datetime.now(tz=UTC)
        result = await self.session.execute(
            select(func.count(UserSubscription.id))
            .where(UserSubscription.tier_id == tariff_id)
            .where(UserSubscription.status.in_(_ACTIVE_STATUSES))
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
        return await self.get_tariff_user_count(tariff_id) > 0

    # ── Статистика биллинга ────────────────────────────────────────────────────

    async def get_billing_stats(self) -> dict[str, Any]:
        """Возвращает KPI-метрики: платные юзеры, MRR, ARR."""
        now = datetime.now(tz=UTC)
        # Загружаем все активные платные подписки с ценами тарифа
        rows = await self.session.execute(
            select(
                UserSubscription.period,
                UserSubscription.is_trial,
                SubscriptionTier.price_monthly,
                SubscriptionTier.price_3_months,
                SubscriptionTier.price_6_months,
                SubscriptionTier.price_yearly,
            )
            .join(SubscriptionTier, UserSubscription.tier_id == SubscriptionTier.id)
            .where(UserSubscription.status.in_(_ACTIVE_STATUSES))
            .where((UserSubscription.expires_at.is_(None)) | (UserSubscription.expires_at > now))
            .where(UserSubscription.is_trial.is_(False))
            .where(SubscriptionTier.price_monthly > 0)
        )
        all_rows = rows.all()

        mrr = Decimal("0")
        paid_users = len(all_rows)
        for row in all_rows:
            period, _, pm, p3m, p6m, py = row
            if period == "monthly" and pm:
                mrr += pm
            elif period == "3_months" and p3m:
                mrr += p3m / 3
            elif period == "6_months" and p6m:
                mrr += p6m / 6
            elif period == "yearly" and py:
                mrr += py / 12
            elif pm:
                # fallback — считаем по месячной цене
                mrr += pm

        return {
            "paid_users": paid_users,
            "mrr": mrr,
            "arr": mrr * 12,
            "avg_price": (mrr / paid_users) if paid_users > 0 else Decimal("0"),
        }

    # ── Создание / обновление ─────────────────────────────────────────────────

    async def create_tariff(self, **kwargs: Any) -> SubscriptionTier:
        tariff = SubscriptionTier(**kwargs)
        self.session.add(tariff)
        await self.session.flush()
        logger.info("tariff_created", extra={"tariff_id": tariff.id, "code": tariff.code})
        return tariff

    async def update_tariff(self, tariff_id: int, **kwargs: Any) -> SubscriptionTier | None:
        tariff = await self.session.get(SubscriptionTier, tariff_id)
        if not tariff:
            return None
        changed: list[str] = []
        for key, value in kwargs.items():
            if hasattr(tariff, key) and getattr(tariff, key) != value:
                changed.append(key)
                setattr(tariff, key, value)
        await self.session.flush()
        logger.info("tariff_updated", extra={"tariff_id": tariff.id, "changed": changed})
        return tariff

    async def duplicate_tariff(self, tariff_id: int) -> SubscriptionTier:
        """Создаёт копию тарифа с суффиксом _copy в коде."""
        source = await self.session.get(SubscriptionTier, tariff_id)
        if not source:
            raise ValueError(f"Тариф {tariff_id} не найден")

        # Генерируем уникальный код для копии
        base_code = source.code.rstrip("_copy").rstrip("_")
        new_code = f"{base_code}_copy"
        suffix = 2
        while await self.code_exists(new_code):
            new_code = f"{base_code}_copy{suffix}"
            suffix += 1

        fields_to_copy = [
            "name", "description", "price_monthly", "price_3_months", "price_6_months",
            "price_yearly", "currency", "max_marketplace_accounts", "max_orders_per_month",
            "max_products", "max_users", "sync_interval_minutes", "analytics_depth_days",
            "feature_web_cabinet", "feature_analytics", "feature_plan_fact", "feature_break_even",
            "feature_stock_forecast", "feature_alerts", "feature_api_access",
            "feature_priority_support", "feature_mrc_pricing", "feature_auto_promotions",
            "feature_telegram_notifications", "is_featured", "badge_text", "trial_days",
            "is_custom_price", "internal_note", "sort_order",
        ]
        data: dict[str, Any] = {f: getattr(source, f) for f in fields_to_copy}
        data["code"] = new_code
        data["name"] = f"{source.name} (копия)"
        data["is_active"] = False   # копия создаётся неактивной
        data["is_public"] = False   # и скрытой
        data["is_featured"] = False

        copy = SubscriptionTier(**data)
        self.session.add(copy)
        await self.session.flush()
        logger.info("tariff_duplicated", extra={"source_id": tariff_id, "copy_id": copy.id})
        return copy

    # ── Переключение статусов ─────────────────────────────────────────────────

    async def toggle_tariff(self, tariff_id: int) -> SubscriptionTier | None:
        """Переключает is_active."""
        tariff = await self.session.get(SubscriptionTier, tariff_id)
        if not tariff:
            return None
        tariff.is_active = not tariff.is_active
        await self.session.flush()
        logger.info("tariff_toggled", extra={"tariff_id": tariff.id, "is_active": tariff.is_active})
        return tariff

    async def toggle_public(self, tariff_id: int) -> SubscriptionTier | None:
        """Переключает is_public."""
        tariff = await self.session.get(SubscriptionTier, tariff_id)
        if not tariff:
            return None
        tariff.is_public = not tariff.is_public
        await self.session.flush()
        logger.info("tariff_public_toggled", extra={"tariff_id": tariff.id, "is_public": tariff.is_public})
        return tariff

    # ── Удаление ──────────────────────────────────────────────────────────────

    async def delete_tariff(self, tariff_id: int) -> None:
        """Удаляет тариф. Raises ValueError если есть активные пользователи."""
        if await self.has_active_subscribers(tariff_id):
            count = await self.get_tariff_user_count(tariff_id)
            raise ValueError(f"Нельзя удалить тариф: {count} активных пользователей")
        tariff = await self.session.get(SubscriptionTier, tariff_id)
        if tariff:
            await self.session.delete(tariff)
            await self.session.flush()
            logger.info("tariff_deleted", extra={"tariff_id": tariff_id})

    # ── Изменение порядка ─────────────────────────────────────────────────────

    async def move_tariff(self, tariff_id: int, direction: str) -> bool:
        """
        Меняет местами sort_order текущего тарифа с соседним.
        direction: "up" или "down".
        Возвращает True если перемещение выполнено.
        """
        tariffs = await self.get_all_tariffs()
        ids = [t.id for t in tariffs]
        if tariff_id not in ids:
            return False
        idx = ids.index(tariff_id)
        if direction == "up" and idx > 0:
            other = tariffs[idx - 1]
        elif direction == "down" and idx < len(tariffs) - 1:
            other = tariffs[idx + 1]
        else:
            return False
        current = tariffs[idx]
        # Меняем sort_order местами
        current.sort_order, other.sort_order = other.sort_order, current.sort_order
        # Если sort_order совпадает — используем ID как тай-брейкер
        if current.sort_order == other.sort_order:
            if direction == "up":
                current.sort_order -= 1
            else:
                current.sort_order += 1
        await self.session.flush()
        return True

    # ── Статические утилиты ───────────────────────────────────────────────────

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
        if tariff.price_monthly and tariff.price_monthly > 0:
            periods["monthly"] = tariff.price_monthly
        if tariff.price_3_months and tariff.price_3_months > 0:
            periods["3_months"] = tariff.price_3_months
        if tariff.price_6_months and tariff.price_6_months > 0:
            periods["6_months"] = tariff.price_6_months
        if tariff.price_yearly and tariff.price_yearly > 0:
            periods["yearly"] = tariff.price_yearly
        return periods

    @staticmethod
    def check_feature_access(tariff: SubscriptionTier, feature_field: str) -> bool:
        return bool(getattr(tariff, feature_field, False))
