"""version: 3.0.0
description: Professional profit dashboard with KPI cards, profit tree, SVG charts, rich table, pagination, attention block.
updated: 2026-06-11
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
    ProfitSkuRow,
    ProfitPageData,
    ProfitAttentionItem,
    ProfitTreeItem,
    ProfitChartData,
    localized_order_date,
    order_state_label,
    ReconciliationStatus,
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
from app.web.view_modules.formatting import _marketplace_label, _rub, _percent_optional, _sale_model_badge
from app.web.view_modules.orders import _reconciliation_badge

__all__ = [
    "_profit_content",
]


def _profit_content(data: ProfitPageData) -> str:
    if not data.has_data:
        return _empty_profit_state(data)
    return (
        _profit_header(data)
        + _profit_attention(data)
        + _profit_kpi_block(data)
        + _profit_tree_block(data)
        + _profit_charts_block(data)
        + _profit_table(data)
    )


def _profit_header(data: ProfitPageData) -> str:
    f = data.filters
    action = "/web/profit"
    period = f.period

    from urllib.parse import urlencode
    def _qp(p: str) -> str:
        params = {"period": p}
        if f.marketplace:
            params["marketplace"] = f.marketplace.value
        if f.sale_model:
            params["sale_model"] = f.sale_model.value
        if f.sku:
            params["sku"] = f.sku
        if f.economy != "all":
            params["economy"] = f.economy
        if f.status != "all":
            params["status"] = f.status
        if f.sort != "date":
            params["sort"] = f.sort
        if f.direction != "desc":
            params["direction"] = f.direction
        return urlencode(params)

    quick_periods = ""
    for key, label in [("today", "Сегодня"), ("yesterday", "Вчера"), ("7d", "7 дней"), ("30d", "30 дней"), ("current_month", "Этот месяц"), ("previous_month", "Прошлый месяц")]:
        cls = "button primary" if key == period else "button"
        quick_periods += f'<a class="{cls}" href="{escape(action)}?{_qp(key)}">{label}</a>'

    selected_mp = f.marketplace.value if f.marketplace else "all"
    selected_sm = f.sale_model.value if f.sale_model else "all"
    date_from_val = f.local_date_from.isoformat()
    date_to_val = f.local_date_to.isoformat()
    export_params = _qp(period)
    export_url = f"{action}/export?{export_params}"

    return f"""
      {_section_subnav_finance("profit")}
      <section class="band" style="padding:18px 22px;margin-bottom:14px">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
          <div>
            <h2 style="margin:0 0 2px;font-size:18px">Прибыль</h2>
            <p class="muted" style="margin:0">Контроль выручки, расходов, маржи и фактической прибыли по заказам и SKU</p>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            <a class="button" href="{escape(export_url)}" download>Экспорт в Excel</a>
          </div>
        </div>
        <div class="quick-periods" style="display:flex;flex-wrap:wrap;gap:4px;margin-top:12px">
          {quick_periods}
        </div>
        <details style="margin-top:10px">
          <summary style="cursor:pointer;color:var(--accent);font-size:12px;font-weight:600">Расширенные фильтры</summary>
          <form class="filters" method="get" action="{escape(action)}" style="margin-top:10px;margin-bottom:0">
            <input type="hidden" name="period" value="{escape(period)}">
            <div><label>Маркетплейс</label><select name="marketplace">
              <option value="all"{" selected" if selected_mp == "all" else ""}>Все</option>
              <option value="wb"{" selected" if selected_mp == "wb" else ""}>Wildberries</option>
              <option value="ozon"{" selected" if selected_mp == "ozon" else ""}>Ozon</option>
            </select></div>
            <div><label>Модель</label><select name="sale_model">
              <option value="all"{" selected" if selected_sm == "all" else ""}>Все</option>
              <option value="FBO"{" selected" if selected_sm == "FBO" else ""}>FBO</option>
              <option value="FBS"{" selected" if selected_sm == "FBS" else ""}>FBS</option>
              <option value="rFBS"{" selected" if selected_sm == "rFBS" else ""}>rFBS</option>
            </select></div>
            <div><label>Экономика</label><select name="economy">
              <option value="all"{" selected" if f.economy == "all" else ""}>Все</option>
              <option value="profit"{" selected" if f.economy == "profit" else ""}>Прибыльные</option>
              <option value="loss"{" selected" if f.economy == "loss" else ""}>Убыточные</option>
              <option value="missing_cost"{" selected" if f.economy == "missing_cost" else ""}>Без себестоимости</option>
            </select></div>
            <div><label>Поиск</label><input name="sku" type="search" value="{escape(f.sku)}" placeholder="Название, SKU, артикул"></div>
            <div><label>Дата с</label><input name="date_from" type="date" value="{date_from_val}"></div>
            <div><label>Дата по</label><input name="date_to" type="date" value="{date_to_val}"></div>
            <div><label>Сортировка</label><select name="sort">
              <option value="profit_actual"{" selected" if f.sort == "actual_profit" or f.sort == "profit" else ""}>Прибыль</option>
              <option value="revenue"{" selected" if f.sort == "revenue" else ""}>Выручка</option>
              <option value="margin"{" selected" if f.sort == "margin" else ""}>Маржа</option>
              <option value="roi"{" selected" if f.sort == "roi" else ""}>ROI</option>
              <option value="orders"{" selected" if f.sort == "orders" else ""}>Заказы</option>
              <option value="title"{" selected" if f.sort == "title" else ""}>Название</option>
            </select></div>
            <div><label>Порядок</label><select name="direction">
              <option value="desc"{" selected" if f.direction == "desc" else ""}>По убыванию</option>
              <option value="asc"{" selected" if f.direction == "asc" else ""}>По возрастанию</option>
            </select></div>
            <div style="display:flex;gap:6px;align-items:end">
              <button class="button primary" type="submit">Применить</button>
              <a class="button" href="/web/profit?period=30d">Сбросить</a>
            </div>
          </form>
        </details>
      </section>
    """


def _profit_attention(data: ProfitPageData) -> str:
    items = data.attention_items
    if not items or (len(items) == 1 and items[0].tone == "good"):
        return ""
    cards = []
    for item in items:
        tone = item.tone
        icon_map = {"good": "✓", "bad": "✗", "warn": "!"}
        cards.append(f'''
          <article class="attention-item {tone}" style="cursor:pointer" onclick="this.closest('.attention-item').classList.toggle('collapsed')">
            <div><strong>{icon_map.get(tone, "")} {escape(item.title)} ({item.count})</strong><p>{escape(item.description)}</p></div>
          </article>
        ''')
    return f'''
      <div class="band" style="padding:14px 18px;margin-bottom:14px">
        <h3 style="margin:0 0 8px;font-size:13px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.04em">Что требует внимания</h3>
        <div class="attention-list">{"".join(cards)}</div>
      </div>
    '''


def _profit_kpi_block(data: ProfitPageData) -> str:
    s = data.summary
    profit_tone = "good" if s.profit_actual >= ZERO else "bad"
    plan_tone = "good" if s.profit_plan >= ZERO else "bad"
    dev_tone = "good" if s.deviation >= ZERO else "bad"
    margin_tone = "good" if (s.avg_margin or ZERO) >= 10 else ("warn" if (s.avg_margin or ZERO) >= 0 else "bad")
    roi_tone = "good" if (s.roi_percent or ZERO) >= 20 else ("warn" if (s.roi_percent or ZERO) >= 0 else "bad")
    rev_tone = "neutral"
    payout_tone = "neutral"
    cost_tone = "warn"

    dev_pct = ""
    if s.deviation_percent is not None:
        sign = "+" if s.deviation_percent >= 0 else ""
        dev_pct = f'<small style="color:var(--text-muted)">{sign}{s.deviation_percent}% от плана</small>'

    return f'''
      <div class="premium-kpi-grid">
        <article class="premium-kpi {profit_tone}">
          <span>Фактическая прибыль</span>
          <strong>{_rub(s.profit_actual)}</strong>
          <small>Выручка − Комиссия − Логистика − Себестоимость</small>
        </article>
        <article class="premium-kpi {plan_tone}">
          <span>Плановая прибыль</span>
          <strong>{_rub(s.profit_plan)}</strong>
          <small>Ожидаемая прибыль на момент заказа</small>
        </article>
        <article class="premium-kpi {dev_tone}">
          <span>Отклонение план/факт</span>
          <strong>{_rub(s.deviation)}</strong>
          {dev_pct}
        </article>
        <article class="premium-kpi {rev_tone}">
          <span>Выручка</span>
          <strong>{_rub(s.revenue)}</strong>
          <small>Сумма продаж без вычета расходов</small>
        </article>
        <article class="premium-kpi {payout_tone}">
          <span>К перечислению</span>
          <strong>{_rub(s.payout)}</strong>
          <small>Сумма к получению от маркетплейса</small>
        </article>
        <article class="premium-kpi {cost_tone}">
          <span>Себестоимость</span>
          <strong>{_rub(s.cost_price)}</strong>
          <small>Затраты на закупку проданных товаров</small>
        </article>
        <article class="premium-kpi {margin_tone}">
          <span>Средняя маржа</span>
          <strong>{_format_pct(s.avg_margin)}</strong>
          <small>{(s.profit_actual / s.revenue * 100).quantize(Decimal("0.1")) if s.revenue else "—"} %</small>
        </article>
        <article class="premium-kpi {roi_tone}">
          <span>ROI на себестоимость</span>
          <strong>{_format_pct(s.roi_percent)}</strong>
          <small>Прибыль / Себестоимость × 100</small>
        </article>
      </div>
    '''


def _profit_tree_block(data: ProfitPageData) -> str:
    tree = data.profit_tree
    if not tree:
        return ""
    rows = ""
    for item in tree:
        amount_str = _rub(abs(item.amount))
        prefix = "+ " if item.amount >= 0 else "− "
        sign_class = "tone-good" if item.amount >= 0 else "tone-bad"
        rows += f'''
          <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border-light);font-size:13px">
            <span style="color:var(--text-secondary)">{escape(item.label)}</span>
            <span class="{sign_class}" style="font-weight:600;font-variant-numeric:tabular-nums">{prefix}{amount_str}</span>
          </div>
        '''
    return f'''
      <div class="band" style="padding:18px 22px;margin-bottom:14px">
        <div class="section-head">
          <h2>Структура прибыли</h2>
        </div>
        <div style="max-width:500px">
          {rows}
        </div>
      </div>
    '''


def _profit_charts_block(data: ProfitPageData) -> str:
    chart = data.chart_data
    top_chart = _top_sku_bar_chart(chart.top_sku_labels, chart.top_sku_values)
    expense_chart = _expense_donut_chart(chart.expense_labels, chart.expense_values)
    return f'''
      <div class="dashboard-grid" style="margin-bottom:14px">
        <div class="band" style="padding:18px 22px">
          <h3 style="margin:0 0 10px;font-size:14px">ТОП-10 SKU по прибыли</h3>
          {top_chart}
        </div>
        <div class="band" style="padding:18px 22px">
          <h3 style="margin:0 0 10px;font-size:14px">Структура расходов</h3>
          {expense_chart}
        </div>
      </div>
    '''


def _top_sku_bar_chart(labels: list[str], values: list[Decimal]) -> str:
    if not values or not any(v for v in values):
        return '<div class="chart-empty">Данных для графика пока нет</div>'
    max_val = max(abs(v) for v in values) or Decimal("1")
    bars = []
    for i, (label, value) in enumerate(zip(labels, values)):
        pct = float(value / max_val * 100)
        color = "var(--success)" if value >= 0 else "var(--danger)"
        bars.append(f'''
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span style="min-width:120px;font-size:11px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{escape(label)}">{escape(label)}</span>
            <div style="flex:1;height:16px;background:var(--bg-muted);border-radius:4px;overflow:hidden;position:relative">
              <div style="width:{abs(pct):.1f}%;height:100%;background:{color};border-radius:4px;opacity:0.8;{"" if value >= 0 else "margin-left:auto"}"></div>
            </div>
            <span style="min-width:70px;text-align:right;font-size:11px;font-weight:600;color:var(--text);font-variant-numeric:tabular-nums">{_rub(value)}</span>
          </div>
        ''')
    return f'<div style="margin-top:4px">{"".join(bars)}</div>'


def _expense_donut_chart(labels: list[str], values: list[Decimal]) -> str:
    if not values or not any(v for v in values):
        return '<div class="chart-empty">Данных для графика пока нет</div>'
    total = sum(values, ZERO)
    if total == 0:
        return '<div class="chart-empty">Расходы за период отсутствуют</div>'
    colors = ["#059669", "#2563eb", "#d97706", "#dc2626"]
    items = ""
    cumulative = 0
    for i, (label, value) in enumerate(zip(labels, values)):
        pct = float(value / total * 100)
        cumulative += float(value)
        items += f'<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:12px"><span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:{colors[i % len(colors)]};margin-right:6px"></span>{escape(label)}</span><span style="font-weight:600">{_rub(value)} ({pct:.1f}%)</span></div>'
    return f'''
      <div>
        <div style="text-align:center;margin-bottom:10px">
          <div style="font-size:22px;font-weight:750;color:var(--text)">{_rub(total)}</div>
          <div style="font-size:11px;color:var(--text-muted)">Всего расходов</div>
        </div>
        {items}
      </div>
    '''


def _profit_table(data: ProfitPageData) -> str:
    row_html = []
    for row in data.rows:
        row_id = f"sku-{abs(hash(row.seller_article + str(row.marketplace.value)))}"
        profit_tone = "tone-good" if row.actual_profit >= 0 else "tone-bad"
        margin_str = _format_pct(row.actual_margin) if row.actual_margin is not None else _format_pct(row.margin_percent)
        roi_str = _format_pct(row.roi_percent)
        delta_str = _rub(row.profit_delta)
        delta_tone = "tone-good" if row.profit_delta >= 0 else "tone-bad"
        warning_icons = ""
        if row.missing_cost_items:
            warning_icons += '<span class="badge warn" title="Нет себестоимости">C</span> '
        if row.actual_profit < ZERO:
            warning_icons += '<span class="badge bad" title="Убыток">!</span> '
        title_cell = f'''
          <div style="min-width:160px">
            <div style="font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:200px" title="{escape(row.title)}">{escape(row.title)}</div>
            <div class="muted" style="font-size:11px">{escape(row.seller_article)}</div>
            <div style="margin-top:2px">{warning_icons}</div>
          </div>
        '''
        row_html.append(f'''
          <tr class="profit-row" data-row-id="{row_id}" style="cursor:pointer" onclick="toggleSkuDetail('{row_id}')">
            <td>{title_cell}</td>
            <td>{_marketplace_label(row.marketplace)}</td>
            <td>{_sale_model_badge(row.sale_model.value if row.sale_model else None)}</td>
            <td class="num">{row.orders}</td>
            <td class="num">{row.sales}</td>
            <td class="num">{row.returns_count}</td>
            <td class="num" style="color:var(--text-secondary)">{_rub(row.estimated_revenue)}</td>
            <td class="num">{_rub(row.actual_revenue)}</td>
            <td class="num">{_rub(row.payout)}</td>
            <td class="num" style="font-size:11px;line-height:1.6">
              <div>С/с: {_rub(row.cost)}</div>
              <div>Ком: {_rub(row.avg_commission)}</div>
              <div>Лог: {_rub(row.avg_logistics)}</div>
            </td>
            <td class="num" style="color:var(--text-secondary)">{_rub(row.estimated_profit)}</td>
            <td class="num {profit_tone}" style="font-weight:700">{_rub(row.actual_profit)}</td>
            <td class="num {delta_tone}" style="font-size:12px">{delta_str}</td>
            <td class="num">{margin_str}</td>
            <td class="num">{roi_str}</td>
            <td>{_reconciliation_badge_v2(row.reconciliation_status, row)}</td>
          </tr>
          <tr class="sku-detail" id="detail-{row_id}" style="display:none">
            <td colspan="16" style="padding:0">
              <div class="order-detail-body">
                <div class="detail-grid-compact">
                  <div><strong>Товар:</strong> {escape(row.title)}</div>
                  <div><strong>Артикул:</strong> {escape(row.seller_article)}</div>
                  <div><strong>Маркетплейс:</strong> {marketplace_title(row.marketplace)}</div>
                  <div><strong>Модель:</strong> {sale_model_title(row.sale_model)}</div>
                  <div><strong>Заказы:</strong> {row.orders}</div>
                  <div><strong>Продажи:</strong> {row.sales}</div>
                  <div><strong>Возвраты:</strong> {row.returns_count}</div>
                  <div><strong>Статус:</strong> {_reconciliation_status_label(row.reconciliation_status)}</div>
                </div>
                <div class="detail-grid-compact" style="margin-top:8px;grid-template-columns:repeat(4,minmax(0,1fr))">
                  <div><strong>Выручка:</strong> {_rub(row.revenue)}</div>
                  <div><strong>К перечислению:</strong> {_rub(row.payout)}</div>
                  <div><strong>Себестоимость:</strong> <span class="tone-bad">{_rub(row.cost)}</span></div>
                  <div><strong>Комиссия МП:</strong> <span class="tone-bad">{_rub(row.avg_commission)}</span></div>
                  <div><strong>Логистика:</strong> <span class="tone-bad">{_rub(row.avg_logistics)}</span></div>
                  <div><strong>Прибыль план:</strong> {_rub(row.estimated_profit)}</div>
                  <div><strong>Прибыль факт:</strong> <span class="{profit_tone}">{_rub(row.actual_profit)}</span></div>
                  <div><strong>ROI:</strong> {roi_str}</div>
                </div>
                {_sku_warnings(row)}
              </div>
            </td>
          </tr>
        ''')
    body = "".join(row_html) if row_html else (
        '<tr><td colspan="16"><div class="empty-state">Данных по прибыли за выбранный период нет.</div></td></tr>'
    )
    return f'''
      <div class="band" style="padding:0;overflow:hidden">
        <div style="padding:16px 18px 8px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
          <h2 style="margin:0;font-size:15px">Прибыль по SKU <span class="muted" style="font-weight:500">({data.total_count} SKU)</span></h2>
        </div>
        <div class="table-wrap" style="border:none;border-top:1px solid var(--border);border-radius:0">
          <table class="table profit-table" style="font-size:12px">
            <thead>
              <tr>
                <th>Товар</th>
                <th>МП</th>
                <th>Модель</th>
                <th class="num">Заказы</th>
                <th class="num">Продажи</th>
                <th class="num">Возвраты</th>
                <th class="num">Выручка план</th>
                <th class="num">Выручка факт</th>
                <th class="num">К перечислению</th>
                <th class="num">Расходы</th>
                <th class="num">Прибыль план</th>
                <th class="num">Прибыль факт</th>
                <th class="num">Δ</th>
                <th class="num">Маржа</th>
                <th class="num">ROI</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
        {_profit_pagination(data)}
      </div>
      <script>
        function toggleSkuDetail(id) {{
          var el = document.getElementById('detail-' + id);
          if (el) {{
            var isVisible = el.style.display !== 'none';
            el.style.display = isVisible ? 'none' : 'table-row';
          }}
        }}
      </script>
    '''


def _sku_warnings(row: ProfitSkuRow) -> str:
    warnings = []
    if row.missing_cost_items:
        warnings.append(f'<span class="badge warn">Нет себестоимости ({row.missing_cost_items} позиций)</span>')
    if row.actual_profit < ZERO:
        warnings.append('<span class="badge bad">Убыточная позиция</span>')
    if row.avg_commission == ZERO:
        warnings.append('<span class="badge warn">Комиссия не учтена</span>')
    if row.avg_logistics == ZERO:
        warnings.append('<span class="badge warn">Логистика не учтена</span>')
    if row.reconciliation_status in (ReconciliationStatus.PRELIMINARY, ReconciliationStatus.FACT_UNMATCHED):
        warnings.append('<span class="badge warn">Нет финансовых данных</span>')
    if not warnings:
        return ""
    return f'<div style="margin-top:8px;display:flex;gap:4px;flex-wrap:wrap">{"".join(warnings)}</div>'


def _profit_pagination(data: ProfitPageData) -> str:
    if data.total_pages <= 1:
        return ""
    from urllib.parse import urlencode
    f = data.filters
    base_params = {
        "period": f.period,
        "marketplace": f.marketplace.value if f.marketplace else "all",
        "sale_model": f.sale_model.value if f.sale_model else "all",
        "economy": f.economy,
        "status": f.status,
        "sku": f.sku,
        "sort": f.sort if f.sort != "date" else "profit_actual",
        "direction": f.direction,
        "per_page": data.page_size,
    }
    if f.period == "custom":
        base_params["date_from"] = f.local_date_from.isoformat()
        base_params["date_to"] = f.local_date_to.isoformat()

    def page_url(p: int) -> str:
        params = {**base_params, "page": p}
        return f"/web/profit?{urlencode(params)}"

    pages_links = []
    pages_links.append(f'<a href="{page_url(1)}" class="button {"disabled" if data.page <= 1 else ""}">«</a>')
    pages_links.append(f'<a href="{page_url(max(1, data.page - 1))}" class="button {"disabled" if data.page <= 1 else ""}">←</a>')
    window = 2
    start = max(1, data.page - window)
    end = min(data.total_pages, data.page + window)
    if start > 1:
        pages_links.append(f'<a href="{page_url(1)}" class="button">1</a>')
        if start > 2:
            pages_links.append('<span class="muted" style="padding:0 4px">…</span>')
    for p in range(start, end + 1):
        if p == data.page:
            pages_links.append(f'<span class="button primary">{p}</span>')
        else:
            pages_links.append(f'<a href="{page_url(p)}" class="button">{p}</a>')
    if end < data.total_pages:
        if end < data.total_pages - 1:
            pages_links.append('<span class="muted" style="padding:0 4px">…</span>')
        pages_links.append(f'<a href="{page_url(data.total_pages)}" class="button">{data.total_pages}</a>')
    pages_links.append(f'<a href="{page_url(min(data.total_pages, data.page + 1))}" class="button {"disabled" if data.page >= data.total_pages else ""}">→</a>')
    pages_links.append(f'<a href="{page_url(data.total_pages)}" class="button {"disabled" if data.page >= data.total_pages else ""}">»</a>')
    per_page_opts = [25, 50, 100]
    per_page_html = '<span class="muted" style="font-size:12px;margin-left:auto">Показать: '
    per_page_html += " · ".join(
        f"<strong>{data.page_size}</strong>" if opt == data.page_size
        else f'<a href="{page_url(1).replace("per_page=" + str(data.page_size), "per_page=" + str(opt))}">{opt}</a>'
        for opt in per_page_opts
    )
    per_page_html += "</span>"
    return f'''
      <div class="pagination-bar" style="display:flex;justify-content:center;align-items:center;flex-wrap:wrap;gap:6px;padding:14px 18px;border-top:1px solid var(--border-light)">
        {" ".join(pages_links)}
        {per_page_html}
      </div>
    '''


def _reconciliation_badge_v2(status: ReconciliationStatus, row: ProfitSkuRow | None = None) -> str:
    mapping = {
        ReconciliationStatus.FACT_MATCHED: ("good", "Сверено", "Все финансовые данные загружены"),
        ReconciliationStatus.FACT_PARTIAL: ("warn", "Частично", "Часть финансовых данных отсутствует"),
        ReconciliationStatus.PRELIMINARY: ("warn", "Нет данных", "Финансовые отчёты ещё не загружены"),
        ReconciliationStatus.FACT_UNMATCHED: ("warn", "Не сопоставлено", "Данные отчёта не сопоставлены с заказом"),
        ReconciliationStatus.FACT_AMBIGUOUS: ("bad", "Ошибка", "Неоднозначное сопоставление"),
        ReconciliationStatus.MANUAL_REVIEW: ("bad", "Требует проверки", "Нет себестоимости или ошибка данных"),
        ReconciliationStatus.MISSING_COST: ("warn", "Нет себестоимости", "Не задана себестоимость товара"),
        ReconciliationStatus.MISSING_REPORT: ("warn", "Нет отчёта", "Финансовый отчёт не загружен"),
    }
    tone, label, tooltip = mapping.get(status, ("neutral", status.value if status else "н/д", ""))
    if row and row.actual_profit < ZERO:
        tone = "bad"
        label = "Убыточно"
        tooltip = "Фактическая прибыль отрицательная"
    return f'<span class="badge {tone}" title="{escape(tooltip)}">{escape(label)}</span>'


def _reconciliation_status_label(status: ReconciliationStatus) -> str:
    labels = {
        ReconciliationStatus.FACT_MATCHED: "Сверено",
        ReconciliationStatus.FACT_PARTIAL: "Частично сверено",
        ReconciliationStatus.PRELIMINARY: "Нет финансовых данных",
        ReconciliationStatus.FACT_UNMATCHED: "Не сопоставлено",
        ReconciliationStatus.FACT_AMBIGUOUS: "Ошибка сверки",
        ReconciliationStatus.MANUAL_REVIEW: "Требует проверки",
        ReconciliationStatus.MISSING_COST: "Нет себестоимости",
        ReconciliationStatus.MISSING_REPORT: "Нет отчёта",
    }
    return labels.get(status, status.value if status else "н/д")


def _format_pct(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{value.quantize(Decimal('0.1'))}%"


def _empty_profit_state(data: ProfitPageData) -> str:
    return f"""
      {_section_subnav_finance("profit")}
      <section class="band" style="padding:18px 22px;margin-bottom:14px">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
          <div>
            <h2 style="margin:0 0 2px;font-size:18px">Прибыль</h2>
            <p class="muted" style="margin:0">Контроль выручки, расходов, маржи и фактической прибыли по заказам и SKU</p>
          </div>
        </div>
      </section>
      <section class="band">
        <div class="empty-state" style="min-height:220px">
          <strong>Данных о прибыли пока нет</strong>
          <span>Загрузите заказы и финансовые отчёты маркетплейсов,<br>чтобы увидеть фактическую прибыль, маржу и ROI.</span>
          <div style="margin-top:12px;display:flex;gap:8px">
            <a class="button primary" href="/web/sync-center?tab=sync">Перейти в синхронизацию</a>
            <a class="button" href="/web/settings?tab=marketplaces">Настроить кабинеты</a>
          </div>
        </div>
      </section>
    """
