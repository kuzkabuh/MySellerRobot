"""Sync run management for web cabinet: trigger, track, history, api key verification."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from arq.connections import RedisSettings, create_pool
from redis.asyncio import Redis
from sqlalchemy import and_, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import get_settings
from app.core.redis import redis_settings_from_url
from app.models.domain import MarketplaceAccount, SyncRun, User
from app.services.common.sync_period_limits import (
    ManualSyncPeriodLimits,
    get_manual_sync_period_limits,
    parse_period_preset,
)

logger = logging.getLogger(__name__)

STALE_SYNC_TIMEOUT_MINUTES = 30
STALE_BACKFILL_TIMEOUT_HOURS = 6
STALE_QUEUED_TIMEOUT_MINUTES = 10

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
        "label": "Сборочные задания FBS",
        "description": "Загружает FBS-сборочные задания, а не все заказы. Доступны за последние 3 месяца. Максимум 30 дней за один API-запрос.",
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
        "description": "Используется для расчёта комиссий, логистики, штрафов, удержаний и суммы к перечислению.",
    },
    "wb_orders_stats": {
        "task_wb": "sync_wb_orders_stats",
        "task_ozon": None,
        "label": "Заказы WB",
        "description": "Загружает заказы из статистики WB. Доступны за последние 90 дней. Данные обновляются WB примерно раз в 30 минут.",
        "source_api": "/api/v1/supplier/orders",
        "max_api_days_back": 90,
    },
    "wb_fbs_assembly_orders": {
        "task_wb": "sync_wb_fbs_assembly_orders",
        "task_ozon": None,
        "label": "Сборочные задания FBS",
        "description": "Загружает FBS-сборочные задания, а не все заказы. Доступны за последние 3 месяца. Максимум 30 дней за один API-запрос.",
        "source_api": "/api/v3/orders",
        "max_api_days_back": 90,
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
    "wb_financial_backfill": {
        "task_wb": "backfill_wb_daily_financial_details",
        "task_ozon": None,
        "label": "Дозагрузка финансов WB",
        "description": "Перезагружает финансовые данные Wildberries за выбранный период для исправления расхождений.",
        "is_global": True,
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
        details: dict[str, Any] | None = None,
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
        if details:
            run.details_json = details
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
        run = await self.mark_success(
            run_id,
            records_loaded=records_loaded,
            records_created=records_created,
            records_updated=records_updated,
            records_skipped=records_skipped,
        )
        if run and details:
            run.details_json = details
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

    async def find_active_run(
        self,
        user_id: int,
        account_id: int,
        marketplace: str,
        sync_type: str,
        trigger_source: str = "manual",
    ) -> SyncRun | None:
        result = await self.session.execute(
            select(SyncRun)
            .where(
                SyncRun.user_id == user_id,
                SyncRun.marketplace_account_id == account_id,
                SyncRun.marketplace == marketplace,
                SyncRun.sync_type == sync_type,
                SyncRun.trigger_source == trigger_source,
                SyncRun.status.in_(["queued", "running"]),
            )
            .order_by(SyncRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

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
        date_from: str | None = None,
        date_to: str | None = None,
        period_preset: str | None = None,
    ) -> dict[str, Any]:
        task_name = _resolve_task(sync_type, account.marketplace.value)
        if task_name is None:
            return {
                "ok": False,
                "status": "not_implemented",
                "message": f"Синхронизация «{SYNC_TYPE_MAP.get(sync_type, {}).get('label', sync_type)}» для {account.marketplace.value} пока не реализована.",
            }

        limits = await get_manual_sync_period_limits(self.session, user_id)
        period_result = await self._validate_sync_period(limits, date_from, date_to, period_preset, sync_type=sync_type)
        if "error_code" in period_result:
            return {
                "ok": False,
                "status": period_result["error_code"],
                "message": period_result["message"],
            }

        existing = await self.find_active_run(
            user_id=user_id,
            account_id=account.id,
            marketplace=account.marketplace.value,
            sync_type=sync_type,
            trigger_source=trigger_source,
        )
        if existing is not None:
            return {
                "ok": True,
                "already_running": True,
                "run_id": existing.id,
                "status": existing.status,
                "message": "Эта синхронизация уже находится в очереди или выполняется",
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

        try:
            run = await self.create_run(
                user_id=user_id,
                account_id=account.id,
                marketplace=account.marketplace.value,
                sync_type=sync_type,
                trigger_source=trigger_source,
            )
            if period_result.get("period_applied"):
                run.details_json = {
                    "date_from": period_result["date_from"],
                    "date_to": period_result["date_to"],
                    "period_days": period_result["period_days"],
                    "period_preset": period_result["period_preset"],
                    "tariff_code": period_result["tariff_code"],
                    "tariff_name": period_result["tariff_name"],
                    "limit_max_days_back": period_result["limit_max_days_back"],
                    "limit_max_range_days": period_result["limit_max_range_days"],
                }
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.find_active_run(
                user_id=user_id,
                account_id=account.id,
                marketplace=account.marketplace.value,
                sync_type=sync_type,
                trigger_source=trigger_source,
            )
            if existing is not None:
                return {
                    "ok": True,
                    "already_running": True,
                    "run_id": existing.id,
                    "status": existing.status,
                    "message": "Эта синхронизация уже находится в очереди или выполняется",
                }
            raise

        try:
            queue = await create_pool(_redis_settings())
            try:
                enqueue_kwargs: dict[str, Any] = {
                    "triggered_by_user_id": user_id,
                    "source": "web_sync_center",
                    "sync_run_id": run.id,
                    "marketplace_account_id": account.id,
                }
                if period_result.get("period_applied"):
                    enqueue_kwargs["date_from"] = period_result["date_from"]
                    enqueue_kwargs["date_to"] = period_result["date_to"]
                    enqueue_kwargs["period_days"] = period_result["period_days"]
                job = await queue.enqueue_job(task_name, **enqueue_kwargs)
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

    async def _validate_sync_period(
        self,
        limits: ManualSyncPeriodLimits,
        date_from: str | None,
        date_to: str | None,
        period_preset: str | None,
        sync_type: str | None = None,
    ) -> dict:
        today = datetime.now(tz=UTC).date()
        effective_max_days = limits.max_days_back

        sync_info = SYNC_TYPE_MAP.get(sync_type) if sync_type else None
        if sync_info:
            api_max = sync_info.get("max_api_days_back")
            if api_max is not None:
                effective_max_days = min(effective_max_days, api_max)

        if period_preset and period_preset != "custom":
            preset_days = parse_period_preset(period_preset)
            if preset_days is None:
                return {"error_code": "invalid_period_preset", "message": f"Неизвестный пресет периода: {period_preset}"}
            if preset_days > effective_max_days:
                return {
                    "error_code": "period_exceeds_limits",
                    "message": f"Период {preset_days} дн. превышает лимит ({effective_max_days} дн.).",
                }
            effective_date_from = today - timedelta(days=preset_days)
            effective_date_to = today
            period_days = preset_days
        elif date_from and date_to:
            try:
                parsed_from = datetime.strptime(date_from, "%Y-%m-%d").date()
                parsed_to = datetime.strptime(date_to, "%Y-%m-%d").date()
            except ValueError:
                return {"error_code": "invalid_date_format", "message": "Неверный формат даты. Используйте ГГГГ-ММ-ДД."}
            if parsed_from > parsed_to:
                return {"error_code": "invalid_date_range", "message": "Дата начала не может быть позже даты окончания."}
            if parsed_from < today - timedelta(days=effective_max_days):
                return {
                    "error_code": "period_exceeds_limits",
                    "message": f"Дата начала {date_from} выходит за лимит в {effective_max_days} дн.",
                }
            range_days = (parsed_to - parsed_from).days
            if range_days > min(effective_max_days, limits.max_range_days):
                return {
                    "error_code": "period_exceeds_limits",
                    "message": f"Диапазон {range_days} дн. превышает лимит ({min(effective_max_days, limits.max_range_days)} дн.).",
                }
            effective_date_from = parsed_from
            effective_date_to = parsed_to
            period_days = range_days
        else:
            return {"period_applied": False}

        return {
            "period_applied": True,
            "date_from": effective_date_from.isoformat(),
            "date_to": effective_date_to.isoformat(),
            "period_days": period_days,
            "period_preset": period_preset or "custom",
            "tariff_code": limits.tariff_code,
            "tariff_name": limits.tariff_name,
            "limit_max_days_back": limits.max_days_back,
            "limit_max_range_days": limits.max_range_days,
            "effective_max_days": effective_max_days,
        }

    async def trigger_global_backfill(self, user_id: int, days: int = 15) -> dict[str, Any]:
        """Enqueue backfill_wb_daily_financial_details as a global (non-account-specific) task."""
        from app.workers.tasks_main import WB_FINANCIAL_BACKFILL_ALLOWED_PERIODS
        if days not in WB_FINANCIAL_BACKFILL_ALLOWED_PERIODS:
            return {
                "ok": False,
                "status": "invalid_days",
                "message": f"Недопустимый период дозагрузки: {days}. Допустимые значения: {WB_FINANCIAL_BACKFILL_ALLOWED_PERIODS}",
            }
        try:
            queue = await create_pool(_redis_settings())
            try:
                await queue.enqueue_job(
                    "backfill_wb_daily_financial_details",
                    days=days,
                    triggered_by_user_id=user_id,
                    source="web_settings",
                )
            finally:
                await queue.close()
        except Exception as exc:
            logger.error(
                "Failed to enqueue global backfill task",
                extra={"user_id": user_id, "days": days, "error": str(exc)},
            )
            return {
                "ok": False,
                "status": "enqueue_failed",
                "message": "Не удалось поставить задачу в очередь. Попробуйте позже.",
            }
        logger.info(
            "Global WB financial backfill triggered",
            extra={"user_id": user_id, "days": days},
        )
        return {"ok": True, "days": days}

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
        queued_cutoff = now - timedelta(minutes=STALE_QUEUED_TIMEOUT_MINUTES)

        count = 0
        for status, cutoff, sync_type_filter, target_status, error_code in [
            ("queued", queued_cutoff, None, "error", "SYNC_RUN_QUEUE_TIMEOUT"),
            ("running", running_cutoff, None, "timeout", "SYNC_RUN_TIMEOUT"),
            ("running", backfill_cutoff, "wb_financial_details", "timeout", "SYNC_RUN_TIMEOUT"),
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
                run.status = target_status
                run.finished_at = now
                if run.started_at:
                    run.duration_seconds = Decimal(str((now - run.started_at).total_seconds()))
                if status == "queued":
                    run.error_message = (
                        f"Задача не была запущена: превышено время ожидания в очереди "
                        f"({STALE_QUEUED_TIMEOUT_MINUTES} мин)."
                    )[:5000]
                else:
                    run.error_message = (
                        f"Задача не завершилась корректно: превышено время выполнения "
                        f"({STALE_SYNC_TIMEOUT_MINUTES if sync_type_filter is None else STALE_BACKFILL_TIMEOUT_HOURS} мин)."
                    )[:5000]
                run.error_code = error_code
                count += 1
                logger.warning(
                    "stale_sync_run_marked_failed",
                    extra={
                        "run_id": run.id,
                        "sync_type": run.sync_type,
                        "marketplace": run.marketplace,
                        "status": status,
                        "started_at": run.started_at.isoformat() if run.started_at else None,
                        "error_code": error_code,
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
