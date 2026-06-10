"""Telegram notifications for sync run lifecycle events."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.core.config import get_settings
from app.models.domain import SyncRun, User
from app.services.common.web_sync_run_service import SYNC_TYPE_MAP

logger = logging.getLogger(__name__)

MOSCOW_TZ_OFFSET = timedelta(hours=3)


def _format_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    msk = dt.replace(tzinfo=UTC) + MOSCOW_TZ_OFFSET
    return msk.strftime("%d.%m.%Y %H:%M")


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = int(seconds)
    if total < 60:
        return f"{total} сек"
    minutes = total // 60
    secs = total % 60
    if minutes < 60:
        return f"{minutes} мин {secs} сек"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours} ч {minutes} мин"


def _sync_type_label(sync_type: str) -> str:
    info = SYNC_TYPE_MAP.get(sync_type, {})
    return info.get("label", sync_type)


def _trigger_source_label(source: str) -> str:
    return {"manual": "Вручную", "auto": "Автоматически", "automatic": "Автоматически", "cron": "Автоматически", "scheduler": "Автоматически", "system": "Система"}.get(source, source)


def _account_name(run: SyncRun) -> str:
    if run.account and run.account.name:
        return run.account.name
    return f"#{run.marketplace_account_id or '?'}"


def _user_name(run: SyncRun) -> str:
    if run.user and run.user.first_name:
        return run.user.first_name
    if run.user and run.user.username:
        return run.user.username
    return f"#{run.user_id or 'система'}"


def _build_start_text(run: SyncRun) -> str:
    return (
        "🚀 Запущена синхронизация\n\n"
        f"Маркетплейс: {run.marketplace}\n"
        f"Тип: {_sync_type_label(run.sync_type)}\n"
        f"Источник: {_trigger_source_label(run.trigger_source)}\n"
        f"Кабинет: {_account_name(run)}\n"
        f"Запустил: {_user_name(run)}\n"
        f"Время старта: {_format_dt(run.started_at)}\n\n"
        "Статус: ⏳ выполняется\n\n"
        f"<code>Run ID: {run.id}</code>"
    )


def _build_success_text(run: SyncRun) -> str:
    return (
        "✅ Синхронизация завершена\n\n"
        f"Маркетплейс: {run.marketplace}\n"
        f"Тип: {_sync_type_label(run.sync_type)}\n"
        f"Источник: {_trigger_source_label(run.trigger_source)}\n"
        f"Кабинет: {_account_name(run)}\n\n"
        f"Начало: {_format_dt(run.started_at)}\n"
        f"Завершение: {_format_dt(run.finished_at)}\n"
        f"Длительность: {_format_duration(float(run.duration_seconds) if run.duration_seconds else None)}\n\n"
        f"Загружено: {run.records_loaded:,}\n"
        f"Создано: {run.records_created:,}\n"
        f"Обновлено: {run.records_updated:,}\n"
        f"Пропущено: {run.records_skipped:,}\n\n"
        "Результат: ✅ данные успешно обновлены.\n"
        f"<code>Run ID: {run.id}</code>"
    ).replace(",", " ")


def _build_warning_text(run: SyncRun) -> str:
    details = ""
    if run.details_json:
        parts = []
        for key, val in run.details_json.items():
            parts.append(f"- {key}: {val}")
        if parts:
            details = "\n" + "\n".join(parts[:5]) + "\n"

    error_section = ""
    if run.error_message:
        error_section = f"\nПоследняя ошибка:\n<code>{run.error_message[:500]}</code>\n"

    return (
        "⚠️ Синхронизация завершена с предупреждениями\n\n"
        f"Маркетплейс: {run.marketplace}\n"
        f"Тип: {_sync_type_label(run.sync_type)}\n"
        f"Источник: {_trigger_source_label(run.trigger_source)}\n"
        f"Кабинет: {_account_name(run)}\n\n"
        f"Загружено: {run.records_loaded:,}\n"
        f"Создано: {run.records_created:,}\n"
        f"Обновлено: {run.records_updated:,}\n"
        f"Ошибок: {run.error_message or 0}\n"
        f"{error_section}"
        f"{details}"
        f"<code>Run ID: {run.id}</code>"
    ).replace(",", " ")


def _build_error_text(run: SyncRun) -> str:
    return (
        "❌ Синхронизация завершилась с ошибкой\n\n"
        f"Маркетплейс: {run.marketplace}\n"
        f"Тип: {_sync_type_label(run.sync_type)}\n"
        f"Источник: {_trigger_source_label(run.trigger_source)}\n"
        f"Кабинет: {_account_name(run)}\n\n"
        f"Начало: {_format_dt(run.started_at)}\n"
        f"Завершение: {_format_dt(run.finished_at)}\n"
        f"Длительность: {_format_duration(float(run.duration_seconds) if run.duration_seconds else None)}\n\n"
        "Ошибка:\n"
        f"<code>{(run.error_message or 'Неизвестная ошибка')[:1000]}</code>\n\n"
        f"<code>Run ID: {run.id}</code>"
    )


def _build_text(run: SyncRun, event: str) -> str:
    builders = {
        "start": _build_start_text,
        "success": _build_success_text,
        "warning": _build_warning_text,
        "error": _build_error_text,
    }
    builder = builders.get(event)
    if builder is None:
        return f"Синхронизация #{run.id}: статус {event}"
    return builder(run)


def _recipient_telegram_ids(run: SyncRun) -> list[int]:
    ids: set[int] = set()
    settings = get_settings()
    for aid in settings.admin_ids:
        ids.add(aid)
    if run.user and run.user.telegram_id:
        ids.add(run.user.telegram_id)
    elif run.user_id:
        pass
    return list(ids)


class SyncNotificationService:
    def __init__(self) -> None:
        self._bot: Bot | None = None

    @asynccontextmanager
    async def _bot_session(self) -> AsyncGenerator[Bot, None]:
        settings = get_settings()
        bot = Bot(
            token=settings.bot_token.get_secret_value(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            yield bot
        finally:
            try:
                await bot.session.close()
            except Exception:
                logger.exception("sync_notification_bot_session_close_failed")

    async def send_sync_start(self, run: SyncRun) -> None:
        await self._send_notification(run, "start")

    async def send_sync_finish(self, run: SyncRun) -> None:
        if run.status == "success":
            await self._send_notification(run, "success")
        elif run.status == "warning":
            await self._send_notification(run, "warning")
        elif run.status in ("error", "timeout"):
            await self._send_notification(run, "error")

    async def _send_notification(self, run: SyncRun, event: str) -> None:
        text = _build_text(run, event)
        recipient_ids = _recipient_telegram_ids(run)
        if not recipient_ids:
            return
        async with self._bot_session() as bot:
            for tid in recipient_ids:
                try:
                    await bot.send_message(chat_id=tid, text=text)
                    logger.info(
                        "sync_notification_sent",
                        extra={
                            "run_id": run.id,
                            "event": event,
                            "telegram_id": tid,
                            "status": run.status,
                        },
                    )
                except Exception:
                    logger.exception(
                        "sync_notification_failed",
                        extra={
                            "run_id": run.id,
                            "event": event,
                            "telegram_id": tid,
                            "status": run.status,
                        },
                    )
