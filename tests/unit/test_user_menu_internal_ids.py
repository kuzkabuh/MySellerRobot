"""version: 1.0.0
description: Регрессия против смешивания Telegram ID и внутреннего users.id.
updated: 2026-06-07
"""

from pathlib import Path


def test_api_key_checks_do_not_use_telegram_id_as_account_user_id() -> None:
    source = Path("app/bot/handlers/user_menu.py").read_text(encoding="utf-8")

    assert "MarketplaceAccount.user_id == callback.from_user.id" not in source
    assert "MarketplaceAccount.user_id == user.id" in source


def test_profile_updates_use_internal_user_id() -> None:
    source = Path("app/bot/handlers/user_menu.py").read_text(encoding="utf-8")

    legacy_call = "ProfileService(session).update_profile(\n                message.from_user.id"

    assert legacy_call not in source
    assert "ProfileService(session).update_profile(\n                user.id" in source
