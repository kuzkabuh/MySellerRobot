"""version: 1.1.1
description: Smoke tests for API, bot, worker, and package startup boundaries.
updated: 2026-05-15
"""

import importlib.util

from app.api.main import create_app
from app.bot.main import create_dispatcher
from app.core.config import Settings
from app.workers.settings import WorkerSettings


def test_create_app() -> None:
    app = create_app()

    assert app.title == "Seller Profit Bot API"
    assert app.version == "1.4.9"


def test_web_routes_are_registered() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/web/login" in paths
    assert "/web/" in paths
    assert "/web/orders" in paths
    assert "/web/orders/{order_id}" in paths
    assert "/web/profit" in paths
    assert "/web/logout" in paths


def test_app_package_discovery_includes_utility_package() -> None:
    assert importlib.util.find_spec("app") is not None
    assert importlib.util.find_spec("app.utils") is not None


def test_bot_dispatcher_factory_registers_routers_without_polling() -> None:
    dispatcher = create_dispatcher()

    assert [router.name for router in dispatcher.sub_routers] == [
        "accounts",
        "costs",
        "common",
    ]


def test_worker_settings_register_expected_tasks() -> None:
    function_names = {function.__name__ for function in WorkerSettings.functions}

    assert "poll_new_orders" in function_names
    assert "process_history_backfills" in function_names
    assert WorkerSettings.cron_jobs


def test_settings_expose_history_backfill_defaults() -> None:
    settings = Settings()

    assert settings.backfill_default_days == 30
    assert settings.backfill_chunk_days == 7
