"""version: 1.0.0
description: Main Telegram inline keyboards.
updated: 2026-05-14
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models.domain import MarketplaceAccount


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


def accounts_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подключить Wildberries", callback_data="connect_wb")],
            [InlineKeyboardButton(text="Подключить Ozon", callback_data="connect_ozon")],
            [InlineKeyboardButton(text="Мои кабинеты", callback_data="accounts")],
            [InlineKeyboardButton(text="Назад", callback_data="settings")],
        ]
    )


def accounts_list_menu(accounts: list[MarketplaceAccount]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for account in accounts:
        status = "✓" if account.is_active else "×"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{status} {account.marketplace.value}: {account.name}",
                    callback_data=f"account:{account.id}:view",
                )
            ]
        )
    buttons.extend(
        [
            [InlineKeyboardButton(text="Подключить Wildberries", callback_data="connect_wb")],
            [InlineKeyboardButton(text="Подключить Ozon", callback_data="connect_ozon")],
            [InlineKeyboardButton(text="Назад", callback_data="settings")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def account_actions(account_id: int, is_active: bool) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    if is_active:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Удалить кабинет",
                    callback_data=f"account:{account_id}:delete_confirm",
                )
            ]
        )
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="accounts")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_delete_account(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить",
                    callback_data=f"account:{account_id}:delete",
                ),
                InlineKeyboardButton(text="Отмена", callback_data=f"account:{account_id}:view"),
            ]
        ]
    )


def back_to_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="settings")]]
    )


def costs_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Синхронизировать товары", callback_data="products_sync")],
            [
                InlineKeyboardButton(
                    text="Указать себестоимость вручную",
                    callback_data="cost_manual",
                )
            ],
            [InlineKeyboardButton(text="Скачать Excel-шаблон", callback_data="cost_template")],
            [InlineKeyboardButton(text="Загрузить Excel-файл", callback_data="cost_upload")],
            [InlineKeyboardButton(text="Назад", callback_data="settings")],
        ]
    )
