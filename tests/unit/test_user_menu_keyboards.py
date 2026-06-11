"""Tests for user menu bot keyboards."""

from app.bot.keyboards.main import (
    user_api_keys_menu,
    user_menu,
    user_notifications_menu,
    user_profile_menu,
    user_support_menu,
    user_tariff_menu,
)


def test_user_menu_has_all_buttons():
    kb = user_menu()
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "👤 Профиль" in texts
    assert "💳 Тариф" in texts
    assert "🔑 API-ключи" in texts
    assert "🔔 Уведомления" in texts
    assert "🏪 Кабинеты МП" in texts
    assert "🎁 Промокод" in texts
    assert "⚙️ Настройки" in texts
    assert "🆘 Поддержка" in texts
    assert "🏠 Главное меню" in texts


def test_user_profile_menu():
    kb = user_profile_menu()
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "Изменить email" in texts
    assert "Изменить телефон" in texts
    assert "Изменить часовой пояс" in texts


def test_user_tariff_menu():
    kb = user_tariff_menu("pro")
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "Продлить тариф" in texts
    assert "Сменить тариф" in texts
    assert "Применить промокод" in texts
    assert "История платежей" in texts


def test_user_api_keys_menu():
    kb = user_api_keys_menu()
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "Проверить WB ключ" in texts
    assert "Проверить Ozon ключ" in texts
    assert "Обновить WB ключ" in texts
    assert "Обновить Ozon ключ" in texts


def test_user_notifications_menu_toggle():
    kb_enabled = user_notifications_menu(enabled=True)
    texts_enabled = [btn.text for row in kb_enabled.inline_keyboard for btn in row]
    kb_disabled = user_notifications_menu(enabled=False)
    texts_disabled = [btn.text for row in kb_disabled.inline_keyboard for btn in row]
    assert any("Выключить" in t for t in texts_enabled)
    assert any("Включить" in t for t in texts_disabled)


def test_user_support_menu():
    kb = user_support_menu()
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "Написать в поддержку" in texts
    assert "Мои обращения" in texts
