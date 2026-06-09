"""version: 2.1.0
description: Compact sidebar navigation for MP Control web cabinet – rebuilt from actual routes.
updated: 2026-06-10
"""

# ruff: noqa: E501

from html import escape

from app.web.rendering_modules.icons import NAV_ICONS, NAV_ICONS_FALLBACK

# ── User sidebar ──
NAV_GROUPS = [
    (
        "Основное",
        [
            ("Дашборд", "/web/"),
            ("Заказы", "/web/orders"),
            ("Продажи", "/web/sales"),
            ("Возвраты", "/web/returns"),
        ],
    ),
    (
        "Товары",
        [
            ("Товары", "/web/products"),
            ("Сопоставление", "/web/product-matching"),
            ("Остатки", "/web/stocks"),
            ("Себестоимость", "/web/costs"),
            ("Алерты", "/web/alerts"),
            ("Качество данных", "/web/data-quality"),
        ],
    ),
    (
        "Финансы",
        [
            ("Прибыль", "/web/profit"),
            ("План/факт", "/web/plan-fact"),
            ("Безубыточность", "/web/break-even"),
            ("Финансовый обзор", "/web/finances"),
        ],
    ),
    (
        "Цены и акции",
        [
            ("Цены", "/web/pricing"),
            ("МРЦ WB", "/web/mrc-pricing"),
            ("Акции WB", "/web/wb-promotions"),
            ("Автоакции WB", "/web/auto-promo-prices"),
        ],
    ),
    (
        "Отчёты",
        [
            ("Ежедневные WB", "/web/reports/wb-daily"),
        ],
    ),
    (
        "Мониторинг",
        [
            ("Контроль ошибок", "/web/control"),
            ("Синхронизация", "/web/sync-center"),
            ("Аналитика", "/web/analytics"),
        ],
    ),
    (
        "Аккаунт",
        [
            ("Профиль", "/web/settings?tab=profile"),
            ("Кабинеты МП", "/web/accounts"),
            ("Настройки", "/web/settings"),
            ("Подписка и тариф", "/web/subscription"),
            ("Безопасность", "/web/settings/security"),
        ],
    ),
    (
        "Помощь",
        [
            ("Поддержка", "/web/settings?tab=support"),
        ],
    ),
]

# ── Admin sidebar: shown only for admin/superadmin ──
ADMIN_NAV_GROUPS = [
    (
        "Админка",
        [
            ("Обзор", "/web/admin"),
            ("Пользователи", "/web/admin/users"),
        ],
    ),
    (
        "Финансы",
        [
            ("Тарифы", "/web/admin/tariffs"),
            ("Промокоды", "/web/admin/promocodes"),
            ("Платежи", "/web/admin/payments"),
            ("Комиссии", "/web/admin/commissions"),
        ],
    ),
    (
        "Система",
        [
            ("Логи", "/web/admin/logs"),
            ("Аудит", "/web/admin/audit-log"),
            ("Синхронизации", "/web/admin/sync-status"),
            ("Воркеры", "/web/admin/worker-diagnostics"),
            ("Бэкапы", "/web/admin/backups"),
            ("Обращения", "/web/admin/support"),
            ("Логистика WB", "/admin/wb-logistics"),
        ],
    ),
]

# ── Prefix-based section membership for active detection ──
SECTION_PREFIXES: dict[str, list[str]] = {
    "Дашборд": ["/web/?"],
    "Заказы": ["/web/orders"],
    "Продажи": ["/web/sales"],
    "Возвраты": ["/web/returns"],
    "Товары": ["/web/products"],
    "Сопоставление": ["/web/product-matching"],
    "Остатки": ["/web/stocks"],
    "Себестоимость": ["/web/costs"],
    "Алерты": ["/web/alerts"],
    "Качество данных": ["/web/data-quality"],
    "Прибыль": ["/web/profit$"],
    "План/факт": ["/web/plan-fact"],
    "Безубыточность": ["/web/break-even"],
    "Финансовый обзор": ["/web/finances"],
    "Цены": ["/web/pricing$"],
    "МРЦ WB": ["/web/mrc-pricing", "/web/auto-promo"],
    "Акции WB": ["/web/wb-promotions"],
    "Автоакции WB": ["/web/auto-promo-prices", "/web/auto-promo-import"],
    "Ежедневные WB": ["/web/reports/wb-daily"],
    "Контроль ошибок": ["/web/control"],
    "Синхронизация": ["/web/sync-center", "/web/sync/"],
    "Аналитика": ["/web/analytics"],
    "Профиль": ["/web/settings?tab=profile"],
    "Кабинеты МП": ["/web/accounts"],
    "Настройки": ["/web/settings"],
    "Подписка и тариф": ["/web/subscription"],
    "Безопасность": ["/web/settings/security"],
    "Поддержка": ["/web/settings?tab=support", "/web/settings/support"],
    # Admin
    "Обзор": ["/web/admin$"],
    "Пользователи": ["/web/admin/users"],
    "Тарифы": ["/web/admin/tariffs"],
    "Промокоды": ["/web/admin/promocodes"],
    "Платежи": ["/web/admin/payments"],
    "Комиссии": ["/web/admin/commissions"],
    "Обращения": ["/web/admin/support"],
    "Логи": ["/web/admin/logs"],
    "Аудит": ["/web/admin/audit-log"],
    "Синхронизации": ["/web/admin/sync-status"],
    "Воркеры": ["/web/admin/worker-diagnostics"],
    "Бэкапы": ["/web/admin/backups"],
    "Логистика WB": ["/admin/wb-logistics"],
}

__all__ = [
    "NAV_GROUPS",
    "ADMIN_NAV_GROUPS",
    "SECTION_PREFIXES",
    "_nav",
    "_nav_is_active",
]


def _nav_is_active(path: str, href: str, label: str) -> bool:
    """Check if a sidebar item should be highlighted based on current path."""
    if href == path:
        return True
    # Handle settings tab
    if href.startswith("/web/settings?tab="):
        if path.startswith("/web/settings?tab="):
            return href == path
        if path == "/web/settings":
            return href.endswith("=profile")
        return False
    # Use prefix-based matching from SECTION_PREFIXES
    prefixes = SECTION_PREFIXES.get(label)
    if prefixes:
        for prefix in prefixes:
            if prefix.endswith("$"):
                if path == prefix[:-1]:
                    return True
            elif prefix == "/web/?":
                if path == "/web/" or path == "/web":
                    return True
            elif path.startswith(prefix):
                return True
    return False


def _nav(active_path: str, show_admin: bool = False) -> str:
    groups = []
    for title, items in NAV_GROUPS:
        links = []
        for label, href in items:
            active = ' class="active"' if _nav_is_active(active_path, href, label) else ""
            icon_svg = NAV_ICONS.get(label, NAV_ICONS_FALLBACK)
            links.append(
                f'<a{active} href="{href}"><span class="nav-icon">{icon_svg}</span>'
                f"<span>{escape(label)}</span></a>"
            )
        if links:
            groups.append(
                '<div class="nav-group">'
                f'<div class="nav-title">{escape(title)}</div>' + "\n".join(links) + "</div>"
            )
    if show_admin:
        for title, items in ADMIN_NAV_GROUPS:
            links = []
            for label, href in items:
                active = ' class="active"' if _nav_is_active(active_path, href, label) else ""
                icon_svg = NAV_ICONS.get(label, NAV_ICONS_FALLBACK)
                links.append(
                    f'<a{active} href="{href}"><span class="nav-icon">{icon_svg}</span>'
                    f"<span>{escape(label)}</span></a>"
                )
            if links:
                groups.append(
                    '<div class="nav-group">'
                    f'<div class="nav-title">{escape(title)}</div>' + "\n".join(links) + "</div>"
                )
    return "\n".join(groups)
