"""version: 1.0.0
description: User-facing sync status tracking service.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import SyncStatus

logger = logging.getLogger(__name__)

SYNC_TYPES = [
    ("orders", "Заказы"),
    ("sales", "Продажи и выкупы"),
    ("stocks", "Остатки"),
    ("products", "Товары и карточки"),
    ("prices", "Цены"),
    ("commissions", "Комиссии"),
    ("financial_reports", "Финансовые отчёты"),
    ("auto_promotions", "Автоакции"),
    ("reviews", "Отзывы и вопросы"),
]

SYNC_TYPE_LABELS = dict(SYNC_TYPES)


@dataclass
class SyncStatusData:
    sync_type: str
    sync_type_label: str
    status: str
    last_run_at: datetime | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error_message: str | None
    items_processed: int | None
    duration_seconds: float | None


class UserSyncStatusService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_statuses(
        self, user_id: int, account_id: int | None = None
    ) -> list[SyncStatusData]:
        stmt = select(SyncStatus).where(SyncStatus.user_id == user_id)
        if account_id is not None:
            stmt = stmt.where(SyncStatus.account_id == account_id)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        existing_types = {r.sync_type for r in rows}
        all_statuses = []
        for row in rows:
            all_statuses.append(
                SyncStatusData(
                    sync_type=row.sync_type,
                    sync_type_label=SYNC_TYPE_LABELS.get(row.sync_type, row.sync_type),
                    status=row.status,
                    last_run_at=row.last_run_at,
                    last_success_at=row.last_success_at,
                    last_error_at=row.last_error_at,
                    last_error_message=row.last_error_message,
                    items_processed=row.items_processed,
                    duration_seconds=float(row.duration_seconds) if row.duration_seconds else None,
                )
            )

        for code, label in SYNC_TYPES:
            if code not in existing_types:
                all_statuses.append(
                    SyncStatusData(
                        sync_type=code,
                        sync_type_label=label,
                        status="pending",
                        last_run_at=None,
                        last_success_at=None,
                        last_error_at=None,
                        last_error_message=None,
                        items_processed=None,
                        duration_seconds=None,
                    )
                )

        return all_statuses

    async def update_status(
        self,
        user_id: int,
        sync_type: str,
        status: str,
        account_id: int | None = None,
        items_processed: int | None = None,
        duration_seconds: float | None = None,
        error_message: str | None = None,
    ) -> SyncStatus:
        stmt = select(SyncStatus).where(
            SyncStatus.user_id == user_id,
            SyncStatus.account_id == account_id,
            SyncStatus.sync_type == sync_type,
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()

        now = datetime.now(UTC)
        if row is None:
            row = SyncStatus(
                user_id=user_id,
                account_id=account_id,
                sync_type=sync_type,
                status=status,
                last_run_at=now,
            )
            self.session.add(row)
        else:
            row.status = status
            row.last_run_at = now

        if status == "success":
            row.last_success_at = now
            row.last_error_at = None
            row.last_error_message = None
        elif status == "error":
            row.last_error_at = now
            row.last_error_message = error_message[:2000] if error_message else None

        if items_processed is not None:
            row.items_processed = items_processed
        if duration_seconds is not None:
            row.duration_seconds = duration_seconds

        await self.session.commit()
        await self.session.refresh(row)
        return row


SYNC_STATUS_LABELS = {
    "pending": "Ожидает",
    "running": "Выполняется",
    "success": "Успешно",
    "error": "Ошибка",
    "skipped": "Пропущено",
}
