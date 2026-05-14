"""version: 1.0.0
description: Main Telegram inline keyboards.
updated: 2026-05-14
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Сводка", callback_data="summary"),
                InlineKeyboardButton(text="🛒 Заказы", callback_data="orders"),
            ],
            [
                InlineKeyboardButton(text="💰 Прибыль", callback_data="profit"),
                InlineKeyboardButton(text="📦 Остатки", callback_data="stocks"),
            ],
            [
                InlineKeyboardButton(text="⚠ Контроль", callback_data="control"),
                InlineKeyboardButton(text="⚙ Настройки", callback_data="settings"),
            ],
        ]
    )


def settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подключить Wildberries", callback_data="connect_wb")],
            [InlineKeyboardButton(text="Подключить Ozon", callback_data="connect_ozon")],
            [InlineKeyboardButton(text="Мои кабинеты", callback_data="accounts")],
            [InlineKeyboardButton(text="Себестоимость товаров", callback_data="costs")],
            [InlineKeyboardButton(text="Настройки уведомлений", callback_data="notifications")],
            [InlineKeyboardButton(text="Время ежедневных отчётов", callback_data="report_time")],
            [InlineKeyboardButton(text="Налоговая ставка", callback_data="tax_rate")],
            [
                InlineKeyboardButton(
                    text="Стоимость упаковки по умолчанию", callback_data="package_cost"
                )
            ],
            [InlineKeyboardButton(text="Управление подпиской", callback_data="subscription")],
            [InlineKeyboardButton(text="Назад", callback_data="back_main")],
        ]
    )
