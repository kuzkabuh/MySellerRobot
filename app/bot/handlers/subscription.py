"""version: 1.0.0
description: Telegram bot handlers for subscription management.
updated: 2026-05-16
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.domain import User
from app.services.payment_service import PaymentService
from app.services.subscription_service import SubscriptionService

router = Router(name="subscription")
logger = logging.getLogger(__name__)


@router.message(Command("subscription", "tariff", "pricing"))
async def show_subscription_info(
    message: Message,
    user: User,
    session: AsyncSession,
) -> None:
    """Show current subscription and available tiers."""
    service = SubscriptionService(session)

    current_tier = await service.get_user_tier(user.id)
    active_subscription = await service.get_active_subscription(user.id)

    lines = [
        "💳 <b>Ваша подписка</b>",
        "",
        f"Текущий тариф: <b>{current_tier.name}</b>",
    ]

    if active_subscription:
        if active_subscription.is_trial:
            lines.append(f"🎁 Пробный период до {active_subscription.trial_ends_at:%d.%m.%Y}")
        if active_subscription.expires_at:
            lines.append(f"Действует до: {active_subscription.expires_at:%d.%m.%Y}")

    lines.extend([
        "",
        "📊 <b>Доступные функции:</b>",
        f"{'✅' if current_tier.feature_web_cabinet else '❌'} Web-кабинет",
        f"{'✅' if current_tier.feature_analytics else '❌'} Аналитика",
        f"{'✅' if current_tier.feature_plan_fact else '❌'} План/факт",
        f"{'✅' if current_tier.feature_break_even else '❌'} Безубыточность",
        f"{'✅' if current_tier.feature_stock_forecast else '❌'} Прогноз остатков",
        f"{'✅' if current_tier.feature_alerts else '❌'} Алерты",
        "",
        f"Аккаунтов МП: {len(user.accounts)}/{current_tier.max_marketplace_accounts}",
    ])

    # Show available tiers
    all_tiers = await service.get_all_tiers()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    for tier in all_tiers:
        if tier.code == "free":
            continue

        price_text = f"{tier.price_monthly}₽/мес"
        if tier.price_yearly:
            price_text += f" или {tier.price_yearly}₽/год"

        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"💎 {tier.name} — {price_text}",
                callback_data=f"subscribe:{tier.code}",
            )
        ])

    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="📜 История платежей", callback_data="payment_history")
    ])

    await message.answer("\n".join(lines), reply_markup=keyboard)


@router.callback_query(F.data.startswith("subscribe:"))
async def handle_subscribe(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
) -> None:
    """Handle subscription tier selection."""
    if not callback.data or not callback.message:
        return

    tier_code = callback.data.split(":")[1]

    service = SubscriptionService(session)
    tier = await service._get_tier_by_code(tier_code)

    if not tier:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💳 Оплатить {tier.price_monthly}₽/мес",
                    callback_data=f"pay:{tier_code}:monthly",
                )
            ],
        ]
    )

    if tier.price_yearly:
        keyboard.inline_keyboard.insert(
            0,
            [
                InlineKeyboardButton(
                    text=f"💳 Оплатить {tier.price_yearly}₽/год (выгоднее!)",
                    callback_data=f"pay:{tier_code}:yearly",
                )
            ],
        )

    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription")
    ])

    text = [
        f"💎 <b>{tier.name}</b>",
        "",
        tier.description or "",
        "",
        "<b>Что входит:</b>",
        f"• Аккаунтов МП: {tier.max_marketplace_accounts}",
    ]

    if tier.max_orders_per_month:
        text.append(f"• Заказов в месяц: {tier.max_orders_per_month}")
    else:
        text.append("• Заказов в месяц: неограниченно")

    text.extend([
        "",
        "<b>Функции:</b>",
        f"{'✅' if tier.feature_web_cabinet else '❌'} Web-кабинет",
        f"{'✅' if tier.feature_analytics else '❌'} Расширенная аналитика",
        f"{'✅' if tier.feature_plan_fact else '❌'} План/факт анализ",
        f"{'✅' if tier.feature_break_even else '❌'} Безубыточная цена",
        f"{'✅' if tier.feature_stock_forecast else '❌'} Прогноз остатков",
        f"{'✅' if tier.feature_alerts else '❌'} Умные алерты",
        f"{'✅' if tier.feature_priority_support else '❌'} Приоритетная поддержка",
    ])

    await callback.message.edit_text("\n".join(text), reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("pay:"))
async def handle_payment(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
) -> None:
    """Create payment and send payment link."""
    if not callback.data or not callback.message:
        return

    parts = callback.data.split(":")
    tier_code = parts[1]
    period = parts[2]

    settings = get_settings()
    return_url = f"{settings.web_base_url}/payment/success"

    try:
        payment_service = PaymentService(session)
        payment, confirmation_url = await payment_service.create_subscription_payment(
            user_id=user.id,
            tier_code=tier_code,
            period=period,
            return_url=return_url,
        )
        await session.commit()

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перейти к оплате", url=confirmation_url)],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription")],
            ]
        )

        await callback.message.edit_text(
            "✅ Счет создан!\n\n"
            "Нажмите кнопку ниже для перехода на страницу оплаты.\n\n"
            "После успешной оплаты подписка активируется автоматически.",
            reply_markup=keyboard,
        )
        await callback.answer()

    except Exception as e:
        logger.exception("payment_creation_failed", extra={"user_id": user.id})
        await callback.answer(f"Ошибка создания платежа: {e}", show_alert=True)


@router.callback_query(F.data == "payment_history")
async def show_payment_history(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
) -> None:
    """Show user's payment history."""
    if not callback.message:
        return

    payment_service = PaymentService(session)
    payments = await payment_service.get_user_payments(user.id, limit=10)

    if not payments:
        await callback.message.edit_text(
            "📜 История платежей пуста",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription")]
                ]
            ),
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

        lines.append(
            f"{status_emoji} {payment.amount}₽ — {payment.created_at:%d.%m.%Y %H:%M}"
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription")]
        ]
    )

    await callback.message.edit_text("\n".join(lines), reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "back_to_subscription")
async def back_to_subscription(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
) -> None:
    """Return to subscription info."""
    if not callback.message:
        return

    # Re-create the subscription message
    await callback.message.delete()
    await show_subscription_info(callback.message, user, session)
    await callback.answer()
