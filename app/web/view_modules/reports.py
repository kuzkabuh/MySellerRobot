"""version: 1.0.0
description: Marketplace report HTML view helpers for MP Control web cabinet.
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
from app.services.data_quality_service import DataQualityReport
from app.services.marketplace_presentation import (
    marketplace_css_class,
    marketplace_title,
    order_status_tone,
    sale_model_title,
    source_event_label,
)
from app.services.marketplace_presentation import (
    order_status_label as presentation_order_status_label,
)
from app.services.master_product_service import (
    MasterProductAnalyticsRow,
    MasterProductDetail,
    ProductMatchingCandidate,
)
from app.services.plan_fact_service import PlanFactPageData
from app.services.stock_forecast_service import (
    StockForecastRow,
    stock_status_label,
    stock_status_tone,
)
from app.services.unit_economics_service import BreakEvenRow
from app.services.web_cabinet_service import (
    AccountsPageData,
    ControlPageData,
    CostsPageData,
    ProductCostDetail,
    ReturnsPageData,
    SalesPageData,
    SubscriptionPageData,
    subscription_status,
)
from app.services.web_dashboard_service import (
    DailyPoint,
    DashboardData,
    DashboardEvent,
    DashboardFilters,
    KpiMetric,
)
from app.services.web_orders_profit_service import (
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

from app.web.view_modules.formatting import _rub

__all__ = [
    "_wb_reports_web",
    "_report_short",
]


def _wb_reports_web(daily: object | None, weekly: object | None, states: Sequence[object]) -> str:
    state_by_period = {getattr(state, "period_type", ""): state for state in states}
    if daily is None and weekly is None and not states:
        return '<span class="muted">Пока не проверялись</span>'
    return (
        f"<div>День: {_report_short(daily, state_by_period.get('daily'))}</div>"
        f"<div>Неделя: {_report_short(weekly, state_by_period.get('weekly'))}</div>"
    )

def _report_short(report: object | None, state: object | None) -> str:
    if report is not None:
        period = f"{getattr(report, 'date_from', '')} — {getattr(report, 'date_to', '')}"
        amount = getattr(report, "for_pay_sum", None)
        return f'{escape(period)}<div class="muted">к выплате: {_rub(amount)}</div>'
    if state is None:
        return '<span class="muted">нет данных</span>'
    status = getattr(state, "status", "")
    if status in {"NO_ACCESS", "RATE_LIMITED"}:
        return '<span class="muted">нет Finance-доступа или лимит</span>'
    return '<span class="muted">не найден</span>'
