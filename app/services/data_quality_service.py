"""version: 1.0.0
description: Data quality diagnostics for marketplace sync, costs, orders, and API errors.
updated: 2026-05-15
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import ApiRequestLog, MarketplaceAccount, Order, OrderItem, SyncJob
from app.models.enums import AccountStatus, SyncJobStatus


@dataclass(slots=True)
class DataQualityMetric:
    title: str
    value: int
    status: str
    description: str


@dataclass(slots=True)
class DataQualityReport:
    score: int
    metrics: list[DataQualityMetric]
    recommendations: list[str]


class DataQualityService:
    """Build a compact quality report for data completeness and sync health."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def report(self, *, user_id: int) -> DataQualityReport:
        missing_cost = await self._missing_cost_items(user_id)
        missing_commission = await self._missing_commission_items(user_id)
        failed_jobs = await self._failed_jobs(user_id)
        api_errors = await self._api_errors()
        stale_accounts = await self._stale_accounts(user_id)
        metrics = [
            _metric(
                "Позиции без себестоимости",
                missing_cost,
                "critical" if missing_cost else "ok",
                "Без себестоимости прибыль считается неполной.",
            ),
            _metric(
                "Позиции без комиссии",
                missing_commission,
                "warning" if missing_commission else "ok",
                "Комиссия нужна для корректной юнит-экономики.",
            ),
            _metric(
                "Ошибки синхронизации",
                failed_jobs,
                "critical" if failed_jobs else "ok",
                "Проверьте ключи API и доступность маркетплейсов.",
            ),
            _metric(
                "Ошибки API за сутки",
                api_errors,
                "warning" if api_errors else "ok",
                "Рост ошибок API может задерживать аналитику.",
            ),
            _metric(
                "Кабинеты без свежей синхронизации",
                stale_accounts,
                "warning" if stale_accounts else "ok",
                "Данные могут устареть, если кабинет давно не синхронизировался.",
            ),
        ]
        penalties = sum(_penalty(metric) for metric in metrics)
        score = max(0, 100 - penalties)
        recommendations = _recommendations(metrics)
        return DataQualityReport(score=score, metrics=metrics, recommendations=recommendations)

    async def _missing_cost_items(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count(OrderItem.id))
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.user_id == user_id)
            .where((OrderItem.cost_price_used.is_(None)) | (OrderItem.cost_price_used == 0))
        )
        return int(result.scalar_one() or 0)

    async def _missing_commission_items(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count(OrderItem.id))
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.user_id == user_id)
            .where(OrderItem.commission_estimated.is_(None))
        )
        return int(result.scalar_one() or 0)

    async def _failed_jobs(self, user_id: int) -> int:
        since = datetime.now(tz=UTC) - timedelta(days=7)
        result = await self.session.execute(
            select(func.count(SyncJob.id))
            .where(SyncJob.user_id == user_id)
            .where(SyncJob.status.in_([SyncJobStatus.FAILED, SyncJobStatus.ERROR]))
            .where(SyncJob.created_at >= since)
        )
        return int(result.scalar_one() or 0)

    async def _api_errors(self) -> int:
        since = datetime.now(tz=UTC) - timedelta(days=1)
        result = await self.session.execute(
            select(func.count(ApiRequestLog.id))
            .where(ApiRequestLog.created_at >= since)
            .where((ApiRequestLog.error_message.is_not(None)) | (ApiRequestLog.status_code >= 400))
        )
        return int(result.scalar_one() or 0)

    async def _stale_accounts(self, user_id: int) -> int:
        threshold = datetime.now(tz=UTC) - timedelta(hours=24)
        result = await self.session.execute(
            select(func.count(MarketplaceAccount.id))
            .where(MarketplaceAccount.user_id == user_id)
            .where(MarketplaceAccount.status == AccountStatus.ACTIVE)
            .where(
                (MarketplaceAccount.last_success_sync_at.is_(None))
                | (MarketplaceAccount.last_success_sync_at < threshold)
            )
        )
        return int(result.scalar_one() or 0)


def _metric(title: str, value: int, status: str, description: str) -> DataQualityMetric:
    return DataQualityMetric(title=title, value=value, status=status, description=description)


def _penalty(metric: DataQualityMetric) -> int:
    if metric.status == "critical":
        return min(35, 10 + metric.value * 2)
    if metric.status == "warning":
        return min(20, 5 + metric.value)
    return 0


def _recommendations(metrics: list[DataQualityMetric]) -> list[str]:
    recommendations = [
        f"{metric.title}: {metric.description}"
        for metric in metrics
        if metric.status in {"warning", "critical"}
    ]
    if not recommendations:
        return ["Критичных проблем с качеством данных не найдено."]
    return recommendations
