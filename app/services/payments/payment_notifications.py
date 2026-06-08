"""version: 1.0.0
description: Payment notification helpers for Telegram.
updated: 2026-06-08
"""

import logging
from datetime import UTC, datetime
from html import escape as html_escape
from inspect import isawaitable
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User
from app.models.subscriptions import SubscriptionTier
from app.services.payments.receipt_builder import get_period_label

logger = logging.getLogger(__name__)

_TIER_FEATURE_LABELS = [
    ("feature_web_cabinet", "Web-кабинет"),
    ("feature_analytics", "Расширенная аналитика"),
    ("feature_plan_fact", "План/факт анализ"),
    ("feature_break_even", "Безубыточная цена"),
    ("feature_stock_forecast", "Прогноз остатков"),
    ("feature_alerts", "Умные алерты"),
    ("feature_priority_support", "Приоритетная поддержка"),
    ("feature_api_access", "API-доступ"),
    ("feature_mrc_pricing", "МРЦ и акции WB"),
    ("feature_auto_promotions", "Автоакции WB"),
    ("feature_telegram_notifications", "Telegram-уведомления"),
]


def build_payment_success_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    """Build inline keyboard for payment success message.

    Args:
        payment_id: Payment ID for receipt callback

    Returns:
        Inline keyboard markup
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Моя подписка",
                    callback_data="subscription:current",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧾 Чек по платежу",
                    callback_data=f"subscription:receipt:{payment_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data="back_main",
                )
            ],
        ]
    )


def format_feature_list(tier: SubscriptionTier | None) -> str:
    """Format tier features as bullet list.

    Args:
        tier: Subscription tier or None

    Returns:
        Formatted feature list or empty string
    """
    if not tier:
        return ""

    features = []
    for attr, label in _TIER_FEATURE_LABELS:
        if getattr(tier, attr, False):
            features.append(label)

    if not features:
        return ""

    feature_items = "\n".join(f"✅ {f}" for f in features)
    return f"\n{feature_items}"


async def send_payment_success_notification(
    session: AsyncSession,
    *,
    payment: Any,
    subscription: Any,
    tier: SubscriptionTier | None,
    tier_code: str,
    period: str,
) -> None:
    """Send Telegram notification about successful payment and subscription activation.

    Args:
        session: Database session
        payment: Payment model instance
        subscription: UserSubscription model instance
        tier: SubscriptionTier or None
        tier_code: Tier code string
        period: Payment period

    Idempotent: checks success_notification_sent_at to avoid duplicates.
    """
    from app.bot.main import create_bot
    from app.utils.datetime import format_datetime_for_user

    if payment.success_notification_sent_at is not None:
        logger.info(
            "payment_success_notification_skipped_duplicate",
            extra={
                "payment_id": payment.id,
                "user_id": payment.user_id,
                "yookassa_payment_id": payment.provider_payment_id,
            },
        )
        return

    try:
        user_result = await session.execute(select(User).where(User.id == payment.user_id))
        user = user_result.scalar_one_or_none()
        if not user or not user.telegram_id:
            logger.warning(
                "payment_success_notification_failed",
                extra={
                    "payment_id": payment.id,
                    "user_id": payment.user_id,
                    "error": "user_not_found_or_no_telegram_id",
                },
            )
            return

        tier_name = tier.name if tier else tier_code
        period_label = get_period_label(period)

        expires_str = "н/д"
        if subscription.expires_at:
            expires_str = format_datetime_for_user(subscription.expires_at, user.timezone, "%d.%m.%Y")

        paid_at_str = "н/д"
        if payment.paid_at:
            paid_at_str = format_datetime_for_user(payment.paid_at, user.timezone, "%d.%m.%Y %H:%M")

        feature_lines = format_feature_list(tier)

        text = (
            f"✅ <b>Оплата получена</b>\n\n"
            f"Ваш платёж успешно подтверждён.\n"
            f"Подписка MP Control активирована.\n\n"
            f"💳 <b>Детали платежа</b>\n"
            f"• Тариф: {html_escape(tier_name)}\n"
            f"• Период: {html_escape(period_label)}\n"
            f"• Сумма: {payment.amount} ₽\n"
            f"• Статус: Оплачено\n"
            f"• Дата оплаты: {html_escape(paid_at_str)}\n\n"
            f"🚀 <b>Ваша подписка</b>\n"
            f"• Тариф: {html_escape(tier_name)}\n"
            f"• Статус: Активна\n"
            f"• Действует до: {html_escape(expires_str)}\n\n"
            f"Доступ открыт:{feature_lines}\n\n"
            f"Спасибо за оплату! Подписка уже работает."
        )

        keyboard = build_payment_success_keyboard(payment.id)

        bot = create_bot()
        try:
            await bot.send_message(
                user.telegram_id,
                text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        finally:
            close_result = bot.session.close()
            if isawaitable(close_result):
                await close_result

        payment.success_notification_sent_at = datetime.now(tz=UTC)
        await session.flush()

        logger.info(
            "payment_success_notification_sent",
            extra={
                "payment_id": payment.id,
                "user_id": payment.user_id,
                "telegram_id": user.telegram_id,
                "yookassa_payment_id": payment.provider_payment_id,
            },
        )
    except Exception:
        logger.exception(
            "payment_success_notification_failed",
            extra={
                "payment_id": payment.id,
                "user_id": payment.user_id,
                "yookassa_payment_id": payment.provider_payment_id,
            },
        )
