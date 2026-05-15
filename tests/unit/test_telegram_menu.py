"""version: 1.2.0
description: Unit tests for Telegram menu structure, web cabinet, and admin deploy buttons.
updated: 2026-05-15
"""

from aiogram.types import InlineKeyboardMarkup

from app.bot.handlers.common import SUPPORTED_TIMEZONES, _is_public_web_url, _timezone_text
from app.bot.keyboards.main import (
    admin_deploy_menu,
    admin_menu,
    control_menu,
    costs_menu,
    main_menu,
    notification_settings_menu,
    orders_menu,
    profit_menu,
    sale_notification_settings_menu,
    settings_menu,
    summary_menu,
    timezone_menu,
    web_cabinet_link,
)
from app.services.notification_service import NotificationService


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


def test_timezone_menu_contains_supported_timezone_callbacks() -> None:
    keyboard = timezone_menu("Europe/Moscow")
    callbacks = _callbacks(keyboard)

    assert "timezone:set:Europe/Moscow" in callbacks
    assert "timezone:set:Asia/Vladivostok" in callbacks
    assert "Europe/Moscow" in SUPPORTED_TIMEZONES
    assert "Текущий часовой пояс" in _timezone_text("Europe/Moscow")


def test_known_callback_buttons_have_common_handler_contract() -> None:
    keyboards = [
        main_menu(is_admin=True),
        summary_menu(),
        orders_menu(),
        profit_menu(),
        control_menu(),
        costs_menu(),
        admin_menu(),
        admin_deploy_menu(),
        settings_menu(),
        notification_settings_menu(True),
        sale_notification_settings_menu(True),
        timezone_menu("Europe/Moscow"),
        web_cabinet_link("https://app.mpcontrol.online/web/login?token=abc"),
    ]
    callbacks = {callback for keyboard in keyboards for callback in _callbacks(keyboard)}
    known_exact = {
        "settings",
        "back_main",
        "summary_menu",
        "summary",
        "orders_menu",
        "profit_menu",
        "products_costs_menu",
        "stocks",
        "control_menu",
        "notifications",
        "settings:notifications",
        "notifications:toggle",
        "sale_notifications",
        "sale_notifications:toggle",
        "web_cabinet",
        "admin_menu",
        "report_time",
        "timezone",
        "help",
        "hide",
        "connect_wb",
        "connect_ozon",
        "accounts",
        "costs",
        "products_sync",
        "cost_manual",
        "cost_template",
        "cost_upload",
    }
    known_prefixes = (
        "summary:",
        "orders:",
        "profit:",
        "control:",
        "admin:",
        "admin_deploy:",
        "timezone:set:",
    )

    unknown = {
        callback
        for callback in callbacks
        if callback not in known_exact and not callback.startswith(known_prefixes)
    }

    assert unknown == set()


def test_new_order_notification_callbacks_are_stable() -> None:
    keyboard = NotificationService._build_new_order_keyboard(order_id=10)
    callbacks = set(_callbacks(keyboard))

    assert "order:10:details" in callbacks
    assert "order:10:profit" in callbacks
    assert "order:10:product" in callbacks
    assert "settings:notifications" in callbacks
    assert "hide" in callbacks


def test_new_order_notification_can_include_wb_product_url_button() -> None:
    keyboard = NotificationService._build_new_order_keyboard(
        order_id=10,
        product_url="https://www.wildberries.ru/catalog/303948126/detail.aspx?targetUrl=XS",
    )
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "🛍 Открыть товар на WB" and button.url for button in buttons)
    assert "order:10:product" not in set(_callbacks(keyboard))


def _callbacks(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [
        str(button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]
