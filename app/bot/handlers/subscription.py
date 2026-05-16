"""version: 2.0.0
description: Telegram bot handlers for subscription management with full menu integration.
updated: 2026-05-16
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards.main import (
    subscription_cancel_confirm_menu,
    subscription_current_menu,
    subscription_menu,
    subscription_payment_confirm_menu,
    subscription_payments_menu,
    subscription_pricing_menu,
    subscription_tier_detail_menu,
)
from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.models.domain import User
from app.repositories.users import UserRepository
from app.services.payment_service import PaymentService
from app.services.subscription_service import SubscriptionService

router = Router(name="subscription")
logger = logging.getLogger(__name__)


@router.message(Command("subscription", "tariff", "pricing"))
async def show_subscription_info(message: Message) -> None:
    """Show subscription menu."""
    if not message.from_user:
        return

    await message.answer("💎 Подписка и тарифы", reply_markup=subscription_menu())


@router.callback_query(F.data == "subscription_menu")
async def subscription_menu_handler(callback: CallbackQuery) -> None:
    """Show subscription main menu."""
    if not callback.message:
        return

    await callback.message.edit_text("💎 Подписка и тарифы", reply_markup=subscription_menu())
    await callback.answer()


@router.callback_query(F.data == "subscription:current")
async def show_current_subscription(callback: CallbackQuery) -> None:
    """Show current subscription details."""
    if not callback.from_user or not callback.message:
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
            "📊 <b>Моя подписка</b>",
            "",
            f"Текущий тариф: <b>{current_tier.name}</b>",
        ]

        if active_subscription:
            if active_subscription.is_trial:
                lines.append(
                    f"🎁 Пробный период до {active_subscription.trial_ends_at:%d.%m.%Y}"
                )
            if active_subscription.expires_at:
                lines.append(f"Действует до: {active_subscription.expires_at:%d.%m.%Y}")
            lines.append(f"Автопродление: {'включено' if active_subscription.auto_renew else 'отключено'}")

        lines.extend([
            "",
            "📊 <b>Лимиты тарифа:</b>",
            f"• Кабинетов МП: {len(user.accounts)}/{current_tier.max_marketplace_accounts}",
        ])

        if current_tier.max_orders_per_month:
            lines.append(f"• Заказов в месяц: до {current_tier.max_orders_per_month}")
        else:
            lines.append("• Заказов в месяц: без ограничений")

        if current_tier.max_products:
            lines.append(f"• SKU в аналитике: до {current_tier.max_products}")
        else:
            lines.append("• SKU в аналитике: без ограничений")

        lines.extend([
            "",
            "✨ <b>Доступные функции:</b>",
            f"{'✅' if current_tier.feature_web_cabinet else '❌'} Web-кабинет",
            f"{'✅' if current_tier.feature_analytics else '❌'} Расширенная аналитика",
            f"{'✅' if current_tier.feature_plan_fact else '❌'} План/факт анализ",
            f"{'✅' if current_tier.feature_break_even else '❌'} Безубыточная цена",
            f"{'✅' if current_tier.feature_stock_forecast else '❌'} Прогноз остатков",
            f"{'✅' if current_tier.feature_alerts else '❌'} Умные алерты",
            f"{'✅' if current_tier.feature_priority_support else '❌'} Приоритетная поддержка",
            f"{'✅' if current_tier.feature_api_access else '❌'} API-доступ",
        ])

        has_active = active_subscription is not None and current_tier.code != "free"

        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=subscription_current_menu(has_active=has_active),
        )
        await callback.answer()


@router.callback_query(F.data == "subscription:pricing")
async def show_pricing(callback: CallbackQuery) -> None:
    """Show pricing and tiers."""
    if not callback.message:
        return

    text = [
        "💎 <b>Тарифы и цены</b>",
        "",
        "Выберите тариф, чтобы узнать подробности:",
        "",
        "🆓 <b>FREE</b> — Бесплатно",
        "• 1 кабинет МП",
        "• 100 заказов/месяц",
        "• Базовые уведомления",
        "",
        "⭐ <b>BASIC</b> — 490₽/мес или 4 900₽/год",
        "• 2 кабинета МП",
        "• 1 000 заказов/месяц",
        "• Расширенная аналитика",
        "• Алерты и контроль",
        "",
        "💎 <b>PRO</b> — 1 490₽/мес или 14 900₽/год",
        "• 5 кабинетов МП",
        "• Заказы без ограничений",
        "• План/факт, безубыточность",
        "• Прогноз остатков",
        "• Приоритетная поддержка",
        "",
        "🏢 <b>ENTERPRISE</b> — Индивидуально",
        "• Индивидуальные лимиты",
        "• API-доступ",
        "• Роли и команды",
    ]

    await callback.message.edit_text("\n".join(text), reply_markup=subscription_pricing_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("subscription:tier:"))
async def show_tier_details(callback: CallbackQuery) -> None:
    """Show specific tier details."""
    if not callback.from_user or not callback.message or not callback.data:
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
        tier = await service._get_tier_by_code(tier_code)

        if not tier:
            await callback.answer("Тариф не найден", show_alert=True)
            return

        lines = [f"💎 <b>{tier.name}</b>", ""]

        if tier.description:
            lines.extend([tier.description, ""])

        lines.append("<b>Стоимость:</b>")
        if tier.code == "free":
            lines.append("• Бесплатно")
        elif tier.code == "enterprise":
            lines.append("• По индивидуальному запросу")
        else:
            lines.append(f"• {tier.price_monthly}₽ в месяц")
            if tier.price_yearly:
                monthly_equivalent = tier.price_yearly / 12
                savings = (tier.price_monthly - monthly_equivalent) * 12
                lines.append(
                    f"• {tier.price_yearly}₽ в год (экономия {savings:.0f}₽)"
                )

        lines.extend([
            "",
            "<b>Лимиты:</b>",
            f"• Кабинетов МП: {tier.max_marketplace_accounts}",
        ])

        if tier.max_orders_per_month:
            lines.append(f"• Заказов в месяц: {tier.max_orders_per_month}")
        else:
            lines.append("• Заказов в месяц: без ограничений")

        if tier.max_products:
            lines.append(f"• SKU в аналитике: {tier.max_products}")
        else:
            lines.append("• SKU в аналитике: без ограничений")

        lines.extend([
            "",
            "<b>Функции:</b>",
            f"{'✅' if tier.feature_web_cabinet else '❌'} Web-кабинет",
            f"{'✅' if tier.feature_analytics else '❌'} Расширенная аналитика",
            f"{'✅' if tier.feature_plan_fact else '❌'} План/факт анализ",
            f"{'✅' if tier.feature_break_even else '❌'} Безубыточная цена",
            f"{'✅' if tier.feature_stock_forecast else '❌'} Прогноз остатков",
            f"{'✅' if tier.feature_alerts else '❌'} Умные алерты",
            f"{'✅' if tier.feature_priority_support else '❌'} Приоритетная поддержка",
            f"{'✅' if tier.feature_api_access else '❌'} API-доступ",
        ])

        if tier.code == current_tier.code:
            lines.extend(["", "✅ <b>Это ваш текущий тариф</b>"])

        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=subscription_tier_detail_menu(tier.code, current_tier.code),
        )
        await callback.answer()


@router.callback_query(F.data.startswith("subscription:pay:"))
async def handle_payment_initiation(callback: CallbackQuery) -> None:
    """Handle payment initiation."""
    if not callback.from_user or not callback.message or not callback.data:
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
        tier = await service._get_tier_by_code(tier_code)

        if not tier:
            await callback.answer("Тариф не найден", show_alert=True)
            return

        amount = tier.price_monthly if period == "monthly" else tier.price_yearly
        if not amount:
            await callback.answer("Цена не указана для этого периода", show_alert=True)
            return

        period_text = "месяц" if period == "monthly" else "год"
        text = [
            "💳 <b>Подтверждение оплаты</b>",
            "",
            f"Тариф: <b>{tier.name}</b>",
            f"Период: {period_text}",
            f"Сумма: <b>{amount}₽</b>",
            "",
            "После оплаты подписка активируется автоматически.",
        ]

        await callback.message.edit_text(
            "\n".join(text),
            reply_markup=subscription_payment_confirm_menu(tier_code, period, f"{amount}₽"),
        )
        await callback.answer()


@router.callback_query(F.data.startswith("subscription:pay_confirm:"))
async def handle_payment_confirmation(callback: CallbackQuery) -> None:
    """Create payment and send payment link."""
    if not callback.from_user or not callback.message or not callback.data:
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

        settings = get_settings()
        return_url = f"{settings.web_base_url}/web/payment/success"

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
                    [InlineKeyboardButton(text="Назад", callback_data="subscription:pricing")],
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


@router.callback_query(F.data == "subscription:payments")
async def show_payment_history(callback: CallbackQuery) -> None:
    """Show user's payment history."""
    if not callback.message or not callback.from_user:
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
            await callback.message.edit_text(
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

            lines.append(
                f"{status_emoji} {payment.amount}₽ — {status_text}\n"
                f"   {payment.created_at:%d.%m.%Y %H:%M}"
            )

        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=subscription_payments_menu(),
        )
        await callback.answer()


@router.callback_query(F.data == "subscription:compare")
async def show_comparison(callback: CallbackQuery) -> None:
    """Show tier comparison table."""
    if not callback.message:
        return

    text = [
        "📊 <b>Сравнение тарифов</b>",
        "",
        "<b>FREE</b>",
        "• 1 кабинет, 100 заказов/мес",
        "• Базовые уведомления",
        "• Web-кабинет",
        "",
        "<b>BASIC — 490₽/мес</b>",
        "• 2 кабинета, 1000 заказов/мес",
        "• Расширенная аналитика",
        "• Алерты (маржа, остатки, FBS)",
        "• Базовый экспорт",
        "",
        "<b>PRO — 1490₽/мес</b>",
        "• 5 кабинетов, без лимита заказов",
        "• План/факт анализ",
        "• Безубыточная цена",
        "• Прогноз остатков",
        "• Ручное сопоставление товаров",
        "• Расширенный экспорт",
        "• Приоритетная поддержка",
        "",
        "<b>ENTERPRISE</b>",
        "• Индивидуальные лимиты",
        "• API-доступ",
        "• Роли и команды",
        "• Кастомные интеграции",
    ]

    await callback.message.edit_text("\n".join(text), reply_markup=subscription_pricing_menu())
    await callback.answer()


@router.callback_query(F.data == "subscription:help")
async def show_subscription_help(callback: CallbackQuery) -> None:
    """Show subscription help."""
    if not callback.message:
        return

    text = [
        "❓ <b>Помощь по подпискам</b>",
        "",
        "<b>Как работает подписка?</b>",
        "После оплаты подписка активируется автоматически. Вы получаете доступ ко всем функциям выбранного тарифа.",
        "",
        "<b>Как оплатить?</b>",
        "Выберите тариф → нажмите кнопку оплаты → оплатите через ЮКасса (карта, СБП, электронные кошельки).",
        "",
        "<b>Можно ли отменить?</b>",
        "Да, вы можете отменить подписку в любой момент. Доступ сохранится до конца оплаченного периода.",
        "",
        "<b>Что будет после окончания?</b>",
        "Если автопродление отключено, вы вернётесь на тариф FREE. Ваши данные сохранятся.",
        "",
        "<b>Есть пробный период?</b>",
        "Да, для новых пользователей доступен пробный период PRO на 14 дней.",
        "",
        "<b>Вопросы?</b>",
        "Напишите в поддержку: @mpcontrol_support",
    ]

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Выбрать тариф", callback_data="subscription:pricing")],
            [InlineKeyboardButton(text="Назад", callback_data="subscription_menu")],
        ]
    )

    await callback.message.edit_text("\n".join(text), reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "subscription:cancel_confirm")
async def confirm_subscription_cancel(callback: CallbackQuery) -> None:
    """Confirm subscription cancellation."""
    if not callback.message:
        return

    text = [
        "❌ <b>Отмена подписки</b>",
        "",
        "Вы уверены, что хотите отменить подписку?",
        "",
        "• Доступ к функциям сохранится до конца оплаченного периода",
        "• После этого вы вернётесь на тариф FREE",
        "• Ваши данные не будут удалены",
        "• Вы сможете возобновить подписку в любой момент",
    ]

    await callback.message.edit_text(
        "\n".join(text),
        reply_markup=subscription_cancel_confirm_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "subscription:cancel_confirmed")
async def cancel_subscription(callback: CallbackQuery) -> None:
    """Cancel user subscription."""
    if not callback.from_user or not callback.message:
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

        text = [
            "✅ <b>Подписка отменена</b>",
            "",
            f"Доступ к функциям тарифа {active_subscription.tier.name} сохранится до "
            f"{active_subscription.expires_at:%d.%m.%Y}.",
            "",
            "После этого вы вернётесь на тариф FREE.",
            "Вы можете возобновить подписку в любой момент.",
        ]

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💎 Выбрать тариф", callback_data="subscription:pricing")],
                [InlineKeyboardButton(text="Назад", callback_data="subscription_menu")],
            ]
        )

        await callback.message.edit_text("\n".join(text), reply_markup=keyboard)
        await callback.answer("Подписка отменена")




