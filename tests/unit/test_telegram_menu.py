"""version: 1.1.0
description: Unit tests for Telegram menu structure, web cabinet, and admin deploy buttons.
updated: 2026-05-15
"""

from app.bot.handlers.common import _is_public_web_url
from app.bot.keyboards.main import admin_deploy_menu, admin_menu, main_menu, web_cabinet_link


def test_main_menu_contains_web_and_no_admin_for_regular_user() -> None:
    texts = [button.text for row in main_menu().inline_keyboard for button in row]

    assert "🌐 Web-кабинет" in texts
    assert "🛠 Администрирование" not in texts


def test_main_menu_contains_admin_button_for_admin() -> None:
    texts = [button.text for row in main_menu(is_admin=True).inline_keyboard for button in row]

    assert "🛠 Администрирование" in texts


def test_admin_menu_contains_deploy_section() -> None:
    texts = [button.text for row in admin_menu().inline_keyboard for button in row]

    assert "🚀 Обновление и деплой" in texts


def test_admin_deploy_menu_contains_required_actions() -> None:
    texts = [button.text for row in admin_deploy_menu().inline_keyboard for button in row]

    assert "📌 Текущая версия" in texts
    assert "🔍 Проверить обновления" in texts
    assert "⬆ Запустить обновление" in texts
    assert "📄 Последний лог обновления" in texts
    assert "💾 Последние backup" in texts


def test_web_cabinet_keyboard_uses_url_button() -> None:
    keyboard = web_cabinet_link("https://seller.example/web/login?token=abc")
    button = keyboard.inline_keyboard[0][0]

    assert button.text == "🔗 Открыть web-кабинет"
    assert str(button.url) == "https://seller.example/web/login?token=abc"


def test_web_cabinet_rejects_localhost_url_for_telegram() -> None:
    assert not _is_public_web_url("http://localhost:8000/web/login?token=abc")
    assert not _is_public_web_url("http://127.0.0.1:8000/web/login?token=abc")
    assert _is_public_web_url("https://seller.example/web/login?token=abc")
