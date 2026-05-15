"""version: 1.1.0
description: Telegram notification delivery service.
updated: 2026-05-15
"""

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class NotificationService:
    """Send user-facing Telegram notifications."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_new_order(
        self, telegram_id: int, text: str, order_id: int | None = None
    ) -> None:
        await self.bot.send_message(
            telegram_id,
            text,
            reply_markup=self._build_new_order_keyboard(order_id),
        )

    @staticmethod
    def _build_new_order_keyboard(order_id: int | None = None) -> InlineKeyboardMarkup:
        details_callback = f"order:{order_id}:details" if order_id else "orders:last10"
        profit_callback = f"order:{order_id}:profit" if order_id else "profit:today"
        product_callback = f"order:{order_id}:product" if order_id else "products_costs_menu"
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📋 Детали заказа", callback_data=details_callback),
                    InlineKeyboardButton(text="💰 Расчёт прибыли", callback_data=profit_callback),
                ],
                [
                    InlineKeyboardButton(text="📦 О товаре", callback_data=product_callback),
                    InlineKeyboardButton(
                        text="⚙ Настройки уведомлений",
                        callback_data="settings:notifications",
                    ),
                ],
                [
                    InlineKeyboardButton(text="❌ Скрыть", callback_data="hide"),
                ],
            ]
        )

    async def send_fbo_digest(self, telegram_id: int, text: str) -> None:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📋 Открыть список заказов",
                        callback_data="orders:fbo",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⚙ Настройки уведомлений",
                        callback_data="settings:notifications",
                    )
                ],
            ]
        )
        await self.bot.send_message(telegram_id, text, reply_markup=keyboard)

    async def send_sale_completed(self, telegram_id: int, text: str) -> None:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💰 Экономика продажи",
                        callback_data="profit:today",
                    ),
                    InlineKeyboardButton(text="📦 Товар", callback_data="products_costs_menu"),
                ],
                [
                    InlineKeyboardButton(
                        text="🌐 Открыть в web-кабинете",
                        callback_data="web_cabinet",
                    )
                ],
            ]
        )
        await self.bot.send_message(telegram_id, text, reply_markup=keyboard)
