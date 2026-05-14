"""version: 1.0.0
description: Telegram notification delivery service.
updated: 2026-05-14
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
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📋 Детали заказа", callback_data=f"order:{order_id}:details"
                    ),
                    InlineKeyboardButton(
                        text="💰 Расчёт прибыли", callback_data=f"order:{order_id}:profit"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="📦 О товаре", callback_data=f"order:{order_id}:product"
                    ),
                    InlineKeyboardButton(text="❌ Скрыть", callback_data="hide"),
                ],
            ]
        )
        await self.bot.send_message(telegram_id, text, reply_markup=keyboard)
