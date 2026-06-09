"""version: 1.0.0
description: Admin panel keyboards for tariff and promo code management.
updated: 2026-05-31
"""

from decimal import Decimal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models.enums import PromoType
from app.models.promo_codes import PromoCode
from app.models.subscriptions import SubscriptionTier
from app.services.subscriptions.tariff_service import TARIFF_FEATURE_FIELDS

_PERIOD_LABELS = {
    "monthly": "Месяц",
    "3_months": "3 месяца",
    "6_months": "6 месяцев",
    "yearly": "Год",
}


def _rub(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}".replace(",", " ") + " ₽"


def admin_tariffs_list(
    tariffs: list[tuple[SubscriptionTier, int]],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for tariff, user_count in tariffs:
        status = "✅" if tariff.is_active else "❌"
        label = f"{status} {tariff.name} — {_rub(tariff.price_monthly)} ({user_count})"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"ap:tariff:{tariff.id}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_tariff_card(tariff: SubscriptionTier, user_count: int) -> InlineKeyboardMarkup:
    tid = tariff.id
    toggle_text = "❌ Отключить" if tariff.is_active else "✅ Включить"
    public_text = "🙈 Скрыть" if tariff.is_public else "👁 Показать"

    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="✏️ Цена/мес", callback_data=f"ap:tariff:{tid}:price:monthly"
            ),
            InlineKeyboardButton(
                text="✏️ Цена/3мес", callback_data=f"ap:tariff:{tid}:price:3_months"
            ),
        ],
        [
            InlineKeyboardButton(
                text="✏️ Цена/6мес", callback_data=f"ap:tariff:{tid}:price:6_months"
            ),
            InlineKeyboardButton(text="✏️ Цена/год", callback_data=f"ap:tariff:{tid}:price:yearly"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Лимиты", callback_data=f"ap:tariff:{tid}:limits"),
        ],
        [
            InlineKeyboardButton(text=toggle_text, callback_data=f"ap:tariff:{tid}:toggle"),
            InlineKeyboardButton(text=public_text, callback_data=f"ap:tariff:{tid}:public"),
        ],
        [InlineKeyboardButton(text="🔙 К тарифам", callback_data="ap:tariffs")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_tariff_limits_menu(tariff_id: int) -> InlineKeyboardMarkup:
    tid = tariff_id
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Кабинеты МП",
                    callback_data=f"ap:tariff:{tid}:limit:max_marketplace_accounts",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Товары", callback_data=f"ap:tariff:{tid}:limit:max_products"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Пользователи", callback_data=f"ap:tariff:{tid}:limit:max_users"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Интервал синхр. (мин)",
                    callback_data=f"ap:tariff:{tid}:limit:sync_interval_minutes",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Глубина аналитики (дн)",
                    callback_data=f"ap:tariff:{tid}:limit:analytics_depth_days",
                ),
            ],
            [InlineKeyboardButton(text="🔙 К тарифу", callback_data=f"ap:tariff:{tid}")],
        ]
    )


def admin_tariff_confirm(tariff_id: int, field: str, value: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Сохранить",
                    callback_data=f"ap:tariff:{tariff_id}:save:{field}:{value}",
                ),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"ap:tariff:{tariff_id}"),
            ]
        ]
    )


def admin_promos_list(promos: list[PromoCode]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for promo in promos:
        status = "✅" if promo.is_active else "❌"
        if promo.promo_type == PromoType.PERCENT_DISCOUNT:
            discount = f"{promo.discount_percent}%"
        elif promo.promo_type == PromoType.FIXED_DISCOUNT:
            discount = _rub(promo.discount_amount)
        else:
            discount = f"{promo.free_days}д"
        total = str(promo.max_uses_total) if promo.max_uses_total else "∞"
        label = f"{status} {promo.code} — {discount} — {promo.used_count}/{total}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"ap:promo:{promo.id}")])
    rows.append(
        [
            InlineKeyboardButton(text="➕ Создать", callback_data="ap:promo:create"),
            InlineKeyboardButton(text="🔎 Найти", callback_data="ap:promo:search"),
        ]
    )
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_promo_card(promo: PromoCode) -> InlineKeyboardMarkup:
    pid = promo.id
    toggle_text = "❌ Отключить" if promo.is_active else "✅ Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=toggle_text, callback_data=f"ap:promo:{pid}:toggle"),
            ],
            [
                InlineKeyboardButton(text="✏️ Лимит", callback_data=f"ap:promo:{pid}:edit_limit"),
                InlineKeyboardButton(text="✏️ Срок", callback_data=f"ap:promo:{pid}:edit_expires"),
            ],
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data=f"ap:promo:{pid}:stats"),
                InlineKeyboardButton(
                    text="👥 Использования", callback_data=f"ap:promo:{pid}:usages:0"
                ),
            ],
            [InlineKeyboardButton(text="🔙 К промокодам", callback_data="ap:promos")],
        ]
    )


def admin_promo_type_select() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Скидка %", callback_data="ap:promo:type:percent_discount"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💰 Фикс. скидка", callback_data="ap:promo:type:fixed_discount"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎁 Бесплатные дни", callback_data="ap:promo:type:free_days"
                ),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="ap:promos")],
        ]
    )


def admin_promo_tariffs_select(
    tariffs: list[SubscriptionTier], selected: set[int]
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for t in tariffs:
        mark = "☑️" if t.id in selected else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {t.name}",
                    callback_data=f"ap:promo:sel_tariff:{t.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="ap:promo:tariffs_done")])
    rows.append(
        [InlineKeyboardButton(text="⏭ Пропустить (все)", callback_data="ap:promo:tariffs_skip")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_promo_periods_select(selected: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in _PERIOD_LABELS.items():
        mark = "☑️" if code in selected else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {label}",
                    callback_data=f"ap:promo:sel_period:{code}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="ap:promo:periods_done")])
    rows.append(
        [InlineKeyboardButton(text="⏭ Пропустить (все)", callback_data="ap:promo:periods_skip")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_promo_new_users_select() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🆕 Только новые", callback_data="ap:promo:new_users:yes"
                ),
                InlineKeyboardButton(text="👥 Все", callback_data="ap:promo:new_users:no"),
            ]
        ]
    )


def admin_promo_confirm_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Создать", callback_data="ap:promo:confirm_create"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="ap:promos"),
            ]
        ]
    )


def admin_promo_usages_nav(promo_id: int, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"ap:promo:{promo_id}:usages:{page - 1}")
        )
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(text="➡️", callback_data=f"ap:promo:{promo_id}:usages:{page + 1}")
        )
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 К промокоду", callback_data=f"ap:promo:{promo_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_promo_features_text(tariff: SubscriptionTier) -> str:
    lines: list[str] = []
    for field, label in TARIFF_FEATURE_FIELDS:
        enabled = getattr(tariff, field, False)
        icon = "✅" if enabled else "❌"
        lines.append(f"{icon} {label}")
    return "\n".join(lines)
