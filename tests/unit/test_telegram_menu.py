"""version: 1.3.0
description: Unit tests for Telegram menu, analytics actions, web cabinet, and admin deploy buttons.
updated: 2026-05-15
"""

from decimal import Decimal

from aiogram.types import InlineKeyboardMarkup

from app.bot.handlers.common import SUPPORTED_TIMEZONES, _is_public_web_url, _timezone_text
from app.bot.keyboards.main import (
    admin_deploy_menu,
    admin_menu,
    admin_tariff_select_menu,
    control_menu,
    costs_menu,
    low_margin_threshold_menu,
    main_menu,
    mrc_menu,
    notification_settings_menu,
    orders_menu,
    profile_menu,
    profit_menu,
    sale_notification_settings_menu,
    settings_menu,
    summary_menu,
    sync_menu,
    timezone_menu,
    web_cabinet_link,
)
from app.bot.main import BOT_COMMANDS
from app.services.alerts.notification_service import NotificationService


def test_main_menu_contains_web_and_no_admin_for_regular_user() -> None:
    texts = [button.text for row in main_menu().inline_keyboard for button in row]

    assert "🌐 Web-кабинет" in texts
    assert "🛠 Администрирование" not in texts


def test_main_menu_contains_admin_button_for_admin() -> None:
    texts = [button.text for row in main_menu(is_admin=True).inline_keyboard for button in row]

    assert "🛠 Администрирование" in texts


def test_main_menu_contains_mrc_button() -> None:
    texts = [button.text for row in main_menu().inline_keyboard for button in row]

    assert "💰 МРЦ и акции WB" in texts


def test_admin_menu_contains_deploy_section() -> None:
    texts = [button.text for row in admin_menu().inline_keyboard for button in row]

    assert "🚀 Обновление и деплой" in texts


def test_admin_menu_contains_tariff_management() -> None:
    texts = [button.text for row in admin_menu().inline_keyboard for button in row]

    assert "💳 Управление тарифами" in texts


def test_admin_tariff_select_menu_can_bind_target_user() -> None:
    callbacks = _callbacks(admin_tariff_select_menu(target_telegram_id=123456789))

    assert "admin_tariff:assign:free:0:123456789" in callbacks
    assert "admin_tariff:assign:basic:30:123456789" in callbacks
    assert "admin_tariff:assign:basic:365:123456789" in callbacks
    assert "admin_tariff:assign:pro:30:123456789" in callbacks
    assert "admin_tariff:assign:pro:365:123456789" in callbacks
    assert "admin_tariff:assign:enterprise:0:123456789" in callbacks


def test_admin_deploy_menu_contains_required_actions() -> None:
    texts = [button.text for row in admin_deploy_menu().inline_keyboard for button in row]

    assert "📌 Текущая версия" in texts
    assert "🔍 Проверить обновления" in texts
    assert "⬆ Запустить обновление" in texts
    assert "📄 Последний лог обновления" in texts
    assert "💾 Последние backup" in texts


def test_profit_menu_contains_plan_fact_report() -> None:
    texts = [button.text for row in profit_menu().inline_keyboard for button in row]

    assert "План/факт и отклонения" in texts
    assert "Безубыточная цена" in texts


def test_control_menu_contains_stockout_and_quality_actions() -> None:
    texts = [button.text for row in control_menu().inline_keyboard for button in row]

    assert "Прогноз out-of-stock" in texts
    assert "Качество данных" in texts


def test_menus_do_not_contain_duplicate_callback_actions() -> None:
    for keyboard in [
        main_menu(is_admin=True),
        summary_menu(),
        orders_menu(),
        profit_menu(),
        control_menu(),
        costs_menu(),
        sync_menu(),
        profile_menu(),
        admin_menu(),
        admin_deploy_menu(),
        settings_menu(),
    ]:
        callbacks = _callbacks(keyboard)
        assert len(callbacks) == len(set(callbacks))


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
        low_margin_threshold_menu(Decimal("10")),
        timezone_menu("Europe/Moscow"),
        web_cabinet_link("https://app.mpcontrol.online/web/login?token=abc"),
        mrc_menu(),
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
        "profile",
        "sync_menu",
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
        "low_margin:manual",
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
        "subscription_menu",
        "admin_tariff_menu",
        "mrc_menu",
    }
    known_prefixes = (
        "summary:",
        "orders:",
        "profit:",
        "control:",
        "admin:",
        "ap:",
        "admin_deploy:",
        "timezone:set:",
        "low_margin:set:",
        "subscription:",
        "admin_tariff:",
        "sync:",
        "mrc:",
        "user:",
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


def test_low_margin_threshold_menu_contains_quick_values_and_manual_input() -> None:
    keyboard = low_margin_threshold_menu(Decimal("10"))
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    texts = {button.text for button in buttons}
    callbacks = {button.callback_data for button in buttons if button.callback_data}

    assert "✓ 10%" in texts
    assert "Ввести вручную" in texts
    assert "low_margin:set:15" in callbacks
    assert "low_margin:manual" in callbacks


def test_bot_commands_cover_real_public_screens() -> None:
    commands = {command.command: command.description for command in BOT_COMMANDS}

    assert commands["start"] == "Открыть главное меню"
    assert "profile" in commands
    assert "accounts" in commands
    assert "sync" in commands
    assert "subscription" in commands


def test_sync_menu_contains_supported_manual_tasks() -> None:
    callbacks = set(_callbacks(sync_menu()))

    assert callbacks == {
        "sync:orders",
        "sync:sales",
        "sync:stocks",
        "sync:products",
        "sync:wb-profile",
        "sync:wb-reports",
        "sync:ozon-enrichment",
        "back_main",
    }


def _callbacks(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [
        str(button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]
