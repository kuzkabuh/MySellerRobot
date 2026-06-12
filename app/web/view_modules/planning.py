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

from app.web.view_modules.common import _section_subnav_finance
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
      {_section_subnav_finance("plan_fact")}
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
    return f"""
      {_section_subnav_finance("break_even")}
      <link rel="stylesheet" href="https://cdn.datatables.net/2.0.8/css/dataTables.dataTables.min.css">
      <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
      <script src="https://cdn.datatables.net/2.0.8/js/dataTables.min.js"></script>
      <style>
        .be-toolbar {{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:10px;align-items:end;margin:12px 0}}
        .be-toolbar input,.be-toolbar select {{width:100%;min-height:38px}}
        .be-kpis {{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:14px 0}}
        .be-kpi {{border:1px solid var(--border);border-radius:8px;padding:12px;background:var(--surface)}}
        .be-kpi strong {{display:block;font-size:22px;line-height:1.1}}
        .be-status {{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 8px;font-weight:700;font-size:12px}}
        .be-status.loss {{background:#fee2e2;color:#991b1b}}
        .be-status.risk {{background:#fef3c7;color:#92400e}}
        .be-status.profit {{background:#dcfce7;color:#166534}}
        .be-status.high {{background:#dbeafe;color:#1d4ed8}}
        .be-thumb {{width:44px;height:44px;border-radius:6px;object-fit:cover;background:var(--muted-bg)}}
        .be-actions {{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}}
        .be-panel-grid {{display:grid;grid-template-columns:1.1fr .9fr;gap:14px}}
        .be-modal {{position:fixed;inset:0;background:rgba(15,23,42,.45);z-index:50;display:none;align-items:center;justify-content:center;padding:20px}}
        .be-modal.open {{display:flex}}
        .be-modal-body {{background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:8px;max-width:1120px;width:100%;max-height:90vh;overflow:auto;padding:18px}}
        .be-detail-head {{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:10px}}
        .be-expense-list {{display:grid;gap:6px}}
        .be-expense-line {{display:grid;grid-template-columns:1fr 90px 70px;gap:10px;align-items:center}}
        .be-table-wrap {{overflow:auto;max-height:70vh;border:1px solid var(--border);border-radius:8px}}
        #breakEvenTable th {{white-space:nowrap;position:sticky;top:0;z-index:2}}
        @media (max-width:900px) {{.be-toolbar,.be-panel-grid {{grid-template-columns:1fr}}}}
      </style>

      <section class="band">
        <form class="be-toolbar" method="get" action="/web/break-even" id="breakEvenFilters">
          <div><label for="target_margin">Целевая маржа, %</label><input id="target_margin" name="target_margin" type="number" step="0.1" value="{escape(target_margin)}"></div>
          <div><label for="price_delta">Симуляция цены, %</label><input id="price_delta" name="price_delta" type="number" step="0.1" value="{escape(price_delta)}"></div>
          <div><label for="beMarketplace">Маркетплейс</label><select id="beMarketplace" name="marketplace"><option value="all">Все</option><option value="wb">Wildberries</option><option value="ozon">Ozon</option></select></div>
          <div><label for="beStatus">Статус</label><select id="beStatus" name="status"><option value="all">Все</option><option value="loss">Убыток</option><option value="risk">Риск</option><option value="profit">Прибыль</option><option value="high">Высокая маржа</option></select></div>
          <div><label for="beCategory">Категория</label><input id="beCategory" name="category" type="search"></div>
          <div><button class="button primary" type="submit">Применить</button></div>
        </form>

        <div class="be-kpis" id="breakEvenKpis">
          <div class="be-kpi"><span class="muted">Всего товаров</span><strong data-kpi="total_products">0</strong></div>
          <div class="be-kpi"><span class="muted">Убыточных</span><strong data-kpi="loss_products">0</strong></div>
          <div class="be-kpi"><span class="muted">Рискованных</span><strong data-kpi="risky_products">0</strong></div>
          <div class="be-kpi"><span class="muted">Прибыльных</span><strong data-kpi="profitable_products">0</strong></div>
          <div class="be-kpi"><span class="muted">Средняя маржа</span><strong data-kpi="average_margin_percent">0%</strong></div>
          <div class="be-kpi"><span class="muted">Средняя прибыль</span><strong data-kpi="average_profit">0 ₽</strong></div>
          <div class="be-kpi"><span class="muted">Потерянная прибыль</span><strong data-kpi="potential_lost_profit">0 ₽</strong></div>
          <div class="be-kpi"><span class="muted">После оптимизации</span><strong data-kpi="additional_profit_after_optimization">0 ₽</strong></div>
        </div>

        <div class="be-actions">
          <button class="button" type="button" data-quick-status="loss">Ниже безубыточности</button>
          <button class="button" type="button" data-quick-status="risk">Низкая прибыль</button>
          <button class="button" type="button" id="beThemeToggle">Тема</button>
          <a class="button" href="/web/break-even/export.xlsx">Excel</a>
          <a class="button" href="/web/break-even/export.csv">CSV</a>
          <a class="button" href="/web/break-even/export.pdf">PDF</a>
        </div>

        <div class="be-table-wrap">
          <table class="table" id="breakEvenTable">
            <thead>
              <tr>
                <th>Фото</th><th>Артикул продавца</th><th>SKU</th><th>Бренд</th><th>Название</th>
                <th>Маркетплейс</th><th>Категория</th><th class="num">Текущая цена</th>
                <th class="num">Цена со скидкой</th><th class="num">Себестоимость</th>
                <th class="num">Комиссия MP</th><th class="num">Логистика</th><th class="num">Реклама</th>
                <th class="num">Налоги</th><th class="num">Прочие расходы</th><th class="num">Безубыточная цена</th>
                <th class="num">Мин. прибыльная</th><th class="num">Маржа %</th><th class="num">Прибыль</th>
                <th class="num">Рекоменд. цена</th><th>Статус</th>
              </tr>
            </thead>
          </table>
        </div>
      </section>

      <section class="band" style="margin-top:14px">
        <h2>Центр расходов</h2>
        <form class="filters" method="post" action="/web/break-even/expenses">
          <div><label for="beScope">Уровень</label><select id="beScope" name="scope"><option value="global">Глобально</option><option value="category">Категория</option><option value="product">Товар</option></select></div>
          <div><label for="beExpenseCategory">Категория</label><input id="beExpenseCategory" name="category" type="text"></div>
          <div><label for="beExpenseProduct">ID товара</label><input id="beExpenseProduct" name="product_id" type="number"></div>
          <div><label for="beTax">Налог, %</label><input id="beTax" name="tax_rate" type="number" step="0.01" value="6"></div>
          <div><label for="beAcquiring">Эквайринг, %</label><input id="beAcquiring" name="acquiring_rate" type="number" step="0.01" value="1.5"></div>
          <div><label for="beAds">Реклама, %</label><input id="beAds" name="advertising_rate" type="number" step="0.01" value="5"></div>
          <div><label for="bePack">Упаковка, ₽</label><input id="bePack" name="packaging_cost" type="number" step="0.01" value="0"></div>
          <div><label for="beStorage">Хранение, ₽</label><input id="beStorage" name="storage_cost" type="number" step="0.01" value="0"></div>
          <div><label for="beOther">Прочие, ₽</label><input id="beOther" name="other_cost" type="number" step="0.01" value="0"></div>
          <button class="button primary" type="submit">Сохранить</button>
        </form>
      </section>

      <div class="be-modal" id="breakEvenModal">
        <div class="be-modal-body">
          <div class="be-detail-head">
            <div><h2 id="beDetailTitle">Товар</h2><p class="muted" id="beDetailMeta"></p></div>
            <button class="button" type="button" id="beCloseDetail">Закрыть</button>
          </div>
          <div class="be-panel-grid">
            <div>
              <h3>Финансовая структура</h3>
              <canvas id="beExpenseChart" height="160"></canvas>
              <div class="be-expense-list" id="beExpenseList"></div>
            </div>
            <div>
              <h3>Анализ прибыли</h3>
              <div class="be-kpis" id="beProfitAnalysis"></div>
              <h3>Калькулятор цены</h3>
              <div class="filters">
                <div><label for="calcProfit">Желаемая прибыль</label><input id="calcProfit" type="number" value="300"></div>
                <div><label for="calcMargin">Желаемая маржа, %</label><input id="calcMargin" type="number" value="{escape(target_margin)}"></div>
                <div><label for="calcRoi">ROI, %</label><input id="calcRoi" type="number" value="100"></div>
                <div><label for="calcAds">Реклама, %</label><input id="calcAds" type="number" value="5"></div>
              </div>
              <div class="be-kpis" id="beCalcResult"></div>
            </div>
          </div>
          <h3>Чувствительность цены</h3>
          <canvas id="beSensitivityChart" height="110"></canvas>
        </div>
      </div>

      <script>
      (function() {{
        const fmtMoney = v => (Number(v || 0)).toLocaleString('ru-RU') + ' ₽';
        const fmtPct = v => (Number(v || 0)).toLocaleString('ru-RU') + '%';
        const esc = v => String(v ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
        const filters = document.getElementById('breakEvenFilters');
        const table = new DataTable('#breakEvenTable', {{
          serverSide: true,
          processing: true,
          pageLength: 50,
          scrollX: true,
          ajax: {{
            url: '/web/break-even/api/products',
            data: function(d) {{
              d.target_margin = document.getElementById('target_margin').value;
              d.price_delta = document.getElementById('price_delta').value;
              d.marketplace = document.getElementById('beMarketplace').value;
              d.status = document.getElementById('beStatus').value;
              d.category = document.getElementById('beCategory').value;
            }}
          }},
          columns: [
            {{data:'image_url', orderable:false, render:v=>v ? '<img class="be-thumb" src="'+esc(v)+'" alt="">' : '<div class="be-thumb"></div>'}},
            {{data:'seller_article', render:esc}}, {{data:'sku', render:esc}}, {{data:'brand', render:esc}}, {{data:'title', render:esc}},
            {{data:'marketplace', render:esc}}, {{data:'category', render:esc}},
            {{data:'current_price', className:'num', render:fmtMoney}},
            {{data:'discounted_price', className:'num', render:fmtMoney}},
            {{data:'cost_price', className:'num', render:fmtMoney}},
            {{data:'commission_amount', className:'num', render:fmtMoney}},
            {{data:'logistics_cost', className:'num', render:fmtMoney}},
            {{data:'advertising_cost', className:'num', render:fmtMoney}},
            {{data:'tax_amount', className:'num', render:fmtMoney}},
            {{data:'other_cost', className:'num', render:fmtMoney}},
            {{data:'break_even_price', className:'num', render:fmtMoney}},
            {{data:'min_profitable_price', className:'num', render:fmtMoney}},
            {{data:'current_margin_percent', className:'num', render:fmtPct}},
            {{data:'current_profit', className:'num', render:fmtMoney}},
            {{data:'recommended_price', className:'num', render:fmtMoney}},
            {{data:'status_label', render:(v,t,row)=>'<button class="be-status '+esc(row.status)+'" type="button" data-product="'+esc(row.product_id)+'">'+esc(v)+'</button>'}}
          ],
          language: {{url: 'https://cdn.datatables.net/plug-ins/2.0.8/i18n/ru.json'}}
        }});
        function reloadSummary() {{
          const target = document.getElementById('target_margin').value;
          fetch('/web/break-even/api/summary?target_margin=' + encodeURIComponent(target))
            .then(r => r.json()).then(data => {{
              Object.entries(data).forEach(([k,v]) => {{
                const el = document.querySelector('[data-kpi="'+k+'"]');
                if (!el) return;
                el.textContent = k.includes('margin') ? fmtPct(v) : (k.includes('profit') ? fmtMoney(v) : v);
              }});
            }});
        }}
        filters.addEventListener('submit', e => {{ e.preventDefault(); table.ajax.reload(); reloadSummary(); }});
        document.querySelectorAll('[data-quick-status]').forEach(btn => btn.addEventListener('click', () => {{
          document.getElementById('beStatus').value = btn.dataset.quickStatus;
          table.ajax.reload(); reloadSummary();
        }}));
        document.getElementById('beThemeToggle').addEventListener('click', () => document.documentElement.classList.toggle('theme-dark'));
        let expenseChart, sensitivityChart, currentDetail;
        document.getElementById('breakEvenTable').addEventListener('click', e => {{
          const btn = e.target.closest('[data-product]');
          if (!btn || !btn.dataset.product) return;
          fetch('/web/break-even/api/products/' + btn.dataset.product + '?target_margin=' + encodeURIComponent(document.getElementById('target_margin').value))
            .then(r => r.json()).then(showDetail);
        }});
        document.getElementById('beCloseDetail').addEventListener('click', () => document.getElementById('breakEvenModal').classList.remove('open'));
        function showDetail(data) {{
          currentDetail = data.row;
          document.getElementById('beDetailTitle').textContent = data.row.title;
          document.getElementById('beDetailMeta').textContent = data.row.seller_article + ' · ' + data.row.marketplace + ' · ' + data.row.category;
          document.getElementById('beProfitAnalysis').innerHTML =
            '<div class="be-kpi"><span class="muted">Прибыль</span><strong>'+fmtMoney(data.row.current_profit)+'</strong></div>' +
            '<div class="be-kpi"><span class="muted">Маржинальность</span><strong>'+fmtPct(data.row.current_margin_percent)+'</strong></div>' +
            '<div class="be-kpi"><span class="muted">ROI</span><strong>'+fmtPct(data.row.roi_percent)+'</strong></div>' +
            '<div class="be-kpi"><span class="muted">Валовая прибыль</span><strong>'+fmtMoney(data.row.gross_profit)+'</strong></div>';
          document.getElementById('beExpenseList').innerHTML = data.expense_structure.map(x =>
            '<div class="be-expense-line"><span>'+esc(x.label)+'</span><strong>'+fmtMoney(x.amount)+'</strong><span>'+fmtPct(x.percent)+'</span></div>'
          ).join('');
          if (expenseChart) expenseChart.destroy();
          expenseChart = new Chart(document.getElementById('beExpenseChart'), {{
            type:'doughnut',
            data: {{labels:data.expense_structure.map(x=>x.label), datasets:[{{data:data.expense_structure.map(x=>Number(x.amount))}}]}}
          }});
          if (sensitivityChart) sensitivityChart.destroy();
          sensitivityChart = new Chart(document.getElementById('beSensitivityChart'), {{
            type:'line',
            data: {{labels:data.sensitivity.map(x=>x.price), datasets:[{{label:'Прибыль', data:data.sensitivity.map(x=>x.profit), tension:.25}}]}},
            options: {{plugins:{{annotation:false}}}}
          }});
          recalc();
          document.getElementById('breakEvenModal').classList.add('open');
        }}
        function recalc() {{
          if (!currentDetail) return;
          const desiredProfit = Number(document.getElementById('calcProfit').value || 0);
          const desiredMargin = Number(document.getElementById('calcMargin').value || 0) / 100;
          const ads = Number(document.getElementById('calcAds').value || 0) / 100;
          const current = Number(currentDetail.discounted_price || currentDetail.current_price || 0);
          const fixed = Number(currentDetail.cost_price) + Number(currentDetail.logistics_cost) + Number(currentDetail.storage_cost) + Number(currentDetail.other_cost);
          const variable = current > 0 ? (Number(currentDetail.commission_amount) + Number(currentDetail.acquiring_cost) + Number(currentDetail.tax_amount)) / current + ads : ads;
          const priceForProfit = (fixed + desiredProfit) / Math.max(.01, 1 - variable);
          const priceForMargin = fixed / Math.max(.01, 1 - variable - desiredMargin);
          const required = Math.max(priceForProfit, priceForMargin);
          const profit = required - required * variable - fixed;
          document.getElementById('beCalcResult').innerHTML =
            '<div class="be-kpi"><span class="muted">Цена продажи</span><strong>'+fmtMoney(required)+'</strong></div>' +
            '<div class="be-kpi"><span class="muted">Ожидаемая прибыль</span><strong>'+fmtMoney(profit)+'</strong></div>' +
            '<div class="be-kpi"><span class="muted">Ожидаемая маржа</span><strong>'+fmtPct(required ? profit / required * 100 : 0)+'</strong></div>';
        }}
        ['calcProfit','calcMargin','calcRoi','calcAds'].forEach(id => document.getElementById(id).addEventListener('input', recalc));
        reloadSummary();
      }})();
      </script>
    """
