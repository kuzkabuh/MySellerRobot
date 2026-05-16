"""version: 1.1.0
description: Telegram admin diagnostics for users, accounts, sync jobs, orders, and sale events.
updated: 2026-05-14
"""

from datetime import UTC, date, datetime, timedelta
from html import escape
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, Order, SalesEvent, SyncJob, User
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
            lines.append(f"— {created_at:%d.%m %H:%M}: {_safe_text(username or telegram_id)}")
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

    async def wildberries_diagnostics_text(self) -> str:
        today = datetime.now(tz=UTC).date()
        yesterday = today - timedelta(days=1)
        account = (
            await self.session.execute(
                select(MarketplaceAccount)
                .where(MarketplaceAccount.marketplace == Marketplace.WB)
                .where(MarketplaceAccount.is_active.is_(True))
                .order_by(MarketplaceAccount.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        today_orders = await self._orders_on_local_day(Marketplace.WB, today)
        yesterday_orders = await self._orders_on_local_day(Marketplace.WB, yesterday)
        latest = (
            await self.session.execute(
                select(Order)
                .where(Order.marketplace == Marketplace.WB)
                .order_by(Order.order_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        lines = ["🧪 Диагностика Wildberries", ""]
        if account is None:
            lines.append("Активных WB-кабинетов нет.")
            return "\n".join(lines)
        lines.extend(
            [
                f"Кабинет: {_safe_text(account.name)}",
                f"Последняя успешная синхронизация: {self._dt(account.last_success_sync_at)}",
                f"Последняя ошибка: {_safe_text(account.last_error_message, 'нет')}",
                f"Заказов сегодня в БД: {today_orders}",
                f"Заказов вчера в БД: {yesterday_orders}",
            ]
        )
        if latest:
            lines.extend(
                [
                    "",
                    "Последний WB-заказ в БД:",
                    f"— дата: {self._dt(latest.order_date)}",
                    f"— external_id: {latest.order_external_id}",
                    f"— статус: {latest.status}",
                ]
            )
        return "\n".join(lines)

    async def event_diagnostics_text(self) -> str:
        since = datetime.now(tz=UTC) - timedelta(days=1)
        latest_wb_sale = await self._latest_sale(Marketplace.WB)
        latest_ozon_sale = await self._latest_sale(Marketplace.OZON)
        sent_today = await self._scalar(
            select(func.count(SalesEvent.id)).where(SalesEvent.notification_sent_at >= since)
        )
        pending = await self._scalar(
            select(func.count(SalesEvent.id)).where(SalesEvent.notification_sent_at.is_(None))
        )
        return "\n".join(
            [
                "🧪 Диагностика событий",
                "",
                f"Последний выкуп WB: {self._sale_line(latest_wb_sale)}",
                f"Последняя завершённая продажа Ozon: {self._sale_line(latest_ozon_sale)}",
                f"Уведомлений о выкупах за 24 часа: {sent_today}",
                f"Ожидают уведомления: {pending}",
            ]
        )

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

    async def _orders_on_local_day(self, marketplace: Marketplace, day: date) -> int:
        result = await self.session.execute(
            select(func.count(Order.id))
            .where(Order.marketplace == marketplace)
            .where(func.date(func.timezone("Europe/Moscow", Order.order_date)) == day)
        )
        return int(result.scalar_one() or 0)

    async def _latest_sale(self, marketplace: Marketplace) -> SalesEvent | None:
        return (
            await self.session.execute(
                select(SalesEvent)
                .where(SalesEvent.marketplace == marketplace)
                .order_by(SalesEvent.event_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    @staticmethod
    def _dt(value: datetime | None) -> str:
        return value.strftime("%d.%m.%Y %H:%M") if value else "нет"

    @staticmethod
    def _sale_line(value: SalesEvent | None) -> str:
        if value is None:
            return "нет"
        return f"{value.event_date:%d.%m %H:%M}, {value.external_event_id}, {value.amount} ₽"

    async def _users_with_marketplace(self, marketplace: Marketplace) -> int:
        return await self._scalar(
            select(func.count(func.distinct(MarketplaceAccount.user_id)))
            .where(MarketplaceAccount.marketplace == marketplace)
            .where(MarketplaceAccount.is_active.is_(True))
        )

    async def _scalar(self, statement: Any) -> int:
        result = await self.session.execute(statement)
        return int(result.scalar_one() or 0)


def _safe_text(value: object | None, fallback: str = "н/д") -> str:
    if value is None or value == "":
        return fallback
    return escape(str(value), quote=False)
