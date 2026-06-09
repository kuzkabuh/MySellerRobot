"""version: 1.0.0
description: Reusable chart, KPI, and table components for MP Control web cabinet views.
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

from app.web.view_modules.formatting import _dt, _marketplace_label, _rub

__all__ = [
    "_kpi",
    "_simple_kpi",
    "_format_metric_value",
    "_line_chart",
    "_bar_chart",
    "_grouped_bar_chart",
    "_returns_chart",
    "_sale_model_chart",
    "_marketplace_table",
    "_x_labels",
    "_point_value",
    "_empty_chart",
]


def _kpi(metric: KpiMetric) -> str:
    change = ""
    if metric.change_percent is not None:
        css = "up" if metric.change_percent > 0 else "down" if metric.change_percent < 0 else ""
        sign = "+" if metric.change_percent > 0 else ""
        change = (
            f'<span class="change {css}">{sign}{metric.change_percent}% к прошлому периоду</span>'
        )
    elif metric.label != "Фактическая прибыль":
        change = '<span class="change">нет базы для сравнения</span>'
    value = _format_metric_value(metric.value, metric.suffix)
    return (
        f'<article class="kpi {escape(metric.tone)}">'
        f"<span>{escape(metric.label)}</span><strong>{value}</strong>{change}</article>"
    )

def _simple_kpi(label: str, value: str, tone: str = "neutral") -> str:
    return (
        f'<article class="kpi {tone}">'
        f"<span>{escape(label)}</span><strong>{value}</strong></article>"
    )

def _format_metric_value(value: Decimal | int, suffix: str) -> str:
    if isinstance(value, Decimal):
        if suffix == "%":
            return f"{value.quantize(Decimal('0.1'))}%"
        if suffix == "₽":
            return _rub(value)
    return f"{value}{suffix}"

def _area_chart(points: list[DailyPoint], attr: str, title: str, color: str) -> str:
    values = [_point_value(point, attr) for point in points]
    if not any(values):
        return _empty_chart()
    width = 720
    height = 240
    pad_top = 20
    pad_bottom = 36
    chart_h = height - pad_top - pad_bottom
    max_value = max(values) or Decimal("1")
    coords = []
    step = width / max(len(points) - 1, 1)
    for index, value in enumerate(values):
        x = Decimal(str(index * step))
        y = Decimal(pad_top) + chart_h - (value / max_value * Decimal(chart_h))
        coords.append((float(x), float(y)))
    line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area_points = (
        f"0,{pad_top + chart_h} " + line_points + f" {coords[-1][0]:.1f},{pad_top + chart_h}"
    )
    grid_lines = ""
    for i in range(4):
        gy = pad_top + chart_h * i / 3
        grid_lines += f'<line x1="0" y1="{gy:.1f}" x2="{width}" y2="{gy:.1f}" stroke="#e2e8f0" stroke-width="0.5"/>'
    labels = _x_labels(points, width, height)
    fill_id = f"fill_{attr}_{abs(hash(title)) % 10000}"
    return f"""
      <div class="chart" role="img" aria-label="{escape(title)}">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          <defs>
            <linearGradient id="{fill_id}" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="{color}" stop-opacity="0.18"/>
              <stop offset="100%" stop-color="{color}" stop-opacity="0.02"/>
            </linearGradient>
          </defs>
          {grid_lines}
          <polygon fill="url(#{fill_id})" points="{area_points}"/>
          <polyline fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" points="{line_points}"/>
          {labels}
        </svg>
      </div>
    """

def _line_chart(points: list[DailyPoint], attr: str, title: str, color: str) -> str:
    values = [_point_value(point, attr) for point in points]
    if not any(values):
        return _empty_chart()
    width = 720
    height = 240
    pad_top = 20
    pad_bottom = 36
    chart_h = height - pad_top - pad_bottom
    max_value = max(values) or Decimal("1")
    coords = []
    step = width / max(len(points) - 1, 1)
    for index, value in enumerate(values):
        x = Decimal(str(index * step))
        y = Decimal(pad_top) + chart_h - (value / max_value * Decimal(chart_h))
        coords.append(f"{float(x):.1f},{float(y):.1f}")
    grid_lines = ""
    for i in range(4):
        gy = pad_top + chart_h * i / 3
        grid_lines += f'<line x1="0" y1="{gy:.1f}" x2="{width}" y2="{gy:.1f}" stroke="#e2e8f0" stroke-width="0.5"/>'
    labels = _x_labels(points, width, height)
    return f"""
      <div class="chart" role="img" aria-label="{escape(title)}">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          {grid_lines}
          <polyline fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" points="{" ".join(coords)}"/>
          {labels}
        </svg>
      </div>
    """

def _bar_chart(points: list[DailyPoint], attr: str, title: str, color: str) -> str:
    values = [_point_value(point, attr) for point in points]
    if not any(values):
        return _empty_chart()
    width = 720
    height = 240
    pad_top = 20
    pad_bottom = 36
    chart_h = height - pad_top - pad_bottom
    max_value = max(abs(value) for value in values) or Decimal("1")
    group_w = width / max(len(points), 1)
    bar_width = max(group_w * 0.55, 4)
    bars = []
    for index, value in enumerate(values):
        x = index * group_w + (group_w - bar_width) / 2
        bar_height = abs(value) / max_value * Decimal(chart_h)
        y = Decimal(pad_top) + chart_h - bar_height if value >= 0 else Decimal(pad_top + chart_h)
        tone = color if value >= 0 else "#dc2626"
        bars.append(
            f'<rect x="{x:.1f}" y="{float(y):.1f}" width="{bar_width:.1f}" '
            f'height="{float(bar_height):.1f}" rx="3" fill="{tone}" opacity="0.85"/>'
        )
    grid_lines = ""
    for i in range(4):
        gy = pad_top + chart_h * i / 3
        grid_lines += f'<line x1="0" y1="{gy:.1f}" x2="{width}" y2="{gy:.1f}" stroke="#e2e8f0" stroke-width="0.5"/>'
    labels = _x_labels(points, width, height)
    return f"""
      <div class="chart" role="img" aria-label="{escape(title)}">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          {grid_lines}
          {"".join(bars)}
          {labels}
        </svg>
      </div>
    """

def _grouped_bar_chart(points: list[DailyPoint]) -> str:
    if not any(point.orders or point.sales for point in points):
        return _empty_chart()
    width = 720
    height = 240
    pad_top = 20
    pad_bottom = 36
    chart_h = height - pad_top - pad_bottom
    max_value = max([point.orders for point in points] + [point.sales for point in points] + [1])
    group = width / max(len(points), 1)
    bar_w = max(group * 0.2, 3)
    bars = []
    for index, point in enumerate(points):
        x = index * group + group * 0.22
        order_h = point.orders / max_value * chart_h
        sales_h = point.sales / max_value * chart_h
        bars.append(
            f'<rect x="{x:.1f}" y="{pad_top + chart_h - order_h:.1f}" width="{bar_w:.1f}" '
            f'height="{order_h:.1f}" rx="2" fill="#2563eb" opacity="0.8"/>'
            f'<rect x="{x + bar_w + 2:.1f}" y="{pad_top + chart_h - sales_h:.1f}" '
            f'width="{bar_w:.1f}" height="{sales_h:.1f}" rx="2" fill="#059669" opacity="0.8"/>'
        )
    grid_lines = ""
    for i in range(4):
        gy = pad_top + chart_h * i / 3
        grid_lines += f'<line x1="0" y1="{gy:.1f}" x2="{width}" y2="{gy:.1f}" stroke="#e2e8f0" stroke-width="0.5"/>'
    return f"""
      <div class="chart" role="img" aria-label="Заказы и продажи по дням">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          {grid_lines}
          {"".join(bars)}
          {_x_labels(points, width, height)}
        </svg>
        <div class="legend"><span><i class="dot" style="background:#2563eb"></i>Заказы</span>
        <span><i class="dot" style="background:#059669"></i>Продажи</span></div>
      </div>
    """

def _returns_chart(points: list[DailyPoint]) -> str:
    if not any(point.returns or point.cancellations for point in points):
        return _empty_chart()
    width = 720
    height = 240
    pad_top = 20
    pad_bottom = 36
    chart_h = height - pad_top - pad_bottom
    max_value = max(
        [point.returns for point in points] + [point.cancellations for point in points] + [1]
    )
    group = width / max(len(points), 1)
    bar_w = max(group * 0.2, 3)
    bars = []
    for index, point in enumerate(points):
        x = index * group + group * 0.22
        returns_h = point.returns / max_value * chart_h
        cancel_h = point.cancellations / max_value * chart_h
        bars.append(
            f'<rect x="{x:.1f}" y="{pad_top + chart_h - returns_h:.1f}" '
            f'width="{bar_w:.1f}" height="{returns_h:.1f}" rx="2" fill="#dc2626" opacity="0.8"/>'
            f'<rect x="{x + bar_w + 2:.1f}" y="{pad_top + chart_h - cancel_h:.1f}" '
            f'width="{bar_w:.1f}" height="{cancel_h:.1f}" rx="2" fill="#d97706" opacity="0.8"/>'
        )
    grid_lines = ""
    for i in range(4):
        gy = pad_top + chart_h * i / 3
        grid_lines += f'<line x1="0" y1="{gy:.1f}" x2="{width}" y2="{gy:.1f}" stroke="#e2e8f0" stroke-width="0.5"/>'
    return f"""
      <div class="chart" role="img" aria-label="Возвраты и отмены по дням">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          {grid_lines}
          {"".join(bars)}
          {_x_labels(points, width, height)}
        </svg>
        <div class="legend"><span><i class="dot" style="background:#dc2626"></i>Возвраты</span>
        <span><i class="dot" style="background:#d97706"></i>Отмены</span></div>
      </div>
    """

def _sale_model_chart(points: list[DailyPoint]) -> str:
    totals = {
        "FBO": sum(point.fbo_orders for point in points),
        "FBS": sum(point.fbs_orders for point in points),
        "rFBS": sum(point.rfbs_orders for point in points),
    }
    if not any(totals.values()):
        return _empty_chart()
    max_value = max(totals.values())
    rows = []
    colors = {"FBO": "#7b3fc5", "FBS": "#0f6f8f", "rFBS": "#147d4a"}
    for label, value in totals.items():
        width = 100 if max_value == 0 else value / max_value * 100
        bar_style = f"height:12px;width:{width:.1f}%;background:{colors[label]};border-radius:4px"
        rows.append(
            f'<tr><td>{label}</td><td class="num">{value}</td><td>'
            f'<div style="{bar_style}"></div>'
            "</td></tr>"
        )
    return (
        '<table class="table"><thead><tr><th>Модель</th><th class="num">Заказы</th>'
        f"<th>Доля</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )

def _marketplace_table(data: DashboardData) -> str:
    rows = []
    for item in data.marketplace_breakdown:
        rows.append(
            "<tr>"
            f"<td>{_marketplace_label(item.marketplace)}</td>"
            f'<td class="num">{item.orders}</td>'
            f'<td class="num">{item.sales}</td>'
            f'<td class="num">{_rub(item.revenue)}</td>'
            f'<td class="num">{_rub(item.estimated_profit)}</td>'
            "</tr>"
        )
    return (
        '<table class="table"><thead><tr><th>Площадка</th><th class="num">Заказы</th>'
        '<th class="num">Продажи</th><th class="num">Выручка</th>'
        f'<th class="num">Плановая прибыль</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )

def _x_labels(points: list[DailyPoint], width: int, height: int) -> str:
    if not points:
        return ""
    step = width / max(len(points) - 1, 1)
    labels = []
    for index, point in enumerate(points):
        if len(points) > 10 and index not in {0, len(points) - 1} and index % 5 != 0:
            continue
        x = index * step
        labels.append(
            f'<text x="{x:.1f}" y="{height - 10}" fill="#94a3b8" font-size="10" '
            f'font-weight="500" text-anchor="middle">{escape(point.label)}</text>'
        )
    return "".join(labels)

def _point_value(point: DailyPoint, attr: str) -> Decimal:
    value = getattr(point, attr)
    if isinstance(value, Decimal):
        return value
    return Decimal(value)

def _empty_chart() -> str:
    return '<div class="chart-empty">Данных за выбранный период пока нет</div>'

def _premium_kpi(metric: KpiMetric | None, label: str | None = None) -> str:
    if metric is None:
        return _simple_premium_kpi(label or "Показатель", "н/д", "Данных пока нет")
    title = label or metric.label
    value = _format_metric_value(metric.value, metric.suffix)
    change = _trend_text(metric.change_percent)
    return (
        f'<article class="premium-kpi {escape(metric.tone)}">'
        f"<span>{escape(title)}</span><strong>{value}</strong><small>{change}</small></article>"
    )

def _simple_premium_kpi(
    label: str,
    value: str,
    hint: str,
    tone: str = "neutral",
) -> str:
    return (
        f'<article class="premium-kpi {escape(tone)}">'
        f"<span>{escape(label)}</span><strong>{value}</strong><small>{escape(hint)}</small></article>"
    )

def _trend_text(change_percent: Decimal | None) -> str:
    if change_percent is None:
        return "Сравнение появится после накопления истории"
    if change_percent == 0:
        return "Без изменений к прошлому периоду"
    sign = "+" if change_percent > 0 else ""
    direction = "рост" if change_percent > 0 else "снижение"
    return f"{sign}{change_percent}% к прошлому периоду, {direction}"

def _period_label(filters: DashboardFilters) -> str:
    labels = {
        "today": "сегодня",
        "yesterday": "вчера",
        "7d": "последние 7 дней",
        "30d": "последние 30 дней",
        "current_month": "текущий месяц",
        "previous_month": "прошлый месяц",
        "custom": "выбранный период",
    }
    return labels.get(filters.period, "выбранный период")

def _period_range(filters: DashboardFilters) -> str:
    start = filters.local_date_from.strftime("%d.%m.%Y")
    end = filters.local_date_to.strftime("%d.%m.%Y")
    return start if start == end else f"{start} - {end}"

def _filter_summary(filters: DashboardFilters) -> str:
    marketplace = marketplace_title(filters.marketplace) if filters.marketplace else "все МП"
    sale_model = sale_model_title(filters.sale_model.value) if filters.sale_model else "все модели"
    return f"{marketplace}, {sale_model}"

def _conversion_label(orders: KpiMetric | None, sales: KpiMetric | None) -> str:
    if orders is None or sales is None or not orders.value:
        return "н/д"
    order_count = Decimal(orders.value)
    sales_count = Decimal(sales.value)
    return f"{(sales_count / order_count * Decimal('100')).quantize(Decimal('0.1'))}%"

def _metric_by_label(data: DashboardData, label: str) -> KpiMetric | None:
    return next((metric for metric in data.metrics if metric.label == label), None)

def _metric_value(data: DashboardData, label: str) -> str:
    metric = _metric_by_label(data, label)
    return _format_metric_value(metric.value, metric.suffix) if metric else "н/д"

def _attention_list(data: DashboardData) -> str:
    items = []
    loss = _metric_by_label(data, "Убыточные заказы")
    returns = _metric_by_label(data, "Возвраты")
    revenue = _metric_by_label(data, "Выручка")
    if loss and loss.value:
        items.append(
            _attention_item(
                "bad",
                "Есть убыточные заказы",
                f"{loss.value} заказов требуют проверки себестоимости и комиссий.",
                "/web/profit",
            )
        )
    if returns and returns.value:
        items.append(
            _attention_item(
                "warn",
                "Возвраты за период",
                f"{returns.value} возвратов влияют на прибыльность периода.",
                "/web/returns",
            )
        )
    if revenue and isinstance(revenue.value, Decimal) and revenue.value == ZERO:
        items.append(
            _attention_item(
                "warn",
                "Нет выручки в выбранном периоде",
                "Проверьте фильтры, синхронизацию заказов или подключение кабинетов.",
                "/web/settings?tab=marketplaces",
            )
        )
    if not items:
        items.append(
            _attention_item(
                "good",
                "Нет критичных проблем",
                "По доступным данным за период бизнес выглядит стабильно.",
                "/web/analytics",
            )
        )
    return '<div class="attention-list">' + "".join(items) + "</div>"

def _attention_item(tone: str, title: str, text: str, href: str) -> str:
    return (
        f'<article class="attention-item {escape(tone)}">'
        f"<div><strong>{escape(title)}</strong><p>{escape(text)}</p></div>"
        f'<a class="button" href="{escape(href)}">Перейти</a></article>'
    )

def _marketplace_compare(data: DashboardData) -> str:
    total_revenue = sum((item.revenue for item in data.marketplace_breakdown), ZERO)
    panels = "".join(_marketplace_panel(item, total_revenue) for item in data.marketplace_breakdown)
    if not panels:
        return '<div class="empty-state">Данных по маркетплейсам пока нет.</div>'
    return f'<div class="marketplace-split">{panels}</div>'

def _marketplace_panel(item, total_revenue: Decimal) -> str:  # type: ignore[no-untyped-def]
    share = (
        Decimal("0")
        if total_revenue == ZERO
        else (item.revenue / total_revenue * Decimal("100")).quantize(Decimal("0.1"))
    )
    return f"""
      <article class="marketplace-panel">
        <div class="marketplace-panel-head">
          {_marketplace_label(item.marketplace)}
          <span class="marketplace-share">{share}% выручки</span>
        </div>
        <div class="progress-track"><span style="width:{share}%"></span></div>
        <div class="mini-stat-grid">
          <div class="mini-stat"><span>Выручка</span><strong>{_rub(item.revenue)}</strong></div>
          <div class="mini-stat"><span>Заказы</span><strong>{item.orders}</strong></div>
          <div class="mini-stat"><span>Выкупы</span><strong>{item.sales}</strong></div>
        </div>
      </article>
    """

def _recent_events(events: list[DashboardEvent], timezone: str) -> str:
    if not events:
        return '<div class="empty-state">За выбранный период новых событий пока нет.</div>'
    return (
        '<div class="event-list">'
        + "".join(_event_item(event, timezone) for event in events[:5])
        + "</div>"
    )

def _event_item(event: DashboardEvent, timezone: str) -> str:
    href = event.href or "/web/orders"
    return f"""
      <article class="event-item">
        <div>
          <strong>{escape(event.title)}</strong>
          <p>{escape(event.subtitle)}</p>
          <div class="event-meta">
            {_marketplace_label(event.marketplace)}
            <span class="badge {escape(event.tone)}">{escape(_dt(event.event_date, timezone))}</span>
          </div>
        </div>
        <div class="num">
          <strong>{_rub(event.amount)}</strong>
          <p><a href="{escape(href)}">Открыть</a></p>
        </div>
      </article>
    """

def _quick_actions() -> str:
    actions = [
        ("Открыть аналитику", "Динамика, сравнения и товары-лидеры", "/web/analytics"),
        ("Посмотреть заказы", "Фильтры по статусам и площадкам", "/web/orders"),
        ("Проверить остатки", "Out-of-stock и общий FBS", "/web/stocks"),
        ("Контроль ошибок", "Синхронизация и качество данных", "/web/control"),
        ("План/факт", "Сравнение целей и результата", "/web/plan-fact"),
    ]
    return (
        '<div class="shortcut-grid">'
        + "".join(
            f'<a class="shortcut-card" href="{escape(href)}"><strong>{escape(title)}</strong><p>{escape(text)}</p></a>'
            for title, text, href in actions
        )
        + "</div>"
    )
