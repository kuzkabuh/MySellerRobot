"""version: 3.0.0
description: Telegram bot handlers for subscription management, admin tariff control,
    and centralized formatting.
updated: 2026-05-16
"""

import logging
from html import escape as html_escape
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards.main import (
    admin_tariff_menu,
    admin_tariff_select_menu,
    back_to_settings,
    subscription_cancel_confirm_menu,
    subscription_current_menu_v2,
    subscription_menu,
    subscription_payment_confirm_menu,
    subscription_payments_menu,
    subscription_pricing_menu_v2,
    subscription_tier_detail_menu_v2,
)
from app.bot.states import AdminTariffStates, PaymentStates
from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.repositories.users import UserRepository
from app.services.payment_service import PaymentService
from app.services.subscription_service import SubscriptionService
from app.services.subscription_text_formatter import (
    build_tier_card,
    format_admin_tariff_confirmation,
    format_current_subscription,
    format_pricing_overview,
    format_subscription_help,
    format_tier_card,
    format_user_tariff_notification,
)
from app.utils.datetime import format_datetime_for_user

router = Router(name="subscription")
logger = logging.getLogger(__name__)


def _callback_message(callback: CallbackQuery) -> Message | None:
    """Return editable callback message when Telegram still exposes it."""
    return callback.message if isinstance(callback.message, Message) else None


def _html(value: object | None, fallback: str = "—") -> str:
    """Escape dynamic values before inserting them into Telegram HTML."""
    if value is None or value == "":
        return fallback
    return html_escape(str(value), quote=False)


async def _safe_edit_text(message: Message, text: str, **kwargs: Any) -> None:
    """Safely edit message text, falling back to answer if edit fails."""
    try:
        await message.edit_text(text, **kwargs)
    except Exception as e:
        error_msg = str(e).lower()
        if "there is no text" in error_msg or "message to edit" in error_msg:
            try:
                await message.answer(text, **kwargs)
            except Exception:
                logger.exception("safe_edit_text_fallback_failed")
        else:
            raise


# ============================================================
# PUBLIC SUBSCRIPTION COMMANDS
# ============================================================


@router.message(Command("subscription", "tariff", "pricing"))
async def show_subscription_info(message: Message) -> None:
    """Show subscription main menu."""
    await message.answer("💎 Подписка и тарифы", reply_markup=subscription_menu())


@router.callback_query(F.data == "subscription_menu")
async def subscription_menu_handler(callback: CallbackQuery) -> None:
    """Show subscription main menu."""
    message = _callback_message(callback)
    if not message:
        return
    await _safe_edit_text(message, "💎 Подписка и тарифы", reply_markup=subscription_menu())
    await callback.answer()


# ============================================================
# CURRENT SUBSCRIPTION
# ============================================================


@router.callback_query(F.data == "subscription:current")
async def show_current_subscription(callback: CallbackQuery) -> None:
    """Show current subscription details using centralized formatter."""
    message = _callback_message(callback)
    if not callback.from_user or not message:
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        service = SubscriptionService(session)
        current_tier = await service.get_user_tier(user.id)
        active_subscription = await service.get_active_subscription(user.id)

        is_free = current_tier.code == "free"
        is_active = active_subscription is not None and not is_free
        is_trial = active_subscription.is_trial if active_subscription else False

        expires_at = None
        trial_ends_at = None
        if active_subscription:
            if active_subscription.expires_at:
                expires_at = format_datetime_for_user(
                    active_subscription.expires_at, user.timezone, "%d.%m.%Y"
                )
            if active_subscription.trial_ends_at:
                trial_ends_at = format_datetime_for_user(
                    active_subscription.trial_ends_at, user.timezone, "%d.%m.%Y"
                )

        features = [
            ("Web-кабинет", bool(current_tier.feature_web_cabinet)),
            ("Уведомления о новых заказах", True),
            ("Карточки заказов с плановой прибылью", True),
            ("Расширенная аналитика", bool(current_tier.feature_analytics)),
            ("План/факт анализ", bool(current_tier.feature_plan_fact)),
            ("Безубыточная цена", bool(current_tier.feature_break_even)),
            ("Прогноз остатков", bool(current_tier.feature_stock_forecast)),
            ("Умные алерты", bool(current_tier.feature_alerts)),
        ]

        text = format_current_subscription(
            tier_name=current_tier.name,
            is_active=is_active,
            expires_at=expires_at,
            is_trial=is_trial,
            trial_ends_at=trial_ends_at,
            features=features,
            is_free=is_free,
        )

        await _safe_edit_text(
            message,
            text,
            reply_markup=subscription_current_menu_v2(has_active=is_active),
        )
        await callback.answer()


# ============================================================
# PRICING OVERVIEW
# ============================================================


@router.callback_query(F.data == "subscription:pricing")
async def show_pricing(callback: CallbackQuery) -> None:
    """Show pricing overview using centralized formatter."""
    message = _callback_message(callback)
    if not message:
        return

    async with AsyncSessionFactory() as session:
        service = SubscriptionService(session)
        tiers = await service.get_all_tiers()
        cards = [build_tier_card(t) for t in tiers]

    text = format_pricing_overview(cards)
    await _safe_edit_text(message, text, reply_markup=subscription_pricing_menu_v2())
    await callback.answer()


# ============================================================
# TIER DETAIL CARDS
# ============================================================


@router.callback_query(F.data.startswith("subscription:tier:"))
async def show_tier_details(callback: CallbackQuery) -> None:
    """Show specific tier details using centralized formatter."""
    message = _callback_message(callback)
    if not callback.from_user or not message or not callback.data:
        return

    tier_code = callback.data.split(":")[-1]

    async with AsyncSessionFactory() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        service = SubscriptionService(session)
        current_tier = await service.get_user_tier(user.id)
        tier = await service.get_tier_by_code(tier_code)

        if not tier:
            await callback.answer("Тариф не найден", show_alert=True)
            return

        card = build_tier_card(tier, is_current=(tier.code == current_tier.code))
        settings = get_settings()
        text = format_tier_card(
            card,
            support_username=settings.support_telegram_username,
        )

        await _safe_edit_text(
            message,
            text,
            reply_markup=subscription_tier_detail_menu_v2(
                tier_code=tier.code,
                current_tier_code=current_tier.code,
            ),
        )
        await callback.answer()


# ============================================================
# PAYMENT FLOW
# ============================================================


@router.callback_query(F.data.startswith("subscription:pay:"))
async def handle_payment_initiation(callback: CallbackQuery) -> None:
    """Handle payment initiation."""
    message = _callback_message(callback)
    if not callback.from_user or not message or not callback.data:
        return

    parts = callback.data.split(":")
    tier_code = parts[2]
    period = parts[3]

    async with AsyncSessionFactory() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        service = SubscriptionService(session)
        tier = await service.get_tier_by_code(tier_code)

        if not tier:
            await callback.answer("Тариф не найден", show_alert=True)
            return

        amount = tier.price_monthly if period == "monthly" else tier.price_yearly
        if not amount:
            await callback.answer("Цена не указана для этого периода", show_alert=True)
            return

        period_text = "месяц" if period == "monthly" else "год"
        text = (
            "💳 <b>Подтверждение оплаты</b>\n\n"
            f"Тариф: <b>{_html(tier.name)}</b>\n"
            f"Период: {period_text}\n"
            f"Сумма: <b>{amount} ₽</b>\n\n"
            "После оплаты подписка активируется автоматически."
        )

        await _safe_edit_text(
            message,
            text,
            reply_markup=subscription_payment_confirm_menu(tier_code, period, f"{amount} ₽"),
        )
        await callback.answer()


@router.callback_query(F.data.startswith("subscription:pay_confirm:"))
async def handle_payment_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    """Create payment and send payment link, or prompt for email if missing."""
    message = _callback_message(callback)
    if not callback.from_user or not message or not callback.data:
        return

    parts = callback.data.split(":")
    tier_code = parts[2]
    period = parts[3]

    async with AsyncSessionFactory() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        if user.payment_email:
            await _process_payment(
                callback=callback,
                message=message,
                user=user,
                tier_code=tier_code,
                period=period,
            )
            await callback.answer()
            return

        await state.update_data(tier_code=tier_code, period=period)
        await state.set_state(PaymentStates.waiting_for_email)
        await _safe_edit_text(
            message,
            "Для оплаты необходимо указать ваш e-mail.\n\n"
            "На этот адрес будет отправлен чек от ЮKassa.\n\n"
            "Введите e-mail:",
        )
        await callback.answer()


@router.message(PaymentStates.waiting_for_email)
async def handle_payment_email_input(message: Message, state: FSMContext) -> None:
    """Handle user email input for payment receipt."""
    email = (message.text or "").strip()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        await message.answer("Пожалуйста, введите корректный e-mail.\n\n" "Пример: example@mail.ru")
        return

    data = await state.get_data()
    tier_code = data.get("tier_code")
    period = data.get("period")

    if not tier_code or not period:
        await message.answer("Ошибка: данные платежа не найдены. Начните заново.")
        await state.clear()
        return

    async with AsyncSessionFactory() as session:
        if message.from_user is None:
            await message.answer("Не удалось определить пользователя.")
            await state.clear()
            return
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("Пользователь не найден.")
            await state.clear()
            return

        user.payment_email = email
        await session.commit()

    await state.clear()
    await _process_payment(
        callback=None,
        message=message,
        user=user,
        tier_code=tier_code,
        period=period,
    )


@router.message(PaymentStates.waiting_for_email, Command("cancel"))
async def cancel_payment_email(message: Message, state: FSMContext) -> None:
    """Cancel payment email collection."""
    await state.clear()
    await message.answer("Ввод e-mail отменён.", reply_markup=back_to_settings())


async def _process_payment(
    *,
    callback: CallbackQuery | None,
    message: Message,
    user: Any,
    tier_code: str,
    period: str,
) -> None:
    """Execute payment creation after email is confirmed."""
    settings = get_settings()
    try:
        base_return_url = settings.get_yookassa_return_url()
    except ValueError as exc:
        logger.error("yookassa_return_url_invalid", extra={"error": str(exc)})
        await message.answer(
            "Не удалось создать платёж: некорректно настроен адрес возврата. "
            "Обратитесь в поддержку."
        )
        return

    try:
        async with AsyncSessionFactory() as session:
            payment_service = PaymentService(session)
            payment, confirmation_url = await payment_service.create_subscription_payment(
                user_id=user.id,
                tier_code=tier_code,
                period=period,
                return_url=base_return_url,
                customer_email=user.payment_email,
            )
            await session.commit()

        if confirmation_url:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Перейти к оплате", url=confirmation_url)],
                    [InlineKeyboardButton(text="Назад", callback_data="subscription:pricing")],
                ]
            )

            await _safe_edit_text(
                message,
                "✅ Счет создан!\n\n"
                "Нажмите кнопку ниже для перехода на страницу оплаты.\n\n"
                "После успешной оплаты подписка активируется автоматически.",
                reply_markup=keyboard,
            )
        else:
            retry_cb = f"subscription:pay_confirm:{tier_code}:{period}"
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔄 Попробовать снова",
                            callback_data=retry_cb,
                        )
                    ],
                    [InlineKeyboardButton(text="Назад", callback_data="subscription:pricing")],
                ]
            )

            await _safe_edit_text(
                message,
                "⏳ Платёж ожидает оплаты.\n\n"
                "Ссылка на оплату временно недоступна. "
                "Попробуйте создать новый счёт или обратитесь в поддержку.",
                reply_markup=keyboard,
            )

    except Exception as exc:
        logger.error(
            "payment_creation_failed",
            extra={
                "user_id": user.id,
                "tier_code": tier_code,
                "period": period,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        await message.answer(
            "Не удалось создать платёж. Попробуйте позже.",
        )


# ============================================================
# PAYMENT HISTORY
# ============================================================


@router.callback_query(F.data == "subscription:payments")
async def show_payment_history(callback: CallbackQuery) -> None:
    """Show user's payment history."""
    message = _callback_message(callback)
    if not message or not callback.from_user:
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        payment_service = PaymentService(session)
        payments = await payment_service.get_user_payments(user.id, limit=10)

        if not payments:
            await _safe_edit_text(
                message,
                "📜 <b>История платежей</b>\n\nПлатежей пока нет.",
                reply_markup=subscription_payments_menu(),
            )
            await callback.answer()
            return

        lines = ["📜 <b>История платежей</b>", ""]

        for payment in payments:
            status_emoji = {
                "PENDING": "⏳",
                "SUCCEEDED": "✅",
                "CANCELLED": "❌",
                "FAILED": "❌",
            }.get(payment.status.value, "❓")

            status_text = {
                "PENDING": "Ожидает оплаты",
                "SUCCEEDED": "Оплачен",
                "CANCELLED": "Отменён",
                "FAILED": "Ошибка",
            }.get(payment.status.value, "Неизвестно")

            meta = payment.payment_metadata or {}
            tier_code = meta.get("tier_code", "")
            period = meta.get("period", meta.get("subscription_period", ""))
            period_label = {"monthly": "1 мес", "yearly": "1 год"}.get(period, period)

            tier_info = ""
            if tier_code:
                tier_info = f"\n   Тариф: {_html(tier_code.upper())}, {period_label}"

            receipt_info = ""
            if payment.status.value == "SUCCEEDED":
                receipt_status = payment.receipt_status or ""
                if receipt_status == "succeeded":
                    receipt_info = "\n   Чек: зарегистрирован"
                elif receipt_status == "pending":
                    receipt_info = "\n   Чек: формируется"
                elif payment.receipt_id:
                    receipt_info = "\n   Чек: данные сохранены"
                else:
                    receipt_info = "\n   Чек: отправлен на email"

            lines.append(
                f"{status_emoji} {payment.amount} ₽ — {status_text}\n"
                f"   {format_datetime_for_user(payment.created_at, user.timezone)}"
                f"{tier_info}{receipt_info}"
            )

        await _safe_edit_text(
            message,
            "\n".join(lines),
            reply_markup=subscription_payments_menu(),
        )
        await callback.answer()


# ============================================================
# RECEIPT STATUS
# ============================================================


@router.callback_query(F.data.startswith("subscription:receipt:"))
async def show_receipt_status(callback: CallbackQuery) -> None:
    """Show receipt status for a specific payment."""
    message = _callback_message(callback)
    if not message or not callback.from_user or not callback.data:
        return

    try:
        payment_internal_id = int(callback.data.split(":")[-1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный идентификатор платежа", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        from sqlalchemy import select as sa_select

        from app.models.subscriptions import Payment as PaymentModel

        result = await session.execute(
            sa_select(PaymentModel).where(
                PaymentModel.id == payment_internal_id,
                PaymentModel.user_id == user.id,
            )
        )
        payment = result.scalar_one_or_none()

        if not payment:
            logger.warning(
                "payment_receipt_access_denied",
                extra={
                    "user_id": user.id,
                    "payment_id": payment_internal_id,
                    "telegram_id": callback.from_user.id,
                },
            )
            await callback.answer("Платёж не найден", show_alert=True)
            return

        if payment.status.value != "SUCCEEDED":
            await callback.answer(
                "Чек доступен только для оплаченных платежей",
                show_alert=True,
            )
            return

        payment_service = PaymentService(session)
        receipt_status = await payment_service._fetch_receipt_status(payment)
        await session.commit()

        customer_email = user.payment_email or ""
        masked_email = _mask_email(customer_email) if customer_email else "не указан"

        paid_at_str = format_datetime_for_user(payment.paid_at, user.timezone, "%d.%m.%Y %H:%M")

        if receipt_status == "succeeded":
            text = (
                f"🧾 <b>Чек по платежу</b>\n\n"
                f"Сумма: {payment.amount} ₽\n"
                f"Дата: {paid_at_str}\n\n"
                f"✅ Чек сформирован ЮKassa и отправлен на email:\n"
                f"<b>{_html(masked_email)}</b>\n\n"
                f"ЮKassa отправляет ссылку на чек на email, "
                f"указанный при оплате."
            )
        elif receipt_status == "pending":
            text = (
                f"🧾 <b>Чек по платежу</b>\n\n"
                f"Сумма: {payment.amount} ₽\n\n"
                f"⏳ Чек ещё формируется. Попробуйте позже.\n\n"
                f"После регистрации чек будет отправлен на email:\n"
                f"<b>{_html(masked_email)}</b>"
            )
        else:
            text = (
                f"🧾 <b>Чек по платежу</b>\n\n"
                f"Сумма: {payment.amount} ₽\n"
                f"Дата: {paid_at_str}\n\n"
                f"Чек сформирован ЮKassa и отправлен на email:\n"
                f"<b>{_html(masked_email)}</b>\n\n"
                f"ЮKassa отправляет ссылку на чек на email, "
                f"указанный при оплате."
            )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔄 Обновить статус",
                        callback_data=f"subscription:receipt:{payment.id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="◀️ Назад к подписке",
                        callback_data="subscription:current",
                    )
                ],
            ]
        )

        await _safe_edit_text(message, text, reply_markup=keyboard)
        await callback.answer()


def _mask_email(email: str) -> str:
    """Mask email for display: a***m@example.com"""
    if not email or "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[0] + "***" + local[-1]
    return f"{masked_local}@{domain}"


# ============================================================
# SUBSCRIPTION HELP
# ============================================================


@router.callback_query(F.data == "subscription:help")
async def show_subscription_help(callback: CallbackQuery) -> None:
    """Show subscription help using centralized formatter."""
    message = _callback_message(callback)
    if not message:
        return

    settings = get_settings()
    text = format_subscription_help(support_username=settings.support_telegram_username)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Тарифы и цены", callback_data="subscription:pricing")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="subscription_menu")],
        ]
    )

    await message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


# ============================================================
# SUBSCRIPTION CANCELLATION
# ============================================================


@router.callback_query(F.data == "subscription:cancel_confirm")
async def confirm_subscription_cancel(callback: CallbackQuery) -> None:
    """Confirm subscription cancellation."""
    message = _callback_message(callback)
    if not message:
        return

    text = (
        "❌ <b>Отмена подписки</b>\n\n"
        "Вы уверены, что хотите отменить подписку?\n\n"
        "• Доступ к функциям сохранится до конца оплаченного периода\n"
        "• После этого вы вернётесь на тариф FREE\n"
        "• Ваши данные не будут удалены\n"
        "• Вы сможете возобновить подписку в любой момент"
    )

    await _safe_edit_text(
        message,
        text,
        reply_markup=subscription_cancel_confirm_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "subscription:cancel_confirmed")
async def cancel_subscription(callback: CallbackQuery) -> None:
    """Cancel user subscription."""
    message = _callback_message(callback)
    if not callback.from_user or not message:
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        service = SubscriptionService(session)
        active_subscription = await service.get_active_subscription(user.id)

        if not active_subscription:
            await callback.answer("У вас нет активной подписки", show_alert=True)
            return

        await service.cancel_subscription(active_subscription.id)
        await session.commit()

        expires_at = format_datetime_for_user(
            active_subscription.expires_at, user.timezone, "%d.%m.%Y"
        )
        text = (
            "✅ <b>Подписка отменена</b>\n\n"
            f"Доступ к функциям тарифа {active_subscription.tier.name} сохранится до "
            f"{expires_at}.\n\n"
            "После этого вы вернётесь на тариф FREE.\n"
            "Вы можете возобновить подписку в любой момент."
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💎 Выбрать тариф",
                        callback_data="subscription:pricing",
                    )
                ],
                [InlineKeyboardButton(text="Назад", callback_data="subscription_menu")],
            ]
        )

        await _safe_edit_text(message, text, reply_markup=keyboard)
        await callback.answer("Подписка отменена")


# ============================================================
# ADMIN TARIFF MANAGEMENT
# ============================================================


def _is_admin_callback(callback: CallbackQuery) -> bool:
    """Check if callback author is an admin."""
    if not callback.from_user:
        return False
    return callback.from_user.id in get_settings().admin_ids


def _is_admin_message(message: Message) -> bool:
    """Check if message author is an admin."""
    if not message.from_user:
        return False
    return message.from_user.id in get_settings().admin_ids


@router.callback_query(F.data == "admin_tariff_menu")
async def admin_tariff_menu_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Show admin tariff management menu."""
    message = _callback_message(callback)
    if not message:
        return
    if not _is_admin_callback(callback):
        await callback.answer("Доступно только администраторам", show_alert=True)
        return

    await _safe_edit_text(
        message,
        "👑 <b>Управление тарифами</b>\n\nВыберите действие:",
        reply_markup=admin_tariff_menu(),
    )
    await state.clear()
    logger.info("admin_tariff_menu_opened", extra={"admin_telegram_id": callback.from_user.id})
    await callback.answer()


@router.message(Command("admin_tariffs"))
async def admin_tariff_command_handler(message: Message) -> None:
    """Open admin tariff management menu from a safe command."""
    if not _is_admin_message(message):
        await message.answer("Доступно только администраторам.")
        return

    await message.answer(
        "👑 <b>Управление тарифами</b>\n\nВыберите действие:",
        reply_markup=admin_tariff_menu(),
    )
    logger.info(
        "admin_tariff_menu_opened",
        extra={"admin_telegram_id": message.from_user.id if message.from_user else None},
    )


@router.callback_query(F.data == "admin_tariff:self")
async def admin_tariff_self_handler(callback: CallbackQuery) -> None:
    """Admin changes own tariff."""
    message = _callback_message(callback)
    if not message:
        return
    if not _is_admin_callback(callback):
        await callback.answer("Доступно только администраторам", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        service = SubscriptionService(session)
        current_tier = await service.get_user_tier(user.id)
        active_subscription = await service.get_active_subscription(user.id)

        lines = [
            "👤 <b>Изменение собственного тарифа</b>",
            "",
            f"Текущий тариф: <b>{_html(current_tier.name)}</b>",
        ]

        if active_subscription and active_subscription.expires_at:
            expires_at = format_datetime_for_user(
                active_subscription.expires_at, user.timezone, "%d.%m.%Y"
            )
            lines.append(f"Действует до: {expires_at}")

        lines.extend(["", "Выберите новый тариф:"])

        await _safe_edit_text(
            message,
            "\n".join(lines),
            reply_markup=admin_tariff_select_menu(),
        )
        await callback.answer()


@router.callback_query(F.data == "admin_tariff:user")
async def admin_tariff_user_prompt_handler(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Prompt admin for target user Telegram ID."""
    message = _callback_message(callback)
    if not message:
        return
    if not _is_admin_callback(callback):
        await callback.answer("Доступно только администраторам", show_alert=True)
        return

    await _safe_edit_text(
        message,
        "🔎 <b>Изменение тарифа пользователя</b>\n\n"
        "Введите Telegram ID пользователя, которому нужно изменить тариф.\n\n"
        "ID можно узнать через админское меню: 👥 Пользователи.",
    )
    await state.set_state(AdminTariffStates.waiting_for_user_id)
    await callback.answer()


@router.message(AdminTariffStates.waiting_for_user_id, F.text.regexp(r"^\d+$"))
async def admin_tariff_user_lookup_handler(message: Message, state: FSMContext) -> None:
    """Look up user by Telegram ID after admin enters it."""
    if not _is_admin_message(message):
        return

    telegram_id = int(message.text or "")

    async with AsyncSessionFactory() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(telegram_id)

        if not user:
            await message.answer(f"Пользователь с Telegram ID <b>{telegram_id}</b> не найден.")
            await state.clear()
            return

        service = SubscriptionService(session)
        current_tier = await service.get_user_tier(user.id)
        active_subscription = await service.get_active_subscription(user.id)

        lines = [
            "👤 <b>Пользователь найден</b>",
            "",
            f"Имя: <b>{_html(user.first_name)}</b>",
        ]
        if user.username:
            lines.append(f"Username: @{_html(user.username)}")
        lines.append(f"Telegram ID: {user.telegram_id}")
        lines.append("")
        lines.append(f"Текущий тариф: <b>{_html(current_tier.name)}</b>")

        if active_subscription and active_subscription.expires_at:
            expires_at = format_datetime_for_user(
                active_subscription.expires_at, user.timezone, "%d.%m.%Y"
            )
            lines.append(f"Действует до: {expires_at}")

        lines.extend(["", "Выберите новый тариф:"])

        logger.info(
            "admin_tariff_user_selected",
            extra={
                "admin_telegram_id": message.from_user.id if message.from_user else None,
                "target_user_id": user.id,
                "target_telegram_id": user.telegram_id,
                "old_tier": current_tier.code,
                "expires_at": (
                    active_subscription.expires_at.isoformat()
                    if active_subscription and active_subscription.expires_at
                    else None
                ),
            },
        )

        keyboard = admin_tariff_select_menu(target_telegram_id=user.telegram_id)
        keyboard.inline_keyboard.insert(
            0,
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data="admin_tariff:user",
                )
            ],
        )

        await message.answer(
            "\n".join(lines),
            reply_markup=keyboard,
        )
        await state.clear()


@router.message(AdminTariffStates.waiting_for_user_id)
async def admin_tariff_user_lookup_invalid_handler(
    message: Message,
    state: FSMContext,
) -> None:
    """Handle invalid target user input in admin tariff flow."""
    if not _is_admin_message(message):
        await state.clear()
        return
    await message.answer("Введите Telegram ID пользователя цифрами.")


@router.callback_query(F.data.startswith("admin_tariff:assign:"))
async def admin_tariff_assign_handler(callback: CallbackQuery) -> None:
    """Assign tariff to user (self or other)."""
    message = _callback_message(callback)
    if not message or not callback.data:
        return
    if not _is_admin_callback(callback):
        await callback.answer("Доступно только администраторам", show_alert=True)
        return

    parts = callback.data.split(":")
    tier_code = parts[2]
    days: int | None = None
    target_telegram_id_from_callback: int | None = None

    if len(parts) >= 4 and parts[3].isdigit() and parts[3] != "0":
        days = int(parts[3])
    if len(parts) >= 5 and parts[4].isdigit():
        target_telegram_id_from_callback = int(parts[4])

    async with AsyncSessionFactory() as session:
        user_repo = UserRepository(session)
        admin_user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not admin_user:
            await callback.answer("Администратор не найден", show_alert=True)
            return

        service = SubscriptionService(session)
        tier = await service.get_tier_by_code(tier_code)
        if not tier:
            await callback.answer("Тариф не найден", show_alert=True)
            return

        target_user_id: int
        target_user_name: str
        target_telegram_id: int
        target_user_timezone: str = "Europe/Moscow"

        if target_telegram_id_from_callback is not None:
            target_telegram_id = target_telegram_id_from_callback
            target_user_obj = await user_repo.get_by_telegram_id(target_telegram_id)
            if not target_user_obj:
                await callback.answer("Пользователь не найден", show_alert=True)
                return
            target_user_id = target_user_obj.id
            target_user_name = target_user_obj.first_name or f"ID:{target_user_obj.telegram_id}"
            target_telegram_id = target_user_obj.telegram_id
            target_user_timezone = target_user_obj.timezone or "Europe/Moscow"
        else:
            target_user_id = admin_user.id
            target_user_name = admin_user.first_name or "Администратор"
            target_telegram_id = admin_user.telegram_id
            target_user_timezone = admin_user.timezone or "Europe/Moscow"

        new_subscription = None
        try:
            new_subscription = await service.assign_admin_subscription(
                user_id=target_user_id,
                tier_code=tier_code,
                days=days,
                admin_user_id=admin_user.id,
            )
            await session.commit()
        except Exception as e:
            logger.exception(
                "admin_tariff_assignment_failed",
                extra={
                    "admin_telegram_id": callback.from_user.id,
                    "target_user_id": target_user_id,
                    "tier_code": tier_code,
                    "error": str(e),
                },
            )
            await callback.answer(
                "Не удалось изменить тариф. Подробности записаны в лог.",
                show_alert=True,
            )
            await callback.answer()
            return

        try:
            expires_at_str = None
            if new_subscription and new_subscription.expires_at:
                expires_at_str = format_datetime_for_user(
                    new_subscription.expires_at, target_user_timezone, "%d.%m.%Y"
                )

            confirmation_text = format_admin_tariff_confirmation(
                user_name=target_user_name,
                new_tier_name=tier.name,
                expires_at=expires_at_str,
            )

            await _safe_edit_text(
                message,
                confirmation_text,
                reply_markup=admin_tariff_menu(),
            )

            logger.info(
                "admin_tariff_changed",
                extra={
                    "admin_telegram_id": callback.from_user.id,
                    "target_user_id": target_user_id,
                    "target_telegram_id": target_telegram_id,
                    "new_tier": tier_code,
                    "days": days,
                },
            )

            if callback.bot:
                await _notify_user_tariff_change(
                    bot=callback.bot,
                    telegram_id=target_telegram_id,
                    tier_name=tier.name,
                    expires_at=expires_at_str,
                )
        except Exception:
            logger.exception(
                "admin_tariff_confirmation_message_failed",
                extra={
                    "admin_telegram_id": callback.from_user.id,
                    "target_user_id": target_user_id,
                    "subscription_id": new_subscription.id if new_subscription else None,
                },
            )

        await callback.answer()


async def _notify_user_tariff_change(
    bot: Bot,
    telegram_id: int,
    tier_name: str,
    expires_at: str | None,
) -> None:
    """Notify user about tariff change by admin."""
    try:
        text = format_user_tariff_notification(
            new_tier_name=tier_name,
            expires_at=expires_at,
        )
        await bot.send_message(telegram_id, text, parse_mode="HTML")
    except Exception:
        logger.exception(
            "admin_tariff_user_notify_failed",
            extra={"target_telegram_id": telegram_id},
        )
