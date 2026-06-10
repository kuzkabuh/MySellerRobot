"""Sync run management for web cabinet: trigger, track, history, api key verification."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from arq.connections import RedisSettings, create_pool
from redis.asyncio import Redis
from sqlalchemy import and_, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import get_settings
from app.core.redis import redis_settings_from_url
from app.models.domain import MarketplaceAccount, SyncRun, User
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)

STALE_SYNC_TIMEOUT_MINUTES = 30
STALE_BACKFILL_TIMEOUT_HOURS = 6

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

    async def mark_warning(
        self,
        run_id: int,
        warning_message: str,
        *,
        records_loaded: int = 0,
        records_created: int = 0,
        records_updated: int = 0,
        records_skipped: int = 0,
        details: dict[str, Any] | None = None,
    ) -> SyncRun | None:
        run = await self._get_run(run_id)
        if run is None:
            return None
        now = datetime.now(tz=UTC)
        run.status = "warning"
        run.finished_at = now
        if run.started_at:
            run.duration_seconds = Decimal(str((now - run.started_at).total_seconds()))
        run.records_loaded = records_loaded
        run.records_created = records_created
        run.records_updated = records_updated
        run.records_skipped = records_skipped
        run.error_message = warning_message[:5000]
        if details:
            run.details_json = details
        await self.session.flush()
        return run

    async def mark_timeout(
        self,
        run_id: int,
        error_message: str | None = None,
    ) -> SyncRun | None:
        run = await self._get_run(run_id)
        if run is None:
            return None
        now = datetime.now(tz=UTC)
        run.status = "timeout"
        run.finished_at = now
        if run.started_at:
            run.duration_seconds = Decimal(str((now - run.started_at).total_seconds()))
        run.error_message = (error_message or "Превышено время выполнения.")[:5000]
        await self.session.flush()
        return run

    async def finish_run(
        self,
        run_id: int,
        *,
        status: str = "success",
        records_loaded: int = 0,
        records_created: int = 0,
        records_updated: int = 0,
        records_skipped: int = 0,
        error_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> SyncRun | None:
        if status == "error":
            return await self.mark_failed(run_id, error_message or "Неизвестная ошибка")
        if status == "warning":
            return await self.mark_warning(
                run_id,
                error_message or "Завершено с предупреждениями",
                records_loaded=records_loaded,
                records_created=records_created,
                records_updated=records_updated,
                records_skipped=records_skipped,
                details=details,
            )
        if status == "timeout":
            return await self.mark_timeout(run_id, error_message)
        return await self.mark_success(
            run_id,
            records_loaded=records_loaded,
            records_created=records_created,
            records_updated=records_updated,
            records_skipped=records_skipped,
        )

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

        stale_count = await self.mark_stale_syncs_as_failed()
        if stale_count:
            logger.info("stale_syncs_cleaned_on_trigger", extra={"count": stale_count})

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
                    triggered_by_user_id=user_id,
                    source="web_sync_center",
                    sync_run_id=run.id,
                    marketplace_account_id=account.id,
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
        from app.core.security import TokenCipher
        from app.integrations.wb import WildberriesClient

        api_key = TokenCipher().decrypt(account.encrypted_api_key)
        client = WildberriesClient(api_key=api_key)
        info = await client.get_seller_info()
        if info and info.get("name"):
            return {"valid": True, "details": {"seller_name": info.get("name")}}
        return {"valid": False, "details": {}, "error": "Не удалось получить информацию о продавце"}

    async def _verify_ozon_key(self, account: MarketplaceAccount) -> dict[str, Any]:
        from app.core.security import TokenCipher
        from app.integrations.ozon import OzonClient

        api_key = TokenCipher().decrypt(account.encrypted_api_key)
        client_id = ""
        if account.encrypted_client_id:
            client_id = TokenCipher().decrypt(account.encrypted_client_id)
        client = OzonClient(api_key=api_key, client_id=client_id)
        warehouses = await client.get_warehouses()
        if warehouses is not None:
            return {"valid": True, "details": {"warehouses_count": len(warehouses)}}
        return {"valid": False, "details": {}, "error": "Не удалось получить список складов"}

    async def mark_stale_syncs_as_failed(self) -> int:
        now = datetime.now(tz=UTC)
        running_cutoff = now - timedelta(minutes=STALE_SYNC_TIMEOUT_MINUTES)
        backfill_cutoff = now - timedelta(hours=STALE_BACKFILL_TIMEOUT_HOURS)
        queued_cutoff = now - timedelta(minutes=STALE_SYNC_TIMEOUT_MINUTES)

        count = 0
        for status, cutoff, sync_type_filter in [
            ("running", running_cutoff, None),
            ("running", backfill_cutoff, "wb_financial_details"),
            ("queued", queued_cutoff, None),
        ]:
            conditions = [
                SyncRun.status == status,
            ]
            if status == "running":
                conditions.append(SyncRun.started_at.isnot(None))
                conditions.append(SyncRun.started_at < cutoff)
            else:
                conditions.append(SyncRun.created_at < cutoff)
            if sync_type_filter is not None:
                conditions.append(SyncRun.sync_type == sync_type_filter)
            result = await self.session.execute(
                select(SyncRun).where(and_(*conditions))
            )
            stale_runs = list(result.scalars().all())
            for run in stale_runs:
                run.status = "timeout"
                run.finished_at = now
                if run.started_at:
                    run.duration_seconds = Decimal(str((now - run.started_at).total_seconds()))
                run.error_message = (
                    f"Задача не завершилась корректно: превышено время выполнения "
                    f"({STALE_SYNC_TIMEOUT_MINUTES if sync_type_filter is None else STALE_BACKFILL_TIMEOUT_HOURS} мин)."
                )[:5000]
                count += 1
                logger.warning(
                    "stale_sync_run_marked_failed",
                    extra={
                        "run_id": run.id,
                        "sync_type": run.sync_type,
                        "marketplace": run.marketplace,
                        "status": status,
                        "started_at": run.started_at.isoformat() if run.started_at else None,
                    },
                )

        if count:
            await self.session.flush()
        return count

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
        "warning": f"Предупреждение: {run.error_message or 'завершено с предупреждениями'}",
        "error": f"Ошибка: {run.error_message or 'неизвестная ошибка'}",
        "timeout": f"Превышено время: {run.error_message or 'задача не завершилась'}",
    }
    return messages.get(run.status, f"Статус: {run.status}")


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return key[:4] + "****" + key[-4:]
