"""version: 1.0.0
description: FBS deadline control and risk alert service.
updated: 2026-05-14
"""

from datetime import UTC

from sqlalchemy.ext.asyncio import AsyncSession

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
            key = f"fbs_deadline:{order.id}:{order.deadline_at:%Y%m%d%H%M}"
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
        if not orders:
            return "FBS-заказов с риском просрочки нет."
        lines = ["🚨 Риск просрочки FBS", ""]
        for order in orders[:10]:
            deadline = order.deadline_at.astimezone(UTC) if order.deadline_at else None
            deadline_text = deadline.strftime("%d.%m.%Y %H:%M") if deadline else "н/д"
            lines.append(
                f"{order.marketplace.value}: заказ {order.order_external_id}, "
                f"обработать до {deadline_text}"
            )
        if len(orders) > 10:
            lines.append(f"И ещё заказов: {len(orders) - 10}")
        return "\n".join(lines)

    async def _alert_exists(self, idempotency_key: str) -> bool:
        from sqlalchemy import select

        result = await self.session.execute(
            select(AlertEvent.id).where(AlertEvent.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none() is not None
