"""Tests for task registry, translations, and display helpers."""

from app.services.common.task_registry import (
    COUNTER_TRANSLATION,
    ERROR_TRANSLATIONS,
    STATUS_COLORS,
    STATUS_TRANSLATION,
    TASK_REGISTRY,
    format_duration,
    get_task_info,
    status_color,
    translate_category,
    translate_counters,
    translate_error,
    translate_status,
)


def test_task_registry_contains_all_tracked_tasks() -> None:
    expected = {
        "poll_new_orders",
        "sync_sale_events",
        "sync_wb_product_prices",
        "check_auto_promo_prices",
        "sync_products",
        "send_daily_reports",
        "send_alert_notifications",
        "send_fbo_digests",
        "process_history_backfills",
        "relink_wb_report_rows",
        "check_fbs_deadlines",
        "check_low_stocks",
        "sync_wb_daily_sales_reports",
        "sync_ozon_catalog_enrichment",
        "sync_ozon_balances",
        "reconcile_ozon_finance",
        "sync_wb_account_profiles",
        "check_wb_financial_reports",
        "sync_wb_daily_financial_details",
        "backfill_wb_daily_financial_details",
        "reconcile_pending_payments",
        "resend_unnotified_orders",
        "sync_wb_commissions",
        "check_ozon_commission_source",
        "sync_wb_logistics_tariffs",
        "sync_wb_daily_promotions",
    }
    actual = set(TASK_REGISTRY.keys())
    missing = expected - actual
    extra = actual - expected
    assert not missing, f"Missing tasks in registry: {missing}"
    assert not extra, f"Unexpected tasks in registry: {extra}"


def test_key_tasks_are_marked() -> None:
    key_tasks = {"poll_new_orders", "sync_sale_events", "sync_wb_product_prices", "check_auto_promo_prices"}
    for task_name in key_tasks:
        info = get_task_info(task_name)
        assert info["is_key"] is True, f"{task_name} should be key"
    non_key = {"sync_products", "send_daily_reports"}
    for task_name in non_key:
        info = get_task_info(task_name)
        assert info["is_key"] is False, f"{task_name} should not be key"


def test_unknown_task_returns_default() -> None:
    info = get_task_info("nonexistent_task_xyz")
    assert info["title"] == "nonexistent_task_xyz"
    assert "Описание" in str(info["description"])
    assert info["category"] == "unknown"
    assert info["is_key"] is False


def test_status_translation() -> None:
    assert translate_status("success") == "Успешно"
    assert translate_status("warning") == "Предупреждение"
    assert translate_status("error") == "Ошибка"
    assert translate_status("failed") == "Ошибка"
    assert translate_status("running") == "Выполняется"
    assert translate_status("started") == "Выполняется"
    assert translate_status("pending") == "Ожидает запуска"
    assert translate_status("skipped") == "Пропущено"
    assert translate_status("no_runs") == "Не запускалась"
    assert translate_status(None) == "Нет данных"
    assert translate_status("unknown") == "unknown"


def test_status_colors() -> None:
    assert status_color("success") == "#27ae60"
    assert status_color("warning") == "#f39c12"
    assert status_color("error") == "#e74c3c"
    assert status_color("failed") == "#e74c3c"
    assert status_color("running") == "#3498db"
    assert status_color("no_runs") == "#95a5a6"
    assert status_color(None) == "#95a5a6"
    assert status_color("unknown") == "#95a5a6"


def test_format_duration() -> None:
    assert format_duration(None) == "—"
    assert format_duration(0) == "0 мс"
    assert format_duration(43) == "43 мс"
    assert format_duration(999) == "999 мс"
    assert format_duration(1000) == "1,00 сек"
    assert format_duration(2130) == "2,13 сек"
    assert format_duration(9370) == "9,37 сек"
    assert format_duration(10000) == "10,00 сек"
    assert format_duration(59990) == "59,99 сек"
    assert format_duration(60000) == "1 мин 0 сек"
    assert format_duration(130000) == "2 мин 10 сек"
    assert format_duration(3600000) == "60 мин 0 сек"


def test_translate_counters() -> None:
    result = translate_counters({"duplicates": 8, "orders_created": 0, "accounts_total": 2})
    assert ("Дубликатов", 8) in result
    assert ("Заказов создано", 0) in result
    assert ("Кабинетов всего", 2) in result


def test_translate_counters_unknown_key() -> None:
    result = translate_counters({"unknown_key": 42})
    assert ("unknown_key", 42) in result


def test_translate_counters_empty() -> None:
    assert translate_counters(None) == []
    assert translate_counters({}) == []


def test_translate_error_known() -> None:
    assert "часть операций выполнена с ошибками" in translate_error("completed with warnings")
    assert "часть операций не выполнена" in translate_error("completed with failures")
    assert "предупреждениями" in translate_error("poll_new_orders completed with warnings")
    assert "ошибками" in translate_error("sync_sale_events completed with failures")


def test_translate_error_unknown() -> None:
    result = translate_error("something unexpected happened")
    assert "Техническая ошибка" in result
    assert "unexpected" in result


def test_translate_error_empty() -> None:
    assert translate_error(None) == ""
    assert translate_error("") == ""


def test_translate_category() -> None:
    assert translate_category("wb") == "Wildberries"
    assert translate_category("ozon") == "Ozon"
    assert translate_category("system") == "Системные"
    assert translate_category("notifications") == "Уведомления"
    assert translate_category("finance") == "Финансы"
    assert translate_category("unknown") == "Неизвестная"
    assert translate_category("marketplaces") == "Маркетплейсы"


def test_every_task_has_required_fields() -> None:
    for task_name, info in TASK_REGISTRY.items():
        assert "title" in info, f"{task_name} missing title"
        assert "description" in info, f"{task_name} missing description"
        assert "category" in info, f"{task_name} missing category"
        assert "is_key" in info, f"{task_name} missing is_key"
        assert isinstance(info["is_key"], bool), f"{task_name} is_key must be bool"
        assert isinstance(info["title"], str), f"{task_name} title must be str"
        assert isinstance(info["description"], str), f"{task_name} description must be str"
        assert info["category"] in ("marketplaces", "wb", "ozon", "system", "notifications", "finance"), (
            f"{task_name} has invalid category: {info['category']}"
        )


def test_every_status_has_color() -> None:
    for status in STATUS_TRANSLATION:
        assert status in STATUS_COLORS, f"Status '{status}' has no color"


def test_all_counter_keys_are_strings() -> None:
    for key in COUNTER_TRANSLATION:
        assert isinstance(key, str), f"Counter key {key!r} must be str"


def test_all_error_keys_are_strings() -> None:
    for key in ERROR_TRANSLATIONS:
        assert isinstance(key, str), f"Error key {key!r} must be str"
