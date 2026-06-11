"""version: 1.0.1
description: Formatting and badge helpers for MP Control web cabinet views.
updated: 2026-06-11
"""

# ruff: noqa: E501, F401, E402, F811, I001

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
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
    marketplace_logo_html,
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

__all__ = [
    "_limit",
    "_dt",
    "_user_display_name",
    "_rub",
    "_rub_optional",
    "_percent_optional",
    "_marketplace_label",
    "_sale_model_badge",
    "_order_status_badge",
    "_confidence_badge",
    "_account_status_badge",
    "_cost_status_badge",
    "_plan_marketplace",
    "_sync_status",
    "_last_sync_label",
]


def _limit(value: int | None) -> str:
    return "без ограничений" if value is None else str(value)

def _dt(value: datetime | None, timezone: str = "Europe/Moscow") -> str:
    return format_datetime_for_user(value, timezone)

def _user_display_name(user: User) -> str:
    return user.first_name or user.username or str(user.telegram_id)

def _rub(value: object | None) -> str:
    if value is None:
        return "н/д"
    try:
        decimal_value = Decimal(str(value))
        return f"{decimal_value:,.0f} ₽".replace(",", " ")
    except Exception:
        return "н/д"

def _rub_optional(value: Decimal | None) -> str:
    if value is None:
        return "н/д"
    return _rub(value)

def _percent_optional(value: Decimal | int | float | str | None) -> str:
    if value is None:
        return "—"
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return "—"
    return f"{decimal_value.quantize(Decimal('0.1'))}%"

def _marketplace_label(value: Marketplace | str | None) -> str:
    css_class = marketplace_css_class(value)
    logo_svg = marketplace_logo_html(value, size="sm")
    logo_html = f'<span class="mp-logo">{logo_svg}</span>'
    return (
        f'<span class="marketplace-badge {css_class}">'
        f"{logo_html}{escape(marketplace_title(value))}</span>"
    )

def _sale_model_badge(value: str | None) -> str:
    raw = str(value or "")
    tone = "action" if raw in {"FBS", "rFBS", "DBS", "DBW"} else "neutral"
    return f'<span class="badge {tone}">{escape(sale_model_title(value))}</span>'

def _order_status_badge(status: str | None, requires_action: bool = False) -> str:
    tone = order_status_tone(status, requires_action)
    label = presentation_order_status_label(status, requires_action)
    return f'<span class="badge {tone}">{escape(label)}</span>'

def _confidence_badge(value: str | None) -> str:
    labels = {
        "EXACT": ("good", "точный"),
        "ESTIMATED": ("warn", "оценочный"),
        "PRELIMINARY": ("warn", "предварительный"),
    }
    tone, label = labels.get(value or "PRELIMINARY", labels["PRELIMINARY"])
    return f'<span class="badge {tone}">{label}</span>'

def _alert_type_badge(value: str) -> str:
    labels = {
        "LOW_MARGIN": ("warn", "Низкая маржа"),
        "LOSS_ORDER": ("bad", "Убыточный заказ"),
        "MISSING_COST": ("warn", "Нет себестоимости"),
        "LOW_STOCK": ("bad", "Низкий остаток"),
        "STOCKOUT_FORECAST": ("bad", "Риск out-of-stock"),
        "FBS_DEADLINE": ("warn", "FBS-дедлайн"),
        "SYNC_ERROR": ("bad", "Ошибка синхронизации"),
        "ORDERS_DROP": ("warn", "Просадка заказов"),
    }
    tone, label = labels.get(value, ("neutral", value.replace("_", " ").title()))
    return f'<span class="badge {tone}">{escape(label)}</span>'

def _alert_delivery_badge(is_sent: bool) -> str:
    if is_sent:
        return '<span class="badge good">отправлено</span>'
    return '<span class="badge action">новое</span>'

def data_quality_hint(active_accounts: int) -> str:
    return "активен" if active_accounts else "нужна настройка"

def _fact_status_badge(status: str, label: str) -> str:
    tone = {
        "full": "good",
        "partial": "warn",
        "pending_link": "warn",
        "no_report": "",
    }.get(status, "")
    return f'<span class="badge {tone}">{escape(label)}</span>'

def _account_status_badge(status: str, is_active: bool) -> str:
    if not is_active:
        return '<span class="badge">отключён</span>'
    tone = "good" if status == "ACTIVE" else "warn" if status == "DRAFT" else "bad"
    label = {"ACTIVE": "активен", "DRAFT": "черновик", "ERROR": "ошибка"}.get(status, status)
    return f'<span class="badge {tone}">{escape(label)}</span>'

def _cost_status_badge(ok: bool) -> str:
    return (
        '<span class="badge good">задана</span>'
        if ok
        else '<span class="badge warn">не задана</span>'
    )

def _plan_marketplace(raw: str | None) -> Marketplace | None:
    if not raw or raw == "all":
        return None
    try:
        return Marketplace(raw)
    except ValueError:
        return None

def _sync_status(accounts: AccountsPageData) -> str:
    if accounts.active_accounts == 0:
        return "нужна настройка"
    if any(row.account.last_error_message for row in accounts.rows if row.account.is_active):
        return "есть ошибки"
    now = datetime.now(tz=UTC)
    orders_ok = False
    sales_ok = False
    for row in accounts.rows:
        acc = row.account
        if not acc.is_active:
            continue
        if acc.last_orders_sync_at is not None:
            ts = acc.last_orders_sync_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if now - ts < timedelta(minutes=SYNC_FRESHNESS_ORDERS_MINUTES):
                orders_ok = True
        if acc.last_sales_sync_at is not None:
            ts = acc.last_sales_sync_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if now - ts < timedelta(minutes=SYNC_FRESHNESS_SALES_MINUTES):
                sales_ok = True
    if orders_ok and sales_ok:
        return "актуальна"
    if orders_ok or sales_ok:
        return "требует проверки"
    return "ожидает данных"

def _last_sync_label(accounts: AccountsPageData, timezone: str = "Europe/Moscow") -> str:
    dates = []
    for row in accounts.rows:
        acc = row.account
        for field in (
            acc.last_orders_sync_at,
            acc.last_sales_sync_at,
            acc.last_stocks_sync_at,
            acc.last_products_sync_at,
            acc.last_profile_sync_at,
            acc.last_ozon_enrichment_sync_at,
            acc.last_wb_reports_sync_at,
        ):
            if field is not None:
                dates.append(field)
    if not dates:
        return "ещё не было"
    return _dt(max(dates), timezone)
