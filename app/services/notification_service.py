"""version: 1.4.0
description: Telegram notification delivery with marketplace buttons and media fallback.
updated: 2026-05-17
"""

import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models.enums import Marketplace

TELEGRAM_CAPTION_LIMIT = 1024
logger = logging.getLogger(__name__)


class NotificationService:
    """Send user-facing Telegram notifications."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_new_order(
        self,
        telegram_id: int,
        text: str,
        order_id: int | None = None,
        *,
        image_url: str | None = None,
        product_url: str | None = None,
        marketplace: Marketplace | None = None,
        parse_mode: str | None = None,
    ) -> None:
        keyboard = self._build_new_order_keyboard(order_id, product_url, marketplace)
        if image_url:
            try:
                if len(text) <= TELEGRAM_CAPTION_LIMIT:
                    await self.bot.send_photo(
                        telegram_id,
                        photo=image_url,
                        caption=text,
                        parse_mode=parse_mode,
                        reply_markup=keyboard,
                    )
                    return
                await self.bot.send_photo(telegram_id, photo=image_url)
            except Exception:
                logger.exception(
                    "new_order_photo_send_failed_fallback_to_text",
                    extra={
                        "telegram_id": telegram_id,
                        "order_id": order_id,
                        "marketplace": marketplace.value if marketplace else None,
                    },
                )
        await self.bot.send_message(
            telegram_id,
            text,
            parse_mode=parse_mode,
            reply_markup=keyboard,
        )

    @staticmethod
    def _build_new_order_keyboard(
        order_id: int | None = None,
        product_url: str | None = None,
        marketplace: Marketplace | None = None,
    ) -> InlineKeyboardMarkup:
        details_callback = f"order:{order_id}:details" if order_id else "orders:last10"
        profit_callback = f"order:{order_id}:profit" if order_id else "profit:today"
        product_callback = f"order:{order_id}:product" if order_id else "products_costs_menu"

        if product_url:
            if marketplace == Marketplace.OZON:
                button_text = "🛍 Открыть товар на Ozon"
            else:
                button_text = "🛍 Открыть товар на WB"
            product_button = InlineKeyboardButton(text=button_text, url=product_url)
        else:
            product_button = InlineKeyboardButton(
                text="📦 О товаре",
                callback_data=product_callback,
            )

        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📋 Детали заказа", callback_data=details_callback),
                    InlineKeyboardButton(text="💰 Расчёт прибыли", callback_data=profit_callback),
                ],
                [
                    product_button,
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

    async def send_sale_completed(
        self,
        telegram_id: int,
        text: str,
        *,
        image_url: str | None = None,
        product_url: str | None = None,
        marketplace: Marketplace | None = None,
        parse_mode: str | None = None,
    ) -> None:
        if product_url:
            if marketplace == Marketplace.OZON:
                button_text = "🛍 Открыть товар на Ozon"
            else:
                button_text = "🛍 Открыть товар на WB"
            product_button = InlineKeyboardButton(text=button_text, url=product_url)
        else:
            product_button = InlineKeyboardButton(
                text="📦 Товар",
                callback_data="products_costs_menu",
            )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💰 Экономика продажи",
                        callback_data="profit:today",
                    ),
                    product_button,
                ],
                [
                    InlineKeyboardButton(
                        text="🌐 Открыть в web-кабинете",
                        callback_data="web_cabinet",
                    )
                ],
            ]
        )
        if image_url:
            try:
                if len(text) <= TELEGRAM_CAPTION_LIMIT:
                    await self.bot.send_photo(
                        telegram_id,
                        photo=image_url,
                        caption=text,
                        parse_mode=parse_mode,
                        reply_markup=keyboard,
                    )
                    return
                await self.bot.send_photo(telegram_id, photo=image_url)
            except Exception:
                logger.exception(
                    "sale_photo_send_failed_fallback_to_text",
                    extra={
                        "telegram_id": telegram_id,
                        "marketplace": marketplace.value if marketplace else None,
                    },
                )
        await self.bot.send_message(
            telegram_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=keyboard,
        )

    async def send_order_lifecycle_event(
        self,
        telegram_id: int,
        text: str,
        *,
        order_id: int | None = None,
        image_url: str | None = None,
        product_url: str | None = None,
        marketplace: Marketplace | None = None,
        parse_mode: str | None = None,
    ) -> None:
        keyboard = self._build_new_order_keyboard(order_id, product_url, marketplace)
        if image_url:
            try:
                if len(text) <= TELEGRAM_CAPTION_LIMIT:
                    await self.bot.send_photo(
                        telegram_id,
                        photo=image_url,
                        caption=text,
                        parse_mode=parse_mode,
                        reply_markup=keyboard,
                    )
                    return
                await self.bot.send_photo(telegram_id, photo=image_url)
            except Exception:
                logger.exception(
                    "order_lifecycle_photo_send_failed_fallback_to_text",
                    extra={
                        "telegram_id": telegram_id,
                        "order_id": order_id,
                        "marketplace": marketplace.value if marketplace else None,
                    },
                )
        await self.bot.send_message(
            telegram_id,
            text,
            parse_mode=parse_mode,
            reply_markup=keyboard,
        )
