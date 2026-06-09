"""version: 1.1.0
description: Navigation rendering for MP Control web cabinet.
updated: 2026-06-09
"""

# ruff: noqa: E501

from html import escape

from app.web.rendering_modules.icons import NAV_ICONS, NAV_ICONS_FALLBACK

NAV_GROUPS = [
    (
        "Основное",
        [
            ("Главная", "/web/"),
        ],
    ),
    (
        "Заказы и продажи",
        [
            ("Заказы", "/web/orders"),
            ("Продажи", "/web/sales"),
            ("Возвраты", "/web/returns"),
        ],
    ),
    (
        "Товары",
        [
            ("Товары", "/web/products"),
            ("Остатки", "/web/stocks"),
            ("Сопоставление WB / Ozon", "/web/product-matching"),
        ],
    ),
    (
        "Финансы",
        [
            ("Прибыль", "/web/profit"),
            ("План / факт", "/web/plan-fact"),
            ("Безубыточность", "/web/break-even"),
            ("Финансовый обзор", "/web/finances"),
        ],
    ),
    (
        "Цены и акции",
        [
            ("Цены и акции", "/web/pricing"),
            ("МРЦ WB", "/web/mrc-pricing"),
        ],
    ),
    (
        "Данные",
        [
            ("Себестоимость", "/web/costs"),
            ("Качество данных", "/web/data-quality"),
            ("Аналитика", "/web/analytics"),
        ],
    ),
    (
        "Мониторинг",
        [
            ("Алерты", "/web/alerts"),
            ("Контроль ошибок", "/web/control"),
        ],
    ),
    (
        "Отчёты",
        [
            ("WB ежедневные отчёты", "/web/reports/wb-daily"),
        ],
    ),
    (
        "Аккаунт",
        [
            ("Профиль", "/web/settings?tab=profile"),
            ("Кабинеты МП", "/web/settings?tab=marketplaces"),
            ("Настройки", "/web/settings"),
        ],
    ),
]

ADMIN_NAV_GROUPS = [
    (
        "Панель управления",
        [
            ("Обзор", "/web/admin"),
            ("Пользователи", "/web/admin/users"),
        ],
    ),
    (
        "Финансы",
        [
            ("Тарифы и промокоды", "/web/admin/tariffs"),
            ("Платежи", "/web/admin/payments"),
        ],
    ),
    (
        "Интеграции",
        [
            ("Интеграции", "/web/admin/commissions"),
            ("WB Логистика", "/web/admin/wb-logistics"),
            ("WB Отчёты", "/web/reports/wb-daily"),
        ],
    ),
    (
        "Система",
        [
            ("Синхронизации", "/web/admin/sync-status"),
            ("Логи и аудит", "/web/admin/logs"),
            ("Бэкапы", "/web/admin/backups"),
            ("Поддержка", "/web/admin/support"),
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
        if href.startswith("/web/settings?tab="):
            if active_path.startswith("/web/settings?tab="):
                return href == active_path
            if active_path == "/web/settings":
                return href.endswith("=profile")
            return False
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
