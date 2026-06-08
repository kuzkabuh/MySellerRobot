"""version: 1.0.0
description: Dashboard and analytics HTML view helpers for MP Control web cabinet.
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

from app.web.view_modules.components import _area_chart, _attention_list, _conversion_label, _filter_summary, _grouped_bar_chart, _marketplace_compare, _metric_by_label, _metric_value, _period_label, _period_range, _premium_kpi, _quick_actions, _recent_events, _simple_premium_kpi
from app.web.view_modules.formatting import _last_sync_label, _marketplace_label, _rub, _sync_status, data_quality_hint
from app.web.view_modules.forms import _filters, _period_select, _select

__all__ = [
    "_dashboard_content",
    "_dashboard_welcome",
    "_analytics_content",
    "_analytics_filters",
]


def _dashboard_content(data: DashboardData) -> str:
    revenue = _metric_by_label(data, "Выручка")
    orders = _metric_by_label(data, "Заказы")
    sales = _metric_by_label(data, "Продажи")
    profit = _metric_by_label(data, "Плановая прибыль")
    returns = _metric_by_label(data, "Возвраты")
    loss = _metric_by_label(data, "Убыточные заказы")
    margin = _metric_by_label(data, "Средняя маржа")
    actual_profit = _metric_by_label(data, "Фактическая прибыль")
    payout = _metric_by_label(data, "К выплате")
    buyout_rate = _conversion_label(orders, sales)
    return f"""
      <section class="analytics-control">
        {_filters(data)}
      </section>
      <section class="premium-kpi-grid">
        {_premium_kpi(revenue, "Выручка")}
        {_premium_kpi(orders, "Заказы")}
        {_premium_kpi(sales, "Продажи (выкупы)")}
        {_premium_kpi(payout, "К выплате")}
        {_premium_kpi(profit, "Плановая прибыль")}
        {_premium_kpi(actual_profit, "Факт. прибыль")}
        {_premium_kpi(margin, "Средняя маржа")}
        {_simple_premium_kpi("Выкуп", buyout_rate, "Конверсия заказ → выкуп")}
        {_premium_kpi(returns, "Возвраты")}
        {_premium_kpi(loss, "Убыточные заказы")}
      </section>
      <section class="premium-grid">
        <section class="premium-section">
          <div class="section-head">
            <div>
              <h2>Динамика выручки</h2>
              <p class="muted">Выручка по дням за выбранный период</p>
            </div>
            <a class="button" href="/web/analytics">Аналитика</a>
          </div>
          {_area_chart(data.points, "revenue", "Выручка по дням", "#2563eb")}
        </section>
        <section class="premium-section">
          <div class="section-head">
            <div>
              <h2>Что требует внимания</h2>
              <p class="muted">Критичные сигналы за период</p>
            </div>
          </div>
          {_attention_list(data)}
        </section>
      </section>
      <section class="premium-grid">
        <section class="premium-section">
          <div class="section-head">
            <div>
              <h2>Заказы и выкупы</h2>
              <p class="muted">Операционная динамика по дням</p>
            </div>
          </div>
          {_grouped_bar_chart(data.points)}
        </section>
        <section class="premium-section">
          <div class="section-head">
            <div>
              <h2>Wildberries / Ozon</h2>
              <p class="muted">Распределение по маркетплейсам</p>
            </div>
          </div>
          {_marketplace_compare(data)}
        </section>
      </section>
      <section class="premium-grid">
        <section class="premium-section">
          <div class="section-head">
            <div>
              <h2>Последние события</h2>
              <p class="muted">Новые заказы, отмены и возвраты</p>
            </div>
            <a class="button" href="/web/orders">Все заказы</a>
          </div>
          {_recent_events(data.recent_events, data.filters.timezone)}
        </section>
        <section class="premium-section">
          <div class="section-head">
            <div>
              <h2>Быстрые действия</h2>
              <p class="muted">Переходы к ключевым разделам</p>
            </div>
          </div>
          {_quick_actions()}
        </section>
      </section>
    """

def _dashboard_welcome(
    user: User,
    subscription: SubscriptionPageData,
    accounts: AccountsPageData,
    data: DashboardData,
) -> str:
    active = subscription.active_subscription
    expires = (
        format_datetime_for_user(active.expires_at, user.timezone, "%d.%m.%Y")
        if active and active.expires_at
        else "бессрочно"
    )
    return f"""
      <section class="premium-hero">
        <div class="hero-content">
          <span class="hero-eyebrow">Центр управления</span>
          <h2>Добро пожаловать, {escape(user.first_name or user.username or "селлер")}</h2>
          <p class="hero-lead">
            Wildberries и Ozon, заказы, выкупы, прибыль и контроль — всё в одном экране.
            Используйте фильтры для анализа по периодам, маркетплейсам и моделям продаж.
          </p>
          <div class="summary-strip">
            <span><strong>{escape(_period_label(data.filters))}</strong> период</span>
            <span><strong>{escape(_sync_status(accounts))}</strong> синхронизация</span>
            <span><strong>{accounts.active_accounts}</strong> кабинетов</span>
            <span><strong>{data_quality_hint(accounts.active_accounts)}</strong> статус</span>
          </div>
        </div>
        <div class="hero-panel">
          <div class="hero-stat"><span>Последняя синхронизация</span><strong>{escape(_last_sync_label(accounts, user.timezone))}</strong></div>
          <div class="hero-stat"><span>Тариф</span><strong>{escape(subscription.tier.name)} до {escape(expires)}</strong></div>
          <div class="hero-stat"><span>Кабинеты МП</span><strong>{accounts.active_accounts} из {subscription.tier.max_marketplace_accounts}</strong></div>
          <div class="page-actions">
            <a class="button primary" href="/web/analytics">Аналитика</a>
            <a class="button" href="/web/settings?tab=marketplaces">Кабинеты</a>
          </div>
        </div>
      </section>
    """

def _analytics_content(data: DashboardData, profit: ProfitPageData) -> str:
    top_rows = (
        "".join(
            "<tr>"
            f'<td>{escape(row.title)}<div class="muted">{escape(row.seller_article)}</div></td>'
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f'<td class="num">{_rub(row.revenue)}</td>'
            f'<td class="num">{_rub(row.estimated_profit)}</td>'
            f'<td class="num">{row.margin_percent.quantize(Decimal("0.1"))}%</td>'
            "</tr>"
            for row in profit.rows[:8]
        )
        or '<tr><td colspan="5"><div class="empty-state">Недостаточно данных для топа товаров за выбранный период.</div></td></tr>'
    )
    sales = _metric_by_label(data, "Продажи")
    orders = _metric_by_label(data, "Заказы")
    conversion = _conversion_label(orders, sales)
    return f"""
      <section class="premium-hero">
        <div class="hero-content">
          <span class="hero-eyebrow">Аналитика продаж</span>
          <h2>Управленческая картина за {_period_label(data.filters)}</h2>
          <p class="hero-lead">
            Смотрите динамику выручки, заказов, выкупов и прибыльности по Wildberries / Ozon
            в одном рабочем модуле. Фильтры ниже меняют весь экран без перехода в другие разделы.
          </p>
          <div class="summary-strip">
            <span><strong>{_period_range(data.filters)}</strong> период</span>
            <span><strong>{_filter_summary(data.filters)}</strong> срез</span>
            <span><strong>{conversion}</strong> заказ → выкуп</span>
          </div>
        </div>
        <div class="hero-panel">
          <div class="hero-stat"><span>Выручка</span><strong>{_metric_value(data, "Выручка")}</strong></div>
          <div class="hero-stat"><span>Плановая прибыль</span><strong>{_metric_value(data, "Плановая прибыль")}</strong></div>
          <div class="hero-stat"><span>Фактическая прибыль</span><strong>{_rub(data.actual_profit)}</strong></div>
        </div>
      </section>
      <section class="analytics-shell">
        <div class="analytics-control">
          {_analytics_filters(data.filters)}
        </div>
        <section class="premium-kpi-grid">
          {_premium_kpi(_metric_by_label(data, "Выручка"), "Выручка за период")}
          {_premium_kpi(_metric_by_label(data, "Заказы"), "Заказы")}
          {_premium_kpi(_metric_by_label(data, "Продажи"), "Выкупы")}
          {_premium_kpi(_metric_by_label(data, "Возвраты"), "Возвраты")}
          {_premium_kpi(_metric_by_label(data, "Плановая прибыль"), "Плановая прибыль")}
          {_premium_kpi(_metric_by_label(data, "Средняя маржа"), "Средняя маржа")}
          {_simple_premium_kpi("Конверсия в выкуп", conversion, "Доля выкупов от заказов")}
          {_premium_kpi(_metric_by_label(data, "Убыточные заказы"), "Убыточные заказы")}
        </section>
        <section class="premium-section">
          <div class="section-head">
            <div>
              <h2>Главный график периода</h2>
              <p class="muted">Динамика выручки по дням. Используйте фильтр маркетплейса, чтобы сравнивать WB и Ozon отдельно.</p>
            </div>
            <span class="badge action">Выручка</span>
          </div>
          {_area_chart(data.points, "revenue", "Выручка по дням", "#2563eb")}
        </section>
        <section class="premium-grid">
          <section class="premium-section">
            <div class="section-head">
              <div>
                <h2>Сравнение WB и Ozon</h2>
                <p class="muted">Вклад площадок в выручку, заказы и выкупы.</p>
              </div>
            </div>
            {_marketplace_compare(data)}
          </section>
          <section class="premium-section">
            <div class="section-head">
              <div>
                <h2>Заказы и выкупы</h2>
                <p class="muted">Операционная динамика без лишних деталей.</p>
              </div>
            </div>
            {_grouped_bar_chart(data.points)}
          </section>
        </section>
        <section class="premium-section">
          <div class="section-head">
            <div>
              <h2>Товары-лидеры</h2>
              <p class="muted">SKU с наибольшей выручкой и вкладом в прибыльность.</p>
            </div>
            <a class="button" href="/web/profit">Вся прибыль</a>
          </div>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>Товар</th><th>МП</th><th class="num">Выручка</th><th class="num">Прибыль</th><th class="num">Маржа</th></tr></thead>
            <tbody>{top_rows}</tbody>
          </table></div>
        </section>
      </section>
    """

def _analytics_filters(filters: DashboardFilters) -> str:
    selected_marketplace = filters.marketplace.value if filters.marketplace else "all"
    selected_sale_model = filters.sale_model.value if filters.sale_model else "all"
    return f"""
      <form class="filters" method="get" action="/web/analytics">
        {_period_select(filters.period)}
        {_select("marketplace", "Маркетплейс", {"all": "Все", Marketplace.WB.value: "Wildberries", Marketplace.OZON.value: "Ozon"}, selected_marketplace)}
        {_select("sale_model", "Модель", {"all": "Все", "FBO": "FBO", "FBS": "FBS", "rFBS": "rFBS"}, selected_sale_model)}
        <div><label for="date_from">Дата с</label><input id="date_from" name="date_from" type="date" value="{filters.local_date_from.isoformat()}"></div>
        <div><label for="date_to">Дата по</label><input id="date_to" name="date_to" type="date" value="{filters.local_date_to.isoformat()}"></div>
        <button class="button primary" type="submit">Применить</button>
      </form>
    """
