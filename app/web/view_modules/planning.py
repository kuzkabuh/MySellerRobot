"""version: 1.0.0
description: Plan/fact and break-even HTML view helpers.
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

from app.web.view_modules.common import _section_subnav
from app.web.view_modules.components import _simple_kpi
from app.web.view_modules.formatting import _marketplace_label, _percent_optional, _rub
from app.web.view_modules.forms import _plan_fact_filters, _select

__all__ = [
    "_plan_fact_content",
    "_plan_fact_plan_panel",
    "_plan_progress",
    "_decimal_or_none",
    "_break_even_content",
]


def _plan_fact_content(data: PlanFactPageData) -> str:
    summary = data.summary
    row_html = []
    for row in data.rows:
        deviation_tone = "bad" if row.deviation < 0 else "good"
        pending = (
            f'<span class="badge warn">{row.pending_actual} без факта</span>'
            if row.pending_actual
            else ""
        )
        row_html.append(
            "<tr>"
            f'<td>{escape(row.title)}<div class="muted">{escape(row.seller_article)}</div></td>'
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f"<td>{escape(row.sale_model.value if row.sale_model else 'н/д')}</td>"
            f'<td class="num">{row.orders}</td>'
            f'<td class="num">{_rub(row.estimated_profit)}</td>'
            f'<td class="num">{_rub(row.actual_profit)}</td>'
            f'<td class="num"><span class="badge {deviation_tone}">'
            f"{_rub(row.deviation)}</span></td>"
            f'<td class="num">{_percent_optional(row.deviation_percent)}</td>'
            f"<td>{escape(row.reason)} {pending}</td>"
            "</tr>"
        )
    body = (
        "".join(row_html)
        if row_html
        else '<tr><td colspan="9" class="muted">Данных для сравнения план/факт пока нет.</td></tr>'
    )
    deviation_tone = "bad" if summary.deviation < 0 else "good"
    plan = data.plan
    plan_panel = _plan_fact_plan_panel(data)
    return f"""
      {_section_subnav("plan_fact")}
      {_plan_fact_filters(data)}
      {plan_panel}
      <section class="kpi-grid">
        {_simple_kpi("Плановая прибыль", _rub(plan.profit_plan) if plan and plan.profit_plan is not None else _rub(summary.estimated_profit))}
        {_simple_kpi("Фактическая прибыль", _rub(summary.actual_profit))}
        {_simple_kpi("Отклонение", _rub(summary.deviation), deviation_tone)}
        {_simple_kpi("Без факта", str(summary.pending_actual), "warn")}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Отклонения по товарам</h2>
        <p class="muted">
          Факт появляется после сопоставления финансовых отчётов маркетплейса.
          Причина отклонения определяется по основному видимому фактору.
        </p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th>МП</th><th>Модель</th><th class="num">Заказов</th>
                <th class="num">План</th><th class="num">Факт</th>
                <th class="num">Отклонение</th><th class="num">%</th><th>Причина</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """

def _plan_fact_plan_panel(data: PlanFactPageData) -> str:
    filters = data.filters
    plan = data.plan
    target_id = plan.id if plan else ""
    marketplace_value = plan.marketplace.value if plan and plan.marketplace else "all"
    period_start = plan.period_start.isoformat() if plan else filters.local_date_from.isoformat()
    period_end = plan.period_end.isoformat() if plan else filters.local_date_to.isoformat()
    revenue = "" if not plan or plan.revenue_plan is None else str(plan.revenue_plan)
    profit = "" if not plan or plan.profit_plan is None else str(plan.profit_plan)
    orders = "" if not plan or plan.orders_plan is None else str(plan.orders_plan)
    buyouts = "" if not plan or plan.buyouts_plan is None else str(plan.buyouts_plan)
    progress = ""
    if plan:
        progress_items = [
            _plan_progress("Прибыль", data.summary.actual_profit, plan.profit_plan),
            _plan_progress(
                "Заказы", Decimal(data.summary.orders), _decimal_or_none(plan.orders_plan)
            ),
            _plan_progress(
                "Выкупы", Decimal(data.summary.buyouts), _decimal_or_none(plan.buyouts_plan)
            ),
        ]
        progress = '<div class="progress-grid">' + "".join(progress_items) + "</div>"
    else:
        progress = '<p class="muted">План ещё не установлен. Задайте цели, чтобы видеть выполнение и отклонение.</p>'
    delete_form = (
        f'<form method="post" action="/web/plan-fact/plans/{plan.id}/delete">'
        '<button class="button" type="submit">Удалить план</button></form>'
        if plan
        else ""
    )
    return f"""
      <section class="band" style="margin-bottom:14px">
        <h2>Настройка плана</h2>
        {progress}
        <form class="filters" method="post" action="/web/plan-fact/plans">
          <input type="hidden" name="target_id" value="{target_id}">
          <div><label for="period_start">Начало</label><input id="period_start" name="period_start" type="date" value="{period_start}" required></div>
          <div><label for="period_end">Конец</label><input id="period_end" name="period_end" type="date" value="{period_end}" required></div>
          {_select("marketplace", "Маркетплейс", {"all": "Все", Marketplace.WB.value: "Wildberries", Marketplace.OZON.value: "Ozon"}, marketplace_value)}
          <div><label for="revenue_plan">План выручки</label><input id="revenue_plan" name="revenue_plan" type="number" step="0.01" value="{escape(revenue)}"></div>
          <div><label for="profit_plan">План прибыли</label><input id="profit_plan" name="profit_plan" type="number" step="0.01" value="{escape(profit)}"></div>
          <div><label for="orders_plan">План заказов</label><input id="orders_plan" name="orders_plan" type="number" value="{escape(orders)}"></div>
          <div><label for="buyouts_plan">План выкупов</label><input id="buyouts_plan" name="buyouts_plan" type="number" value="{escape(buyouts)}"></div>
          <button class="button primary" type="submit">Сохранить план</button>
          {delete_form}
        </form>
      </section>
    """

def _plan_progress(label: str, fact: Decimal, plan: Decimal | None) -> str:
    if plan is None or plan <= 0:
        return ""
    percent = min(Decimal("100"), (fact / plan * Decimal("100")).quantize(Decimal("0.1")))
    return (
        '<div class="progress-card">'
        f"<div><strong>{escape(label)}</strong><span>{_rub(fact) if label == 'Прибыль' else int(fact)} / {_rub(plan) if label == 'Прибыль' else int(plan)}</span></div>"
        f'<div class="progress-track"><span style="width:{percent}%"></span></div>'
        f'<span class="muted">{percent}% выполнения</span>'
        "</div>"
    )

def _decimal_or_none(value: int | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value)

def _break_even_content(
    rows: list[BreakEvenRow],
    target_margin: str,
    price_delta: str,
) -> str:
    body = "".join(
        "<tr>"
        f'<td>{escape(row.title)}<div class="muted">{escape(row.seller_article)}</div></td>'
        f"<td>{_marketplace_label(row.marketplace)}</td>"
        f'<td class="num">{_rub(row.current_price)}</td>'
        f'<td class="num">{_rub(row.break_even_price)}</td>'
        f'<td class="num">{_rub(row.target_margin_price)}</td>'
        f'<td class="num">{row.commission_rate}%</td>'
        f'<td class="num">{_rub(row.logistics_cost)}</td>'
        f'<td class="num">{_rub(row.simulated_price)}</td>'
        f'<td class="num">{_rub(row.simulated_profit)}</td>'
        f'<td class="num">{row.simulated_margin_percent}%</td>'
        f"<td>{escape(row.recommendation)}</td>"
        "</tr>"
        for row in rows
    )
    if not body:
        body = (
            '<tr><td colspan="11" class="muted">'
            "Недостаточно заказов с экономикой для расчёта безубыточности.</td></tr>"
        )
    return f"""
      {_section_subnav("break_even")}
      <form class="filters" method="get" action="/web/break-even">
        <div>
          <label for="target_margin">Целевая маржа, %</label>
          <input id="target_margin" name="target_margin" type="number"
                 value="{escape(target_margin)}">
        </div>
        <div>
          <label for="price_delta">Симуляция цены, %</label>
          <input id="price_delta" name="price_delta" type="number" value="{escape(price_delta)}">
        </div>
        <button class="button primary" type="submit">Пересчитать</button>
      </form>
      <section class="band">
        <h2>Безубыточная цена и симулятор</h2>
        <p class="muted">
          Расчёт использует средние комиссию, логистику, налог и себестоимость из последних
          заказов. Прогнозные значения не считаются фактическим финансовым отчётом.
        </p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th>МП</th><th class="num">Текущая цена</th>
                <th class="num">Безубыток</th><th class="num">Цена для цели</th>
                <th class="num">Комиссия</th><th class="num">Логистика</th>
                <th class="num">Цена симуляции</th><th class="num">Прибыль</th>
                <th class="num">Маржа</th><th>Рекомендация</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """
