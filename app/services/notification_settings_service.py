"""version: 1.0.0
description: Per-type user notification settings service.
updated: 2026-06-07
"""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import NotificationSetting
from app.models.enums import NotificationType

DEFAULT_ENABLED_TYPES: frozenset[NotificationType] = frozenset(
    {
        NotificationType.NEW_ORDER,
        NotificationType.ORDER_FBS,
        NotificationType.ORDER_RFBS,
        NotificationType.ORDER_FBO,
        NotificationType.FBO_DIGEST,
        NotificationType.SALE_COMPLETED,
        NotificationType.SALE_DIGEST,
        NotificationType.ORDER_CANCELLED,
        NotificationType.RETURN_CREATED,
        NotificationType.DAILY_REPORT,
        NotificationType.FBS_CONTROL,
        NotificationType.STOCK_ALERT,
        NotificationType.PROFIT_ALERT,
    }
)

TYPE_LABELS: dict[NotificationType, str] = {
    NotificationType.NEW_ORDER: "Новые заказы",
    NotificationType.ORDER_FBS: "Заказы FBS",
    NotificationType.ORDER_RFBS: "Заказы rFBS",
    NotificationType.ORDER_FBO: "Заказы FBO",
    NotificationType.FBO_DIGEST: "Дайджест FBO",
    NotificationType.SALE_COMPLETED: "Продажи и выкупы",
    NotificationType.SALE_DIGEST: "Дайджест продаж",
    NotificationType.ORDER_CANCELLED: "Отмены заказов",
    NotificationType.RETURN_CREATED: "Возвраты",
    NotificationType.DAILY_REPORT: "Ежедневный отчёт",
    NotificationType.FBS_CONTROL: "FBS-дедлайны",
    NotificationType.STOCK_ALERT: "Низкие остатки и out-of-stock",
    NotificationType.PROFIT_ALERT: "Алерты по марже",
}

TYPE_DESCRIPTIONS: dict[NotificationType, str] = {
    NotificationType.NEW_ORDER: "Мгновенное уведомление о новом заказе FBS/FBO",
    NotificationType.ORDER_FBS: "Заказы, требующие сборки и отгрузки",
    NotificationType.ORDER_RFBS: "Заказы со склада продавца (rFBS)",
    NotificationType.ORDER_FBO: "Заказы со складов WB",
    NotificationType.FBO_DIGEST: "Сводка по FBO-заказам каждые 30 минут",
    NotificationType.SALE_COMPLETED: "Сообщения о завершённых продажах и выкупах",
    NotificationType.SALE_DIGEST: "Сводка по продажам за период",
    NotificationType.ORDER_CANCELLED: "Уведомление об отмене заказа покупателем",
    NotificationType.RETURN_CREATED: "Уведомление о новом возврате",
    NotificationType.DAILY_REPORT: "Ежедневный отчёт по продажам и прибыли",
    NotificationType.FBS_CONTROL: "Предупреждения о приближающихся FBS-дедлайнах",
    NotificationType.STOCK_ALERT: "Низкие остатки и прогноз out-of-stock",
    NotificationType.PROFIT_ALERT: "Убыточные заказы и резкое падение маржи",
}


class NotificationSettingsService:
    """Read and write per-type notification settings for a user."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_settings(
        self,
        user_id: int,
        *,
        marketplace_account_id: int | None = None,
    ) -> dict[NotificationType, bool]:
        """Return a map of NotificationType -> enabled for the given user.

        Для account-настроек сначала применяются системные значения,
        затем глобальные пользовательские настройки и только потом account override.
        """
        defaults: dict[NotificationType, bool] = {
            t: t in DEFAULT_ENABLED_TYPES for t in NotificationType
        }
        for row in await self._load_settings_rows(user_id, marketplace_account_id=None):
            defaults[NotificationType(row.notification_type)] = bool(row.is_enabled)
        if marketplace_account_id is not None:
            for row in await self._load_settings_rows(
                user_id, marketplace_account_id=marketplace_account_id
            ):
                defaults[NotificationType(row.notification_type)] = bool(row.is_enabled)
        return defaults

    async def update_user_settings(
        self,
        user_id: int,
        *,
        enabled_types: Iterable[NotificationType],
    ) -> None:
        """Persist the user's per-type global (account=None) settings."""
        enabled_set = set(enabled_types)
        for notification_type in NotificationType:
            setting = await self._get_or_create_setting(
                user_id=user_id,
                notification_type=notification_type,
                marketplace_account_id=None,
            )
            setting.is_enabled = notification_type in enabled_set
        await self.session.commit()

    async def get_or_create_for_account(
        self,
        user_id: int,
        marketplace_account_id: int,
    ) -> dict[NotificationType, bool]:
        """Return per-account settings, falling back to the global default."""
        return await self.get_user_settings(user_id, marketplace_account_id=marketplace_account_id)

    async def is_type_enabled(
        self,
        user_id: int,
        notification_type: NotificationType,
    ) -> bool:
        if notification_type not in DEFAULT_ENABLED_TYPES:
            return False
        settings = await self.get_user_settings(user_id)
        return settings.get(notification_type, notification_type in DEFAULT_ENABLED_TYPES)

    async def _get_or_create_setting(
        self,
        *,
        user_id: int,
        notification_type: NotificationType,
        marketplace_account_id: int | None,
    ) -> NotificationSetting:
        stmt = select(NotificationSetting).where(
            NotificationSetting.user_id == user_id,
            NotificationSetting.notification_type == notification_type.value,
            NotificationSetting.marketplace_account_id.is_(marketplace_account_id)
            if marketplace_account_id is None
            else NotificationSetting.marketplace_account_id == marketplace_account_id,
        )
        result = await self.session.execute(stmt)
        setting = result.scalar_one_or_none()
        if setting is not None:
            return setting
        setting = NotificationSetting(
            user_id=user_id,
            notification_type=notification_type,
            marketplace_account_id=marketplace_account_id,
            is_enabled=notification_type in DEFAULT_ENABLED_TYPES,
        )
        self.session.add(setting)
        await self.session.flush()
        return setting

    async def _load_settings_rows(
        self,
        user_id: int,
        *,
        marketplace_account_id: int | None,
    ) -> list[NotificationSetting]:
        stmt = select(NotificationSetting).where(NotificationSetting.user_id == user_id)
        if marketplace_account_id is None:
            stmt = stmt.where(NotificationSetting.marketplace_account_id.is_(None))
        else:
            stmt = stmt.where(NotificationSetting.marketplace_account_id == marketplace_account_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
