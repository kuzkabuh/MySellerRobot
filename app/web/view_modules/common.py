"""version: 1.0.0
description: Common HTML helpers for MP Control web cabinet views.
updated: 2026-06-09
"""

# ruff: noqa: E501, F401, E402, F811, I001

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html import escape
from typing import Any
from urllib.parse import parse_qs

from fastapi import HTTPException, Request

from app.models.domain import AlertEvent, MarketplaceAccount, User
from app.models.enums import Marketplace
from app.models.subscriptions import SubscriptionTier
from app.services.common.data_quality_service import DataQualityReport
from app.services.common.marketplace_presentation import (
    marketplace_css_class,
    marketplace_title,
    order_status_tone,
    sale_model_title,
    source_event_label,
)
from app.services.common.marketplace_presentation import (
    order_status_label as presentation_order_status_label,
)
from app.services.unit_economics.master_product_service import (
    MasterProductAnalyticsRow,
    MasterProductDetail,
    ProductMatchingCandidate,
)
from app.services.unit_economics.plan_fact_service import PlanFactPageData
from app.services.unit_economics.stock_forecast_service import (
    StockForecastRow,
    stock_status_label,
    stock_status_tone,
)
from app.services.unit_economics.unit_economics_service import BreakEvenRow
from app.services.account.web_cabinet_service import (
    AccountsPageData,
    ControlPageData,
    CostsPageData,
    ProductCostDetail,
    ReturnsPageData,
    SalesPageData,
    SubscriptionPageData,
    subscription_status,
)
from app.services.common.web_dashboard_service import (
    DailyPoint,
    DashboardData,
    DashboardEvent,
    DashboardFilters,
    KpiMetric,
)
from app.services.common.web_orders_profit_service import (
    OrderDetail,
    OrderRow,
    OrderWebFilters,
    ProfitPageData,
    localized_order_date,
    order_state_label,
)
from app.utils.datetime import format_datetime_for_user, get_user_timezone, user_day_bounds_utc
from app.web.rendering import page

ZERO = Decimal("0")

SYNC_FRESHNESS_ORDERS_MINUTES = 30
SYNC_FRESHNESS_SALES_MINUTES = 60
SYNC_FRESHNESS_STOCKS_HOURS = 24
SYNC_FRESHNESS_PRODUCTS_HOURS = 48
SYNC_FRESHNESS_PROFILE_HOURS = 48

from app.web.view_modules.formatting import _limit, _rub

__all__ = [
    "_placeholder_page",
    "_section_subnav",
    "_section_subnav_orders",
    "_section_subnav_products",
    "_section_subnav_finance",
    "_section_subnav_pricing",
    "_section_subnav_reports",
    "_section_subnav_monitoring",
    "_sync_center_subnav",
    "_section_subnav_account",
    "_section_subnav_admin_overview",
    "_section_subnav_admin_users",
    "_section_subnav_admin_finance",
    "_section_subnav_admin_integrations",
    "_section_subnav_admin_system",
    "_section_subnav_admin_main",
    "_page_header",
    "_web_tier_card",
]


def _placeholder_page(section: str, user: User) -> str:
    titles = {
        "orders": "Заказы",
        "profit": "Прибыль",
        "break-even": "Безубыточность",
        "sales": "Продажи",
        "returns": "Возвраты",
        "products": "Товары",
        "stocks": "Остатки",
        "alerts": "Алерты",
        "data-quality": "Качество данных",
        "analytics": "Аналитика",
        "control": "Контроль",
        "costs": "Себестоимость",
        "settings": "Настройки",
    }
    title = titles.get(section)
    if title is None:
        raise HTTPException(status_code=404, detail="Раздел не найден")
    content = (
        '<section class="band">'
        f"<h2>{title}</h2>"
        '<div class="empty-state">Откройте раздел через основное меню web-кабинета.</div>'
        "</section>"
    )
    return page(
        title,
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path=f"/web/{section}",
    )


def _subnav_render(items: list[tuple[str, str, str]], active: str) -> str:
    """Render a subnav from (key, label, href) tuples, highlighting active."""
    return (
        '<div class="subnav">'
        + "".join(
            f'<a class="{"active" if key == active else ""}" href="{href}">{label}</a>'
            for key, label, href in items
        )
        + "</div>"
    )


def _section_subnav(active: str) -> str:
    """Legacy subnav covering all sections (backward compat)."""
    items: list[tuple[str, str, str]] = [
        ("orders", "Заказы", "/web/orders"),
        ("sales", "Продажи", "/web/sales"),
        ("returns", "Возвраты", "/web/returns"),
        ("profit", "Прибыль", "/web/profit"),
        ("plan_fact", "План/факт", "/web/plan-fact"),
        ("break_even", "Безубыточность", "/web/break-even"),
        ("products", "Товары", "/web/products"),
        ("stocks", "Остатки", "/web/stocks"),
        ("costs", "Себестоимость", "/web/costs"),
        ("product_matching", "Сопоставление", "/web/product-matching"),
        ("data_quality", "Качество данных", "/web/data-quality"),
        ("alerts", "Алерты", "/web/alerts"),
    ]
    return _subnav_render(items, active)


def _section_subnav_orders(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("orders", "Заказы", "/web/orders"),
        ("sales", "Продажи", "/web/sales"),
        ("returns", "Возвраты", "/web/returns"),
    ]
    return _subnav_render(items, active)


def _section_subnav_products(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("products", "Товары", "/web/products"),
        ("stocks", "Остатки", "/web/stocks"),
        ("costs", "Себестоимость", "/web/costs"),
        ("product_matching", "Сопоставление", "/web/product-matching"),
        ("data_quality", "Качество данных", "/web/data-quality"),
        ("alerts", "Алерты", "/web/alerts"),
    ]
    return _subnav_render(items, active)


def _section_subnav_finance(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("profit", "Прибыль", "/web/profit"),
        ("plan_fact", "План/факт", "/web/plan-fact"),
        ("break_even", "Безубыточность", "/web/break-even"),
        ("finances", "Финансовый обзор", "/web/finances"),
    ]
    return _subnav_render(items, active)


def _section_subnav_pricing(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("pricing", "Цены", "/web/pricing"),
        ("mrc_pricing", "МРЦ WB", "/web/mrc-pricing"),
        ("wb_promotions", "Акции WB", "/web/wb-promotions"),
        ("auto_promo", "Автоакции WB", "/web/auto-promo-prices"),
    ]
    return _subnav_render(items, active)


def _section_subnav_reports(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("wb_daily", "Ежедневные WB", "/web/reports/wb-daily"),
    ]
    return _subnav_render(items, active)


def _section_subnav_monitoring(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("control", "Контроль ошибок", "/web/control"),
        ("sync", "Синхронизация", "/web/sync-center"),
        ("analytics", "Аналитика", "/web/analytics"),
    ]
    return _subnav_render(items, active)


def _sync_center_subnav(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("overview", "Обзор", "/web/sync-center?tab=overview"),
        ("sync", "Синхронизация", "/web/sync-center?tab=sync"),
        ("errors", "Ошибки", "/web/sync-center?tab=errors"),
        ("history", "История запусков", "/web/sync-center?tab=history"),
        ("settings", "Настройки", "/web/sync-center?tab=settings"),
    ]
    return _subnav_render(items, active)


def _section_subnav_account(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("profile", "Профиль", "/web/settings?tab=profile"),
        ("accounts", "Кабинеты МП", "/web/accounts"),
        ("settings", "Настройки", "/web/settings"),
        ("subscription", "Подписка и тариф", "/web/subscription"),
        ("security", "Безопасность", "/web/settings/security"),
    ]
    return _subnav_render(items, active)


def _section_subnav_admin_overview(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("admin", "Обзор", "/web/admin"),
        ("health", "Здоровье системы", "/web/health"),
    ]
    return _subnav_render(items, active)


def _section_subnav_admin_users(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("users", "Пользователи", "/web/admin/users"),
    ]
    return _subnav_render(items, active)


def _section_subnav_admin_finance(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("tariffs", "Тарифы", "/web/admin/tariffs"),
        ("promocodes", "Промокоды", "/web/admin/promocodes"),
        ("payments", "Платежи", "/web/admin/payments"),
        ("commissions", "Комиссии", "/web/admin/commissions"),
    ]
    return _subnav_render(items, active)


def _section_subnav_admin_main(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("admin", "Обзор", "/web/admin"),
        ("users", "Пользователи", "/web/admin/users"),
    ]
    return _subnav_render(items, active)


def _section_subnav_admin_integrations(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("commissions", "Комиссии", "/web/admin/commissions"),
        ("wb_logistics", "Логистика WB", "/admin/wb-logistics"),
    ]
    return _subnav_render(items, active)


def _section_subnav_admin_system(active: str) -> str:
    items: list[tuple[str, str, str]] = [
        ("sync", "Синхронизации", "/web/admin/sync-status"),
        ("workers", "Воркеры", "/web/admin/worker-diagnostics"),
        ("logs", "Логи", "/web/admin/logs"),
        ("audit", "Аудит", "/web/admin/audit-log"),
        ("backups", "Бэкапы", "/web/admin/backups"),
        ("support", "Обращения", "/web/admin/support"),
    ]
    return _subnav_render(items, active)

def _render_sync_freshness(last_poll_info: dict[str, object], timezone: str) -> str:
    """Render a sync freshness indicator badge for the orders page."""
    last_poll_at = last_poll_info.get("last_poll_at")

    if not last_poll_at:
        return (
            '<div style="margin-bottom:14px">'
            '<span class="badge warn">Синхронизация заказов: не выполнялась</span>'
            "</div>"
        )

    from datetime import UTC, datetime

    now = datetime.now(tz=UTC)
    poll_dt = last_poll_at
    if not isinstance(poll_dt, datetime):
        return ""
    if hasattr(poll_dt, "tzinfo") and poll_dt.tzinfo is None:
        poll_dt = poll_dt.replace(tzinfo=UTC)
    age_seconds = (now - poll_dt).total_seconds()
    age_minutes = int(age_seconds / 60)

    if age_minutes < 5:
        badge_class = "good"
        label = f"Синхронизация: {age_minutes} мин назад"
    elif age_minutes < 10:
        badge_class = "good"
        label = f"Синхронизация: {age_minutes} мин назад"
    elif age_minutes < 30:
        badge_class = "warn"
        label = f"Синхронизация: {age_minutes} мин назад"
    else:
        badge_class = "bad"
        label = f"Синхронизация: {age_minutes} мин назад (возможна задержка)"

    account_hints = []
    accounts = last_poll_info.get("accounts", [])
    if not isinstance(accounts, list):
        accounts = []
    for acc in accounts[:3]:
        if not isinstance(acc, dict):
            continue
        mp = acc.get("marketplace", "?")
        acc_poll = acc.get("last_poll_at")
        if acc_poll and isinstance(acc_poll, datetime):
            if acc_poll.tzinfo is None:
                acc_poll = acc_poll.replace(tzinfo=UTC)
            acc_age = int((now - acc_poll).total_seconds() / 60)
            account_hints.append(f"{mp}: {acc_age} мин")

    hint_text = " · ".join(account_hints) if account_hints else ""

    return (
        '<div style="margin-bottom:14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
        f'<span class="badge {badge_class}">{escape(label)}</span>'
        f"{'<span class="muted" style="font-size:12px">' + escape(hint_text) + '</span>' if hint_text else ''}"
        "</div>"
    )

def _render_pagination(
    filters: OrderWebFilters,
    page: int,
    total_pages: int,
    per_page: int,
    total_count: int,
) -> str:
    if total_pages <= 1:
        return ""

    from urllib.parse import urlencode

    base_params = {
        "period": filters.period,
        "marketplace": filters.marketplace.value if filters.marketplace else "all",
        "sale_model": filters.sale_model.value if filters.sale_model else "all",
        "economy": filters.economy,
        "status": filters.status,
        "sku": filters.sku,
        "sort": filters.sort,
        "direction": filters.direction,
        "per_page": per_page,
    }
    if filters.period == "custom":
        base_params["date_from"] = filters.local_date_from.isoformat()
        base_params["date_to"] = filters.local_date_to.isoformat()

    def page_url(p: int) -> str:
        params = {**base_params, "page": p}
        return f"/web/orders?{urlencode(params)}"

    pages: list[str] = []

    if page > 1:
        pages.append(f'<a href="{page_url(page - 1)}" class="button">← Назад</a>')

    window = 2
    start = max(1, page - window)
    end = min(total_pages, page + window)

    if start > 1:
        pages.append(f'<a href="{page_url(1)}" class="button">1</a>')
        if start > 2:
            pages.append('<span class="muted" style="padding:0 4px">…</span>')

    for p in range(start, end + 1):
        if p == page:
            pages.append(f'<span class="button primary" style="cursor:default">{p}</span>')
        else:
            pages.append(f'<a href="{page_url(p)}" class="button">{p}</a>')

    if end < total_pages:
        if end < total_pages - 1:
            pages.append('<span class="muted" style="padding:0 4px">…</span>')
        pages.append(f'<a href="{page_url(total_pages)}" class="button">{total_pages}</a>')

    if page < total_pages:
        pages.append(f'<a href="{page_url(page + 1)}" class="button">Далее →</a>')

    per_page_options = [20, 50, 100, 200]
    per_page_html = '<span class="muted" style="font-size:12px;margin-left:12px">На странице: '
    per_page_links = []
    for opt in per_page_options:
        if opt == per_page:
            per_page_links.append(f"<strong>{opt}</strong>")
        else:
            params = {**base_params, "page": 1, "per_page": opt}
            per_page_links.append(f'<a href="/web/orders?{urlencode(params)}">{opt}</a>')
    per_page_html += " · ".join(per_page_links) + "</span>"

    return (
        '<div style="display:flex;justify-content:center;align-items:center;flex-wrap:wrap;'
        f'gap:8px;margin-top:16px;padding:12px 0">{" ".join(pages)}{per_page_html}</div>'
    )

def _page_header(title: str, description: str, href: str, action: str) -> str:
    return (
        '<section class="page-header">'
        f'<div><h2>{escape(title)}</h2><p class="muted">{escape(description)}</p></div>'
        f'<div class="page-actions"><a class="button" href="{escape(href)}">{escape(action)}</a></div>'
        "</section>"
    )

def _web_tier_card(tier: SubscriptionTier, current_code: str) -> str:
    current = tier.code == current_code
    badge = '<span class="badge good">Текущий тариф</span>' if current else ""
    price = "Бесплатно" if tier.price_monthly == 0 else f"{_rub(tier.price_monthly)} / месяц"
    return f"""
      <section class="band">
        <h2>{escape(tier.name)} {badge}</h2>
        <p class="muted">{escape(tier.description or "")}</p>
        <div class="kv">
          <span>Стоимость</span><strong>{price}</strong>
          <span>Кабинеты</span><strong>{tier.max_marketplace_accounts}</strong>
          <span>Заказы</span><strong>{_limit(tier.max_orders_per_month)}</strong>
          <span>SKU</span><strong>{_limit(tier.max_products)}</strong>
        </div>
        <p class="muted">Оформление и оплата подписки сейчас выполняются через Telegram-бота.</p>
      </section>
    """
