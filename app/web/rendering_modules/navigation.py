"""version: 1.0.0
description: Navigation rendering for MP Control web cabinet.
updated: 2026-06-09
"""

# ruff: noqa: E501

from html import escape

from app.web.rendering_modules.icons import NAV_ICONS, NAV_ICONS_FALLBACK

NAV_GROUPS = [
    ("Основное", [("Главная", "/web/")]),
    ("Заказы", [("Заказы", "/web/orders")]),
    (
        "Товары",
        [
            ("Товары", "/web/products"),
        ],
    ),
    (
        "Финансы",
        [
            ("Прибыль", "/web/profit"),
        ],
    ),
    (
        "Цены и акции",
        [
            ("Цены и акции", "/web/pricing"),
        ],
    ),
    (
        "Кабинеты МП",
        [
            ("Кабинеты МП", "/web/settings?tab=marketplaces"),
        ],
    ),
    (
        "Аккаунт",
        [
            ("Аккаунт", "/web/settings?tab=profile"),
        ],
    ),
]

ADMIN_NAV_GROUPS = [
    (
        "Админка",
        [
            ("Обзор", "/web/admin"),
            ("Пользователи", "/web/admin/users"),
            ("Тарифы и промокоды", "/web/admin/tariffs"),
            ("Платежи", "/web/admin/payments"),
            ("Интеграции", "/web/admin/commissions"),
            ("Синхронизации", "/web/admin/sync-status"),
            ("Логи и аудит", "/web/admin/logs"),
            ("Бэкапы", "/web/admin/backups"),
        ],
    ),
]

__all__ = [
    "NAV_GROUPS",
    "ADMIN_NAV_GROUPS",
    "_nav",
]


def _nav(active_path: str, show_admin: bool = False) -> str:
    def is_active(href: str) -> bool:
        if href == active_path:
            return True
        if href.startswith("/web/settings?tab=") and active_path == "/web/settings":
            return href.endswith("=profile")
        if href.startswith("/web/settings?tab=") and active_path.startswith("/web/settings?tab="):
            return href == active_path
        return False

    groups = []
    for title, items in NAV_GROUPS:
        links = []
        for label, href in items:
            active = ' class="active"' if is_active(href) else ""
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
                active = ' class="active"' if is_active(href) else ""
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
