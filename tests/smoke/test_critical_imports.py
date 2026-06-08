"""Smoke tests for critical imports.

These tests ensure that core modules can be imported without errors,
preventing deployment failures due to missing imports or circular dependencies.
"""

import pytest


def test_app_api_main_import():
    """Test that app.api.main can be imported successfully."""
    try:
        from app.api.main import app

        assert app is not None
    except ImportError as e:
        pytest.fail(f"Failed to import app.api.main: {e}")


def test_app_web_routes_import():
    """Test that app.web.routes can be imported successfully."""
    try:
        from app.web import routes

        assert routes.router is not None
    except ImportError as e:
        pytest.fail(f"Failed to import app.web.routes: {e}")


def test_app_web_routes_has_all_routers():
    """Test that all expected routers are registered."""
    from app.web import routes

    router = routes.router
    assert router is not None

    # Check that user_settings router is included
    route_paths = [route.path for route in router.routes]

    # Critical paths that must exist
    critical_paths = [
        "/web/settings",  # From user_settings
        "/web/settings/company",  # From user_settings
        "/web/admin/backups",  # From backup_admin
        "/web/profile",  # From account_settings
        "/web/accounts",  # From account_settings
        "/web/subscription",  # From account_settings
    ]

    for path in critical_paths:
        assert any(
            path in route_path for route_path in route_paths
        ), f"Critical path {path} not found in router"


def test_user_settings_module_exists():
    """Test that user_settings module exists and has router."""
    try:
        from app.web.route_modules import user_settings

        assert hasattr(user_settings, "router")
        assert user_settings.router is not None
    except ImportError as e:
        pytest.fail(f"Failed to import user_settings module: {e}")


def test_admin_logs_module_exists():
    """Test that admin_logs module exists and has router."""
    try:
        from app.web.route_modules import admin_logs

        assert hasattr(admin_logs, "router")
        assert admin_logs.router is not None
    except ImportError as e:
        pytest.fail(f"Failed to import admin_logs module: {e}")


def test_app_bot_main_import():
    """Test that app.bot.main can be imported successfully."""
    try:
        import app.bot.main

        assert app.bot.main is not None
    except ImportError as e:
        pytest.fail(f"Failed to import app.bot.main: {e}")


def test_app_bot_handlers_user_menu_import():
    """Test that app.bot.handlers.user_menu can be imported successfully."""
    try:
        from app.bot.handlers import user_menu

        assert hasattr(user_menu, "router")
        assert user_menu.router is not None
    except ImportError as e:
        pytest.fail(f"Failed to import app.bot.handlers.user_menu: {e}")
