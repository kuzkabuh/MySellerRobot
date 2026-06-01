"""version: 1.0.0
description: User activity logging service.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import UserActivityLog

logger = logging.getLogger(__name__)


@dataclass
class ActivityLogEntry:
    id: int
    user_id: int
    action: str
    entity_type: str | None
    entity_id: int | None
    details: dict[str, Any] | None
    ip_address: str | None
    created_at: datetime


class UserActivityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log_activity(
        self,
        user_id: int,
        action: str,
        entity_type: str | None = None,
        entity_id: int | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> UserActivityLog:
        entry = UserActivityLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip_address[:64] if ip_address else None,
            user_agent=user_agent[:512] if user_agent else None,
        )
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def get_recent_activity(
        self, user_id: int, limit: int = 50
    ) -> list[ActivityLogEntry]:
        stmt = (
            select(UserActivityLog)
            .where(UserActivityLog.user_id == user_id)
            .order_by(UserActivityLog.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            ActivityLogEntry(
                id=row.id,
                user_id=row.user_id,
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                details=row.details,
                ip_address=row.ip_address,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def get_activity_for_admin(
        self, user_id: int, limit: int = 200
    ) -> list[ActivityLogEntry]:
        return await self.get_recent_activity(user_id, limit)


ACTION_LABELS: dict[str, str] = {
    "profile_update": "Обновление профиля",
    "api_key_added": "Добавлен API-ключ",
    "api_key_updated": "Обновлён API-ключ",
    "api_key_deleted": "Удалён API-ключ",
    "api_key_checked": "Проверка API-ключa",
    "subscription_created": "Оформлена подписка",
    "subscription_renewed": "Продлена подписка",
    "subscription_cancelled": "Отменена подписка",
    "promo_applied": "Применён промокод",
    "notification_settings_update": "Настройки уведомлений",
    "login": "Вход в систему",
    "logout": "Выход из системы",
    "web_login": "Вход в web-кабинет",
    "account_connected": "Подключён кабинет МП",
    "account_disconnected": "Отключён кабинет МП",
    "sync_triggered": "Запущена синхронизация",
    "support_ticket_created": "Создан тикет поддержки",
    "support_ticket_closed": "Закрыт тикет поддержки",
    "settings_update": "Обновление настроек",
    "cost_update": "Обновление себестоимости",
    "plan_created": "Создан план",
    "plan_deleted": "Удалён план",
}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)
