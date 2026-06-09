"""version: 1.1.0
description: Profit HTML view helpers with reconciliation status badge, commission/logistics columns, actual margin.
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

from app.web.view_modules.common import _section_subnav_finance
from app.web.view_modules.components import _simple_kpi
from app.web.view_modules.formatting import _marketplace_label, _rub, _percent_optional
from app.web.view_modules.forms import _profit_filters
from app.web.view_modules.orders import _reconciliation_badge

__all__ = [
    "_profit_content",
]


def _profit_content(data: ProfitPageData) -> str:
    summary = data.summary
    row_html = []
    for row in data.rows:
        roi = f"{row.roi_percent}%" if row.roi_percent is not None else "н/д"
        missing = (
            f'<span class="badge warn">{row.missing_cost_items} без себестоимости</span>'
            if row.missing_cost_items
            else ""
        )
        preliminary = (
            f'<span class="badge warn">{row.preliminary_items} предв.</span>'
            if row.preliminary_items
            else ""
        )
        title_cell = (
            f"<td>{escape(row.title)}"
            f'<div class="muted">{escape(row.seller_article)}</div>{missing} {preliminary}</td>'
        )
        actual_margin_str = (
            f"{row.actual_margin.quantize(Decimal('0.1'))}%"
            if row.actual_margin is not None
            else "н/д"
        )
        row_html.append(
            "<tr>"
            f"{title_cell}"
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f"<td>{escape(row.sale_model.value if row.sale_model else 'н/д')}</td>"
            f'<td class="num">{row.orders}</td>'
            f'<td class="num">{row.sales}</td>'
            f"<td>{_reconciliation_badge(row.reconciliation_status)}</td>"
            f'<td class="num">{_rub(row.estimated_revenue)}</td>'
            f'<td class="num">{_rub(row.actual_revenue)}</td>'
            f'<td class="num">{_rub(row.payout)}</td>'
            f'<td class="num">{_rub(row.cost)}</td>'
            f'<td class="num">{_rub(row.avg_commission)}</td>'
            f'<td class="num">{_rub(row.avg_logistics)}</td>'
            f'<td class="num">{_rub(row.estimated_profit)}</td>'
            f'<td class="num">{_rub(row.actual_profit)}</td>'
            f'<td class="num">{row.margin_percent.quantize(Decimal("0.1"))}%</td>'
            f'<td class="num">{actual_margin_str}</td>'
            f'<td class="num">{roi}</td>'
            "</tr>"
        )
    body = (
        "".join(row_html)
        if row_html
        else (
            '<tr><td colspan="17" class="muted">'
            "Данных по прибыли за выбранный период пока нет.</td></tr>"
        )
    )
    estimated_tone = "good" if summary.estimated_profit >= 0 else "bad"
    actual_tone = "good" if summary.actual_profit >= 0 else "bad"
    deviation_tone = "bad" if summary.deviation < 0 else "good"
    roi_value = f"{summary.roi_percent}%" if summary.roi_percent is not None else "н/д"
    return f"""
      {_section_subnav_finance("profit")}
      {_profit_filters(data.filters)}
      <section class="kpi-grid">
        {_simple_kpi("Плановая прибыль", _rub(summary.estimated_profit), estimated_tone)}
        {_simple_kpi("Фактическая прибыль", _rub(summary.actual_profit), actual_tone)}
        {_simple_kpi("Отклонение план/факт", _rub(summary.deviation), deviation_tone)}
        {_simple_kpi("Прибыль с заказа", _rub(summary.average_unit_profit))}
        {_simple_kpi("Средняя маржа", f"{summary.average_margin}%")}
        {_simple_kpi("ROI на себестоимость", roi_value)}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Прибыль по SKU</h2>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th>МП</th><th>Модель</th><th class="num">Заказов</th>
                <th class="num">Продаж</th><th>Статус сверки</th>
                <th class="num">Плановая выручка</th>
                <th class="num">Фактическая выручка</th><th class="num">К перечислению</th>
                <th class="num">Себестоимость</th><th class="num">Комиссия</th>
                <th class="num">Логистика</th>
                <th class="num">Плановая прибыль</th><th class="num">Фактическая прибыль</th>
                <th class="num">Маржа план</th><th class="num">Маржа факт</th>
                <th class="num">ROI</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """
