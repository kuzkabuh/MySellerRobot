"""version: 1.0.0
description: Notification policy resolution for FBO, FBS, and rFBS order events.
updated: 2026-05-14
"""

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, NotificationSetting
from app.models.enums import FboNotificationMode, NotificationType, SaleModel


@dataclass(frozen=True, slots=True)
class OrderNotificationPolicy:
    """Resolved order notification settings for one marketplace account."""

    fbs_enabled: bool = True
    rfbs_enabled: bool = True
    fbo_enabled: bool = True
    fbo_mode: FboNotificationMode = FboNotificationMode.DIGEST_30_MIN
    fbs_deadline_enabled: bool = True
    rfbs_deadline_enabled: bool = True

    def is_instant_enabled_for(self, sale_model: SaleModel | None) -> bool:
        if sale_model == SaleModel.FBO:
            return self.fbo_enabled and self.fbo_mode == FboNotificationMode.INSTANT
        if sale_model == SaleModel.RFBS:
            return self.rfbs_enabled
        if sale_model in {SaleModel.FBS, SaleModel.DBS, SaleModel.DBW, None}:
            return self.fbs_enabled
        return True

    def should_queue_fbo_digest(self, sale_model: SaleModel | None) -> bool:
        return (
            sale_model == SaleModel.FBO
            and self.fbo_enabled
            and self.fbo_mode == FboNotificationMode.DIGEST_30_MIN
        )


class OrderNotificationPolicyService:
    """Build order notification policy from account JSON and normalized settings rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(self, account: MarketplaceAccount) -> OrderNotificationPolicy:
        raw = dict(account.notification_settings or {})
        result = await self.session.execute(
            select(NotificationSetting).where(
                NotificationSetting.user_id == account.user_id,
                or_(
                    NotificationSetting.marketplace_account_id == account.id,
                    NotificationSetting.marketplace_account_id.is_(None),
                ),
                NotificationSetting.notification_type.in_(
                    [
                        NotificationType.NEW_ORDER,
                        NotificationType.ORDER_FBS,
                        NotificationType.ORDER_RFBS,
                        NotificationType.ORDER_FBO,
                        NotificationType.FBO_DIGEST,
                        NotificationType.FBS_CONTROL,
                    ]
                ),
            )
        )
        rows = list(result.scalars().all())
        return self.from_sources(raw, rows)

    @classmethod
    def from_sources(
        cls,
        raw: dict[str, Any] | None = None,
        rows: list[NotificationSetting] | None = None,
    ) -> OrderNotificationPolicy:
        settings = raw or {}
        global_orders_enabled = cls._bool(settings, "new_order_enabled", True)
        fbo_mode = cls._fbo_mode(settings.get("fbo_notification_mode"))
        policy = OrderNotificationPolicy(
            fbs_enabled=global_orders_enabled and cls._bool(settings, "order_fbs_enabled", True),
            rfbs_enabled=global_orders_enabled and cls._bool(settings, "order_rfbs_enabled", True),
            fbo_enabled=global_orders_enabled and cls._bool(settings, "order_fbo_enabled", True),
            fbo_mode=fbo_mode,
            fbs_deadline_enabled=cls._bool(settings, "fbs_deadline_enabled", True),
            rfbs_deadline_enabled=cls._bool(settings, "rfbs_deadline_enabled", True),
        )
        for row in rows or []:
            policy = cls._apply_row(policy, row)
        return policy

    @staticmethod
    def _apply_row(
        policy: OrderNotificationPolicy,
        row: NotificationSetting,
    ) -> OrderNotificationPolicy:
        values = asdict(policy)
        if row.notification_type == NotificationType.NEW_ORDER and not row.is_enabled:
            values.update(fbs_enabled=False, rfbs_enabled=False, fbo_enabled=False)
        if row.notification_type == NotificationType.ORDER_FBS:
            values["fbs_enabled"] = row.is_enabled
        if row.notification_type == NotificationType.ORDER_RFBS:
            values["rfbs_enabled"] = row.is_enabled
        if row.notification_type == NotificationType.ORDER_FBO:
            values["fbo_enabled"] = row.is_enabled
            values["fbo_mode"] = OrderNotificationPolicyService._fbo_mode(
                row.settings.get("mode") if row.settings else None,
                fallback=policy.fbo_mode,
            )
        if row.notification_type == NotificationType.FBO_DIGEST and not row.is_enabled:
            values["fbo_mode"] = FboNotificationMode.DAILY_ONLY
        if row.notification_type == NotificationType.FBS_CONTROL:
            values["fbs_deadline_enabled"] = row.is_enabled
            values["rfbs_deadline_enabled"] = row.is_enabled
        return OrderNotificationPolicy(**values)

    @staticmethod
    def _bool(settings: dict[str, Any], key: str, default: bool) -> bool:
        value = settings.get(key, default)
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on", "да"}
        return bool(value)

    @staticmethod
    def _fbo_mode(
        value: Any,
        fallback: FboNotificationMode = FboNotificationMode.DIGEST_30_MIN,
    ) -> FboNotificationMode:
        if value is None:
            return fallback
        try:
            return FboNotificationMode(str(value))
        except ValueError:
            return fallback
