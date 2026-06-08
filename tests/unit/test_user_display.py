"""version: 1.0.0
description: Unit tests for user display helpers.
updated: 2026-06-07
"""

from __future__ import annotations

from types import SimpleNamespace

from app.utils.user_display import safe_username_value, user_display_name, username_label


def _user(**kwargs):
    base = {"first_name": None, "last_name": None, "username": None, "telegram_id": 123}
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_display_name_uses_first_name() -> None:
    assert user_display_name(_user(first_name="Иван")) == "Иван"


def test_display_name_uses_last_name_when_no_first() -> None:
    assert user_display_name(_user(last_name="Петров")) == "Петров"


def test_display_name_uses_username() -> None:
    assert user_display_name(_user(username="seller")) == "seller"


def test_display_name_falls_back_to_telegram_id() -> None:
    assert user_display_name(_user(telegram_id=12345)) == "12345"


def test_display_name_handles_none() -> None:
    assert user_display_name(None) == "селлер"


def test_display_name_trims_whitespace() -> None:
    assert user_display_name(_user(first_name="   ")) == "123"


def test_username_label_returns_at_prefix() -> None:
    result = username_label(_user(username="seller"))
    assert "seller" in result
    assert "@" in result


def test_username_label_says_not_specified_for_missing() -> None:
    assert username_label(_user()) == "не указан"


def test_username_label_says_not_specified_for_none() -> None:
    assert username_label(None) == "не указан"


def test_safe_username_value_returns_stripped() -> None:
    assert safe_username_value(_user(username="  seller  ")) == "seller"


def test_safe_username_value_empty_when_missing() -> None:
    assert safe_username_value(_user()) == ""


def test_safe_username_value_empty_for_none() -> None:
    assert safe_username_value(None) == ""
