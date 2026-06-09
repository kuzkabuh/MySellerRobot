"""version: 1.0.0
description: Diagnostic tests verifying navigation–route consistency.
updated: 2026-06-10
"""

from app.web.rendering import (
    ADMIN_NAV_GROUPS,
    NAV_GROUPS,
    NAV_ICONS,
    _nav,
    page,
)
from app.web.routes import router


def _all_web_routes() -> set[str]:
    """Return set of all unique GET route paths under /web/... or /admin/...
    Includes routes registered on the /web prefix router plus known app-level routes.
    """
    paths: set[str] = set()
    for route in router.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            path: str = route.path
            methods = route.methods  # type: ignore[attr-defined]
            if "GET" in methods and not path.endswith("/{section:path}"):
                normalized = path.rstrip("/") or "/"
                paths.add(normalized)
                if "{" not in path:
                    paths.add(path)
    # App-level routes not under /web prefix (registered directly in create_app)
    paths.add("/admin/wb-logistics")
    return paths


def test_all_nav_urls_exist_as_routes() -> None:
    """Every href in NAV_GROUPS and ADMIN_NAV_GROUPS must match a real route."""
    routes_set = _all_web_routes()
    errors = []
    for group_title, items in NAV_GROUPS:
        for label, href in items:
            path = href.split("?")[0]
            path = path.rstrip("/") or "/"
            if path not in routes_set and not _is_pattern_path(href, routes_set):
                errors.append(f"User nav '{label}' → {href} not found in routes")
    for group_title, items in ADMIN_NAV_GROUPS:
        for label, href in items:
            path = href.split("?")[0]
            path = path.rstrip("/") or "/"
            if path not in routes_set and not _is_pattern_path(href, routes_set):
                errors.append(f"Admin nav '{label}' → {href} not found in routes")
    assert not errors, "\n".join(errors)


def _is_pattern_path(href: str, routes_set: set[str]) -> bool:
    """Check if href matches a pattern route like /web/orders/{order_id}."""
    base = href.split("?")[0].rstrip("/")
    for route in routes_set:
        if "{" in route:
            route_base = route.split("{")[0].rstrip("/")
            if base.startswith(route_base):
                return True
        if base + "/" == route:
            return True
    return False


def test_no_duplicate_hrefs_in_nav() -> None:
    """No duplicate URLs across user or admin nav groups."""
    seen: set[str] = set()
    duplicates: list[str] = []
    for group_title, items in list(NAV_GROUPS) + list(ADMIN_NAV_GROUPS):
        for label, href in items:
            if href in seen:
                duplicates.append(f"Duplicate: {href} ({label})")
            seen.add(href)
    assert not duplicates, "\n".join(duplicates)


def test_no_admin_urls_in_user_nav() -> None:
    """User navigation must not contain admin-prefixed URLs."""
    for group_title, items in NAV_GROUPS:
        for label, href in items:
            if href.startswith("/web/admin/") or href.startswith("/admin/"):
                assert False, f"Admin URL {href} found in user nav ({label})"


def test_all_nav_labels_have_icons() -> None:
    """Every label in NAV_GROUPS and ADMIN_NAV_GROUPS must have an icon."""
    missing: list[str] = []
    for group_title, items in list(NAV_GROUPS) + list(ADMIN_NAV_GROUPS):
        for label, href in items:
            if label not in NAV_ICONS:
                missing.append(f"Missing icon for '{label}' ({href})")
    assert not missing, "\n".join(missing)


def test_nav_builds_for_guest() -> None:
    """nav() with show_admin=False must not raise."""
    html = _nav("/web/", False)
    assert '<a' in html
    assert 'href="/web/"' in html


def test_nav_builds_for_user() -> None:
    """nav() with user-level path."""
    html = _nav("/web/orders", False)
    assert 'href="/web/orders"' in html


def test_nav_builds_for_admin() -> None:
    """nav() with admin path and show_admin=True."""
    html = _nav("/web/admin", True)
    assert 'href="/web/admin"' in html
    assert 'href="/web/admin/users"' in html


def test_page_renders_for_all_nav_active_paths() -> None:
    """page() must render without error for every nav href as active_path."""
    for group_title, items in list(NAV_GROUPS) + list(ADMIN_NAV_GROUPS):
        for label, href in items:
            html = page("Test", "User", "<p>OK</p>", active_path=href)
            assert "<p>OK</p>" in html
            assert "Test" in html
