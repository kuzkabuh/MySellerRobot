"""version: 1.5.0
description: Main Telegram inline keyboards and control settings menus.
updated: 2026-05-15
"""

from decimal import Decimal

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
        [
            InlineKeyboardButton(text="💎 Подписка и тарифы", callback_data="subscription_menu"),
            InlineKeyboardButton(text="⚙ Настройки", callback_data="settings"),
        ],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
            InlineKeyboardButton(text="🔄 Синхронизация", callback_data="sync_menu"),
        ],
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
            [
                InlineKeyboardButton(
                    text="💳 Управление тарифами",
                    callback_data="admin_tariff_menu",
                )
            ],
            [InlineKeyboardButton(text="🔄 Синхронизации", callback_data="admin:sync")],
            [InlineKeyboardButton(text="📊 Системная статистика", callback_data="admin:system")],
            [InlineKeyboardButton(text="🧪 Диагностика заказов", callback_data="admin:orders")],
            [InlineKeyboardButton(text="🧪 Диагностика Wildberries", callback_data="admin:wb")],
            [InlineKeyboardButton(text="🧪 Диагностика событий", callback_data="admin:events")],
            [InlineKeyboardButton(text="🚀 Обновление и деплой", callback_data="admin:deploy")],
            [
                InlineKeyboardButton(
                    text="🔧 Реконсиляция подписок",
                    callback_data="admin:reconcile_subs",
                )
            ],
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
            [InlineKeyboardButton(text="Профиль", callback_data="profile")],
            [InlineKeyboardButton(text="Запустить синхронизацию", callback_data="sync_menu")],
            [InlineKeyboardButton(text="Товары и себестоимость", callback_data="costs")],
            [InlineKeyboardButton(text="Настройки уведомлений", callback_data="notifications")],
            [InlineKeyboardButton(text="Время ежедневных отчётов", callback_data="report_time")],
            [InlineKeyboardButton(text="Часовой пояс", callback_data="timezone")],
            [InlineKeyboardButton(text="🌐 Web-кабинет", callback_data="web_cabinet")],
            [InlineKeyboardButton(text="Помощь / инструкция", callback_data="help")],
            [InlineKeyboardButton(text="Назад", callback_data="back_main")],
        ]
    )


def sync_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Заказы", callback_data="sync:orders")],
            [InlineKeyboardButton(text="Продажи и выкупы", callback_data="sync:sales")],
            [InlineKeyboardButton(text="Остатки", callback_data="sync:stocks")],
            [InlineKeyboardButton(text="Товары", callback_data="sync:products")],
            [InlineKeyboardButton(text="Продавец и баланс WB", callback_data="sync:wb-profile")],
            [InlineKeyboardButton(text="Отчёты WB", callback_data="sync:wb-reports")],
            [InlineKeyboardButton(text="Каталог Ozon", callback_data="sync:ozon-enrichment")],
            [InlineKeyboardButton(text="Назад", callback_data="back_main")],
        ]
    )


def profile_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Web-кабинет", callback_data="web_cabinet")],
            [InlineKeyboardButton(text="🏪 Мои кабинеты", callback_data="accounts")],
            [InlineKeyboardButton(text="💎 Подписка", callback_data="subscription:current")],
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


def low_margin_threshold_menu(current_threshold: Decimal) -> InlineKeyboardMarkup:
    """Build quick controls for the user's low-margin threshold."""

    quick_values = ("5", "10", "15", "20")
    rows = []
    for value in quick_values:
        marker = "✓ " if current_threshold == Decimal(value) else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker}{value}%",
                    callback_data=f"low_margin:set:{value}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Ввести вручную", callback_data="low_margin:manual")])
    rows.append([InlineKeyboardButton(text="Открыть прибыль в web", callback_data="web_cabinet")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="control_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
                    text="👤 Продавец и баланс",
                    callback_data=f"account:{account_id}:seller",
                )
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="📄 Отчёты WB",
                    callback_data=f"account:{account_id}:reports",
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


def subscription_menu() -> InlineKeyboardMarkup:
    """Main subscription menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Моя подписка", callback_data="subscription:current")],
            [InlineKeyboardButton(text="💎 Тарифы и цены", callback_data="subscription:pricing")],
            [
                InlineKeyboardButton(
                    text="📜 История платежей",
                    callback_data="subscription:payments",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❓ Помощь по подпискам",
                    callback_data="subscription:help",
                )
            ],
            [InlineKeyboardButton(text="Назад", callback_data="back_main")],
        ]
    )


def subscription_current_menu(has_active: bool = False) -> InlineKeyboardMarkup:
    """Menu for current subscription view."""
    buttons = [
        [InlineKeyboardButton(text="💎 Сменить тариф", callback_data="subscription:pricing")],
        [InlineKeyboardButton(text="📜 История платежей", callback_data="subscription:payments")],
    ]
    if has_active:
        buttons.insert(
            1,
            [
                InlineKeyboardButton(
                    text="❌ Отменить подписку",
                    callback_data="subscription:cancel_confirm",
                )
            ],
        )
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="subscription_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def subscription_pricing_menu() -> InlineKeyboardMarkup:
    """Menu for pricing/tiers selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🆓 FREE — Бесплатно",
                    callback_data="subscription:tier:free",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭐ BASIC — 490₽/мес",
                    callback_data="subscription:tier:basic",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 PRO — 1490₽/мес",
                    callback_data="subscription:tier:pro",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏢 ENTERPRISE — По запросу",
                    callback_data="subscription:tier:enterprise",
                )
            ],
            [InlineKeyboardButton(text="📊 Сравнить тарифы", callback_data="subscription:compare")],
            [InlineKeyboardButton(text="Назад", callback_data="subscription_menu")],
        ]
    )


def subscription_tier_detail_menu(tier_code: str, current_tier_code: str) -> InlineKeyboardMarkup:
    """Menu for specific tier details."""
    buttons = []

    if tier_code != "free" and tier_code != current_tier_code:
        if tier_code == "basic":
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="💳 Оплатить 490₽/мес",
                        callback_data=f"subscription:pay:{tier_code}:monthly",
                    ),
                    InlineKeyboardButton(
                        text="💳 Оплатить 4900₽/год",
                        callback_data=f"subscription:pay:{tier_code}:yearly",
                    ),
                ]
            )
        elif tier_code == "pro":
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="💳 Оплатить 1490₽/мес",
                        callback_data=f"subscription:pay:{tier_code}:monthly",
                    ),
                    InlineKeyboardButton(
                        text="💳 Оплатить 14900₽/год",
                        callback_data=f"subscription:pay:{tier_code}:yearly",
                    ),
                ]
            )
        elif tier_code == "enterprise":
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="📧 Связаться с нами", url="https://t.me/mpcontrol_support"
                    ),
                ]
            )

    buttons.extend(
        [
            [InlineKeyboardButton(text="📊 Сравнить тарифы", callback_data="subscription:compare")],
            [InlineKeyboardButton(text="Назад", callback_data="subscription:pricing")],
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def subscription_payment_confirm_menu(
    tier_code: str,
    period: str,
    amount: str,
) -> InlineKeyboardMarkup:
    """Confirmation menu before payment."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ Оплатить {amount}",
                    callback_data=f"subscription:pay_confirm:{tier_code}:{period}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"subscription:tier:{tier_code}",
                )
            ],
        ]
    )


def subscription_cancel_confirm_menu() -> InlineKeyboardMarkup:
    """Confirmation menu for subscription cancellation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, отменить",
                    callback_data="subscription:cancel_confirmed",
                ),
                InlineKeyboardButton(text="❌ Нет, оставить", callback_data="subscription:current"),
            ],
        ]
    )


def subscription_payments_menu() -> InlineKeyboardMarkup:
    """Menu for payment history."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="subscription_menu")],
        ]
    )


def subscription_tier_detail_menu_v2(
    tier_code: str,
    current_tier_code: str,
    has_payment: bool = True,
) -> InlineKeyboardMarkup:
    """Unified tier detail menu with payment buttons."""
    buttons: list[list[InlineKeyboardButton]] = []

    if tier_code != "free" and tier_code != current_tier_code and has_payment:
        if tier_code == "basic":
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="💳 Оплатить 490 ₽ / месяц",
                        callback_data="subscription:pay:basic:monthly",
                    ),
                    InlineKeyboardButton(
                        text="💳 Оплатить 4 900 ₽ / год",
                        callback_data="subscription:pay:basic:yearly",
                    ),
                ]
            )
        elif tier_code == "pro":
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="💳 Оплатить 1 490 ₽ / месяц",
                        callback_data="subscription:pay:pro:monthly",
                    ),
                    InlineKeyboardButton(
                        text="💳 Оплатить 14 900 ₽ / год",
                        callback_data="subscription:pay:pro:yearly",
                    ),
                ]
            )
        elif tier_code == "enterprise":
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="💬 Написать в поддержку",
                        url="https://t.me/mpcontrol_support",
                    ),
                ]
            )

    buttons.append(
        [
            InlineKeyboardButton(text="◀️ К тарифам", callback_data="subscription:pricing"),
        ]
    )
    buttons.append(
        [
            InlineKeyboardButton(text="❓ Помощь", callback_data="subscription:help"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def subscription_pricing_menu_v2() -> InlineKeyboardMarkup:
    """Unified pricing menu with all tiers."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆓 FREE", callback_data="subscription:tier:free")],
            [InlineKeyboardButton(text="⭐️ BASIC", callback_data="subscription:tier:basic")],
            [InlineKeyboardButton(text="💎 PRO", callback_data="subscription:tier:pro")],
            [
                InlineKeyboardButton(
                    text="🏢 ENTERPRISE",
                    callback_data="subscription:tier:enterprise",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❓ Помощь по подпискам",
                    callback_data="subscription:help",
                )
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="subscription_menu")],
        ]
    )


def subscription_current_menu_v2(has_active: bool = False) -> InlineKeyboardMarkup:
    """Unified current subscription menu."""
    buttons: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="💎 Тарифы и цены", callback_data="subscription:pricing")],
    ]
    if has_active:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="❌ Отменить подписку",
                    callback_data="subscription:cancel_confirm",
                ),
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(
                text="📜 История платежей",
                callback_data="subscription:payments",
            )
        ]
    )
    buttons.append(
        [
            InlineKeyboardButton(
                text="❓ Помощь по подпискам",
                callback_data="subscription:help",
            )
        ]
    )
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="subscription_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_tariff_menu() -> InlineKeyboardMarkup:
    """Admin tariff management main menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Изменить мой тариф", callback_data="admin_tariff:self")],
            [
                InlineKeyboardButton(
                    text="🔎 Изменить тариф пользователя",
                    callback_data="admin_tariff:user",
                )
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")],
        ]
    )


def admin_tariff_select_menu(target_telegram_id: int | None = None) -> InlineKeyboardMarkup:
    """Tariff selection menu for admin assignment."""

    def callback(tier_code: str, days: int | None = None) -> str:
        parts = ["admin_tariff", "assign", tier_code]
        if days is not None:
            parts.append(str(days))
        if target_telegram_id is not None:
            if days is None:
                parts.append("0")
            parts.append(str(target_telegram_id))
        return ":".join(parts)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆓 FREE", callback_data=callback("free"))],
            [
                InlineKeyboardButton(text="⭐️ BASIC 30 дней", callback_data=callback("basic", 30)),
                InlineKeyboardButton(
                    text="⭐️ BASIC 365 дней",
                    callback_data=callback("basic", 365),
                ),
            ],
            [
                InlineKeyboardButton(text="💎 PRO 30 дней", callback_data=callback("pro", 30)),
                InlineKeyboardButton(text="💎 PRO 365 дней", callback_data=callback("pro", 365)),
            ],
            [
                InlineKeyboardButton(
                    text="🏢 ENTERPRISE бессрочно",
                    callback_data=callback("enterprise"),
                )
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_tariff_menu")],
        ]
    )
