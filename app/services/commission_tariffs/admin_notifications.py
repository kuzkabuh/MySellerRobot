"""version: 1.0.0
description: Admin notification helpers for commission tariff system.
updated: 2026-05-20
"""

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def notify_admins(bot: Bot, message: str, *, parse_mode: str = "HTML") -> int:
    """Send a notification message to all configured admin Telegram IDs.

    Returns the number of admins successfully notified.
    """
    settings = get_settings()
    admin_ids = settings.admin_ids
    if not admin_ids:
        logger.warning("notify_admins_no_admin_ids_configured")
        return 0

    sent = 0
    for telegram_id in admin_ids:
        try:
            await bot.send_message(telegram_id, message, parse_mode=parse_mode)
            sent += 1
        except TelegramForbiddenError:
            logger.warning(
                "notify_admin_bot_blocked",
                extra={"telegram_id": telegram_id},
            )
        except TelegramBadRequest as exc:
            logger.warning(
                "notify_admin_bad_request",
                extra={"telegram_id": telegram_id, "error": str(exc)[:200]},
            )
        except Exception:
            logger.exception(
                "notify_admin_failed",
                extra={"telegram_id": telegram_id},
            )

    return sent


def format_wb_sync_notification(result: dict[str, Any]) -> str:
    """Format a WB sync result into an admin notification."""
    if result.get("success"):
        if not result.get("changed"):
            return "✅ Комиссии Wildberries проверены — изменений нет."
        rates_count = result.get("rates_count", 0)
        if rates_count == 0:
            return (
                "⚠️ <b>Синхронизация WB: 0 ставок</b>\n\n"
                "Версия создана, но ставки не распознаны. "
                "Проверьте формат ответа WB API."
            )
        return (
            "🔄 <b>Обновлены комиссии Wildberries</b>\n\n"
            f"Версия: {result.get('version_label', 'н/д')}\n"
            f"Ставок: {rates_count}\n"
            f"ID версии: {result.get('version_id', 'н/д')}"
        )
    error = result.get("error", "Неизвестная ошибка")
    error_type = result.get("error_type", "")
    return "⚠️ <b>Ошибка синхронизации комиссий WB</b>\n\n" f"Тип: {error_type}\n" f"Ошибка: {error}"


def format_ozon_monitor_notification(result: dict[str, Any]) -> str | None:
    """Format an Ozon monitor result into an admin notification."""
    change_type = result.get("change_type", "no_change")
    fetch_method = result.get("fetch_method", "http")

    if result.get("has_changes"):
        period = result.get("period_label") or "Период не определён"
        method_label = {"http": "HTTP", "browser": "Browser", "manual": "Manual"}.get(
            fetch_method, fetch_method
        )
        return (
            "🔔 <b>Обнаружено обновление таблицы комиссий Ozon</b>\n\n"
            f"Новый период: {period}\n"
            f"Способ: {method_label}\n"
            f"Требуется загрузить новый XLSX-файл через WEB-админку или бот."
        )

    if change_type in ("source_unavailable", "file_unavailable"):
        error = result.get("error", "")
        method_label = {"http": "HTTP", "browser": "Browser", "manual": "Manual"}.get(
            fetch_method, fetch_method
        )
        return (
            "⚠️ <b>Источник комиссий Ozon недоступен</b>\n\n"
            f"Способ: {method_label}\n"
            f"Ошибка: {error}\n"
            "Последняя рабочая версия комиссий сохранена.\n"
            "Загрузите XLSX вручную через WEB-админку."
        )

    return None


def format_ozon_import_notification(result: dict[str, Any]) -> str:
    """Format an Ozon import result into an admin notification."""
    if result.get("success"):
        diff = result.get("diff_summary", {})
        diff_text = ""
        if diff:
            parts = []
            if diff.get("added"):
                parts.append(f"+{diff['added']} добавлено")
            if diff.get("removed"):
                parts.append(f"-{diff['removed']} удалено")
            if diff.get("changed"):
                parts.append(f"~{diff['changed']} изменено")
            if parts:
                diff_text = f"\nИзменения: {', '.join(parts)}"
        return (
            "✅ <b>Импортированы комиссии Ozon</b>\n\n"
            f"Файл: {result.get('file_name', 'н/д')}\n"
            f"Версия: {result.get('version_label', 'н/д')}\n"
            f"Ставок импортировано: {result.get('rows_imported', 0)}\n"
            f"Дата начала: {result.get('effective_from', 'н/д')}{diff_text}"
        )
    if result.get("duplicate"):
        return "ℹ️ Этот файл комиссий Ozon уже был импортирован ранее."
    return (
        "⚠️ <b>Ошибка импорта комиссий Ozon</b>\n\n"
        f"Ошибка: {result.get('message', 'Неизвестная ошибка')}"
    )
