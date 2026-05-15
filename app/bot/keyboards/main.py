"""version: 1.4.0
description: Main Telegram inline keyboards.
updated: 2026-05-15
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models.domain import MarketplaceAccount

TIMEZONE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Калининград UTC+2", "Europe/Kaliningrad"),
    ("Москва UTC+3", "Europe/Moscow"),
    ("Самара UTC+4", "Europe/Samara"),
    ("Екатеринбург UTC+5", "Asia/Yekaterinburg"),
    ("Омск UTC+6", "Asia/Omsk"),
    ("Красноярск UTC+7", "Asia/Krasnoyarsk"),
    ("Иркутск UTC+8", "Asia/Irkutsk"),
    ("Якутск UTC+9", "Asia/Yakutsk"),
    ("Владивосток UTC+10", "Asia/Vladivostok"),
    ("Магадан UTC+11", "Asia/Magadan"),
    ("Камчатка UTC+12", "Asia/Kamchatka"),
)


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📊 Сводка", callback_data="summary_menu"),
            InlineKeyboardButton(text="🛒 Заказы", callback_data="orders_menu"),
        ],
        [
            InlineKeyboardButton(text="💰 Прибыль", callback_data="profit_menu"),
            InlineKeyboardButton(
                text="📦 Товары и себестоимость",
                callback_data="products_costs_menu",
            ),
        ],
        [
            InlineKeyboardButton(text="⚠ Контроль и уведомления", callback_data="control_menu"),
            InlineKeyboardButton(text="🌐 Web-кабинет", callback_data="web_cabinet"),
        ],
        [InlineKeyboardButton(text="⚙ Настройки", callback_data="settings")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Администрирование", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def summary_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сегодня", callback_data="summary:today")],
            [InlineKeyboardButton(text="Вчера", callback_data="summary:yesterday")],
            [InlineKeyboardButton(text="7 дней", callback_data="summary:7d")],
            [InlineKeyboardButton(text="30 дней", callback_data="summary:30d")],
            [InlineKeyboardButton(text="🌐 Открыть web-аналитику", callback_data="web_cabinet")],
            [InlineKeyboardButton(text="Назад", callback_data="back_main")],
        ]
    )


def orders_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Новые заказы", callback_data="orders:new")],
            [InlineKeyboardButton(text="Заказы за сегодня", callback_data="orders:today")],
            [InlineKeyboardButton(text="FBS / rFBS к обработке", callback_data="orders:fbs")],
            [InlineKeyboardButton(text="FBO заказы", callback_data="orders:fbo")],
            [InlineKeyboardButton(text="Последние 10 заказов", callback_data="orders:last10")],
            [InlineKeyboardButton(text="🌐 Смотреть все заказы", callback_data="web_cabinet")],
            [InlineKeyboardButton(text="Назад", callback_data="back_main")],
        ]
    )


def profit_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Прибыль за сегодня", callback_data="profit:today")],
            [InlineKeyboardButton(text="Прибыль за 7 дней", callback_data="profit:7d")],
            [InlineKeyboardButton(text="Убыточные заказы", callback_data="profit:loss")],
            [InlineKeyboardButton(text="План/факт и отклонения", callback_data="profit:plan_fact")],
            [
                InlineKeyboardButton(
                    text="Безубыточная цена",
                    callback_data="profit:break_even",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Заказы без себестоимости",
                    callback_data="profit:missing_cost",
                )
            ],
            [InlineKeyboardButton(text="🌐 Web-аналитика прибыли", callback_data="web_cabinet")],
            [InlineKeyboardButton(text="Назад", callback_data="back_main")],
        ]
    )


def control_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Уведомления о заказах", callback_data="notifications")],
            [
                InlineKeyboardButton(
                    text="Уведомления о выкупах", callback_data="sale_notifications"
                )
            ],
            [InlineKeyboardButton(text="FBS/rFBS контроль", callback_data="control:fbs")],
            [InlineKeyboardButton(text="Остатки", callback_data="stocks")],
            [InlineKeyboardButton(text="Прогноз out-of-stock", callback_data="control:stockout")],
            [InlineKeyboardButton(text="Убыточные заказы", callback_data="profit:loss")],
            [InlineKeyboardButton(text="Низкая маржа", callback_data="control:low_margin")],
            [
                InlineKeyboardButton(
                    text="Ошибки синхронизации",
                    callback_data="control:sync_errors",
                )
            ],
            [InlineKeyboardButton(text="Качество данных", callback_data="control:data_quality")],
            [InlineKeyboardButton(text="Назад", callback_data="back_main")],
        ]
    )


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users")],
            [InlineKeyboardButton(text="🏪 Подключённые кабинеты", callback_data="admin:accounts")],
            [InlineKeyboardButton(text="🔄 Синхронизации", callback_data="admin:sync")],
            [InlineKeyboardButton(text="📊 Системная статистика", callback_data="admin:system")],
            [InlineKeyboardButton(text="🧪 Диагностика заказов", callback_data="admin:orders")],
            [InlineKeyboardButton(text="🧪 Диагностика Wildberries", callback_data="admin:wb")],
            [InlineKeyboardButton(text="🧪 Диагностика событий", callback_data="admin:events")],
            [InlineKeyboardButton(text="🚀 Обновление и деплой", callback_data="admin:deploy")],
            [InlineKeyboardButton(text="Назад", callback_data="back_main")],
        ]
    )


def admin_deploy_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📌 Текущая версия",
                    callback_data="admin_deploy:version",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Проверить обновления",
                    callback_data="admin_deploy:check",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬆ Запустить обновление",
                    callback_data="admin_deploy:update",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧾 Статус последнего деплоя",
                    callback_data="admin_deploy:status",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📄 Последний лог обновления",
                    callback_data="admin_deploy:log",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💾 Последние backup",
                    callback_data="admin_deploy:backups",
                )
            ],
            [InlineKeyboardButton(text="Назад", callback_data="admin_menu")],
        ]
    )


def confirm_deploy_update() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, обновить",
                    callback_data="admin_deploy:update_confirm",
                ),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_deploy:cancel"),
            ],
            [InlineKeyboardButton(text="Назад", callback_data="admin:deploy")],
        ]
    )


def web_cabinet_link(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Открыть web-кабинет", url=url)],
            [InlineKeyboardButton(text="📊 Сводка", callback_data="summary")],
        ]
    )


def settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подключить Wildberries", callback_data="connect_wb")],
            [InlineKeyboardButton(text="Подключить Ozon", callback_data="connect_ozon")],
            [InlineKeyboardButton(text="Подключённые магазины", callback_data="accounts")],
            [InlineKeyboardButton(text="Товары и себестоимость", callback_data="costs")],
            [InlineKeyboardButton(text="Настройки уведомлений", callback_data="notifications")],
            [InlineKeyboardButton(text="Время ежедневных отчётов", callback_data="report_time")],
            [InlineKeyboardButton(text="Часовой пояс", callback_data="timezone")],
            [InlineKeyboardButton(text="🌐 Web-кабинет", callback_data="web_cabinet")],
            [InlineKeyboardButton(text="Помощь / инструкция", callback_data="help")],
            [InlineKeyboardButton(text="Назад", callback_data="back_main")],
        ]
    )


def notification_settings_menu(enabled: bool) -> InlineKeyboardMarkup:
    text = "Отключить уведомления" if enabled else "Включить уведомления"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data="notifications:toggle")],
            [InlineKeyboardButton(text="Назад", callback_data="control_menu")],
        ]
    )


def sale_notification_settings_menu(enabled: bool) -> InlineKeyboardMarkup:
    text = "Отключить уведомления о выкупах" if enabled else "Включить уведомления о выкупах"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data="sale_notifications:toggle")],
            [InlineKeyboardButton(text="Назад", callback_data="control_menu")],
        ]
    )


def timezone_menu(current_timezone: str = "Europe/Moscow") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for label, value in TIMEZONE_OPTIONS:
        marker = "✓ " if value == current_timezone else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker}{label}",
                    callback_data=f"timezone:set:{value}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Назад", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
                    text="🔄 Загрузить историю",
                    callback_data=f"account:{account_id}:history",
                )
            ]
        )
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


def account_history_periods(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Последние 30 дней",
                    callback_data=f"account:{account_id}:history_30",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Последние 90 дней",
                    callback_data=f"account:{account_id}:history_90",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Последние 180 дней",
                    callback_data=f"account:{account_id}:history_180",
                )
            ],
            [InlineKeyboardButton(text="Назад", callback_data=f"account:{account_id}:view")],
        ]
    )


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
