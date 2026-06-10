"""Sync run management for web cabinet: trigger, track, history, api key verification."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from arq.connections import RedisSettings, create_pool
from redis.asyncio import Redis
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import get_settings
from app.core.redis import redis_settings_from_url
from app.models.domain import MarketplaceAccount, SyncRun, User
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)

SYNC_TYPE_MAP: dict[str, dict[str, Any]] = {
    "products": {
        "task": "sync_products",
        "label": "Товары",
        "description": "Синхронизация товаров",
    },
    "stocks": {
        "task": "check_low_stocks",
        "label": "Остатки",
        "description": "Синхронизация остатков",
    },
    "orders": {
        "task": "poll_new_orders",
        "label": "Заказы",
        "description": "Синхронизация заказов",
    },
    "sales": {
        "task": "sync_sale_events",
        "label": "Продажи",
        "description": "Синхронизация продаж и возвратов",
    },
    "returns": {
        "task": "sync_sale_events",
        "label": "Возвраты",
        "description": "Синхронизация возвратов",
    },
    "profile": {
        "task_wb": "sync_wb_account_profiles",
        "task_ozon": None,
        "label": "Профиль",
        "description": "Синхронизация профиля кабинета",
    },
    "finances": {
        "task_wb": "sync_wb_daily_financial_details",
        "task_ozon": "reconcile_ozon_finance",
        "label": "Финансы",
        "description": "Синхронизация финансов",
    },
    "reports": {
        "task_wb": "check_wb_financial_reports",
        "task_ozon": None,
        "label": "Отчёты",
        "description": "Синхронизация отчётов",
    },
    "logistics": {
        "task_wb": "sync_wb_logistics_tariffs",
        "task_ozon": None,
        "label": "Логистика",
        "description": "Синхронизация тарифов логистики",
    },
    "wb_financial_details": {
        "task_wb": "sync_wb_daily_financial_details",
        "task_ozon": None,
        "label": "Финансовые детализации WB",
        "description": "Синхронизация финансовых детализаций WB",
    },
    "ozon_finances": {
        "task_wb": None,
        "task_ozon": "reconcile_ozon_finance",
        "label": "Финансы Ozon",
        "description": "Синхронизация финансов Ozon",
    },
    "ozon_balance": {
        "task_wb": None,
        "task_ozon": "sync_ozon_balances",
        "label": "Баланс Ozon",
        "description": "Синхронизация баланса Ozon",
    },
    "ozon_enrichment": {
        "task_wb": None,
        "task_ozon": "sync_ozon_catalog_enrichment",
        "label": "Обогащение каталога Ozon",
        "description": "Синхронизация каталога Ozon",
    },
    "wb_promotions": {
        "task_wb": "sync_wb_daily_promotions",
        "task_ozon": None,
        "label": "Акции WB",
        "description": "Синхронизация акций WB",
    },
    "wb_reports": {
        "task_wb": "check_wb_financial_reports",
        "task_ozon": None,
        "label": "Отчёты WB",
        "description": "Проверка финансовых отчётов WB",
    },
}

ALL_SYNC_TYPES = list(SYNC_TYPE_MAP.keys())

WB_SYNC_TYPES = [
    k for k, v in SYNC_TYPE_MAP.items()
    if v.get("task") or v.get("task_wb")
]
OZON_SYNC_TYPES = [
    k for k, v in SYNC_TYPE_MAP.items()
    if v.get("task") or v.get("task_ozon")
]


def _resolve_task(sync_type: str, marketplace: str) -> str | None:
    info = SYNC_TYPE_MAP.get(sync_type)
    if not info:
        return None
    task = info.get("task")
    if task:
        return task
    key = "task_wb" if marketplace == "WB" else "task_ozon"
    return info.get(key)


class WebSyncRunService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_run(
        self,
        user_id: int,
        account_id: int,
        marketplace: str,
        sync_type: str,
        trigger_source: str = "manual",
    ) -> SyncRun:
        run = SyncRun(
            user_id=user_id,
            marketplace_account_id=account_id,
            marketplace=marketplace,
            sync_type=sync_type,
            trigger_source=trigger_source,
            status="queued",
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def mark_started(self, run_id: int) -> SyncRun | None:
        run = await self._get_run(run_id)
        if run is None:
            return None
        run.status = "running"
        run.started_at = datetime.now(tz=UTC)
        await self.session.flush()
        return run

    async def mark_success(
        self,
        run_id: int,
        *,
        records_loaded: int = 0,
        records_created: int = 0,
        records_updated: int = 0,
        records_skipped: int = 0,
    ) -> SyncRun | None:
        run = await self._get_run(run_id)
        if run is None:
            return None
        now = datetime.now(tz=UTC)
        run.status = "success"
        run.finished_at = now
        if run.started_at:
            run.duration_seconds = Decimal(str((now - run.started_at).total_seconds()))
        run.records_loaded = records_loaded
        run.records_created = records_created
        run.records_updated = records_updated
        run.records_skipped = records_skipped
        await self.session.flush()
        return run

    async def mark_failed(
        self,
        run_id: int,
        error_message: str,
        error_code: str | None = None,
    ) -> SyncRun | None:
        run = await self._get_run(run_id)
        if run is None:
            return None
        now = datetime.now(tz=UTC)
        run.status = "error"
        run.finished_at = now
        if run.started_at:
            run.duration_seconds = Decimal(str((now - run.started_at).total_seconds()))
        run.error_message = error_message[:5000]
        run.error_code = error_code
        await self.session.flush()
        return run

    async def get_run(self, run_id: int) -> SyncRun | None:
        return await self._get_run(run_id)

    async def get_run_status(self, run_id: int) -> dict[str, Any] | None:
        run = await self._get_run(run_id)
        if run is None:
            return None
        return {
            "ok": True,
            "run_id": run.id,
            "status": run.status,
            "message": _status_message(run),
            "records_loaded": run.records_loaded,
            "duration_seconds": float(run.duration_seconds) if run.duration_seconds else None,
        }

    async def check_running(self, account_id: int, sync_type: str) -> bool:
        result = await self.session.execute(
            select(func.count(SyncRun.id)).where(
                SyncRun.marketplace_account_id == account_id,
                SyncRun.sync_type == sync_type,
                SyncRun.status.in_(["queued", "running"]),
            )
        )
        count = result.scalar_one() or 0
        return count > 0

    async def history(
        self,
        user_id: int | None = None,
        account_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
        status_filter: str | None = None,
    ) -> list[SyncRun]:
        query = select(SyncRun).options(
            joinedload(SyncRun.account),
        )
        conditions = []
        if user_id is not None:
            conditions.append(SyncRun.user_id == user_id)
        if account_id is not None:
            conditions.append(SyncRun.marketplace_account_id == account_id)
        if status_filter:
            conditions.append(SyncRun.status == status_filter)
        if conditions:
            query = query.where(and_(*conditions))
        query = query.order_by(desc(SyncRun.created_at)).limit(limit).offset(offset)
        result = await self.session.execute(query)
        return list(result.unique().scalars().all())

    async def history_count(
        self,
        user_id: int | None = None,
        account_id: int | None = None,
        status_filter: str | None = None,
    ) -> int:
        query = select(func.count(SyncRun.id))
        conditions = []
        if user_id is not None:
            conditions.append(SyncRun.user_id == user_id)
        if account_id is not None:
            conditions.append(SyncRun.marketplace_account_id == account_id)
        if status_filter:
            conditions.append(SyncRun.status == status_filter)
        if conditions:
            query = query.where(and_(*conditions))
        result = await self.session.execute(query)
        return int(result.scalar_one() or 0)

    async def errors(
        self,
        user_id: int | None = None,
        account_id: int | None = None,
        limit: int = 20,
    ) -> list[SyncRun]:
        query = select(SyncRun).options(
            joinedload(SyncRun.account),
        )
        conditions = [SyncRun.status == "error"]
        if user_id is not None:
            conditions.append(SyncRun.user_id == user_id)
        if account_id is not None:
            conditions.append(SyncRun.marketplace_account_id == account_id)
        query = query.where(and_(*conditions))
        query = query.order_by(desc(SyncRun.created_at)).limit(limit)
        result = await self.session.execute(query)
        return list(result.unique().scalars().all())

    async def trigger_sync(
        self,
        user_id: int,
        account: MarketplaceAccount,
        sync_type: str,
        trigger_source: str = "manual",
    ) -> dict[str, Any]:
        task_name = _resolve_task(sync_type, account.marketplace.value)
        if task_name is None:
            return {
                "ok": False,
                "status": "not_implemented",
                "message": f"Синхронизация «{SYNC_TYPE_MAP.get(sync_type, {}).get('label', sync_type)}» для {account.marketplace.value} пока не реализована.",
            }

        running = await self.check_running(account.id, sync_type)
        if running:
            return {
                "ok": False,
                "status": "already_running",
                "message": f"Синхронизация «{SYNC_TYPE_MAP.get(sync_type, {}).get('label', sync_type)}» уже выполняется. Дождитесь завершения.",
            }

        if account.api_key_status == "unchecked":
            return {
                "ok": False,
                "status": "api_key_not_verified",
                "message": "API-ключ не проверен. Сначала проверьте ключ в настройках кабинета.",
            }

        if account.api_key_status == "invalid":
            return {
                "ok": False,
                "status": "api_key_invalid",
                "message": "API-ключ недействителен. Проверьте ключ в настройках кабинета.",
            }

        if not account.is_active:
            return {
                "ok": False,
                "status": "account_inactive",
                "message": "Кабинет отключён. Активируйте кабинет перед синхронизацией.",
            }

        run = await self.create_run(
            user_id=user_id,
            account_id=account.id,
            marketplace=account.marketplace.value,
            sync_type=sync_type,
            trigger_source=trigger_source,
        )
        await self.session.flush()

        try:
            queue = await create_pool(_redis_settings())
            try:
                job = await queue.enqueue_job(
                    task_name,
                    {
                        "triggered_by_user_id": user_id,
                        "source": "web_sync_center",
                        "sync_run_id": run.id,
                        "marketplace_account_id": account.id,
                    },
                )
            finally:
                await queue.close()
        except Exception as exc:
            logger.error(
                "Failed to enqueue sync task",
                extra={
                    "user_id": user_id,
                    "account_id": account.id,
                    "sync_type": sync_type,
                    "task": task_name,
                    "error": str(exc),
                },
            )
            await self.mark_failed(run.id, f"Не удалось запустить задачу: {exc}")
            return {
                "ok": False,
                "status": "enqueue_failed",
                "message": "Не удалось поставить задачу в очередь. Попробуйте позже.",
            }

        await self.mark_started(run.id)

        label = SYNC_TYPE_MAP.get(sync_type, {}).get("label", sync_type)
        logger.info(
            "Manual sync triggered",
            extra={
                "user_id": user_id,
                "account_id": account.id,
                "marketplace": account.marketplace.value,
                "sync_type": sync_type,
                "task": task_name,
                "run_id": run.id,
                "job_id": job.job_id if job else None,
            },
        )

        return {
            "ok": True,
            "status": "queued",
            "run_id": run.id,
            "message": f"Синхронизация «{label}» поставлена в очередь.",
        }

    async def verify_api_key(
        self,
        user: User,
        account: MarketplaceAccount,
    ) -> dict[str, Any]:
        marketplace = account.marketplace.value
        api_key_masked = _mask_key(account.encrypted_api_key)

        try:
            if marketplace == "WB":
                result = await self._verify_wb_key(account)
            elif marketplace == "OZON":
                result = await self._verify_ozon_key(account)
            else:
                return {"ok": False, "status": "unknown_marketplace", "message": "Неизвестный маркетплейс."}

            account.api_key_status = "valid" if result["valid"] else "invalid"
            account.api_key_checked_at = datetime.now(tz=UTC)
            account.api_key_check_result = result.get("details", {})
            await self.session.flush()

            logger.info(
                "API key verification completed",
                extra={
                    "user_id": user.id,
                    "account_id": account.id,
                    "marketplace": marketplace,
                    "api_key_masked": api_key_masked,
                    "valid": result["valid"],
                },
            )

            if result["valid"]:
                return {"ok": True, "status": "valid", "message": "API-ключ действителен."}
            return {
                "ok": False,
                "status": "invalid",
                "message": f"API-ключ недействителен: {result.get('error', 'ошибка проверки')}",
            }

        except Exception as exc:
            account.api_key_status = "invalid"
            account.api_key_checked_at = datetime.now(tz=UTC)
            account.api_key_check_result = {"error": str(exc)[:500]}
            await self.session.flush()

            logger.error(
                "API key verification failed",
                extra={
                    "user_id": user.id,
                    "account_id": account.id,
                    "marketplace": marketplace,
                    "api_key_masked": api_key_masked,
                    "error": str(exc),
                },
            )

            return {
                "ok": False,
                "status": "invalid",
                "message": f"Ошибка проверки API-ключа: {exc}",
            }

    async def _verify_wb_key(self, account: MarketplaceAccount) -> dict[str, Any]:
        from app.integrations.wb_api import WildberriesAPI

        client = WildberriesAPI(account)
        try:
            info = await client.get_seller_info()
            if info and info.get("name"):
                return {"valid": True, "details": {"seller_name": info.get("name")}}
            return {"valid": False, "details": {}, "error": "Не удалось получить информацию о продавце"}
        finally:
            await client.close()

    async def _verify_ozon_key(self, account: MarketplaceAccount) -> dict[str, Any]:
        from app.integrations.ozon_api import OzonAPI

        client = OzonAPI(account)
        try:
            warehouses = await client.get_warehouses()
            if warehouses is not None:
                return {"valid": True, "details": {"warehouses_count": len(warehouses)}}
            return {"valid": False, "details": {}, "error": "Не удалось получить список складов"}
        finally:
            await client.close()

    async def _get_run(self, run_id: int) -> SyncRun | None:
        result = await self.session.execute(
            select(SyncRun).where(SyncRun.id == run_id)
        )
        return result.scalar_one_or_none()


def _redis() -> Redis:
    return cast(
        Redis,
        Redis.from_url(get_settings().redis_url, encoding="utf-8", decode_responses=True),
    )


def _redis_settings() -> RedisSettings:
    return redis_settings_from_url(get_settings().redis_url)


def _status_message(run: SyncRun) -> str:
    messages = {
        "queued": "Синхронизация ожидает запуска.",
        "running": "Синхронизация выполняется.",
        "success": "Синхронизация завершена успешно.",
        "error": f"Ошибка: {run.error_message or 'неизвестная ошибка'}",
    }
    return messages.get(run.status, f"Статус: {run.status}")


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return key[:4] + "****" + key[-4:]
