"""version: 1.0.0
description: FBO order digest queue aggregation and Russian message formatting.
updated: 2026-05-14
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import FboDigestQueue, User
from app.models.enums import Marketplace
from app.repositories.orders import FboDigestQueueRepository
from app.services.common.message_formatter import rub


@dataclass(slots=True)
class FboDigestNotification:
    user_id: int
    telegram_id: int
    row_ids: list[int]
    text: str


class FboDigestService:
    """Create user-level FBO digest notifications from queued order rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.queue = FboDigestQueueRepository(session)

    async def collect_pending(self) -> list[FboDigestNotification]:
        rows = await self.queue.pending_digest_rows()
        if not rows:
            return []
        telegram_ids = await self._telegram_ids({row.user_id for row in rows})
        grouped: dict[int, list[FboDigestQueue]] = defaultdict(list)
        for row in rows:
            grouped[row.user_id].append(row)
        notifications: list[FboDigestNotification] = []
        for user_id, user_rows in grouped.items():
            telegram_id = telegram_ids.get(user_id)
            if telegram_id is None:
                continue
            notifications.append(
                FboDigestNotification(
                    user_id=user_id,
                    telegram_id=telegram_id,
                    row_ids=[row.id for row in user_rows],
                    text=self.format_digest(user_rows),
                )
            )
        return notifications

    async def mark_sent(self, row_ids: list[int]) -> None:
        await self.queue.mark_sent(row_ids)
        await self.session.commit()

    @staticmethod
    def format_digest(rows: list[FboDigestQueue]) -> str:
        by_marketplace: dict[Marketplace, dict[str, Decimal | int]] = defaultdict(
            lambda: {"orders": 0, "revenue": Decimal("0"), "profit": Decimal("0")}
        )
        for row in rows:
            bucket = by_marketplace[row.marketplace]
            bucket["orders"] = int(bucket["orders"]) + 1
            bucket["revenue"] = Decimal(str(bucket["revenue"])) + Decimal(str(row.revenue or 0))
            bucket["profit"] = Decimal(str(bucket["profit"])) + Decimal(
                str(row.estimated_profit or 0)
            )

        total_orders = sum(int(bucket["orders"]) for bucket in by_marketplace.values())
        total_revenue = sum(
            (Decimal(str(bucket["revenue"])) for bucket in by_marketplace.values()),
            Decimal("0"),
        )
        total_profit = sum(
            (Decimal(str(bucket["profit"])) for bucket in by_marketplace.values()),
            Decimal("0"),
        )
        lines = ["🛒 Новые FBO-заказы за последние 30 минут", ""]
        for marketplace in [Marketplace.WB, Marketplace.OZON]:
            if marketplace not in by_marketplace:
                continue
            bucket = by_marketplace[marketplace]
            title = "Wildberries" if marketplace == Marketplace.WB else "Ozon"
            lines.extend(
                [
                    f"{title}:",
                    f"— {bucket['orders']} заказов на {rub(Decimal(str(bucket['revenue'])))}",
                    f"— Плановая прибыль: {rub(Decimal(str(bucket['profit'])))}",
                    "",
                ]
            )
        lines.extend(
            [
                "Всего:",
                f"— {total_orders} заказов",
                f"— Выручка: {rub(total_revenue)}",
                f"— Плановая прибыль: {rub(total_profit)}",
            ]
        )
        return "\n".join(lines)

    async def _telegram_ids(self, user_ids: set[int]) -> dict[int, int]:
        if not user_ids:
            return {}
        result = await self.session.execute(
            select(User.id, User.telegram_id).where(User.id.in_(user_ids))
        )
        return {int(user_id): int(telegram_id) for user_id, telegram_id in result.all()}
