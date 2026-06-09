"""version: 1.0.0
description: Tests for split web rendering compatibility facade.
updated: 2026-06-09
"""

from app.web.rendering import (
    ADMIN_NAV_GROUPS,
    NAV_GROUPS,
    NAV_ICONS,
    _css,
    _js,
    _nav,
    page,
)


def test_rendering_facade_exports_page() -> None:
    html = page("Тест", "Пользователь", "<p>OK</p>")

    assert '<html lang="ru">' in html
    assert "Тест" in html
    assert "<p>OK</p>" in html


def test_rendering_facade_exports_navigation_constants() -> None:
    assert NAV_GROUPS
    assert ADMIN_NAV_GROUPS
    assert NAV_ICONS


def test_rendering_css_and_js_are_available() -> None:
    assert ":root" in _css()
    assert "sidebar" in _js()


def test_user_nav_contains_orders() -> None:
    html = _nav("/web/orders", False)

    assert "Заказы" in html
    assert "Панель управления" not in html


def test_admin_nav_contains_admin_group() -> None:
    html = _nav("/web/admin", True)

    assert "Панель управления" in html


def test_web_routes_import_after_rendering_split() -> None:
    from app.web.routes import router

    assert router.prefix == "/web"
