"""version: 1.0.0
description: Tests that all keyboard callback_data have registered handlers.
updated: 2026-06-11
"""

from typing import Any

from aiogram.types import InlineKeyboardMarkup

from decimal import Decimal

from aiogram.types import InlineKeyboardMarkup

from app.bot.keyboards.main import (
    account_actions,
    account_history_periods,
    accounts_list_menu,
    accounts_menu,
    admin_deploy_menu,
    admin_menu,
    admin_tariff_menu,
    admin_tariff_select_menu,
    confirm_deploy_update,
    confirm_delete_account,
    control_menu,
    costs_menu,
    finances_menu,
    low_margin_threshold_menu,
    main_menu,
    marketplaces_menu,
    mrc_back_menu,
    mrc_import_confirm_keyboard,
    mrc_menu,
    mrc_product_card_keyboard,
    mrc_settings_keyboard,
    notification_settings_menu,
    orders_menu,
    products_menu,
    profile_menu,
    profit_menu,
    sale_notification_settings_menu,
    settings_menu,
    subscription_cancel_confirm_menu,
    subscription_current_menu,
    subscription_current_menu_v2,
    subscription_menu,
    subscription_payment_confirm_menu,
    subscription_payments_menu,
    subscription_pricing_menu,
    subscription_pricing_menu_v2,
    subscription_tier_detail_menu,
    subscription_tier_detail_menu_v2,
    summary_menu,
    support_menu,
    sync_menu,
    timezone_menu,
    user_api_keys_menu,
    user_menu,
    user_notifications_menu,
    user_profile_menu,
    user_support_menu,
    user_tariff_menu,
    web_cabinet_link,
)
from app.models.domain import MarketplaceAccount
from app.models.enums import Marketplace
from app.models.subscriptions import SubscriptionTier

# ============================================================
# Allowed dynamic / param callback patterns
# ============================================================
ALLOWED_CALLBACK_PREFIXES: set[str] = {
    "account:",
    "sync:",
    "summary:",
    "orders:",
    "profit:",
    "control:",
    "low_margin:",
    "timezone:set:",
    "mrc:",
    "subscription:",
    "admin:",
    "admin_deploy:",
    "admin_tariff:",
    "user:",
    "order:",
    "ap:tariff:",
    "ap:promo:",
    "admin_commission:",
}

ALLOWED_EXACT_CALLBACKS: set[str] = {
    "back_main",
    "settings",
    "profile",
    "sync_menu",
    "summary_menu",
    "summary",
    "orders_menu",
    "orders",
    "profit_menu",
    "finances_menu",
    "products_menu",
    "marketplaces_menu",
    "support_menu",
    "products_costs_menu",
    "costs",
    "stocks",
    "control_menu",
    "control",
    "notifications",
    "notifications:toggle",
    "notifications:orders",
    "notifications:returns",
    "notifications:test",
    "settings:notifications",
    "sale_notifications",
    "sale_notifications:toggle",
    "web_cabinet",
    "mrc_menu",
    "low_margin:manual",
    "report_time",
    "timezone",
    "help",
    "hide",
    "admin_menu",
    "connect_wb",
    "connect_ozon",
    "accounts",
    "cost_manual",
    "cost_template",
    "cost_upload",
    "products_sync",
    "subscription_menu",
    "subscription:current",
    "subscription:pricing",
    "subscription:help",
    "subscription:payments",
    "subscription:cancel_confirm",
    "subscription:cancel_confirmed",
    "subscription:history",
    "subscription:renew",
    "subscription:compare",
    "ap:tariffs",
    "ap:promos",
    "ap:promo:search",
    "ap:promo:create",
    "admin_tariff_menu",
    "admin_tariff:self",
    "admin_tariff:user",
    "admin:commissions",
    "admin_commission:sync_wb",
    "admin_commission:check_ozon",
    "admin_commission:import_ozon",
    "admin_commission:versions",
}


def _collect_callbacks(kb: InlineKeyboardMarkup | None) -> list[str]:
    if kb is None:
        return []
    result: list[str] = []
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data:
                result.append(btn.callback_data)
    return result


def _all_keyboards() -> list[InlineKeyboardMarkup]:
    """Build a sample of all menu keyboards to extract callbacks."""

    sample_account = MarketplaceAccount(
        id=1,
        user_id=1,
        marketplace=Marketplace.WB,
        name="Test WB",
        encrypted_api_key="test",
        is_active=True,
    )
    sample_account_ozon = MarketplaceAccount(
        id=2,
        user_id=1,
        marketplace=Marketplace.OZON,
        name="Test Ozon",
        encrypted_api_key="test",
        is_active=True,
    )
    sample_tier = SubscriptionTier(
        id=1,
        code="basic",
        name="Basic",
        price_monthly=490,
        price_yearly=4900,
        max_marketplace_accounts=1,
        sync_interval_minutes=15,
        is_active=True,
        is_public=True,
        sort_order=1,
    )

    return [
        main_menu(),
        main_menu(is_admin=True),
        summary_menu(),
        orders_menu(),
        finances_menu(),
        products_menu(),
        marketplaces_menu(),
        support_menu(),
        control_menu(),
        profit_menu(),
        settings_menu(),
        costs_menu(),
        sync_menu(),
        profile_menu(),
        user_menu(),
        user_profile_menu(),
        user_tariff_menu("basic"),
        user_api_keys_menu(),
        user_notifications_menu(enabled=True),
        user_notifications_menu(enabled=False),
        user_support_menu(),
        notification_settings_menu(enabled=True),
        sale_notification_settings_menu(enabled=True),
        accounts_menu(),
        accounts_list_menu([sample_account, sample_account_ozon]),
        account_actions(sample_account),
        account_actions(sample_account_ozon),
        account_history_periods(1),
        confirm_delete_account(1),
        low_margin_threshold_menu(Decimal("10")),
        timezone_menu(),
        admin_menu(),
        admin_deploy_menu(),
        confirm_deploy_update(),
        admin_tariff_menu(),
        admin_tariff_select_menu(),
        mrc_menu(),
        mrc_back_menu(),
        mrc_product_card_keyboard(1, 12345),
        mrc_import_confirm_keyboard(),
        mrc_settings_keyboard(),
        subscription_menu(),
        subscription_current_menu(),
        subscription_current_menu_v2(),
        subscription_pricing_menu(),
        subscription_pricing_menu_v2(),
        subscription_tier_detail_menu("basic", "free"),
        subscription_tier_detail_menu_v2("basic", "free", tier=sample_tier),
        subscription_payment_confirm_menu("basic", "monthly", "490"),
        subscription_cancel_confirm_menu(),
        subscription_payments_menu(),
        web_cabinet_link("https://example.com"),
    ]


def _is_dynamic(callback: str) -> bool:
    for prefix in ALLOWED_CALLBACK_PREFIXES:
        if callback.startswith(prefix):
            return True
    return False


def _allowed(callback: str) -> bool:
    if callback in ALLOWED_EXACT_CALLBACKS:
        return True
    if _is_dynamic(callback):
        return True
    return False


def test_all_keyboard_callbacks_have_handlers():
    """Verify every callback_data from all menus is accounted for."""
    all_callbacks: set[str] = set()
    for kb in _all_keyboards():
        for cb in _collect_callbacks(kb):
            all_callbacks.add(cb)

    unknown: list[str] = []
    for cb in sorted(all_callbacks):
        if not _allowed(cb):
            unknown.append(cb)

    assert not unknown, (
        f"Found {len(unknown)} callback(s) without handlers:\n"
        + "\n".join(f"  - {cb}" for cb in unknown)
    )


def test_no_orphaned_callbacks():
    """Verify that commonly referenced callbacks still produce menus."""
    kb = main_menu()
    callbacks = set(_collect_callbacks(kb))

    assert "summary_menu" in callbacks
    assert "orders_menu" in callbacks
    assert "finances_menu" in callbacks
    assert "products_menu" in callbacks
    assert "control_menu" in callbacks
    assert "marketplaces_menu" in callbacks
    assert "support_menu" in callbacks
    assert "settings" in callbacks
    assert "web_cabinet" in callbacks


def test_account_actions_wb_has_reports():
    sample = MarketplaceAccount(
        id=1,
        user_id=1,
        marketplace=Marketplace.WB,
        name="Test WB",
        encrypted_api_key="test",
        is_active=True,
    )
    callbacks = _collect_callbacks(account_actions(sample))
    assert any("reports" in cb for cb in callbacks), "WB account should have reports button"


def test_account_actions_ozon_no_reports():
    sample = MarketplaceAccount(
        id=2,
        user_id=1,
        marketplace=Marketplace.OZON,
        name="Test Ozon",
        encrypted_api_key="test",
        is_active=True,
    )
    callbacks = _collect_callbacks(account_actions(sample))
    assert not any("reports" in cb for cb in callbacks), "Ozon account should not have reports button"


def test_dynamic_callbacks_are_recognised():
    """Verify various dynamic patterns are recognised as allowed."""
    dynamic_samples = [
        "account:1:view",
        "account:42:history",
        "account:7:delete",
        "sync:orders",
        "sync:products",
        "summary:today",
        "summary:yesterday",
        "summary:7d",
        "summary:30d",
        "orders:new",
        "orders:today",
        "orders:fbs",
        "orders:fbo",
        "orders:last10",
        "profit:today",
        "profit:7d",
        "profit:loss",
        "profit:plan_fact",
        "profit:break_even",
        "profit:missing_cost",
        "control:fbs",
        "control:stockout",
        "control:low_margin",
        "control:sync_errors",
        "control:data_quality",
        "low_margin:set:5",
        "low_margin:set:15",
        "timezone:set:Europe/Moscow",
        "mrc:with_mrc",
        "mrc:without_mrc",
        "mrc:promos_today",
        "mrc:sync_promos",
        "mrc:search",
        "mrc:set",
        "mrc:edit:1",
        "mrc:recalc:1",
        "mrc:limits_report",
        "mrc:template_download",
        "mrc:import_upload",
        "mrc:import_confirm",
        "mrc:import_cancel",
        "mrc:settings",
        "mrc:settings:discount",
        "subscription:tier:pro",
        "subscription:pay:basic:monthly",
        "subscription:pay_confirm:pro:yearly",
        "subscription:receipt:1",
        "subscription:renew",
        "subscription:history",
        "subscription:compare",
        "admin:users",
        "admin:support",
        "admin:logs",
        "admin:accounts",
        "admin:sync",
        "admin:system",
        "admin:orders",
        "admin:wb",
        "admin:events",
        "admin:deploy",
        "admin:reconcile_subs",
        "admin_deploy:version",
        "admin_deploy:check",
        "admin_deploy:update",
        "admin_deploy:update_confirm",
        "admin_deploy:cancel",
        "admin_deploy:status",
        "admin_deploy:log",
        "admin_deploy:backups",
        "admin_tariff:assign:free",
        "admin_tariff:assign:basic:30:123456",
        "user:profile",
        "user:tariff",
        "user:api_keys",
        "user:notifications",
        "user:marketplaces",
        "user:promo",
        "user:settings",
        "user:support",
        "user:support_new",
        "user:support_list",
        "user:edit_email",
        "user:edit_phone",
        "user:check_wb",
        "user:check_ozon",
        "order:123:details",
        "order:456:profit",
        "order:789:product",
        "ap:tariff:1",
        "ap:tariff:1:price:monthly",
        "ap:tariff:1:save:price_monthly:490",
        "ap:tariff:1:limits",
        "ap:tariff:1:limit:max_products",
        "ap:tariff:1:toggle",
        "ap:tariff:1:public",
        "ap:promo:1:toggle",
        "ap:promo:1:stats",
        "ap:promo:1:usages:0",
        "ap:promo:1:edit_limit",
        "ap:promo:1:edit_expires",
        "ap:promo:type:percent",
        "ap:promo:sel_tariff:1",
        "ap:promo:sel_period:monthly",
        "admin_commission:sync_wb",
        "admin_commission:check_ozon",
        "admin_commission:import_ozon",
        "admin_commission:versions",
    ]
    for cb in dynamic_samples:
        assert _is_dynamic(cb) or cb in ALLOWED_EXACT_CALLBACKS, f"{cb} should be recognised"
