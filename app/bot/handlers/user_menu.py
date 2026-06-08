# ruff: noqa: E501
"""version: 1.0.0
description: User menu bot handlers (profile, tariff, API keys, notifications, support).
"""

import logging
from datetime import datetime
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main import (
    user_api_keys_menu,
    user_menu,
    user_notifications_menu,
    user_profile_menu,
    user_support_menu,
    user_tariff_menu,
)
from app.bot.states import PaymentStates
from app.core.config import get_settings
from app.core.db import get_session
from app.models.domain import MarketplaceAccount, User
from app.models.enums import Marketplace
from app.services.commission_tariffs.admin_notifications import notify_admins
from app.services.profile_service import ProfileService, ProfileUpdateData, ProfileValidationError
from app.services.subscription_service import SubscriptionService
from app.services.support_service import SupportService
from app.services.user_activity_service import UserActivityService
from app.utils.datetime import format_datetime_for_user

logger = logging.getLogger(__name__)
router = Router(name="user_menu")


def _dt(dt_value: datetime | None, timezone: str) -> str:
    if dt_value is None:
        return "н/д"
    return format_datetime_for_user(dt_value, timezone, "%d.%m.%Y %H:%M")


@router.callback_query(F.data == "user:menu")
async def show_user_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "👤 <b>Меню пользователя</b>\n\nВыберите раздел:",
        reply_markup=user_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "user:profile")
async def show_user_profile(callback: CallbackQuery) -> None:
    async for session in get_session():
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        tier = await SubscriptionService(session).get_user_tier(user.id)

        text = (
            "👤 <b>Ваш профиль</b>\n\n"
            f"<b>Имя:</b> {user.first_name or 'н/д'}\n"
            f"<b>Фамилия:</b> {user.last_name or 'н/д'}\n"
            f"<b>Телефон:</b> {user.phone or 'н/д'}\n"
            f"<b>Email:</b> {user.email or 'н/д'}\n"
            f"<b>Компания:</b> {user.company_name or 'н/д'}\n"
            f"<b>ИНН:</b> {user.inn or 'н/д'}\n"
            f"<b>ОГРН:</b> {user.ogrn or 'н/д'}\n\n"
            f"<b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
            f"<b>Username:</b> {('@' + user.username) if user.username else 'н/д'}\n"
            f"<b>Часовой пояс:</b> {user.timezone}\n"
            f"<b>Тариф:</b> {tier.name}\n"
            f"<b>Дата регистрации:</b> {_dt(user.created_at, user.timezone)}\n"
            f"<b>Последняя активность:</b> {_dt(user.last_activity_at, user.timezone)}\n"
        )

        await callback.message.edit_text(
            text,
            reply_markup=user_profile_menu(),
            parse_mode="HTML",
        )
        await callback.answer()
        break


@router.callback_query(F.data == "user:tariff")
async def show_user_tariff(callback: CallbackQuery) -> None:
    async for session in get_session():
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        sub_service = SubscriptionService(session)
        tier = await sub_service.get_user_tier(user.id)
        subscription = await sub_service.get_active_subscription(user.id)

        status = (
            "Активна" if subscription and subscription.status.value == "ACTIVE" else "Неактивна"
        )
        expires = (
            _dt(subscription.expires_at, user.timezone)
            if subscription and subscription.expires_at
            else "бессрочно"
        )

        text = (
            "💳 <b>Ваш тариф</b>\n\n"
            f"<b>Тариф:</b> {tier.name}\n"
            f"<b>Статус:</b> {status}\n"
            f"<b>Действует до:</b> {expires}\n\n"
            f"<b>Лимиты тарифа:</b>\n"
            f"• Кабинетов МП: {tier.max_marketplace_accounts}\n"
            f"• Заказов в месяц: {tier.max_orders_per_month or 'без лимита'}\n"
            f"• Товаров: {tier.max_products or 'без лимита'}\n"
            f"• Интервал синхронизации: {tier.sync_interval_minutes} мин\n\n"
            f"<b>Доступные функции:</b>\n"
            f"{'✅' if tier.feature_web_cabinet else '❌'} Web-кабинет\n"
            f"{'✅' if tier.feature_analytics else '❌'} Расширенная аналитика\n"
            f"{'✅' if tier.feature_plan_fact else '❌'} План/факт\n"
            f"{'✅' if tier.feature_break_even else '❌'} Безубыточность\n"
            f"{'✅' if tier.feature_stock_forecast else '❌'} Прогноз остатков\n"
            f"{'✅' if tier.feature_alerts else '❌'} Алерты\n"
        )

        await callback.message.edit_text(
            text,
            reply_markup=user_tariff_menu(tier.code),
            parse_mode="HTML",
        )
        await callback.answer()
        break


@router.callback_query(F.data == "user:api_keys")
async def show_user_api_keys(callback: CallbackQuery) -> None:
    async for session in get_session():
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        stmt = select(MarketplaceAccount).where(
            MarketplaceAccount.user_id == user.id,
            MarketplaceAccount.is_active.is_(True),
        )
        result = await session.execute(stmt)
        accounts = list(result.scalars().all())

        if not accounts:
            text = (
                "🔑 <b>API-ключи</b>\n\n"
                "У вас пока нет подключённых кабинетов.\n\n"
                "Подключите Wildberries или Ozon через меню настроек."
            )
        else:
            lines = ["🔑 <b>API-ключи</b>\n\n"]
            for acc in accounts:
                mp = "Wildberries" if acc.marketplace == Marketplace.WB else "Ozon"
                status_labels = {
                    "active": "✅ Активен",
                    "auth_error": "❌ Ошибка авторизации",
                    "insufficient_permissions": "⚠️ Недостаточно прав",
                    "expired": "⏰ Истёк",
                    "unchecked": "❓ Не проверен",
                    "pending_check": "⏳ Ожидает проверки",
                }
                api_status = status_labels.get(
                    acc.api_key_status or "unchecked", acc.api_key_status
                )
                lines.append(
                    f"<b>{acc.name}</b> ({mp})\n"
                    f"Статус: {api_status}\n"
                    f"Проверен: {_dt(acc.api_key_checked_at, user.timezone)}\n\n"
                )
            text = "".join(lines)

        await callback.message.edit_text(
            text,
            reply_markup=user_api_keys_menu(),
            parse_mode="HTML",
        )
        await callback.answer()
        break


@router.callback_query(F.data == "user:check_wb")
async def check_wb_key(callback: CallbackQuery) -> None:
    async for session in get_session():
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        stmt = select(MarketplaceAccount).where(
            MarketplaceAccount.user_id == user.id,
            MarketplaceAccount.marketplace == Marketplace.WB,
            MarketplaceAccount.is_active.is_(True),
        )
        result = await session.execute(stmt)
        account = result.scalar_one_or_none()

        if account is None:
            await callback.answer("Кабинет WB не найден", show_alert=True)
            return

        await callback.answer("Проверяю ключ...", show_alert=False)

        from app.core.security import TokenCipher
        from app.services.api_key_validation_service import ApiKeyValidationService

        cipher = TokenCipher()
        validator = ApiKeyValidationService(session, cipher)
        check_result = await validator.check_account(account)

        await UserActivityService(session).log_activity(
            account.user_id,
            "api_key_checked",
            entity_type="marketplace_account",
            entity_id=account.id,
            details={"marketplace": "WB", "result": check_result.status},
        )

        await callback.message.edit_text(
            f"🔑 <b>Проверка WB ключа</b>\n\n"
            f"<b>Результат:</b> {check_result.message}\n"
            f"<b>Статус:</b> {check_result.status}\n"
            f"<b>Доступные права:</b> {', '.join(check_result.permissions) or 'нет'}\n"
            f"<b>Недостающие права:</b> {', '.join(check_result.missing_permissions) or 'все есть'}\n",
            reply_markup=user_api_keys_menu(),
            parse_mode="HTML",
        )
        break


@router.callback_query(F.data == "user:check_ozon")
async def check_ozon_key(callback: CallbackQuery) -> None:
    async for session in get_session():
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        stmt = select(MarketplaceAccount).where(
            MarketplaceAccount.user_id == user.id,
            MarketplaceAccount.marketplace == Marketplace.OZON,
            MarketplaceAccount.is_active.is_(True),
        )
        result = await session.execute(stmt)
        account = result.scalar_one_or_none()

        if account is None:
            await callback.answer("Кабинет Ozon не найден", show_alert=True)
            return

        await callback.answer("Проверяю ключ...", show_alert=False)

        from app.core.security import TokenCipher
        from app.services.api_key_validation_service import ApiKeyValidationService

        cipher = TokenCipher()
        validator = ApiKeyValidationService(session, cipher)
        check_result = await validator.check_account(account)

        await UserActivityService(session).log_activity(
            account.user_id,
            "api_key_checked",
            entity_type="marketplace_account",
            entity_id=account.id,
            details={"marketplace": "OZON", "result": check_result.status},
        )

        await callback.message.edit_text(
            f"🔑 <b>Проверка Ozon ключа</b>\n\n"
            f"<b>Результат:</b> {check_result.message}\n"
            f"<b>Статус:</b> {check_result.status}\n"
            f"<b>Доступные права:</b> {', '.join(check_result.permissions) or 'нет'}\n"
            f"<b>Недостающие права:</b> {', '.join(check_result.missing_permissions) or 'все есть'}\n",
            reply_markup=user_api_keys_menu(),
            parse_mode="HTML",
        )
        break


@router.callback_query(F.data == "user:notifications")
async def show_user_notifications(callback: CallbackQuery) -> None:
    async for session in get_session():
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        status = "включены ✅" if user.notifications_enabled else "выключены ❌"
        text = (
            "🔔 <b>Уведомления</b>\n\n"
            f"<b>Telegram-уведомления:</b> {status}\n\n"
            "Вы можете включить или отключить уведомления,\n"
            "а также настроить типы уведомлений."
        )

        await callback.message.edit_text(
            text,
            reply_markup=user_notifications_menu(user.notifications_enabled),
            parse_mode="HTML",
        )
        await callback.answer()
        break


@router.callback_query(F.data == "user:marketplaces")
async def show_user_marketplaces(callback: CallbackQuery) -> None:
    async for session in get_session():
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        stmt = select(MarketplaceAccount).where(
            MarketplaceAccount.user_id == user.id,
            MarketplaceAccount.is_active.is_(True),
        )
        result = await session.execute(stmt)
        accounts = list(result.scalars().all())

        if not accounts:
            text = (
                "🛒 <b>Кабинеты маркетплейсов</b>\n\n"
                "У вас пока нет подключённых кабинетов.\n\n"
                "Подключите Wildberries или Ozon через меню настроек."
            )
        else:
            lines = ["🛒 <b>Кабинеты маркетплейсов</b>\n\n"]
            for acc in accounts:
                mp = "Wildberries" if acc.marketplace == Marketplace.WB else "Ozon"
                lines.append(
                    f"<b>{acc.name}</b> ({mp})\n"
                    f"Статус: {acc.status.value}\n"
                    f"Последняя синхронизация: {_dt(acc.last_success_sync_at, user.timezone)}\n\n"
                )
            text = "".join(lines)

        from app.bot.keyboards.main import settings_menu

        await callback.message.edit_text(
            text,
            reply_markup=settings_menu(),
            parse_mode="HTML",
        )
        await callback.answer()
        break


@router.callback_query(F.data == "user:promo")
async def show_promo_input(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PaymentStates.waiting_promo_code)
    await callback.message.edit_text(
        "🎁 <b>Промокод</b>\n\n"
        "Введите промокод для получения скидки:\n\n"
        "<i>Отправьте /cancel для отмены</i>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "user:settings")
async def show_user_settings(callback: CallbackQuery) -> None:
    async for session in get_session():
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        from app.bot.keyboards.main import settings_menu

        await callback.message.edit_text(
            "⚙️ <b>Настройки</b>\n\nВыберите действие:",
            reply_markup=settings_menu(),
            parse_mode="HTML",
        )
        await callback.answer()
        break


@router.callback_query(F.data == "user:support")
async def show_user_support(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🆘 <b>Поддержка</b>\n\n"
        "Если у вас возникли вопросы или проблемы,\n"
        "напишите в поддержку через web-кабинет\n"
        "или свяжитесь с нами в Telegram.",
        reply_markup=user_support_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "user:support_new")
async def start_support_ticket(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PaymentStates.waiting_support_message)
    await callback.message.edit_text(
        "🆘 <b>Новое обращение</b>\n\n"
        "Напишите текст обращения одним сообщением:\n\n"
        "<i>Отправьте /cancel для отмены</i>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "user:support_list")
async def show_support_tickets(callback: CallbackQuery) -> None:
    async for session in get_session():
        user = await _get_user(session, callback.from_user.id)
        if user is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        tickets = await SupportService(session).get_user_tickets(user.id, limit=10)

        if not tickets:
            text = "🆘 <b>Мои обращения</b>\n\nУ вас пока нет обращений в поддержку."
        else:
            lines = ["🆘 <b>Мои обращения</b>\n\n"]
            for t in tickets:
                status_labels = {
                    "new": "Новое",
                    "in_progress": "В работе",
                    "answered": "Дан ответ",
                    "closed": "Закрыто",
                    "rejected": "Отклонено",
                    "open": "Открыто",
                    "responded": "Отвечено",
                }
                status = status_labels.get(t.status, t.status)
                lines.append(
                    f"<b>#{t.id} {escape(t.subject)}</b>\n"
                    f"Статус: {status}\n"
                    f"Дата: {_dt(t.created_at, user.timezone)}\n\n"
                )
            text = "".join(lines)

        await callback.message.edit_text(
            text,
            reply_markup=user_support_menu(),
            parse_mode="HTML",
        )
        await callback.answer()
        break


@router.callback_query(F.data == "user:edit_email")
async def start_edit_email(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PaymentStates.waiting_email)
    await callback.message.edit_text(
        "📧 <b>Изменение email</b>\n\nВведите новый email:\n\n<i>Отправьте /cancel для отмены</i>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "user:edit_phone")
async def start_edit_phone(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PaymentStates.waiting_phone)
    await callback.message.edit_text(
        "📱 <b>Изменение телефона</b>\n\n"
        "Введите новый телефон (например, +7 900 123-45-67):\n\n"
        "<i>Отправьте /cancel для отмены</i>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(PaymentStates.waiting_email)
async def process_email_input(message: Message, state: FSMContext) -> None:
    if message.text and message.text.startswith("/cancel"):
        await state.clear()
        await message.answer("Отменено.")
        return

    async for session in get_session():
        try:
            user = await _get_user(session, message.from_user.id if message.from_user else 0)
            if user is None:
                await message.answer("Пользователь не найден.")
                return
            await ProfileService(session).update_profile(
                user.id,
                ProfileUpdateData(email=message.text),
            )
            await state.clear()
            await message.answer(
                f"✅ Email успешно обновлён: {message.text}",
                reply_markup=user_profile_menu(),
            )
        except ProfileValidationError as exc:
            await message.answer(f"❌ Ошибка: {exc}\n\nПопробуйте ещё раз или отправьте /cancel")
        break


@router.message(PaymentStates.waiting_phone)
async def process_phone_input(message: Message, state: FSMContext) -> None:
    if message.text and message.text.startswith("/cancel"):
        await state.clear()
        await message.answer("Отменено.")
        return

    async for session in get_session():
        try:
            user = await _get_user(session, message.from_user.id if message.from_user else 0)
            if user is None:
                await message.answer("Пользователь не найден.")
                return
            await ProfileService(session).update_profile(
                user.id,
                ProfileUpdateData(phone=message.text),
            )
            await state.clear()
            await message.answer(
                f"✅ Телефон успешно обновлён: {message.text}",
                reply_markup=user_profile_menu(),
            )
        except ProfileValidationError as exc:
            await message.answer(f"❌ Ошибка: {exc}\n\nПопробуйте ещё раз или отправьте /cancel")
        break


@router.message(PaymentStates.waiting_support_subject)
async def process_support_subject(message: Message, state: FSMContext) -> None:
    if message.text and message.text.startswith("/cancel"):
        await state.clear()
        await message.answer("Отменено.")
        return

    await state.update_data(support_subject=message.text)
    await state.set_state(PaymentStates.waiting_support_message)
    await message.answer("Тема принята. Теперь опишите подробно вашу проблему или вопрос:")


@router.message(PaymentStates.waiting_support_message)
async def process_support_message(message: Message, state: FSMContext) -> None:
    if message.text and message.text.startswith("/cancel"):
        await state.clear()
        await message.answer("Отменено.")
        return

    data = await state.get_data()
    raw_text = (message.text or "").strip()
    subject = data.get("support_subject") or raw_text[:80] or "Обращение"

    async for session in get_session():
        try:
            user = await _get_user(session, message.from_user.id)
            if user is None:
                await message.answer("Пользователь не найден.")
                return

            ticket = await SupportService(session).create_ticket(
                user_id=user.id,
                subject=subject,
                message=raw_text,
            )
            await UserActivityService(session).log_activity(
                user.id,
                "support_ticket_created",
                details={"subject": subject, "ticket_id": ticket.id},
            )
            await state.clear()
            await message.answer(
                f"✅ Обращение принято. Номер обращения: #{ticket.id}. "
                "Администратор рассмотрит его в ближайшее время.",
                reply_markup=user_support_menu(),
            )
            await _notify_admins_about_ticket(message, user, ticket.id, raw_text)
        except Exception:
            logger.exception(
                "support_ticket_create_failed",
                extra={"telegram_id": message.from_user.id if message.from_user else None},
            )
            await message.answer(
                "❌ Не удалось сохранить обращение. Попробуйте позже.",
                reply_markup=user_support_menu(),
            )
        break


async def _notify_admins_about_ticket(
    message: Message,
    user: User,
    ticket_id: int,
    ticket_text: str,
) -> None:
    admin_url = f"{get_settings().get_web_base_url()}/web/admin/support/{ticket_id}"
    full_name = " ".join(part for part in (user.first_name, user.last_name) if part) or "н/д"
    username = f"@{user.username}" if user.username else "н/д"
    created = format_datetime_for_user(datetime.now(), "Europe/Moscow", "%d.%m.%Y %H:%M")
    text = (
        "🆘 <b>Новое обращение пользователя</b>\n\n"
        f"Номер: #{ticket_id}\n"
        f"Пользователь: {escape(full_name)}\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Username: {escape(username)}\n\n"
        "Текст обращения:\n"
        f"{escape(ticket_text)}\n\n"
        f"Дата: {created}"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👁 Открыть в админке", url=admin_url)],
        ]
    )
    sent = await notify_admins(message.bot, text, reply_markup=keyboard)
    if sent == 0:
        logger.warning(
            "support_ticket_admin_notification_no_recipients", extra={"ticket_id": ticket_id}
        )


async def _get_user(session: AsyncSession, telegram_id: int) -> User | None:
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
