"""version: 1.1.0
description: FBS deadline control and formatted risk alert service.
updated: 2026-05-17
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters.common import format_fbs_deadline_alert
from app.models.domain import AlertEvent, Order
from app.models.enums import AlertType
from app.repositories.orders import OrderRepository


class FbsControlService:
    """Find FBS orders close to deadline and create idempotent alert events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.orders = OrderRepository(session)

    async def collect_deadline_risks(self, user_id: int | None = None) -> list[Order]:
        return await self.orders.fbs_deadline_risks(user_id=user_id)

    async def create_deadline_alerts(self) -> int:
        risks = await self.collect_deadline_risks()
        created = 0
        for order in risks:
            deadline = order.processing_deadline_at or order.deadline_at
            if deadline is None:
                continue
            key = f"fbs_deadline:{order.id}:{deadline:%Y%m%d%H%M}"
            exists = await self._alert_exists(key)
            if exists:
                continue
            self.session.add(
                AlertEvent(
                    user_id=order.user_id,
                    rule_id=None,
                    alert_type=AlertType.FBS_DEADLINE_RISK,
                    idempotency_key=key,
                    title="Риск просрочки FBS",
                    message=self.format_deadline_alert([order]),
                    payload={"order_id": order.id},
                    sent_at=None,
                    resolved_at=None,
                )
            )
            created += 1
        await self.session.commit()
        return created

    def format_deadline_alert(self, orders: list[Order]) -> str:
        return format_fbs_deadline_alert(orders)

    async def _alert_exists(self, idempotency_key: str) -> bool:
        from sqlalchemy import select

        result = await self.session.execute(
            select(AlertEvent.id).where(AlertEvent.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none() is not None
