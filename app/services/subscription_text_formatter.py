"""version: 1.0.0
description: Centralized subscription and tariff text formatting service.
updated: 2026-05-16
"""

from dataclasses import dataclass
from decimal import Decimal
from html import escape as html_escape

from app.models.subscriptions import SubscriptionTier


@dataclass(frozen=True, slots=True)
class TierFeatureInfo:
    """Information about a single feature for a tier."""

    name: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class TierCardInfo:
    """Complete information for rendering a tier card."""

    code: str
    name: str
    emoji: str
    description: str
    price_monthly: Decimal | None
    price_yearly: Decimal | None
    max_marketplace_accounts: int | str
    max_orders_per_month: int | str
    max_products: int | str
    features: list[TierFeatureInfo]
    additional_info: list[str] | None = None
    is_current: bool = False


TIER_EMOJI: dict[str, str] = {
    "free": "🆓",
    "basic": "⭐️",
    "pro": "💎",
    "enterprise": "🏢",
}

TIER_MARKETING_DESCRIPTIONS: dict[str, str] = {
    "free": "Бесплатный тариф для начинающих",
    "basic": (
        "Базовый тариф для селлеров, которым нужен ежедневный контроль заказов, прибыли и рисков."
    ),
    "pro": (
        "Профессиональный тариф для активных селлеров, которым нужна глубокая аналитика, "
        "контроль прибыльности и прогнозирование."
    ),
    "enterprise": (
        "Индивидуальный тариф для агентств, крупных брендов, команд и проектов "
        "с особыми требованиями."
    ),
}

TIER_OVERVIEW_DESCRIPTIONS: dict[str, str] = {
    "free": "Бесплатный старт для знакомства с MP Control.",
    "basic": "Для ежедневного контроля заказов, прибыли и ключевых рисков.",
    "pro": "Для глубокой аналитики, план/факт контроля и управления прибыльностью.",
    "enterprise": "Для команд, агентств, крупных брендов и нестандартных интеграций.",
}

TIER_FEATURE_NAMES: list[tuple[str, str]] = [
    ("feature_web_cabinet", "Web-кабинет"),
    ("feature_analytics", "Расширенная аналитика"),
    ("feature_plan_fact", "План/факт анализ"),
    ("feature_break_even", "Безубыточная цена"),
    ("feature_stock_forecast", "Прогноз остатков"),
    ("feature_alerts", "Умные алерты"),
    ("feature_priority_support", "Приоритетная поддержка"),
    ("feature_api_access", "API-доступ"),
]

ENTERPRISE_ADDITIONAL_INFO: list[str] = [
    "Индивидуальные лимиты",
    "Роли и команды",
    "Возможность нестандартных интеграций",
    "Персональные условия сопровождения",
]


def _format_price(value: Decimal | None) -> str:
    """Format a Decimal price value for display with thousand separators."""
    if value is None:
        return "—"
    int_part = int(value)
    formatted = f"{int_part:,}".replace(",", " ")
    if value != int_part:
        formatted = f"{value:,}".replace(",", " ")
    return f"{formatted} ₽"


def _format_limit(value: int | None, unlimited_label: str = "без ограничений") -> str | int:
    """Format a limit value for display."""
    if value is None:
        return unlimited_label
    return value


def _html(value: object) -> str:
    """Escape dynamic values before inserting them into Telegram HTML."""
    return html_escape(str(value), quote=False)


def _build_features_list(tier: SubscriptionTier) -> list[TierFeatureInfo]:
    """Build feature list from a SubscriptionTier model."""
    return [
        TierFeatureInfo(name=label, enabled=getattr(tier, attr, False))
        for attr, label in TIER_FEATURE_NAMES
    ]


def build_tier_card(
    tier: SubscriptionTier,
    *,
    is_current: bool = False,
) -> TierCardInfo:
    """Build a complete tier card from a SubscriptionTier model."""
    code = tier.code.lower()
    emoji = TIER_EMOJI.get(code, "💳")
    description = TIER_MARKETING_DESCRIPTIONS.get(code, tier.description or "")

    max_mp = tier.max_marketplace_accounts if code != "enterprise" else "индивидуально"
    max_orders: int | str
    if code == "enterprise":
        max_orders = "индивидуально"
    elif tier.max_orders_per_month is None:
        max_orders = "без ограничений"
    else:
        max_orders = tier.max_orders_per_month

    max_products: int | str
    if code == "enterprise":
        max_products = "индивидуально"
    elif tier.max_products is None:
        max_products = "без ограничений"
    else:
        max_products = tier.max_products

    additional = None
    if code == "enterprise":
        additional = ENTERPRISE_ADDITIONAL_INFO

    return TierCardInfo(
        code=code,
        name=tier.name,
        emoji=emoji,
        description=description,
        price_monthly=tier.price_monthly if code not in ("free", "enterprise") else None,
        price_yearly=tier.price_yearly if code not in ("free", "enterprise") else None,
        max_marketplace_accounts=max_mp,
        max_orders_per_month=max_orders,
        max_products=max_products,
        features=_build_features_list(tier),
        additional_info=additional,
        is_current=is_current,
    )


def format_tier_card(
    card: TierCardInfo,
    *,
    support_username: str = "mpcontrol_support",
) -> str:
    """Format a tier card into a Telegram-ready message text."""
    lines: list[str] = [
        f"{card.emoji} <b>{_html(card.name)}</b>",
        "",
        _html(card.description),
        "",
        "<b>Стоимость:</b>",
    ]

    if card.code == "free":
        lines.append("• Бесплатно")
    elif card.code == "enterprise":
        lines.append("• Индивидуальные условия")
    else:
        monthly = _format_price(card.price_monthly)
        yearly = _format_price(card.price_yearly)
        lines.append(f"• {monthly} / месяц")
        if card.price_yearly:
            lines.append(f"• {yearly} / год")

    lines.extend(
        [
            "",
            "<b>Лимиты:</b>",
            f"• Кабинетов МП: {card.max_marketplace_accounts}",
            f"• Заказов в месяц: {card.max_orders_per_month}",
            f"• SKU в аналитике: {card.max_products}",
        ]
    )

    lines.extend(["", "<b>Функции:</b>"])
    for feature in card.features:
        icon = "✅" if feature.enabled else "❌"
        lines.append(f"{icon} {_html(feature.name)}")

    if card.additional_info:
        lines.extend(["", "<b>Дополнительно:</b>"])
        for info in card.additional_info:
            lines.append(f"• {_html(info)}")

    if card.is_current:
        lines.extend(["", "✅ <b>Это ваш текущий тариф</b>"])
    elif card.code == "free":
        lines.extend(["", "🆓 Бесплатный тариф доступен всем пользователям."])
    elif card.code == "enterprise":
        support_link = _html(f"@{support_username.lstrip('@')}")
        lines.extend(
            [
                "",
                f"📩 Для подключения тарифа ENTERPRISE напишите в поддержку: {support_link}",
            ]
        )

    return "\n".join(lines)


def format_pricing_overview(tiers: list[TierCardInfo]) -> str:
    """Format the main pricing overview screen."""
    lines = [
        "💎 <b>Тарифы и подписки</b>",
        "",
        "Выберите подходящий тариф и откройте подробное описание его возможностей.",
        "",
    ]

    for tier in tiers:
        description = TIER_OVERVIEW_DESCRIPTIONS.get(tier.code, tier.description)
        if tier.code == "free":
            lines.append(f"{tier.emoji} <b>{_html(tier.name)}</b>")
            lines.append(_html(description))
        elif tier.code == "enterprise":
            lines.append(f"{tier.emoji} <b>{_html(tier.name)}</b>")
            lines.append("Индивидуальные условия.")
            lines.append(_html(description))
        else:
            monthly = _format_price(tier.price_monthly)
            yearly = _format_price(tier.price_yearly)
            lines.append(f"{tier.emoji} <b>{_html(tier.name)}</b>")
            lines.append(f"{monthly} / месяц или {yearly} / год.")
            lines.append(_html(description))
        lines.append("")

    lines.append("<b>Выберите тариф ниже, чтобы посмотреть подробности.</b>")
    return "\n".join(lines)


def format_current_subscription(
    tier_name: str,
    *,
    is_active: bool = False,
    expires_at: str | None = None,
    is_trial: bool = False,
    trial_ends_at: str | None = None,
    features: list[tuple[str, bool]] | None = None,
    is_free: bool = True,
) -> str:
    """Format the current subscription screen."""
    lines = [
        "💳 <b>Ваша подписка</b>",
        "",
        "Текущий тариф:",
        f"<b>{_html(tier_name)}</b>",
        "",
        "<b>Статус:</b>",
    ]

    if is_free:
        lines.append("• Бесплатный тариф активен")
    elif is_trial:
        lines.append("• Пробный период")
        if trial_ends_at:
            lines.append(f"• Пробный период до: {trial_ends_at}")
    elif is_active:
        lines.append("• Активна")
        if expires_at:
            lines.append(f"• Действует до: {expires_at}")
    else:
        lines.append("• Неактивна")

    if features:
        lines.extend(["", "<b>Доступ сейчас:</b>"])
        for name, enabled in features:
            icon = "✅" if enabled else "❌"
            lines.append(f"{icon} {_html(name)}")

    if is_free:
        lines.extend(
            [
                "",
                "Чтобы открыть больше возможностей, выберите подходящий тариф ниже.",
            ]
        )

    return "\n".join(lines)


def format_subscription_help(support_username: str = "mpcontrol_support") -> str:
    """Format the subscription help screen."""
    support_link = _html(f"@{support_username.lstrip('@')}")
    return (
        "❓ <b>Помощь по подпискам</b>\n\n"
        "<b>Как работает подписка?</b>\n"
        "После оплаты подписка активируется автоматически. "
        "Вы получаете доступ ко всем функциям выбранного тарифа.\n\n"
        "<b>Как оплатить?</b>\n"
        "Выберите тариф → нажмите кнопку оплаты → оплатите через ЮКасса "
        "(карта, СБП, электронные кошельки).\n\n"
        "<b>Можно ли отменить?</b>\n"
        "Да, вы можете отменить подписку в любой момент. "
        "Доступ сохранится до конца оплаченного периода.\n\n"
        "<b>Что будет после окончания?</b>\n"
        "Если автопродление отключено, вы вернётесь на тариф FREE. "
        "Ваши данные сохранятся.\n\n"
        "<b>Есть пробный период?</b>\n"
        "Да, для новых пользователей доступен пробный период PRO на 14 дней.\n\n"
        f"<b>Вопросы?</b>\n"
        f"Напишите в поддержку: {support_link}"
    )


def format_admin_tariff_confirmation(
    user_name: str,
    new_tier_name: str,
    expires_at: str | None = None,
) -> str:
    """Format admin tariff change confirmation message."""
    lines = [
        "✅ <b>Тариф успешно изменён</b>",
        "",
        f"Пользователь: <b>{_html(user_name)}</b>",
        f"Новый тариф: <b>{_html(new_tier_name)}</b>",
    ]
    if expires_at:
        lines.append(f"Срок действия: <b>{_html(expires_at)}</b>")
    else:
        lines.append("Срок действия: <b>бессрочно</b>")
    return "\n".join(lines)


def format_user_tariff_notification(
    new_tier_name: str,
    expires_at: str | None = None,
) -> str:
    """Format notification sent to user when admin changes their tariff."""
    lines = [
        "🎉 <b>Ваш тариф изменён</b>",
        "",
        "Администратор сервиса назначил вам тариф:",
        f"<b>{_html(new_tier_name)}</b>",
        "",
        "Действует до:",
    ]
    if expires_at:
        lines.append(f"<b>{_html(expires_at)}</b>")
    else:
        lines.append("<b>бессрочно</b>")
    lines.extend(
        [
            "",
            "Открыть информацию о подписке можно через /subscription.",
        ]
    )
    return "\n".join(lines)
