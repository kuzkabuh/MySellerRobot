"""version: 1.0.0
description: Telegram admin diagnostics for users, accounts, sync jobs, and order polling.
updated: 2026-05-14
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, Order, SyncJob, User
from app.models.enums import AccountStatus, Marketplace, SyncJobStatus


class AdminService:
    """Build concise operational diagnostics for Telegram admins."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def users_text(self) -> str:
        total = await self._scalar(select(func.count(User.id)))
        active = await self._scalar(select(func.count(User.id)).where(User.status == "ACTIVE"))
        wb_users = await self._users_with_marketplace(Marketplace.WB)
        ozon_users = await self._users_with_marketplace(Marketplace.OZON)
        recent = await self.session.execute(
            select(User.telegram_id, User.username, User.created_at)
            .order_by(User.created_at.desc())
            .limit(5)
        )
        lines = [
            "👥 Пользователи",
            "",
            f"Всего: {total}",
            f"Активных: {active}",
            f"С WB: {wb_users}",
            f"С Ozon: {ozon_users}",
            "",
            "Последние регистрации:",
        ]
        for telegram_id, username, created_at in recent.all():
            lines.append(f"— {created_at:%d.%m %H:%M}: {username or telegram_id}")
        return "\n".join(lines)

    async def accounts_text(self) -> str:
        rows = await self.session.execute(
            select(
                MarketplaceAccount.marketplace,
                func.count(MarketplaceAccount.id),
                func.count(MarketplaceAccount.id).filter(
                    MarketplaceAccount.status == AccountStatus.ERROR
                ),
            )
            .where(MarketplaceAccount.is_active.is_(True))
            .group_by(MarketplaceAccount.marketplace)
        )
        by_marketplace = {marketplace: (count, errors) for marketplace, count, errors in rows.all()}
        return "\n".join(
            [
                "🏪 Подключённые кабинеты",
                "",
                f"Wildberries: {by_marketplace.get(Marketplace.WB, (0, 0))[0]}",
                f"Ozon: {by_marketplace.get(Marketplace.OZON, (0, 0))[0]}",
                f"С ошибками: {sum(int(item[1] or 0) for item in by_marketplace.values())}",
            ]
        )

    async def sync_jobs_text(self) -> str:
        rows = await self.session.execute(
            select(
                SyncJob.id,
                SyncJob.marketplace,
                SyncJob.job_type,
                SyncJob.status,
                SyncJob.created_at,
            )
            .order_by(SyncJob.created_at.desc())
            .limit(8)
        )
        lines = ["🔄 Синхронизации", ""]
        for job_id, marketplace, job_type, status, created_at in rows.all():
            title = marketplace.value if marketplace else "н/д"
            lines.append(f"#{job_id} {title} {job_type}: {status.value} ({created_at:%d.%m %H:%M})")
        if len(lines) == 2:
            lines.append("Задач пока нет.")
        failed = await self._scalar(
            select(func.count(SyncJob.id)).where(
                SyncJob.status.in_(
                    [
                        SyncJobStatus.FAILED,
                        SyncJobStatus.ERROR,
                        SyncJobStatus.COMPLETED_WITH_WARNINGS,
                    ]
                )
            )
        )
        lines.extend(["", f"Проблемных задач: {failed}"])
        return "\n".join(lines)

    async def order_diagnostics_text(self) -> str:
        since = datetime.now(tz=UTC) - timedelta(days=1)
        rows = await self.session.execute(
            select(
                Order.marketplace,
                func.count(Order.id).filter(Order.created_at >= since),
                func.max(Order.created_at),
                func.count(Order.id).filter(Order.first_notified_at.is_not(None)),
            ).group_by(Order.marketplace)
        )
        lines = ["🧪 Диагностика заказов", ""]
        by_marketplace = {marketplace: row for marketplace, *row in rows.all()}
        for marketplace in [Marketplace.WB, Marketplace.OZON]:
            created, latest, notified = by_marketplace.get(marketplace, (0, None, 0))
            latest_text = latest.strftime("%d.%m %H:%M") if latest else "нет"
            lines.extend(
                [
                    f"{marketplace.value}:",
                    f"— создано за 24 часа: {created}",
                    f"— последний заказ в БД: {latest_text}",
                    f"— заказов с отметкой уведомления: {notified}",
                ]
            )
        return "\n".join(lines)

    async def system_text(self) -> str:
        users = await self._scalar(select(func.count(User.id)))
        accounts = await self._scalar(
            select(func.count(MarketplaceAccount.id)).where(MarketplaceAccount.is_active.is_(True))
        )
        orders = await self._scalar(select(func.count(Order.id)))
        jobs_pending = await self._scalar(
            select(func.count(SyncJob.id)).where(SyncJob.status == SyncJobStatus.PENDING)
        )
        return "\n".join(
            [
                "📊 Системная статистика",
                "",
                f"Пользователей: {users}",
                f"Активных кабинетов: {accounts}",
                f"Заказов в БД: {orders}",
                f"Ожидающих sync-задач: {jobs_pending}",
            ]
        )

    async def _users_with_marketplace(self, marketplace: Marketplace) -> int:
        return await self._scalar(
            select(func.count(func.distinct(MarketplaceAccount.user_id)))
            .where(MarketplaceAccount.marketplace == marketplace)
            .where(MarketplaceAccount.is_active.is_(True))
        )

    async def _scalar(self, statement: Any) -> int:
        result = await self.session.execute(statement)
        return int(result.scalar_one() or 0)
