"""version: 2.0.0
description: Compact sidebar navigation for MP Control web cabinet.
updated: 2026-06-09
"""

# ruff: noqa: E501

from html import escape

from app.web.rendering_modules.icons import NAV_ICONS, NAV_ICONS_FALLBACK

# ── User sidebar: compact, only top-level sections ──
NAV_GROUPS = [
    (
        "Основное",
        [("Главная", "/web/")],
    ),
    (
        "Продажи",
        [("Заказы и продажи", "/web/orders")],
    ),
    (
        "Товары",
        [("Товары", "/web/products")],
    ),
    (
        "Финансы",
        [("Финансы", "/web/profit")],
    ),
    (
        "Цены",
        [("Цены и акции", "/web/pricing")],
    ),
    (
        "Отчёты",
        [("Отчёты", "/web/reports/wb-daily")],
    ),
    (
        "Мониторинг",
        [("Мониторинг", "/web/control")],
    ),
    (
        "Аккаунт",
        [
            ("Профиль", "/web/settings?tab=profile"),
            ("Мои кабинеты", "/web/accounts"),
            ("Настройки", "/web/settings"),
            ("Подписка и тариф", "/web/subscription"),
        ],
    ),
    (
        "Помощь",
        [("Поддержка", "/web/support")],
    ),
]

# ── Admin sidebar: shown only for admin/superadmin ──
ADMIN_NAV_GROUPS = [
    (
        "Админка",
        [
            ("Обзор", "/web/admin"),
            ("Пользователи", "/web/admin/users"),
            ("Финансы", "/web/admin/tariffs"),
            ("Интеграции", "/web/admin/commissions"),
            ("Система", "/web/admin/logs"),
        ],
    ),
]

# ── Prefix-based section membership for active detection ──
# Each sidebar label maps to URL prefixes that should highlight it.
SECTION_PREFIXES: dict[str, list[str]] = {
    "Главная": ["/web/?"],
    "Заказы и продажи": ["/web/orders", "/web/sales", "/web/returns"],
    "Товары": ["/web/products", "/web/stocks", "/web/costs", "/web/product-matching", "/web/data-quality", "/web/alerts"],
    "Финансы": ["/web/profit", "/web/plan-fact", "/web/break-even", "/web/finances", "/web/finances/unmatched"],
    "Цены и акции": ["/web/pricing", "/web/mrc-pricing", "/web/auto-promo"],
    "Отчёты": ["/web/reports", "/web/wb-daily-reports"],
    "Мониторинг": ["/web/control", "/web/operations"],
    "Мои кабинеты": ["/web/accounts"],
    "Настройки": ["/web/settings"],
    "Подписка и тариф": ["/web/subscription"],
    "Поддержка": ["/web/support"],
    # Admin
    "Обзор": ["/web/admin$", "/web/health"],
    "Пользователи": ["/web/admin/users"],
    "Финансы": ["/web/admin/tariffs", "/web/admin/promocodes", "/web/admin/payments"],
    "Интеграции": ["/web/admin/commissions", "/web/admin/wb-logistics", "/web/admin/wb-reports"],
    "Система": ["/web/admin/logs", "/web/admin/sync-status", "/web/admin/backup", "/web/admin/support", "/web/admin/system"],
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
                # Exact match required
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
