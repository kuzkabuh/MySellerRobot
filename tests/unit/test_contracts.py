"""Contract tests for web route registration and Telegram callback coverage."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.main import create_app
from app.web.views import _placeholder_page

ROOT = Path(__file__).resolve().parents[2]


def _literal_callback_data(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    callbacks: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "callback_data" and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, str):
                    callbacks.add(keyword.value.value)
    return callbacks


def test_main_web_routes_are_registered_without_double_web_links() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}

    for path in (
        "/web/",
        "/web/orders",
        "/web/profit",
        "/web/products",
        "/web/settings",
        "/web/pricing",
        "/web/mrc-pricing",
        "/web/admin",
    ):
        assert path in paths

    assert "/web/web/{section:path}" in paths


def test_unknown_placeholder_section_returns_404() -> None:
    user = SimpleNamespace(first_name="Test", username=None, telegram_id=123)

    with pytest.raises(HTTPException) as exc_info:
        _placeholder_page("missing-section", user)

    assert exc_info.value.status_code == 404


def test_literal_keyboard_callbacks_have_handler_contract() -> None:
    keyboard_dir = ROOT / "app" / "bot" / "keyboards"
    handler_dir = ROOT / "app" / "bot" / "handlers"

    callbacks: set[str] = set()
    for path in keyboard_dir.glob("*.py"):
        callbacks.update(_literal_callback_data(path))

    handler_text = "\n".join(path.read_text(encoding="utf-8") for path in handler_dir.glob("*.py"))
    routed_prefixes = (
        "account:",
        "admin:",
        "admin_commission:",
        "admin_deploy:",
        "admin_tariff:",
        "ap:",
        "control:",
        "mrc:",
        "orders:",
        "profit:",
        "subscription:",
        "summary:",
        "sync:",
        "user:",
    )
    explicit_noops = {"noop"}

    missing = sorted(
        callback
        for callback in callbacks
        if callback not in explicit_noops
        and callback not in handler_text
        and not callback.startswith(routed_prefixes)
    )

    assert missing == []
