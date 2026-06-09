"""version: 1.0.0
description: Form, filter, and query helpers for MP Control web cabinet views.
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

__all__ = [
    "_filters",
    "_orders_filters",
    "_profit_filters",
    "_plan_fact_filters",
    "_shared_order_filters",
    "_select",
    "_period_select",
    "_sales_returns_filters",
    "_form_value",
    "_datetime_from_form",
    "_parse_int_list",
    "_optional_int",
    "_optional_decimal",
    "_mask_token",
    "_request_path",
    "_urlencoded_form",
    "_query_param",
    "_optional_query_param",
    "_decimal_from_query",
]


def _filters(data: DashboardData) -> str:
    filters = data.filters
    selected_marketplace = filters.marketplace.value if filters.marketplace else "all"
    selected_sale_model = filters.sale_model.value if filters.sale_model else "all"
    date_from = filters.local_date_from.isoformat()
    date_to = filters.local_date_to.isoformat()
    return f"""
      <form class="filters" method="get" action="/web/">
        {_period_select(filters.period)}
        {
        _select(
            "marketplace",
            "Маркетплейс",
            {
                "all": "Все",
                Marketplace.WB.value: "Wildberries",
                Marketplace.OZON.value: "Ozon",
            },
            selected_marketplace,
        )
    }
        {
        _select(
            "sale_model",
            "Модель",
            {
                "all": "Все",
                "FBO": "FBO",
                "FBS": "FBS",
                "rFBS": "rFBS",
            },
            selected_sale_model,
        )
    }
        <div>
          <label for="date_from">Дата с</label>
          <input id="date_from" name="date_from" type="date" value="{date_from}">
        </div>
        <div>
          <label for="date_to">Дата по</label>
          <input id="date_to" name="date_to" type="date" value="{date_to}">
        </div>
        <button class="button primary" type="submit">Применить</button>
      </form>
    """

def _orders_filters(filters: OrderWebFilters) -> str:
    return _shared_order_filters(filters, "/web/orders", include_status=True)

def _profit_filters(filters: OrderWebFilters) -> str:
    return _shared_order_filters(filters, "/web/profit", include_status=True)

def _plan_fact_filters(data: PlanFactPageData) -> str:
    filters = data.filters
    selected_marketplace = filters.marketplace.value if filters.marketplace else "all"
    selected_sale_model = filters.sale_model.value if filters.sale_model else "all"
    date_from_value = filters.local_date_from.isoformat()
    date_to_value = filters.local_date_to.isoformat()
    return f"""
      <form class="filters" method="get" action="/web/plan-fact">
        {_period_select(filters.period)}
        {
        _select(
            "marketplace",
            "Маркетплейс",
            {
                "all": "Все",
                Marketplace.WB.value: "Wildberries",
                Marketplace.OZON.value: "Ozon",
            },
            selected_marketplace,
        )
    }
        {
        _select(
            "sale_model",
            "Модель",
            {
                "all": "Все",
                "FBO": "FBO",
                "FBS": "FBS",
                "rFBS": "rFBS",
            },
            selected_sale_model,
        )
    }
        <div>
          <label for="sku">SKU / артикул</label>
          <input id="sku" name="sku" type="search" value="{escape(filters.sku)}">
        </div>
        <div>
          <label for="date_from">Дата с</label>
          <input id="date_from" name="date_from" type="date" value="{date_from_value}">
        </div>
        <div>
          <label for="date_to">Дата по</label>
          <input id="date_to" name="date_to" type="date" value="{date_to_value}">
        </div>
        {
        _select(
            "sort",
            "Сортировка",
            {
                "deviation": "Отклонение",
                "profit": "Плановая прибыль",
                "orders": "Заказы",
            },
            filters.sort,
        )
    }
        {
        _select(
            "direction",
            "Порядок",
            {
                "asc": "Сначала худшие",
                "desc": "Сначала лучшие",
            },
            filters.direction,
        )
    }
        <button class="button primary" type="submit">Применить</button>
      </form>
    """

def _shared_order_filters(
    filters: OrderWebFilters,
    action: str,
    *,
    include_status: bool,
) -> str:
    selected_marketplace = filters.marketplace.value if filters.marketplace else "all"
    selected_sale_model = filters.sale_model.value if filters.sale_model else "all"
    status_filter = (
        _select(
            "status",
            "Статус",
            {
                "all": "Все",
                "active": "Активные",
                "cancelled": "Отменённые",
                "action_required": "Требуют действия",
                "fact_missing": "Без факта",
                "fact_partial": "Частичный факт",
                "fact_complete": "Полный факт",
                "match_problem": "Проблемы сопоставления",
            },
            filters.status,
        )
        if include_status
        else ""
    )
    date_from_value = filters.local_date_from.isoformat()
    date_to_value = filters.local_date_to.isoformat()
    return f"""
      <nav class="tabs" style="margin-bottom:12px">
        <a href="/web/orders">Заказы</a>
        <a href="/web/sales">Продажи</a>
        <a href="/web/returns">Возвраты</a>
        <a href="/web/reports/wb-daily">Финансы WB</a>
      </nav>
      <form class="filters" method="get" action="{escape(action)}">
        {_period_select(filters.period)}
        {
        _select(
            "marketplace",
            "Маркетплейс",
            {
                "all": "Все",
                Marketplace.WB.value: "Wildberries",
                Marketplace.OZON.value: "Ozon",
            },
            selected_marketplace,
        )
    }
        {
        _select(
            "sale_model",
            "Модель",
            {
                "all": "Все",
                "FBO": "FBO",
                "FBS": "FBS",
                "rFBS": "rFBS",
            },
            selected_sale_model,
        )
    }
        {
        _select(
            "economy",
            "Экономика",
            {
                "all": "Все",
                "profit": "Прибыльные",
                "loss": "Убыточные",
                "missing_cost": "Без себестоимости",
            },
            filters.economy,
        )
    }
        {status_filter}
        <div>
          <label for="sku">SKU / артикул</label>
          <input id="sku" name="sku" type="search" value="{escape(filters.sku)}">
        </div>
        <div>
          <label for="date_from">Дата с</label>
          <input id="date_from" name="date_from" type="date" value="{date_from_value}">
        </div>
        <div>
          <label for="date_to">Дата по</label>
          <input id="date_to" name="date_to" type="date" value="{date_to_value}">
        </div>
        {
        _select(
            "sort",
            "Сортировка",
            {
                "date": "Дата",
                "profit": "Прибыль",
                "revenue": "Выручка",
                "margin": "Маржа",
                "orders": "Заказы",
                "roi": "ROI",
            },
            filters.sort,
        )
    }
        {
        _select(
            "direction",
            "Порядок",
            {
                "desc": "По убыванию",
                "asc": "По возрастанию",
            },
            filters.direction,
        )
    }
        <button class="button primary" type="submit">Применить</button>
      </form>
    """

def _select(name: str, label: str, options: dict[str, str], selected: str) -> str:
    items = []
    for value, text in options.items():
        attr = " selected" if value == selected else ""
        items.append(f'<option value="{escape(value)}"{attr}>{escape(text)}</option>')
    return (
        f'<div><label for="{escape(name)}">{escape(label)}</label>'
        f'<select id="{escape(name)}" name="{escape(name)}">{"".join(items)}</select></div>'
    )

def _period_select(selected: str) -> str:
    return _select(
        "period",
        "Период",
        {
            "today": "Сегодня",
            "yesterday": "Вчера",
            "7d": "7 дней",
            "30d": "30 дней",
            "current_month": "Текущий месяц",
            "previous_month": "Прошлый месяц",
            "custom": "Произвольный",
        },
        selected,
    )

def _sales_returns_filters(action: str, filters: DashboardFilters, sku: str) -> str:
    selected_marketplace = filters.marketplace.value if filters.marketplace else "all"
    return f"""
      <form class="filters filter-panel" method="get" action="{escape(action)}">
        {_period_select(filters.period)}
        {
        _select(
            "marketplace",
            "Маркетплейс",
            {
                "all": "Все",
                Marketplace.WB.value: "Wildberries",
                Marketplace.OZON.value: "Ozon",
            },
            selected_marketplace,
        )
    }
        <div>
          <label for="sku">Товар / SKU</label>
          <input id="sku" name="sku" type="search" value="{escape(sku)}">
        </div>
        <div>
          <label for="date_from">Дата с</label>
          <input id="date_from" name="date_from" type="date" value="{
        filters.local_date_from.isoformat()
    }">
        </div>
        <div>
          <label for="date_to">Дата по</label>
          <input id="date_to" name="date_to" type="date" value="{
        filters.local_date_to.isoformat()
    }">
        </div>
        <button class="button primary" type="submit">Применить</button>
      </form>
    """

def _form_value(form: dict[str, list[str]], name: str, default: str) -> str:
    return (form.get(name) or [default])[0]

def _datetime_from_form(value: str, timezone: str = "Europe/Moscow") -> datetime:
    if not value:
        return datetime.now(tz=UTC)
    local_day = datetime.fromisoformat(value).date()
    return user_day_bounds_utc(local_day, timezone)[0]

def _parse_int_list(raw: str) -> list[int]:
    ids: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            ids.append(int(chunk))
    return ids

def _optional_int(raw: str | None) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None

def _optional_decimal(raw: str | None) -> Decimal | None:
    text = (raw or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None

def _mask_token(token: str) -> str:
    if len(token) <= 12:
        return "***"
    return f"{token[:6]}...{token[-4:]}"

def _request_path(request: Request) -> str:
    url = getattr(request, "url", None)
    return str(getattr(url, "path", "unknown"))

async def _urlencoded_form(request: Request) -> dict[str, list[str]]:
    raw = (await request.body()).decode("utf-8")
    return parse_qs(raw, keep_blank_values=True)

def _query_param(request: Request, name: str, default: str) -> str:
    value = request.query_params.get(name)
    return value if value is not None else default

def _optional_query_param(request: Request, name: str) -> str | None:
    return request.query_params.get(name)

def _decimal_from_query(value: str, default: Decimal) -> Decimal:
    try:
        return Decimal(value)
    except Exception:
        return default
