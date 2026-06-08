"""version: 1.0.0
description: Admin panel handlers for tariff and promo code management in Telegram bot.
updated: 2026-05-31
"""

import logging
import math
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import escape as html_escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards.admin_panel import (
    admin_promo_card,
    admin_promo_confirm_cancel,
    admin_promo_features_text,
    admin_promo_new_users_select,
    admin_promo_periods_select,
    admin_promo_tariffs_select,
    admin_promo_type_select,
    admin_promo_usages_nav,
    admin_promos_list,
    admin_tariff_card,
    admin_tariff_confirm,
    admin_tariff_limits_menu,
    admin_tariffs_list,
)
from app.bot.states import AdminPanelStates
from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.models.enums import PromoType, PromoUsageStatus
from app.models.promo_codes import PromoCode
from app.services.promo_code_service import PromoCodeService, PromoValidationError, normalize_code
from app.services.tariff_service import TariffService

router = Router(name="admin_panel")
logger = logging.getLogger(__name__)

_LIMIT_LABELS = {
    "max_marketplace_accounts": "Кабинеты МП",
    "max_products": "Товары",
    "max_users": "Пользователи",
    "sync_interval_minutes": "Интервал синхронизации (мин)",
    "analytics_depth_days": "Глубина аналитики (дни)",
}

_PERIOD_LABELS = {
    "monthly": "Месяц",
    "3_months": "3 месяца",
    "6_months": "6 месяцев",
    "yearly": "Год",
}

_PROMO_TYPE_LABELS = {
    PromoType.PERCENT_DISCOUNT: "Скидка %",
    PromoType.FIXED_DISCOUNT: "Фикс. скидка",
    PromoType.FREE_DAYS: "Бесплатные дни",
}


def _is_admin(telegram_id: int | None) -> bool:
    if telegram_id is None:
        return False
    return telegram_id in get_settings().admin_ids


def _deny_text() -> str:
    return "⛔ У вас нет доступа к административному разделу."


def _h(value: object) -> str:
    if value is None:
        return "—"
    return html_escape(str(value), quote=False)


def _rub(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}".replace(",", " ") + " ₽"


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d.%m.%Y %H:%M")


# ============================================================
# COMMANDS
# ============================================================


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        return
    from app.bot.keyboards.main import admin_menu

    await message.answer("🛠 Администрирование", reply_markup=admin_menu())


@router.message(Command("tariffs"))
async def cmd_tariffs(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        return
    async with AsyncSessionFactory() as session:
        service = TariffService(session)
        tariffs = await service.get_all_tariffs_with_user_counts()
    await message.answer(
        _tariffs_list_text(tariffs),
        reply_markup=admin_tariffs_list(tariffs),
    )


@router.message(Command("promocodes"))
async def cmd_promocodes(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        return
    async with AsyncSessionFactory() as session:
        service = PromoCodeService(session)
        promos = await service.get_all()
    await message.answer(
        _promos_list_text(promos),
        reply_markup=admin_promos_list(promos),
    )


# ============================================================
# TARIFF LIST
# ============================================================


@router.callback_query(F.data == "ap:tariffs")
async def cb_tariffs_list(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    async with AsyncSessionFactory() as session:
        service = TariffService(session)
        tariffs = await service.get_all_tariffs_with_user_counts()
    text = _tariffs_list_text(tariffs)
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=admin_tariffs_list(tariffs))
        except Exception:
            await callback.message.answer(text, reply_markup=admin_tariffs_list(tariffs))
    await callback.answer()
    logger.info("admin_opened_tariffs", extra={"admin_telegram_id": callback.from_user.id})


def _tariffs_list_text(tariffs: list) -> str:
    lines = ["📦 <b>Тарифы</b>\n"]
    for tariff, count in tariffs:
        status = "✅" if tariff.is_active else "❌"
        pub = "👁" if tariff.is_public else "🙈"
        lines.append(
            f"{status}{pub} <b>{_h(tariff.name)}</b> — "
            f"{_rub(tariff.price_monthly)}/мес — {count} польз."
        )
    return "\n".join(lines)


# ============================================================
# TARIFF CARD
# ============================================================


@router.callback_query(
    F.data.startswith("ap:tariff:")
    & ~F.data.contains(":price:")
    & ~F.data.contains(":limit:")
    & ~F.data.contains(":save:")
    & ~F.data.contains(":toggle")
    & ~F.data.contains(":public")
    & ~F.data.contains(":limits")
)
async def cb_tariff_card(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    tariff_id = int(parts[2])
    async with AsyncSessionFactory() as session:
        service = TariffService(session)
        tariff = await service.get_tariff_by_id(tariff_id)
        if not tariff:
            await callback.answer("Тариф не найден", show_alert=True)
            return
        user_count = await service.get_tariff_user_count(tariff_id)
    text = _tariff_card_text(tariff, user_count)
    if callback.message:
        try:
            await callback.message.edit_text(
                text, reply_markup=admin_tariff_card(tariff, user_count)
            )
        except Exception:
            await callback.message.answer(text, reply_markup=admin_tariff_card(tariff, user_count))
    await callback.answer()
    logger.info(
        "admin_opened_tariff_card",
        extra={"admin_telegram_id": callback.from_user.id, "tariff_id": tariff_id},
    )


def _tariff_card_text(tariff, user_count: int) -> str:
    status = "✅ Активен" if tariff.is_active else "❌ Отключён"
    pub = "👁 Публичный" if tariff.is_public else "🙈 Скрытый"
    features = admin_promo_features_text(tariff)

    lines = [
        f"📦 <b>Тариф: {_h(tariff.name)}</b>",
        "",
        f"ID: {tariff.id}",
        f"Код: <code>{_h(tariff.code)}</code>",
        f"Описание: {_h(tariff.description or '—')}",
        "",
        f"💰 Цена/мес: <b>{_rub(tariff.price_monthly)}</b>",
        f"💰 Цена/3мес: {_rub(tariff.price_3_months)}",
        f"💰 Цена/6мес: {_rub(tariff.price_6_months)}",
        f"💰 Цена/год: {_rub(tariff.price_yearly)}",
        f"Валюта: {_h(tariff.currency)}",
        "",
        f"Статус: {status}",
        f"Видимость: {pub}",
        f"Порядок: {tariff.sort_order}",
        "",
        "📊 Лимиты:",
        f"  Кабинеты МП: {tariff.max_marketplace_accounts}",
        f"  Товары: {_h(tariff.max_products) if tariff.max_products else '∞'}",
        f"  Пользователи: {_h(tariff.max_users) if tariff.max_users else '∞'}",
        f"  Синхронизация: {tariff.sync_interval_minutes} мин",
        f"  Аналитика: {tariff.analytics_depth_days} дн",
        "",
        f"👥 Пользователей на тарифе: <b>{user_count}</b>",
        "",
        "🔧 Функции:",
        features,
    ]
    return "\n".join(lines)


# ============================================================
# TARIFF PRICE EDIT
# ============================================================


@router.callback_query(F.data.startswith("ap:tariff:") & F.data.contains(":price:"))
async def cb_tariff_price_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    tariff_id = int(parts[2])
    period = parts[4]
    period_label = _PERIOD_LABELS.get(period, period)

    await state.update_data(
        tariff_id=tariff_id,
        field=f"price_{period}",
        period=period,
    )
    await state.set_state(AdminPanelStates.waiting_for_tariff_price)

    if callback.message:
        await callback.message.answer(
            f"Введите новую цену за <b>{_h(period_label)}</b> (число, ₽).\n"
            f"Для бесплатного тарифа введите 0.\n\n"
            f"Для отмены: /cancel"
        )
    await callback.answer()


@router.message(AdminPanelStates.waiting_for_tariff_price)
async def msg_tariff_price_input(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        await state.clear()
        return

    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return

    try:
        value = Decimal(text)
        if value < 0:
            await message.answer("Цена не может быть отрицательной. Введите число ≥ 0.")
            return
    except (InvalidOperation, ValueError):
        await message.answer("Некорректное число. Введите цену, например: 490 или 0")
        return

    data = await state.get_data()
    tariff_id = data["tariff_id"]
    field = data["field"]
    period = data.get("period", "")

    async with AsyncSessionFactory() as session:
        service = TariffService(session)
        tariff = await service.get_tariff_by_id(tariff_id)
        if not tariff:
            await message.answer("Тариф не найден.")
            await state.clear()
            return

        old_value = getattr(tariff, field, None)
        period_label = _PERIOD_LABELS.get(period, field)

        confirm_text = (
            f"Изменить цену тарифа <b>{_h(tariff.name)}</b> "
            f"за <b>{_h(period_label)}</b>?\n\n"
            f"Было: {_rub(old_value)}\n"
            f"Станет: <b>{_rub(value)}</b>"
        )
        await message.answer(
            confirm_text,
            reply_markup=admin_tariff_confirm(tariff_id, field, str(value)),
        )
    await state.clear()


@router.callback_query(F.data.startswith("ap:tariff:") & F.data.contains(":save:"))
async def cb_tariff_save(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    tariff_id = int(parts[2])
    field = parts[4]
    value_str = parts[5]

    try:
        value = Decimal(value_str)
    except (InvalidOperation, ValueError):
        await callback.answer("Некорректное значение", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        service = TariffService(session)
        await service.update_tariff(tariff_id, **{field: value})
        await session.commit()
        tariff = await service.get_tariff_by_id(tariff_id)
        if not tariff:
            await callback.answer("Тариф не найден", show_alert=True)
            return
        user_count = await service.get_tariff_user_count(tariff_id)

    logger.info(
        "admin_changed_tariff_price",
        extra={
            "admin_telegram_id": callback.from_user.id,
            "tariff_id": tariff_id,
            "field": field,
            "new_value": str(value),
        },
    )

    text = "✅ Цена обновлена.\n\n" + _tariff_card_text(tariff, user_count)
    if callback.message:
        try:
            await callback.message.edit_text(
                text, reply_markup=admin_tariff_card(tariff, user_count)
            )
        except Exception:
            await callback.message.answer(text, reply_markup=admin_tariff_card(tariff, user_count))
    await callback.answer("Сохранено")


# ============================================================
# TARIFF LIMITS
# ============================================================


@router.callback_query(F.data.endswith(":limits"))
async def cb_tariff_limits_menu(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    tariff_id = int(parts[2])
    async with AsyncSessionFactory() as session:
        service = TariffService(session)
        tariff = await service.get_tariff_by_id(tariff_id)
        if not tariff:
            await callback.answer("Тариф не найден", show_alert=True)
            return
    limits = TariffService.get_limits(tariff)
    lines = [f"⚙️ <b>Лимиты: {_h(tariff.name)}</b>\n"]
    for key, label in _LIMIT_LABELS.items():
        val = limits.get(key)
        display = val if val is not None else "∞"
        lines.append(f"• {label}: <b>{display}</b>")
    if callback.message:
        try:
            await callback.message.edit_text(
                "\n".join(lines), reply_markup=admin_tariff_limits_menu(tariff_id)
            )
        except Exception:
            await callback.message.answer(
                "\n".join(lines), reply_markup=admin_tariff_limits_menu(tariff_id)
            )
    await callback.answer()


@router.callback_query(F.data.startswith("ap:tariff:") & F.data.contains(":limit:"))
async def cb_tariff_limit_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    tariff_id = int(parts[2])
    limit_field = parts[4]
    label = _LIMIT_LABELS.get(limit_field, limit_field)

    await state.update_data(tariff_id=tariff_id, field=limit_field)
    await state.set_state(AdminPanelStates.waiting_for_tariff_limit)

    if callback.message:
        await callback.message.answer(
            f"Введите новое значение для <b>{_h(label)}</b>.\n"
            f"Оставьте пустым или введите 0 для безлимита.\n\n"
            f"Для отмены: /cancel"
        )
    await callback.answer()


@router.message(AdminPanelStates.waiting_for_tariff_limit)
async def msg_tariff_limit_input(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        await state.clear()
        return

    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return

    try:
        value = int(text) if text else 0
        if value < 0:
            await message.answer("Значение не может быть отрицательным.")
            return
    except ValueError:
        await message.answer("Введите целое число.")
        return

    data = await state.get_data()
    tariff_id = data["tariff_id"]
    field = data["field"]
    label = _LIMIT_LABELS.get(field, field)

    db_value: int | None = value if value > 0 else None

    async with AsyncSessionFactory() as session:
        service = TariffService(session)
        await service.update_tariff(tariff_id, **{field: db_value})
        await session.commit()
        tariff = await service.get_tariff_by_id(tariff_id)

    logger.info(
        "admin_changed_tariff_limits",
        extra={
            "admin_telegram_id": message.from_user.id,
            "tariff_id": tariff_id,
            "field": field,
            "new_value": str(db_value),
        },
    )

    display = db_value if db_value is not None else "∞"
    await message.answer(f"✅ <b>{_h(label)}</b> изменён на <b>{display}</b>")

    if tariff:
        user_count = 0
        async with AsyncSessionFactory() as session:
            service = TariffService(session)
            user_count = await service.get_tariff_user_count(tariff_id)
        await message.answer(
            _tariff_card_text(tariff, user_count),
            reply_markup=admin_tariff_card(tariff, user_count),
        )
    await state.clear()


# ============================================================
# TARIFF TOGGLE / PUBLIC
# ============================================================


@router.callback_query(F.data.endswith(":toggle") & F.data.startswith("ap:tariff:"))
async def cb_tariff_toggle(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    tariff_id = int(parts[2])

    async with AsyncSessionFactory() as session:
        service = TariffService(session)
        tariff = await service.toggle_tariff(tariff_id)
        await session.commit()
        if not tariff:
            await callback.answer("Тариф не найден", show_alert=True)
            return
        user_count = await service.get_tariff_user_count(tariff_id)

    action = "admin_enabled_tariff" if tariff.is_active else "admin_disabled_tariff"
    logger.info(
        action,
        extra={"admin_telegram_id": callback.from_user.id, "tariff_id": tariff_id},
    )

    text = _tariff_card_text(tariff, user_count)
    if callback.message:
        try:
            await callback.message.edit_text(
                text, reply_markup=admin_tariff_card(tariff, user_count)
            )
        except Exception:
            await callback.message.answer(text, reply_markup=admin_tariff_card(tariff, user_count))
    status = "включён" if tariff.is_active else "отключён"
    await callback.answer(f"Тариф {status}")


@router.callback_query(F.data.endswith(":public") & F.data.startswith("ap:tariff:"))
async def cb_tariff_public(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    tariff_id = int(parts[2])

    async with AsyncSessionFactory() as session:
        service = TariffService(session)
        tariff = await service.get_tariff_by_id(tariff_id)
        if not tariff:
            await callback.answer("Тариф не найден", show_alert=True)
            return
        new_public = not tariff.is_public
        await service.update_tariff(tariff_id, is_public=new_public)
        await session.commit()
        tariff = await service.get_tariff_by_id(tariff_id)
        user_count = await service.get_tariff_user_count(tariff_id)

    logger.info(
        "admin_changed_tariff_publicity",
        extra={
            "admin_telegram_id": callback.from_user.id,
            "tariff_id": tariff_id,
            "is_public": new_public,
        },
    )

    if tariff:
        text = _tariff_card_text(tariff, user_count)
        if callback.message:
            try:
                await callback.message.edit_text(
                    text, reply_markup=admin_tariff_card(tariff, user_count)
                )
            except Exception:
                await callback.message.answer(
                    text, reply_markup=admin_tariff_card(tariff, user_count)
                )
    visibility = "публичный" if new_public else "скрытый"
    await callback.answer(f"Тариф {visibility}")


# ============================================================
# PROMO LIST
# ============================================================


@router.callback_query(F.data == "ap:promos")
async def cb_promos_list(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    async with AsyncSessionFactory() as session:
        service = PromoCodeService(session)
        promos = await service.get_all()
    text = _promos_list_text(promos)
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=admin_promos_list(promos))
        except Exception:
            await callback.message.answer(text, reply_markup=admin_promos_list(promos))
    await callback.answer()
    logger.info("admin_opened_promocodes", extra={"admin_telegram_id": callback.from_user.id})


def _promos_list_text(promos: list) -> str:
    lines = ["🎟 <b>Промокоды</b>\n"]
    if not promos:
        lines.append("Промокоды не найдены.")
        return "\n".join(lines)
    for promo in promos:
        status = "✅" if promo.is_active else "❌"
        if promo.promo_type == PromoType.PERCENT_DISCOUNT:
            discount = f"скидка {promo.discount_percent}%"
        elif promo.promo_type == PromoType.FIXED_DISCOUNT:
            discount = f"скидка {_rub(promo.discount_amount)}"
        else:
            discount = f"{promo.free_days} дн."
        total = str(promo.max_uses_total) if promo.max_uses_total else "∞"
        lines.append(
            f"{status} <code>{_h(promo.code)}</code> — {discount} — {promo.used_count}/{total}"
        )
    return "\n".join(lines)


# ============================================================
# PROMO CARD
# ============================================================


@router.callback_query(
    F.data.startswith("ap:promo:")
    & ~F.data.contains(":toggle")
    & ~F.data.contains(":stats")
    & ~F.data.contains(":usages")
    & ~F.data.contains(":edit_limit")
    & ~F.data.contains(":edit_expires")
    & ~F.data.contains(":create")
    & ~F.data.contains(":search")
    & ~F.data.contains(":type:")
    & ~F.data.contains(":sel_tariff:")
    & ~F.data.contains(":sel_period:")
    & ~F.data.contains(":tariffs_done")
    & ~F.data.contains(":tariffs_skip")
    & ~F.data.contains(":periods_done")
    & ~F.data.contains(":periods_skip")
    & ~F.data.contains(":new_users:")
    & ~F.data.contains(":confirm_create")
)
async def cb_promo_card(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        promo_id = int(parts[2])
    except ValueError:
        await callback.answer()
        return

    async with AsyncSessionFactory() as session:
        service = PromoCodeService(session)
        promo = await service.get_by_id(promo_id)
        if not promo:
            await callback.answer("Промокод не найден", show_alert=True)
            return
    text = _promo_card_text(promo)
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=admin_promo_card(promo))
        except Exception:
            await callback.message.answer(text, reply_markup=admin_promo_card(promo))
    await callback.answer()
    logger.info(
        "admin_opened_promocode_card",
        extra={"admin_telegram_id": callback.from_user.id, "promo_id": promo_id},
    )


def _promo_card_text(promo: PromoCode) -> str:
    status = "✅ Активен" if promo.is_active else "❌ Отключён"
    type_label = _PROMO_TYPE_LABELS.get(promo.promo_type, promo.promo_type)

    if promo.promo_type == PromoType.PERCENT_DISCOUNT:
        discount_info = f"Скидка: {promo.discount_percent}%"
    elif promo.promo_type == PromoType.FIXED_DISCOUNT:
        discount_info = f"Скидка: {_rub(promo.discount_amount)}"
    else:
        discount_info = f"Бесплатных дней: {promo.free_days}"

    total = str(promo.max_uses_total) if promo.max_uses_total else "∞"

    tariff_names = "—"
    if promo.tariffs:
        tariff_names = ", ".join(str(pt.tariff_id) for pt in promo.tariffs)

    period_names = "—"
    if promo.periods:
        period_names = ", ".join(_PERIOD_LABELS.get(pp.period, pp.period) for pp in promo.periods)

    new_only = "Да" if promo.only_for_new_users else "Нет"

    lines = [
        f"🎟 <b>Промокод: <code>{_h(promo.code)}</code></b>",
        "",
        f"ID: {promo.id}",
        f"Название: {_h(promo.name)}",
        f"Описание: {_h(promo.description or '—')}",
        f"Тип: {_h(type_label)}",
        discount_info,
        f"Валюта: {_h(promo.currency)}",
        "",
        f"Статус: {status}",
        f"Начало: {_fmt_dt(promo.starts_at)}",
        f"Окончание: {_fmt_dt(promo.expires_at)}",
        "",
        f"Использовано: {promo.used_count} / {total}",
        f"На пользователя: {promo.max_uses_per_user}",
        f"Мин. сумма: {_rub(promo.min_order_amount)}",
        f"Только новые: {new_only}",
        "",
        f"Тарифы: {_h(tariff_names)}",
        f"Периоды: {_h(period_names)}",
        "",
        f"Создан: {_fmt_dt(promo.created_at)}",
        f"Обновлён: {_fmt_dt(promo.updated_at)}",
    ]
    return "\n".join(lines)


# ============================================================
# PROMO TOGGLE
# ============================================================


@router.callback_query(F.data.startswith("ap:promo:") & F.data.endswith(":toggle"))
async def cb_promo_toggle(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    promo_id = int(parts[2])

    async with AsyncSessionFactory() as session:
        service = PromoCodeService(session)
        promo = await service.toggle(promo_id)
        await session.commit()
        if not promo:
            await callback.answer("Промокод не найден", show_alert=True)
            return

    action = "admin_enabled_promocode" if promo.is_active else "admin_disabled_promocode"
    logger.info(
        action,
        extra={"admin_telegram_id": callback.from_user.id, "promo_id": promo_id},
    )

    text = _promo_card_text(promo)
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=admin_promo_card(promo))
        except Exception:
            await callback.message.answer(text, reply_markup=admin_promo_card(promo))
    status = "включён" if promo.is_active else "отключён"
    await callback.answer(f"Промокод {status}")


# ============================================================
# PROMO STATS
# ============================================================


@router.callback_query(F.data.startswith("ap:promo:") & F.data.endswith(":stats"))
async def cb_promo_stats(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    promo_id = int(parts[2])

    async with AsyncSessionFactory() as session:
        service = PromoCodeService(session)
        promo = await service.get_by_id(promo_id)
        if not promo:
            await callback.answer("Промокод не найден", show_alert=True)
            return
        stats = await service.get_usage_stats(promo_id)
        usages = await service.get_usages(promo_id, limit=10)

    applied = sum(1 for u in usages if u.status == PromoUsageStatus.APPLIED)
    reserved = sum(1 for u in usages if u.status == PromoUsageStatus.RESERVED)
    cancelled = sum(1 for u in usages if u.status == PromoUsageStatus.CANCELLED)
    unique_users = len({u.user_id for u in usages})

    lines = [
        f"📊 <b>Статистика: <code>{_h(promo.code)}</code></b>",
        "",
        f"Успешных применений: <b>{stats['total_uses']}</b>",
        f"Сумма скидок: <b>{_rub(stats['total_discount'])}</b>",
        "",
        "Последние 10 использований:",
        f"  Применено: {applied}",
        f"  Зарезервировано: {reserved}",
        f"  Отменено: {cancelled}",
        f"  Уник. пользователей: {unique_users}",
    ]

    if usages:
        lines.append("")
        for u in usages[:5]:
            lines.append(
                f"  {_fmt_dt(u.used_at)} — user {u.user_id} — "
                f"{_rub(u.original_amount)} → {_rub(u.final_amount)} — {u.status}"
            )

    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К промокоду", callback_data=f"ap:promo:{promo_id}")]
        ]
    )
    if callback.message:
        try:
            await callback.message.edit_text("\n".join(lines), reply_markup=back_kb)
        except Exception:
            await callback.message.answer("\n".join(lines), reply_markup=back_kb)
    await callback.answer()


# ============================================================
# PROMO USAGES (paginated)
# ============================================================

USAGES_PAGE_SIZE = 10


@router.callback_query(F.data.startswith("ap:promo:") & F.data.contains(":usages:"))
async def cb_promo_usages(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    promo_id = int(parts[2])
    page = int(parts[4]) if len(parts) > 4 else 0

    async with AsyncSessionFactory() as session:
        service = PromoCodeService(session)
        promo = await service.get_by_id(promo_id)
        if not promo:
            await callback.answer("Промокод не найден", show_alert=True)
            return
        all_usages = await service.get_usages(promo_id, limit=1000)

    total_pages = max(1, math.ceil(len(all_usages) / USAGES_PAGE_SIZE))
    page = min(page, total_pages - 1)
    start = page * USAGES_PAGE_SIZE
    page_usages = all_usages[start : start + USAGES_PAGE_SIZE]

    lines = [f"👥 <b>Использования: <code>{_h(promo.code)}</code></b>\n"]
    if not page_usages:
        lines.append("Использований нет.")
    else:
        for u in page_usages:
            lines.append(
                f"{_fmt_dt(u.used_at)} — user {u.user_id} — "
                f"{_rub(u.original_amount)} → {_rub(u.final_amount)} — {u.status}"
            )

    logger.info(
        "admin_viewed_promocode_usages",
        extra={"admin_telegram_id": callback.from_user.id, "promo_id": promo_id},
    )

    kb = admin_promo_usages_nav(promo_id, page, total_pages)
    if callback.message:
        try:
            await callback.message.edit_text("\n".join(lines), reply_markup=kb)
        except Exception:
            await callback.message.answer("\n".join(lines), reply_markup=kb)
    await callback.answer()


# ============================================================
# PROMO EDIT LIMIT / EXPIRES
# ============================================================


@router.callback_query(F.data.startswith("ap:promo:") & F.data.endswith(":edit_limit"))
async def cb_promo_edit_limit(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    promo_id = int(parts[2])
    await state.update_data(promo_id=promo_id)
    await state.set_state(AdminPanelStates.waiting_for_promo_limit_edit)
    if callback.message:
        await callback.message.answer(
            "Введите новый общий лимит использований (число).\n"
            "Введите 0 для безлимита.\n\nДля отмены: /cancel"
        )
    await callback.answer()


@router.message(AdminPanelStates.waiting_for_promo_limit_edit)
async def msg_promo_limit_edit(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        await state.clear()
        return
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return
    try:
        value = int(text)
        if value < 0:
            await message.answer("Число не может быть отрицательным.")
            return
    except ValueError:
        await message.answer("Введите целое число.")
        return

    data = await state.get_data()
    promo_id = data["promo_id"]
    new_limit = value if value > 0 else None

    async with AsyncSessionFactory() as session:
        service = PromoCodeService(session)
        await service.update(promo_id, max_uses_total=new_limit)
        await session.commit()
        promo = await service.get_by_id(promo_id)

    logger.info(
        "admin_changed_promocode_limit",
        extra={
            "admin_telegram_id": message.from_user.id,
            "promo_id": promo_id,
            "new_limit": new_limit,
        },
    )

    display = str(new_limit) if new_limit else "∞"
    await message.answer(f"✅ Лимит изменён на <b>{display}</b>")
    if promo:
        await message.answer(_promo_card_text(promo), reply_markup=admin_promo_card(promo))
    await state.clear()


@router.callback_query(F.data.startswith("ap:promo:") & F.data.endswith(":edit_expires"))
async def cb_promo_edit_expires(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    parts = callback.data.split(":")
    promo_id = int(parts[2])
    await state.update_data(promo_id=promo_id)
    await state.set_state(AdminPanelStates.waiting_for_promo_expires_edit)
    if callback.message:
        await callback.message.answer(
            "Введите новую дату окончания в формате ДД.ММ.ГГГГ.\n"
            "Введите 'без срока' для бессрочного промокода.\n\nДля отмены: /cancel"
        )
    await callback.answer()


@router.message(AdminPanelStates.waiting_for_promo_expires_edit)
async def msg_promo_expires_edit(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        await state.clear()
        return
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return

    new_expires: datetime | None = None
    if text.lower() not in ("без срока", "бессрочно", "0"):
        try:
            new_expires = datetime.strptime(text, "%d.%m.%Y").replace(tzinfo=UTC)
        except ValueError:
            await message.answer("Некорректная дата. Формат: ДД.ММ.ГГГГ или 'без срока'.")
            return
        if new_expires < datetime.now(tz=UTC):
            await message.answer("Дата окончания не может быть в прошлом.")
            return

    data = await state.get_data()
    promo_id = data["promo_id"]

    async with AsyncSessionFactory() as session:
        service = PromoCodeService(session)
        await service.update(promo_id, expires_at=new_expires)
        await session.commit()
        promo = await service.get_by_id(promo_id)

    logger.info(
        "admin_changed_promocode_expiration",
        extra={
            "admin_telegram_id": message.from_user.id,
            "promo_id": promo_id,
            "expires_at": str(new_expires),
        },
    )

    display = _fmt_dt(new_expires) if new_expires else "бессрочно"
    await message.answer(f"✅ Срок действия: <b>{display}</b>")
    if promo:
        await message.answer(_promo_card_text(promo), reply_markup=admin_promo_card(promo))
    await state.clear()


# ============================================================
# PROMO SEARCH
# ============================================================


@router.callback_query(F.data == "ap:promo:search")
async def cb_promo_search_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    await state.set_state(AdminPanelStates.waiting_for_promo_search)
    if callback.message:
        await callback.message.answer("Введите код промокода для поиска.\n\nДля отмены: /cancel")
    await callback.answer()


@router.message(AdminPanelStates.waiting_for_promo_search)
async def msg_promo_search(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        await state.clear()
        return
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return

    normalized = normalize_code(text)
    async with AsyncSessionFactory() as session:
        service = PromoCodeService(session)
        promo = await service.get_by_code(normalized)

    if not promo:
        await message.answer(f"Промокод <code>{_h(normalized)}</code> не найден.")
        await state.clear()
        return

    await message.answer(_promo_card_text(promo), reply_markup=admin_promo_card(promo))
    await state.clear()


# ============================================================
# PROMO CREATE FSM
# ============================================================


@router.callback_query(F.data == "ap:promo:create")
async def cb_promo_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    await state.set_state(AdminPanelStates.waiting_for_promo_code)
    await state.update_data(
        promo_data={},
        selected_tariffs=[],
        selected_periods=[],
    )
    if callback.message:
        await callback.message.answer(
            "➕ <b>Создание промокода</b>\n\n"
            "Шаг 1/10: Введите код промокода.\n"
            "Только латинские буквы, цифры, дефис, подчёркивание.\n"
            "Пример: START10\n\nДля отмены: /cancel"
        )
    await callback.answer()


@router.message(AdminPanelStates.waiting_for_promo_code)
async def msg_promo_create_code(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        await state.clear()
        return
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Создание отменено.")
        return

    code = normalize_code(text)
    import re

    if not re.match(r"^[A-Z0-9_-]+$", code):
        await message.answer(
            "Некорректный код. Только латинские буквы, цифры, дефис и подчёркивание."
        )
        return

    async with AsyncSessionFactory() as session:
        service = PromoCodeService(session)
        if await service.get_by_code(code):
            await message.answer(f"Промокод <code>{_h(code)}</code> уже существует.")
            return

    data = await state.get_data()
    promo_data = data.get("promo_data", {})
    promo_data["code"] = code
    await state.update_data(promo_data=promo_data)
    await state.set_state(AdminPanelStates.waiting_for_promo_name)
    await message.answer("Шаг 2/10: Введите название промокода.\nПример: Стартовая скидка")


@router.message(AdminPanelStates.waiting_for_promo_name)
async def msg_promo_create_name(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        await state.clear()
        return
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Создание отменено.")
        return

    data = await state.get_data()
    promo_data = data.get("promo_data", {})
    promo_data["name"] = text
    await state.update_data(promo_data=promo_data)
    await state.set_state(AdminPanelStates.waiting_for_promo_type)
    await message.answer(
        "Шаг 3/10: Выберите тип промокода.",
        reply_markup=admin_promo_type_select(),
    )


@router.callback_query(AdminPanelStates.waiting_for_promo_type, F.data.startswith("ap:promo:type:"))
async def cb_promo_create_type(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    promo_type = callback.data.split(":")[3]
    data = await state.get_data()
    promo_data = data.get("promo_data", {})
    promo_data["promo_type"] = promo_type
    await state.update_data(promo_data=promo_data)
    await state.set_state(AdminPanelStates.waiting_for_promo_value)

    if promo_type == PromoType.PERCENT_DISCOUNT:
        prompt = "Шаг 4/10: Введите процент скидки (1-100)."
    elif promo_type == PromoType.FIXED_DISCOUNT:
        prompt = "Шаг 4/10: Введите сумму скидки в рублях (≥ 1)."
    else:
        prompt = "Шаг 4/10: Введите количество бесплатных дней (≥ 1)."

    if callback.message:
        await callback.message.answer(prompt)
    await callback.answer()


@router.message(AdminPanelStates.waiting_for_promo_value)
async def msg_promo_create_value(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        await state.clear()
        return
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Создание отменено.")
        return

    data = await state.get_data()
    promo_data = data.get("promo_data", {})
    promo_type = promo_data.get("promo_type", "")

    try:
        value = int(text)
    except ValueError:
        await message.answer("Введите целое число.")
        return

    if promo_type == PromoType.PERCENT_DISCOUNT:
        if value < 1 or value > 100:
            await message.answer("Процент должен быть от 1 до 100.")
            return
        promo_data["discount_percent"] = value
    elif promo_type == PromoType.FIXED_DISCOUNT:
        if value < 1:
            await message.answer("Сумма должна быть ≥ 1.")
            return
        promo_data["discount_amount"] = value
    else:
        if value < 1:
            await message.answer("Количество дней должно быть ≥ 1.")
            return
        promo_data["free_days"] = value

    await state.update_data(promo_data=promo_data)

    async with AsyncSessionFactory() as session:
        service = TariffService(session)
        tariffs = await service.get_all_tariffs()

    await state.set_state(AdminPanelStates.waiting_for_promo_tariffs)
    await message.answer(
        "Шаг 5/10: Выберите тарифы (или пропустите для всех).",
        reply_markup=admin_promo_tariffs_select(tariffs, set()),
    )


@router.callback_query(
    AdminPanelStates.waiting_for_promo_tariffs, F.data.startswith("ap:promo:sel_tariff:")
)
async def cb_promo_toggle_tariff(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    tariff_id = int(callback.data.split(":")[3])
    data = await state.get_data()
    selected = set(data.get("selected_tariffs", []))
    if tariff_id in selected:
        selected.discard(tariff_id)
    else:
        selected.add(tariff_id)
    await state.update_data(selected_tariffs=list(selected))

    async with AsyncSessionFactory() as session:
        service = TariffService(session)
        tariffs = await service.get_all_tariffs()

    if callback.message:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=admin_promo_tariffs_select(tariffs, selected)
            )
        except Exception:
            pass
    await callback.answer()


@router.callback_query(
    AdminPanelStates.waiting_for_promo_tariffs, F.data == "ap:promo:tariffs_done"
)
async def cb_promo_tariffs_done(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    data = await state.get_data()
    selected = data.get("selected_tariffs", [])
    promo_data = data.get("promo_data", {})
    promo_data["tariff_ids"] = selected if selected else None
    await state.update_data(promo_data=promo_data)
    await state.set_state(AdminPanelStates.waiting_for_promo_periods)
    if callback.message:
        await callback.message.answer(
            "Шаг 6/10: Выберите периоды (или пропустите для всех).",
            reply_markup=admin_promo_periods_select(set()),
        )
    await callback.answer()


@router.callback_query(
    AdminPanelStates.waiting_for_promo_tariffs, F.data == "ap:promo:tariffs_skip"
)
async def cb_promo_tariffs_skip(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    data = await state.get_data()
    promo_data = data.get("promo_data", {})
    promo_data["tariff_ids"] = None
    await state.update_data(promo_data=promo_data, selected_tariffs=[])
    await state.set_state(AdminPanelStates.waiting_for_promo_periods)
    if callback.message:
        await callback.message.answer(
            "Шаг 6/10: Выберите периоды (или пропустите для всех).",
            reply_markup=admin_promo_periods_select(set()),
        )
    await callback.answer()


@router.callback_query(
    AdminPanelStates.waiting_for_promo_periods, F.data.startswith("ap:promo:sel_period:")
)
async def cb_promo_toggle_period(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    period = callback.data.split(":")[3]
    data = await state.get_data()
    selected = set(data.get("selected_periods", []))
    if period in selected:
        selected.discard(period)
    else:
        selected.add(period)
    await state.update_data(selected_periods=list(selected))
    if callback.message:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=admin_promo_periods_select(selected)
            )
        except Exception:
            pass
    await callback.answer()


@router.callback_query(
    AdminPanelStates.waiting_for_promo_periods, F.data == "ap:promo:periods_done"
)
async def cb_promo_periods_done(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    data = await state.get_data()
    selected = data.get("selected_periods", [])
    promo_data = data.get("promo_data", {})
    promo_data["periods"] = selected if selected else None
    await state.update_data(promo_data=promo_data)
    await state.set_state(AdminPanelStates.waiting_for_promo_total_limit)
    if callback.message:
        await callback.message.answer(
            "Шаг 7/10: Введите общий лимит использований (число).\nВведите 0 для безлимита."
        )
    await callback.answer()


@router.callback_query(
    AdminPanelStates.waiting_for_promo_periods, F.data == "ap:promo:periods_skip"
)
async def cb_promo_periods_skip(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    data = await state.get_data()
    promo_data = data.get("promo_data", {})
    promo_data["periods"] = None
    await state.update_data(promo_data=promo_data, selected_periods=[])
    await state.set_state(AdminPanelStates.waiting_for_promo_total_limit)
    if callback.message:
        await callback.message.answer(
            "Шаг 7/10: Введите общий лимит использований (число).\nВведите 0 для безлимита."
        )
    await callback.answer()


@router.message(AdminPanelStates.waiting_for_promo_total_limit)
async def msg_promo_create_total_limit(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        await state.clear()
        return
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Создание отменено.")
        return
    try:
        value = int(text)
        if value < 0:
            await message.answer("Число не может быть отрицательным.")
            return
    except ValueError:
        await message.answer("Введите целое число.")
        return

    data = await state.get_data()
    promo_data = data.get("promo_data", {})
    promo_data["max_uses_total"] = value if value > 0 else None
    await state.update_data(promo_data=promo_data)
    await state.set_state(AdminPanelStates.waiting_for_promo_user_limit)
    await message.answer("Шаг 8/10: Введите лимит на одного пользователя (по умолчанию 1).")


@router.message(AdminPanelStates.waiting_for_promo_user_limit)
async def msg_promo_create_user_limit(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        await state.clear()
        return
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Создание отменено.")
        return
    try:
        value = int(text)
        if value < 1:
            await message.answer("Лимит должен быть ≥ 1.")
            return
    except ValueError:
        await message.answer("Введите целое число ≥ 1.")
        return

    data = await state.get_data()
    promo_data = data.get("promo_data", {})
    promo_data["max_uses_per_user"] = value
    await state.update_data(promo_data=promo_data)
    await state.set_state(AdminPanelStates.waiting_for_promo_expires)
    await message.answer("Шаг 9/10: Введите дату окончания (ДД.ММ.ГГГГ) или 'без срока'.")


@router.message(AdminPanelStates.waiting_for_promo_expires)
async def msg_promo_create_expires(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer(_deny_text())
        await state.clear()
        return
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Создание отменено.")
        return

    expires_at: datetime | None = None
    if text.lower() not in ("без срока", "бессрочно", "0", ""):
        try:
            expires_at = datetime.strptime(text, "%d.%m.%Y").replace(tzinfo=UTC)
        except ValueError:
            await message.answer("Некорректная дата. Формат: ДД.ММ.ГГГГ или 'без срока'.")
            return
        if expires_at < datetime.now(tz=UTC):
            await message.answer("Дата окончания не может быть в прошлом.")
            return

    data = await state.get_data()
    promo_data = data.get("promo_data", {})
    promo_data["expires_at"] = expires_at
    await state.update_data(promo_data=promo_data)
    await state.set_state(AdminPanelStates.waiting_for_promo_new_users)
    await message.answer(
        "Шаг 10/10: Промокод только для новых пользователей?",
        reply_markup=admin_promo_new_users_select(),
    )


@router.callback_query(
    AdminPanelStates.waiting_for_promo_new_users,
    F.data.startswith("ap:promo:new_users:"),
)
async def cb_promo_create_new_users(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    only_new = callback.data.split(":")[3] == "yes"
    data = await state.get_data()
    promo_data = data.get("promo_data", {})
    promo_data["only_for_new_users"] = only_new
    await state.update_data(promo_data=promo_data)
    await state.set_state(AdminPanelStates.waiting_for_promo_confirm)

    text = _promo_confirm_text(promo_data)
    if callback.message:
        await callback.message.answer(text, reply_markup=admin_promo_confirm_cancel())
    await callback.answer()


def _promo_confirm_text(pd: dict) -> str:
    promo_type = pd.get("promo_type", "")
    type_label = _PROMO_TYPE_LABELS.get(promo_type, promo_type)

    if promo_type == PromoType.PERCENT_DISCOUNT:
        discount = f"скидка {pd.get('discount_percent', '?')}%"
    elif promo_type == PromoType.FIXED_DISCOUNT:
        discount = f"скидка {pd.get('discount_amount', '?')} ₽"
    else:
        discount = f"{pd.get('free_days', '?')} дней"

    total = str(pd.get("max_uses_total")) if pd.get("max_uses_total") else "∞"
    per_user = pd.get("max_uses_per_user", 1)
    expires = _fmt_dt(pd.get("expires_at")) if pd.get("expires_at") else "бессрочно"
    new_only = "Да" if pd.get("only_for_new_users") else "Нет"

    tariff_ids = pd.get("tariff_ids")
    tariffs_text = ", ".join(str(t) for t in tariff_ids) if tariff_ids else "Все"

    periods = pd.get("periods")
    periods_text = ", ".join(_PERIOD_LABELS.get(p, p) for p in periods) if periods else "Все"

    lines = [
        "🎟 <b>Проверьте промокод перед созданием</b>",
        "",
        f"Код: <code>{_h(pd.get('code', ''))}</code>",
        f"Название: {_h(pd.get('name', ''))}",
        f"Тип: {_h(type_label)} — {discount}",
        f"Тарифы: {_h(tariffs_text)}",
        f"Периоды: {_h(periods_text)}",
        f"Общий лимит: {total}",
        f"На пользователя: {per_user}",
        f"Срок: до {expires}",
        f"Только для новых: {new_only}",
        "",
        "Создать промокод?",
    ]
    return "\n".join(lines)


@router.callback_query(
    AdminPanelStates.waiting_for_promo_confirm, F.data == "ap:promo:confirm_create"
)
async def cb_promo_confirm_create(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(_deny_text(), show_alert=True)
        return
    data = await state.get_data()
    pd = data.get("promo_data", {})

    expires_at = pd.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = None

    discount_amount = pd.get("discount_amount")
    if discount_amount is not None:
        discount_amount = Decimal(str(discount_amount))

    try:
        async with AsyncSessionFactory() as session:
            service = PromoCodeService(session)
            promo = await service.create(
                code=pd["code"],
                name=pd["name"],
                promo_type=pd["promo_type"],
                discount_percent=pd.get("discount_percent"),
                discount_amount=discount_amount,
                free_days=pd.get("free_days"),
                is_active=True,
                expires_at=expires_at,
                max_uses_total=pd.get("max_uses_total"),
                max_uses_per_user=pd.get("max_uses_per_user", 1),
                only_for_new_users=pd.get("only_for_new_users", False),
                created_by_admin_id=callback.from_user.id,
                tariff_ids=pd.get("tariff_ids"),
                periods=pd.get("periods"),
            )
            await session.commit()

        logger.info(
            "admin_created_promocode",
            extra={
                "admin_telegram_id": callback.from_user.id,
                "promo_code": promo.code,
                "promo_id": promo.id,
            },
        )

        if callback.message:
            await callback.message.answer(
                f"✅ Промокод <code>{_h(promo.code)}</code> создан!",
                reply_markup=admin_promo_card(promo),
            )
    except PromoValidationError as e:
        if callback.message:
            await callback.message.answer(f"❌ Ошибка: {_h(str(e))}")
    except Exception:
        logger.exception("admin_promo_create_failed")
        if callback.message:
            await callback.message.answer("❌ Не удалось создать промокод.")

    await state.clear()
    await callback.answer()


# ============================================================
# NOOP callback (for pagination display)
# ============================================================


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()
