"""HTML rendering helpers and form/query utilities for the web cabinet."""

# ruff: noqa: E501, F401

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

__all__ = [
    "_placeholder_page",
    "_orders_content",
    "_order_detail_content",
    "_plan_fact_content",
    "_plan_fact_plan_panel",
    "_plan_progress",
    "_decimal_or_none",
    "_break_even_content",
    "_products_content",
    "_master_product_detail_content",
    "_product_matching_content",
    "_stocks_forecast_content",
    "_filter_stock_rows",
    "_stock_filters",
    "_alerts_content",
    "_sales_content",
    "_returns_content",
    "_costs_content",
    "_cost_edit_content",
    "_accounts_content",
    "_sync_detail_cell",
    "_sync_actions",
    "_seller_name_hint",
    "_seller_profile_web",
    "_wb_reports_web",
    "_report_short",
    "_ozon_price_label",
    "_subscription_content",
    "_profile_content",
    "_analytics_content",
    "_analytics_filters",
    "_control_content",
    "_settings_content",
    "_data_quality_content",
    "_profit_content",
    "_section_subnav",
    "_dashboard_content",
    "_dashboard_welcome",
    "_filters",
    "_orders_filters",
    "_profit_filters",
    "_plan_fact_filters",
    "_shared_order_filters",
    "_select",
    "_period_select",
    "_page_header",
    "_sales_returns_filters",
    "_web_tier_card",
    "_account_status_badge",
    "_cost_status_badge",
    "_limit",
    "_dt",
    "_user_display_name",
    "_form_value",
    "_datetime_from_form",
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
    "_rub",
    "_rub_optional",
    "_percent_optional",
    "_marketplace_label",
    "_sale_model_badge",
    "_order_status_badge",
    "_confidence_badge",
    "_parse_int_list",
    "_optional_int",
    "_optional_decimal",
    "_plan_marketplace",
    "_mask_token",
    "_request_path",
    "_urlencoded_form",
    "_query_param",
    "_optional_query_param",
    "_decimal_from_query",
    "_last_sync_label",
    "_sync_status",
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


def _orders_content(
    result: Any, timezone: str, *, last_poll_info: dict[str, object] | None = None
) -> str:
    from app.services.web_orders_profit_service import OrderPageResult

    if isinstance(result, OrderPageResult):
        page_result = result
        rows = page_result.rows
        filters = page_result.filters
        total_count = page_result.total_count
        page = page_result.page
        per_page = page_result.per_page
        total_pages = page_result.total_pages
    else:
        filters, rows = result
        total_count = len(rows)
        page = 1
        per_page = 100
        total_pages = 1

    table_rows = []
    for row in rows:
        profit = row.estimated_profit
        profit_badge = "bad" if profit is not None and profit < 0 else "good"
        cost_badge = '<span class="badge warn">без себестоимости</span>' if row.missing_cost else ""
        confidence_badge = _confidence_badge(row.economy_confidence)
        profit_cell = (
            f'<td class="num"><span class="badge {profit_badge}">'
            f"{_rub_optional(profit)}</span></td>"
        )
        table_rows.append(
            "<tr>"
            f"<td>{localized_order_date(row.order_date, timezone)}</td>"
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f"<td>{_sale_model_badge(row.sale_model)}</td>"
            f'<td><a href="/web/orders/{row.order_id}">{escape(row.title)}</a>'
            f'<div class="muted">{escape(row.seller_article)}</div>{cost_badge}</td>'
            f"<td>{escape(row.order_external_id)}"
            f'<div class="muted">{escape(row.posting_number or "")}</div></td>'
            f'<td class="num">{row.quantity}</td>'
            f'<td class="num">{_rub(row.revenue)}</td>'
            f"{profit_cell}"
            f'<td class="num">{_percent_optional(row.margin_percent)}</td>'
            f"<td>{_order_status_badge(row.status, row.requires_action)}<div>{confidence_badge}</div></td>"
            f"<td>{escape(source_event_label(row.source_event_type))}</td>"
            "</tr>"
        )
    body = (
        "".join(table_rows)
        if table_rows
        else '<tr><td colspan="11" class="muted">Заказов по выбранным фильтрам пока нет.</td></tr>'
    )

    range_start = (page - 1) * per_page + 1 if total_count > 0 else 0
    range_end = min(page * per_page, total_count)
    range_text = (
        f"Показано {range_start}–{range_end} из {total_count}" if total_count > 0 else "Нет заказов"
    )

    pagination_html = _render_pagination(filters, page, total_pages, per_page, total_count)

    sync_badge = _render_sync_freshness(last_poll_info, timezone) if last_poll_info else ""

    return f"""
      {_section_subnav("orders")}
      {_orders_filters(filters)}
      {sync_badge}
      <section class="band">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
          <h2 style="margin:0">Заказы и позиции</h2>
          <div class="muted" style="font-size:13px">{range_text}</div>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Дата</th><th>МП</th><th>Модель</th><th>Товар</th>
                <th>Заказ / отправление</th><th class="num">Кол-во</th>
                <th class="num">Цена</th><th class="num">Плановая прибыль</th>
                <th class="num">Маржа</th><th>Статус</th><th>Источник</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
        {pagination_html}
      </section>
    """


def _order_detail_content(detail: OrderDetail, timezone: str) -> str:
    order = detail.order
    item_rows = []
    for item_detail in detail.items:
        item = item_detail.item
        estimated = item_detail.estimated_snapshot
        actual = item_detail.actual_snapshot
        estimated_profit = estimated.profit if estimated else item.profit_estimated
        actual_profit = actual.profit if actual else None
        confidence = (
            estimated.economy_confidence
            if estimated and estimated.economy_confidence
            else item.economy_confidence
        )
        item_rows.append(
            "<tr>"
            f"<td>{escape(item.title or 'Без названия')}"
            f'<div class="muted">{escape(item.seller_article or "н/д")}</div></td>'
            f'<td class="num">{item.quantity}</td>'
            f'<td class="num">{_rub(item.discounted_price * item.quantity)}</td>'
            f'<td class="num">{_rub_optional(item.commission_estimated)}</td>'
            f'<td class="num">{_rub_optional(item.logistics_estimated)}</td>'
            f'<td class="num">{_rub_optional(item.cost_price_used)}</td>'
            f'<td class="num">{_rub_optional(item.package_cost_used)}</td>'
            f'<td class="num">{_rub_optional(item.tax_amount_estimated)}</td>'
            f'<td class="num">{_rub_optional(estimated_profit)}</td>'
            f'<td class="num">{_rub_optional(actual_profit)}</td>'
            f"<td>{_confidence_badge(confidence)}</td>"
            "</tr>"
        )
    raw_payload = escape(json.dumps(order.raw_payload or {}, ensure_ascii=False, indent=2))
    deadline = (
        localized_order_date(order.processing_deadline_at, timezone)
        if order.processing_deadline_at
        else "н/д"
    )
    sale_model = _sale_model_badge(order.sale_model)
    order_date = localized_order_date(order.order_date, timezone)
    order_state = escape(order_state_label(order.normalized_status, order.requires_seller_action))
    return f"""
      {_section_subnav("orders")}
      <section class="detail-grid">
        <section class="band">
          <h2>Информация</h2>
          <div class="kv">
            <span>Маркетплейс</span><strong>{_marketplace_label(order.marketplace)}</strong>
            <span>Модель</span><strong>{sale_model}</strong>
            <span>Статус</span><strong>{_order_status_badge(order.normalized_status or order.status, order.requires_seller_action)}</strong>
            <span>Дата заказа</span><strong>{order_date}</strong>
            <span>Дедлайн</span><strong>{deadline}</strong>
            <span>Заказ</span><strong>{escape(order.order_external_id)}</strong>
            <span>Действие</span><strong>{order_state}</strong>
          </div>
        </section>
        <section class="band">
          <h2>План / факт</h2>
          <div class="kv">
            <span>Плановая прибыль</span><strong>{_rub(detail.estimated_profit)}</strong>
            <span>Фактическая прибыль</span><strong>{_rub_optional(detail.actual_profit)}</strong>
            <span>Отклонение</span><strong>{_rub_optional(detail.deviation)}</strong>
          </div>
          <p class="muted">
            Если фактическая прибыль отсутствует, финансовые отчёты маркетплейса
            ещё не сопоставлены с заказом.
          </p>
        </section>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Экономика позиций</h2>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th class="num">Кол-во</th><th class="num">Цена</th>
                <th class="num">Комиссия</th><th class="num">Логистика</th>
                <th class="num">Себестоимость</th><th class="num">Упаковка</th>
                <th class="num">Налог</th><th class="num">План</th><th class="num">Факт</th>
                <th>Достоверность</th>
              </tr>
            </thead>
            <tbody>{"".join(item_rows)}</tbody>
          </table>
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Исходные данные</h2>
        <pre class="mono">{raw_payload}</pre>
      </section>
    """


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


def _products_content(rows: list[MasterProductAnalyticsRow]) -> str:
    row_html = []
    for row in rows:
        marketplace_badges = (
            f'<span class="badge wb">WB: {row.wb_products}</span> '
            f'<span class="badge ozon">Ozon: {row.ozon_products}</span>'
        )
        linked_products = "".join(
            '<div class="muted">'
            f"{_marketplace_label(item.marketplace)}: "
            f"{escape(item.seller_article)} / {escape(item.marketplace_article)}"
            f' · <a href="/web/costs/{item.product_id}">себестоимость</a>'
            "</div>"
            for item in row.marketplace_products
        )
        image = (
            f'<img src="{escape(row.image_url)}" alt="{escape(row.title)}" '
            'style="width:48px;height:48px;object-fit:cover;border-radius:6px;margin-right:10px" '
            "onerror=\"this.style.display='none'\">"
            if row.image_url
            else '<div class="product-thumb">нет фото</div>'
        )
        title_cell = (
            '<div style="display:flex;align-items:center;gap:10px">'
            f'{image}<div><strong><a href="/web/products/{row.master_product_id}">'
            f"{escape(row.title)}</a></strong>"
            f'<div class="muted">{escape(row.brand)} · {escape(row.category)}</div>'
            f"{linked_products}</div></div>"
        )
        profit_badge = "bad" if row.estimated_profit < 0 else "good"
        row_html.append(
            "<tr>"
            f"<td>{title_cell}</td>"
            f"<td>{escape(row.canonical_sku)}</td>"
            f"<td>{marketplace_badges}</td>"
            f'<td class="num">{row.orders}</td>'
            f'<td class="num">{row.sales}</td>'
            f'<td class="num">{_rub(row.revenue)}</td>'
            f'<td class="num"><span class="badge {profit_badge}">'
            f"{_rub(row.estimated_profit)}</span></td>"
            f'<td class="num">{row.stock_quantity}</td>'
            "</tr>"
        )
    body = (
        "".join(row_html)
        if row_html
        else (
            '<tr><td colspan="8" class="muted">'
            "Товары пока не импортированы. Подключите кабинет или запустите "
            "синхронизацию.</td></tr>"
        )
    )
    return f"""
      {_section_subnav("products")}
      <section class="band">
        <h2>Единые карточки товаров</h2>
        <p class="muted">
          Товары WB и Ozon сопоставляются по артикулу продавца. Это база для сравнения
          площадок, общей прибыли и карточки MasterProduct.
        </p>
        <p><a class="button" href="/web/product-matching">Сопоставление товаров</a></p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th>Единый SKU</th><th>Площадки</th>
                <th class="num">Заказов</th><th class="num">Выкупов</th>
                <th class="num">Выручка</th><th class="num">Плановая прибыль</th>
                <th class="num">Остаток</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """


def _master_product_detail_content(detail: MasterProductDetail) -> str:
    product_rows = "".join(
        "<tr>"
        f"<td>{_marketplace_label(item.marketplace)}</td>"
        f"<td>{escape(item.seller_article)}</td>"
        f"<td>{escape(item.marketplace_article)}</td>"
        f"<td>{escape(item.title)}</td>"
        f"<td>{escape(item.brand)}</td>"
        f'<td><a class="button" href="/web/costs/{item.product_id}">Себестоимость</a></td>'
        "</tr>"
        for item in detail.marketplace_products
    )
    comparison_rows = "".join(
        "<tr>"
        f"<td>{_marketplace_label(row.marketplace)}</td>"
        f'<td class="num">{row.orders}</td>'
        f'<td class="num">{row.sales}</td>'
        f'<td class="num">{_rub(row.revenue)}</td>'
        f'<td class="num">{_rub(row.estimated_profit)}</td>'
        f'<td class="num">{_rub(row.actual_profit)}</td>'
        f'<td class="num">{_percent_optional(row.margin_percent)}</td>'
        f'<td class="num">{row.stock_quantity}</td>'
        "</tr>"
        for row in detail.marketplace_comparison
    )
    recommendations = "".join(f"<li>{escape(item)}</li>" for item in detail.recommendations)
    image = (
        f'<img src="{escape(detail.image_url)}" alt="{escape(detail.title)}" '
        'style="width:96px;height:96px;object-fit:cover;border-radius:6px" '
        "onerror=\"this.style.display='none'\">"
        if detail.image_url
        else '<div class="product-thumb">нет фото</div>'
    )
    return f"""
      {_section_subnav("products")}
      <section class="band">
        <div style="display:flex;align-items:center;gap:14px">
          {image}
          <div>
            <h2>{escape(detail.title)}</h2>
            <p class="muted">{escape(detail.brand)} · {escape(detail.category)}</p>
            <p class="muted">Единый SKU: {escape(detail.canonical_sku)}</p>
          </div>
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Сравнение WB / Ozon</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>МП</th><th class="num">Заказов</th><th class="num">Выкупов</th>
            <th class="num">Выручка</th><th class="num">План</th><th class="num">Факт</th>
            <th class="num">Маржа</th><th class="num">Остаток</th></tr></thead>
            <tbody>{comparison_rows}</tbody>
          </table>
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Что важно</h2>
        <ul>{recommendations}</ul>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Связанные карточки</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>МП</th><th>Артикул продавца</th><th>Артикул МП</th>
          <th>Название</th><th>Бренд</th><th>Действие</th></tr></thead>
          <tbody>{product_rows}</tbody>
        </table></div>
      </section>
    """


def _product_matching_content(candidates: list[ProductMatchingCandidate]) -> str:
    rows = "".join(
        "<tr>"
        f'<td><input type="checkbox" name="product_ids" value="{item.product_id}"></td>'
        f"<td>{_marketplace_label(item.marketplace)}</td>"
        f"<td>{escape(item.seller_article)}</td>"
        f"<td>{escape(item.marketplace_article)}</td>"
        f"<td>{escape(item.title)}</td>"
        f"<td>{escape(item.current_group or 'нет группы')}</td>"
        f'<td><form method="post" action="/web/product-matching/unlink">'
        f'<input type="hidden" name="product_id" value="{item.product_id}">'
        '<button class="button" type="submit">Исключить</button></form></td>'
        "</tr>"
        for item in candidates
    )
    if not rows:
        rows = (
            '<tr><td colspan="7" class="muted">Товары для сопоставления пока не найдены.</td></tr>'
        )
    return f"""
      {_section_subnav("products")}
      <section class="band">
        <h2>Сопоставление товаров</h2>
        <p class="muted">
          Отметьте карточки WB/Ozon одного товара и создайте ручную группу. Ручная связь
          имеет приоритет над автоматическим сопоставлением по артикулу.
        </p>
        <form method="post" action="/web/product-matching/create">
          <div class="table-wrap"><table class="table">
            <thead><tr><th></th><th>МП</th><th>Артикул продавца</th><th>Артикул МП</th>
            <th>Название</th><th>Группа</th><th>Действие</th></tr></thead>
            <tbody>{rows}</tbody>
          </table></div>
          <button class="button primary" type="submit">Создать ручную MasterProduct-группу</button>
        </form>
      </section>
    """


def _stocks_forecast_content(
    rows: list[StockForecastRow],
    *,
    marketplace: str = "all",
    sale_model: str = "all",
    stock_status: str = "all",
) -> str:
    body_rows = []
    critical_count = 0
    warning_count = 0
    out_count = 0
    common_fbs_count = 0
    total_quantity = 0
    for row in rows:
        total_quantity += row.quantity
        common_fbs_count += int(row.is_common_fbs)
        if row.status == "out_of_stock":
            out_count += 1
        elif row.status == "critical":
            critical_count += 1
        elif row.status == "warning":
            warning_count += 1
        days_until_stockout = (
            str(row.days_until_stockout) if row.days_until_stockout is not None else "н/д"
        )
        marketplace_cell = (
            '<span class="marketplace-badge neutral"><span class="mp-logo">FBS</span>Общий FBS</span>'
            if row.is_common_fbs
            else _marketplace_label(row.marketplace)
        )
        status = stock_status_label(row.status)
        tone = stock_status_tone(row.status)
        body_rows.append(
            "<tr>"
            f'<td>{escape(row.title)}<div class="muted">{escape(row.seller_article)}</div></td>'
            f"<td>{marketplace_cell}</td>"
            f"<td>{_sale_model_badge(row.sale_model)}</td>"
            f"<td>{escape(row.warehouse)}</td>"
            f'<td class="num">{row.quantity}</td>'
            f'<td class="num">{row.average_daily_sales}</td>'
            f'<td class="num">{days_until_stockout}</td>'
            f'<td class="num">{_rub(row.lost_revenue_30d)}</td>'
            f'<td><span class="badge {tone}">{escape(status)}</span></td>'
            f"<td>{escape(row.recommendation)}</td>"
            "</tr>"
        )
    body = "".join(body_rows)
    if not body:
        body = (
            '<tr><td colspan="10"><div class="empty-state">'
            "Остатков пока нет. Запустите синхронизацию или дождитесь фоновой загрузки складов."
            "</div></td></tr>"
        )
    return f"""
      {_section_subnav("stocks")}
      {_stock_filters(marketplace, sale_model, stock_status)}
      <section class="kpi-grid">
        {_simple_kpi("Всего позиций", str(len(rows)))}
        {_simple_kpi("Суммарный остаток", str(total_quantity))}
        {_simple_kpi("Нет в наличии", str(out_count), "bad" if out_count else "neutral")}
        {_simple_kpi("Низкий остаток", str(critical_count + warning_count), "warn" if critical_count + warning_count else "neutral")}
        {_simple_kpi("Общий FBS", str(common_fbs_count), "action" if common_fbs_count else "neutral")}
      </section>
      <section class="band">
        <h2>Остатки, out-of-stock и потери выручки</h2>
        <p class="muted">
          Прогноз: текущий остаток делится на среднедневные выкупы за 30 дней.
          Упущенная выручка оценивается на горизонте 30 дней после даты возможного stockout.
        </p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th>МП</th><th>Модель</th><th>Склад</th><th class="num">Остаток</th>
                <th class="num">Продаж/день</th><th class="num">Дней запаса</th>
                <th class="num">Потери 30д</th><th>Статус</th><th>Рекомендация</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """


def _filter_stock_rows(
    rows: list[StockForecastRow],
    marketplace: str,
    sale_model: str,
    stock_status: str,
) -> list[StockForecastRow]:
    filtered = rows
    if marketplace in {Marketplace.WB.value, Marketplace.OZON.value}:
        parsed = Marketplace(marketplace)
        filtered = [
            row
            for row in filtered
            if row.marketplace == parsed or (row.is_common_fbs and sale_model in {"all", "FBS"})
        ]
    if sale_model in {"FBO", "FBS"}:
        filtered = [row for row in filtered if row.sale_model == sale_model]
    if stock_status == "out":
        filtered = [row for row in filtered if row.status == "out_of_stock"]
    elif stock_status == "low":
        filtered = [row for row in filtered if row.status in {"critical", "warning"}]
    return filtered


def _stock_filters(marketplace: str, sale_model: str, stock_status: str) -> str:
    return f"""
      <form class="filters" method="get" action="/web/stocks">
        {_select("marketplace", "Маркетплейс", {"all": "Все", Marketplace.WB.value: "Wildberries", Marketplace.OZON.value: "Ozon"}, marketplace)}
        {_select("sale_model", "Модель остатков", {"all": "Все", "FBO": "FBO", "FBS": "FBS"}, sale_model)}
        {_select("stock_status", "Состояние", {"all": "Все", "out": "Нет в наличии", "low": "Низкий остаток"}, stock_status)}
        <button class="button primary" type="submit">Показать</button>
      </form>
    """


def _alerts_content(events: list[AlertEvent], timezone: str = "Europe/Moscow") -> str:
    pending = sum(1 for event in events if not event.sent_at)
    sent = len(events) - pending
    critical = sum(
        1
        for event in events
        if event.alert_type.value in {"LOSS_ORDER", "LOW_STOCK", "STOCKOUT_FORECAST"}
    )
    body = "".join(
        "<tr>"
        f"<td>{escape(_dt(event.created_at, timezone))}</td>"
        f"<td>{_alert_type_badge(event.alert_type.value)}</td>"
        f"<td>{escape(event.title)}</td>"
        f"<td>{escape(event.message)}</td>"
        f"<td>{_alert_delivery_badge(event.sent_at is not None)}</td>"
        "</tr>"
        for event in events
    )
    if not body:
        body = '<tr><td colspan="5"><div class="empty-state">Активных алертов пока нет. Всё спокойно.</div></td></tr>'
    return f"""
      {_section_subnav("alerts")}
      <section class="kpi-grid">
        {_simple_kpi("Всего алертов", str(len(events)))}
        {_simple_kpi("Новые", str(pending), "action" if pending else "neutral")}
        {_simple_kpi("Критичные", str(critical), "bad" if critical else "neutral")}
        {_simple_kpi("Отправлены", str(sent), "good" if sent else "neutral")}
      </section>
      <section class="band">
        <h2>Расширенные алерты</h2>
        <p class="muted">
          Здесь отображаются события по низкой марже, убыточным заказам, FBS-дедлайнам,
          остаткам, out-of-stock и качеству синхронизации.
        </p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>Дата</th><th>Тип</th><th>Заголовок</th><th>Сообщение</th><th>Статус</th></tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """


def _sales_content(data: SalesPageData, timezone: str, sku: str) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{localized_order_date(row.event_date, timezone)}</td>"
        f"<td>{_marketplace_label(row.marketplace)}</td>"
        f"<td>{escape(row.event_type)}</td>"
        f"<td>{escape(row.seller_article)}"
        f'<div class="muted">{escape(row.marketplace_article)}</div></td>'
        f'<td class="num">{row.quantity}</td>'
        f'<td class="num">{_rub(row.amount)}</td>'
        f'<td class="num">{_rub_optional(row.expected_payout)}</td>'
        f'<td class="num">{_rub_optional(row.estimated_profit)}</td>'
        f'<td class="num">{_rub_optional(row.actual_profit)}</td>'
        f"<td>{escape(row.order_external_id or 'н/д')}</td>"
        "</tr>"
        for row in data.rows
    )
    if not rows:
        rows = (
            '<tr><td colspan="10"><div class="empty-state">'
            "Продаж за выбранный период пока нет. Дождитесь синхронизации выкупов WB/Ozon."
            "</div></td></tr>"
        )
    return f"""
      {_page_header("Продажи", "Отслеживайте выкупы и завершённые продажи WB/Ozon.", "/web/orders", "Заказы")}
      {_sales_returns_filters("/web/sales", data.filters, sku)}
      <section class="kpi-grid">
        {_simple_kpi("Продаж", str(data.total_quantity))}
        {_simple_kpi("Выручка", _rub(data.total_amount))}
        {_simple_kpi("Плановая прибыль", _rub(data.total_profit), "good" if data.total_profit >= 0 else "bad")}
        {_simple_kpi("Средний чек", _rub(data.total_amount / Decimal(data.total_quantity) if data.total_quantity else ZERO))}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>События продаж</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Дата</th><th>МП</th><th>Тип</th><th>Товар</th>
          <th class="num">Кол-во</th><th class="num">Сумма</th><th class="num">Выплата</th>
          <th class="num">План</th><th class="num">Факт</th><th>Заказ</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
    """


def _returns_content(data: ReturnsPageData, timezone: str, sku: str) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{localized_order_date(row.event_date, timezone)}</td>"
        f"<td>{_marketplace_label(row.marketplace)}</td>"
        f"<td>{escape(row.order_external_id or 'н/д')}</td>"
        f'<td class="num">{row.quantity}</td>'
        f'<td class="num">{_rub(row.amount)}</td>'
        f"<td>{escape(row.reason)}</td>"
        "</tr>"
        for row in data.rows
    )
    if not rows:
        rows = (
            '<tr><td colspan="6"><div class="empty-state">'
            "Возвратов за выбранный период нет. Это хороший знак для контроля качества продаж."
            "</div></td></tr>"
        )
    return f"""
      {_page_header("Возвраты", "Контролируйте возвраты, суммы и причины по маркетплейсам.", "/web/sales", "Продажи")}
      {_sales_returns_filters("/web/returns", data.filters, sku)}
      <section class="kpi-grid">
        {_simple_kpi("Возвратов", str(data.total_quantity), "bad" if data.total_quantity else "neutral")}
        {_simple_kpi("Сумма возвратов", _rub(data.total_amount), "bad" if data.total_amount else "neutral")}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>События возвратов</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Дата</th><th>МП</th><th>Связанный заказ</th>
          <th class="num">Кол-во</th><th class="num">Сумма</th><th>Причина</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
    """


def _costs_content(data: CostsPageData, timezone: str = "Europe/Moscow") -> str:
    rows = "".join(
        "<tr>"
        f"<td>{escape(row.product.title or 'Без названия')}"
        f'<div class="muted">{escape(row.product.seller_article or "н/д")}</div></td>'
        f"<td>{_marketplace_label(row.product.marketplace)}"
        f'<div class="muted">{escape(row.account_name)}</div></td>'
        f'<td class="num">{_rub(row.cost.cost_price) if row.cost else "не задана"}</td>'
        f'<td class="num">{_rub(row.cost.package_cost) if row.cost else "н/д"}</td>'
        f'<td class="num">{_rub(row.cost.additional_cost) if row.cost else "н/д"}</td>'
        f'<td class="num">{(row.cost.tax_rate * Decimal("100")).quantize(Decimal("0.01")) if row.cost else "н/д"}%</td>'
        f"<td>{format_datetime_for_user(row.cost.valid_from, timezone, '%d.%m.%Y') if row.cost else 'н/д'}</td>"
        f"<td>{_cost_status_badge(row.cost is not None and row.cost.cost_price > 0)}</td>"
        f'<td><a class="button" href="/web/costs/{row.product.id}">Редактировать</a></td>'
        "</tr>"
        for row in data.rows
    )
    if not rows:
        rows = (
            '<tr><td colspan="10"><div class="empty-state">'
            "Товары ещё не синхронизированы. Подключите кабинет в Telegram-боте и дождитесь загрузки."
            "</div></td></tr>"
        )
    return f"""
      {_page_header("Себестоимость", "Контролируйте себестоимость, упаковку, доп. расходы и налог по товарам.", "/web/products", "Товары")}
      <section class="kpi-grid">
        {_simple_kpi("Себестоимость задана", str(data.configured_count), "good")}
        {_simple_kpi("Без себестоимости", str(data.missing_count), "warn" if data.missing_count else "neutral")}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Товары и текущая себестоимость</h2>
        <p class="muted">Новая запись создаётся исторически: предыдущий период закрывается датой начала новой себестоимости.</p>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Товар</th><th>Кабинет</th><th class="num">Себестоимость</th>
          <th class="num">Упаковка</th><th class="num">Доп. расходы</th><th class="num">Налог</th>
          <th>Обновлено</th><th>Статус</th><th>Действие</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
    """


def _cost_edit_content(detail: ProductCostDetail, timezone: str = "Europe/Moscow") -> str:
    latest = detail.history[0] if detail.history else None
    history = (
        "".join(
            "<tr>"
            f"<td>{format_datetime_for_user(row.valid_from, timezone, '%d.%m.%Y')}</td>"
            f"<td>{format_datetime_for_user(row.valid_to, timezone, '%d.%m.%Y') if row.valid_to else 'сейчас'}</td>"
            f'<td class="num">{_rub(row.cost_price)}</td>'
            f'<td class="num">{_rub(row.package_cost)}</td>'
            f'<td class="num">{_rub(row.additional_cost)}</td>'
            f'<td class="num">{(row.tax_rate * Decimal("100")).quantize(Decimal("0.01"))}%</td>'
            f"<td>{escape(row.comment or '')}</td>"
            "</tr>"
            for row in detail.history
        )
        or '<tr><td colspan="7" class="muted">Истории себестоимости пока нет.</td></tr>'
    )
    return f"""
      {_page_header("Редактирование себестоимости", escape(detail.product.title or "Без названия"), "/web/costs", "К списку")}
      <section class="detail-grid">
        <section class="band">
          <h2>Новая себестоимость</h2>
          <form method="post" action="/web/costs/{detail.product.id}">
            <label for="cost_price">Себестоимость</label>
            <input id="cost_price" name="cost_price" type="number" step="0.01" value="{latest.cost_price if latest else 0}">
            <label for="package_cost">Упаковка</label>
            <input id="package_cost" name="package_cost" type="number" step="0.01" value="{latest.package_cost if latest else 0}">
            <label for="additional_cost">Доп. расходы</label>
            <input id="additional_cost" name="additional_cost" type="number" step="0.01" value="{latest.additional_cost if latest else 0}">
            <label for="tax_rate">Налог, %</label>
            <input id="tax_rate" name="tax_rate" type="number" step="0.01" value="{(latest.tax_rate * Decimal("100")).quantize(Decimal("0.01")) if latest else 0}">
            <label for="valid_from">Дата начала действия</label>
            <input id="valid_from" name="valid_from" type="date" value="{datetime.now(tz=get_user_timezone(timezone)).date().isoformat()}">
            <label for="comment">Комментарий</label>
            <input id="comment" name="comment" type="text" value="WEB-обновление">
            <p><button class="button primary" type="submit">Сохранить</button></p>
          </form>
        </section>
        <section class="band">
          <h2>Товар</h2>
          <div class="kv">
            <span>Маркетплейс</span><strong>{_marketplace_label(detail.product.marketplace)}</strong>
            <span>Кабинет</span><strong>{escape(detail.account_name)}</strong>
            <span>Артикул продавца</span><strong>{escape(detail.product.seller_article or "н/д")}</strong>
            <span>Артикул МП</span><strong>{escape(detail.product.marketplace_article or detail.product.external_product_id)}</strong>
            <span>Актуальная цена Ozon</span><strong>{_ozon_price_label(getattr(detail, "latest_ozon_price", None), timezone)}</strong>
          </div>
        </section>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>История себестоимости</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>С</th><th>По</th><th class="num">Себестоимость</th>
          <th class="num">Упаковка</th><th class="num">Доп. расходы</th>
          <th class="num">Налог</th><th>Комментарий</th></tr></thead>
          <tbody>{history}</tbody>
        </table></div>
      </section>
    """


def _accounts_content(data: AccountsPageData, timezone: str = "Europe/Moscow") -> str:
    rows = "".join(
        "<tr>"
        f'<td>{escape(row.account.name)}<div class="muted">#{row.account.id}'
        f"{_seller_name_hint(row.account)}</div></td>"
        f"<td>{_marketplace_label(row.account.marketplace)}</td>"
        f"<td>{_account_status_badge(row.account.status.value, row.account.is_active)}</td>"
        f"<td>{_seller_profile_web(row.account, row.latest_balance)}</td>"
        f"<td>{_wb_reports_web(row.latest_daily_report, row.latest_weekly_report, row.report_states or [])}</td>"
        f"<td>{_sync_detail_cell(row.account, timezone)}</td>"
        f'<td>{_dt(row.account.last_error_at, timezone)}<div class="muted">{escape(row.account.last_error_message or row.latest_job_error or "")}</div></td>'
        f'<td class="num">{row.products_count}</td>'
        f'<td class="num">{row.orders_30d}</td>'
        f"<td>{escape(row.latest_job_status or 'нет задач')}</td>"
        "</tr>"
        for row in data.rows
    )
    if not rows:
        rows = (
            '<tr><td colspan="10"><div class="empty-state">'
            "Кабинеты ещё не подключены. Подключение нового кабинета выполняется через Telegram-бота."
            "</div></td></tr>"
        )
    return f"""
      {_page_header("Кабинеты маркетплейсов", "Проверяйте подключённые кабинеты, статусы синхронизации и ошибки доступа.", "/web/settings?tab=profile", "Профиль")}
      {_sync_actions()}
      <section class="kpi-grid">
        {_simple_kpi("Подключено кабинетов", f"{data.active_accounts} из {data.tier.max_marketplace_accounts}")}
        {_simple_kpi("Тариф", escape(data.tier.name))}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Wildberries и Ozon</h2>
        <p class="muted">Подключение нового кабинета сейчас выполняется через Telegram-бота: откройте настройки и выберите подключение WB или Ozon.</p>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Кабинет</th><th>МП</th><th>Статус</th><th>Продавец и баланс</th>
          <th>Отчёты WB</th><th>Синхронизации</th>
          <th>Последняя ошибка</th><th class="num">Товаров</th><th class="num">Заказов 30д</th><th>Последняя задача</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
    """


def _sync_detail_cell(account: MarketplaceAccount, timezone: str) -> str:
    items = [
        ("Заказы", account.last_orders_sync_at),
        ("Продажи", account.last_sales_sync_at),
        ("Остатки", account.last_stocks_sync_at),
        ("Товары", account.last_products_sync_at),
        ("Профиль", account.last_profile_sync_at),
    ]
    if account.marketplace.value == "ozon":
        items.append(("Ozon каталог", account.last_ozon_enrichment_sync_at))
    if account.marketplace.value == "wb":
        items.append(("Отчёты WB", account.last_wb_reports_sync_at))
    parts = []
    for label, ts in items:
        if ts is None:
            parts.append(f'<div class="muted">{escape(label)}: ещё не запускалась</div>')
        else:
            parts.append(f"<div>{escape(label)}: {_dt(ts, timezone)}</div>")
    return "".join(parts)


def _sync_actions() -> str:
    actions = [
        ("orders", "Заказы"),
        ("sales", "Продажи"),
        ("stocks", "Остатки"),
        ("products", "Товары"),
        ("wb-reports", "Отчёты WB"),
        ("ozon-enrichment", "Ozon каталог"),
        ("ozon-balance", "Баланс Ozon"),
    ]
    buttons = "".join(
        f'<form method="post" action="/web/sync/{key}">'
        f'<button class="button" type="submit">{label}</button></form>'
        for key, label in actions
    )
    return (
        '<section class="band"><h2>Запустить синхронизацию</h2>'
        f'<div class="page-actions">{buttons}</div></section>'
    )


def _seller_name_hint(account: MarketplaceAccount) -> str:
    if not account.seller_name and not account.seller_external_id:
        return ""
    label = account.seller_name or account.seller_external_id or ""
    return f" · продавец: {escape(label)}"


def _seller_profile_web(account: MarketplaceAccount, balance: object | None) -> str:
    payload = account.seller_info_payload or {}
    parts = [
        escape(account.seller_name or account.seller_legal_name or "н/д"),
        f'<div class="muted">ИНН: {escape(str(payload.get("tin") or "н/д"))}</div>',
    ]
    if balance is None:
        parts.append('<div class="muted">Баланс не загружен</div>')
    elif getattr(balance, "status", "") == "OK":
        currency = getattr(balance, "currency", "RUB")
        current = getattr(balance, "current", None)
        if account.marketplace == Marketplace.WB:
            for_withdraw = getattr(balance, "for_withdraw", None)
            parts.append(f'<div class="muted">Баланс: {_rub(current)} {escape(currency)}</div>')
            parts.append(
                f'<div class="muted">К выводу: {_rub(for_withdraw)} {escape(currency)}</div>'
            )
        else:
            parts.append(
                f'<div class="muted">💰 Баланс Ozon: {_rub(current)} {escape(currency)}</div>'
            )
            period_from = getattr(balance, "period_from", None)
            period_to = getattr(balance, "period_to", None)
            if period_from and period_to:
                parts.append(
                    f'<div class="muted">Период: {escape(str(period_from))} — {escape(str(period_to))}</div>'
                )
            accrued = getattr(balance, "accrued", None)
            if accrued is not None:
                parts.append(
                    f'<div class="muted">Начислено: {_rub(accrued)} {escape(currency)}</div>'
                )
            opening = getattr(balance, "opening_balance", None)
            if opening is not None:
                parts.append(
                    f'<div class="muted">На начало периода: {_rub(opening)} {escape(currency)}</div>'
                )
            payments = getattr(balance, "payments_total", None)
            if payments is not None:
                parts.append(
                    f'<div class="muted">Выплаты: {_rub(payments)} {escape(currency)}</div>'
                )
    else:
        error_msg = getattr(balance, "error_message", None)
        if account.marketplace == Marketplace.WB:
            parts.append('<div class="muted">Для баланса нужен Finance-доступ WB</div>')
        else:
            parts.append('<div class="muted">💰 Баланс Ozon: не удалось обновить</div>')
            if error_msg:
                user_msg = _ozon_balance_user_message(str(error_msg))
                parts.append(f'<div class="muted">{escape(user_msg)}</div>')
    return "".join(parts)


def _ozon_balance_user_message(error_code: str) -> str:
    if "auth" in error_code.lower() or "401" in error_code or "403" in error_code:
        return "Проверьте ключи доступа Ozon"
    if "rate" in error_code.lower() or "429" in error_code:
        return "Слишком много запросов, повторим позже"
    if "invalid_response" in error_code.lower():
        return "Нет данных"
    if "http" in error_code.lower():
        return "Временно недоступен"
    return "Ошибка синхронизации"


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


def _ozon_price_label(snapshot: object | None, timezone: str = "Europe/Moscow") -> str:
    if snapshot is None or not hasattr(snapshot, "price"):
        return "н/д"
    price = getattr(snapshot, "price", None)
    synced_at = getattr(snapshot, "synced_at", None)
    if price is None:
        return "н/д"
    date_label = f" · {_dt(synced_at, timezone)}" if synced_at else ""
    return f"{_rub(price)}{date_label}"


def _subscription_content(
    data: SubscriptionPageData,
    tiers: list[SubscriptionTier],
    timezone: str = "Europe/Moscow",
) -> str:
    active = data.active_subscription
    raw_status = subscription_status(active)
    status_map = {
        "ACTIVE": "Активен",
        "EXPIRED": "Истёк",
        "CANCELLED": "Отменён",
        "TRIAL": "Пробный",
        "PENDING": "Ожидает оплаты",
        "FREE": "Бесплатный тариф",
        "REPLACED": "Заменён",
    }
    status = status_map.get(raw_status.upper(), raw_status)
    expires = (
        format_datetime_for_user(active.expires_at, timezone, "%d.%m.%Y")
        if active and active.expires_at
        else "бессрочно"
    )
    feature_rows = "".join(
        f"<li>{'✅' if enabled else '❌'} {escape(label)}</li>"
        for label, enabled in [
            ("Web-кабинет", data.tier.feature_web_cabinet),
            ("Расширенная аналитика", data.tier.feature_analytics),
            ("План/факт", data.tier.feature_plan_fact),
            ("Безубыточность", data.tier.feature_break_even),
            ("Прогноз остатков", data.tier.feature_stock_forecast),
            ("Алерты", data.tier.feature_alerts),
            ("API-доступ", data.tier.feature_api_access),
        ]
    )
    tier_cards = "".join(_web_tier_card(tier, data.tier.code) for tier in tiers)
    payment_rows = (
        "".join(
            "<tr>"
            f"<td>{format_datetime_for_user(payment.created_at, timezone, '%d.%m.%Y')}</td>"
            f"<td>{_rub(payment.amount)}</td>"
            f"<td>{escape(payment.status.value)}</td>"
            f"<td>{escape(payment.provider)}</td>"
            "</tr>"
            for payment in data.payments
        )
        or '<tr><td colspan="4" class="muted">Платежей пока нет.</td></tr>'
    )
    return f"""
      {_page_header("Подписка и тариф", "Следите за лимитами, функциями и историей платежей.", "/web/settings?tab=marketplaces", "Кабинеты МП")}
      <section class="detail-grid">
        <section class="band">
          <h2>Текущая подписка</h2>
          <div class="kv">
            <span>Тариф</span><strong>{escape(data.tier.name)}</strong>
            <span>Статус</span><strong>{escape(status)}</strong>
            <span>Действует до</span><strong>{escape(expires)}</strong>
            <span>Кабинеты</span><strong>{data.used_accounts} / {data.tier.max_marketplace_accounts}</strong>
            <span>Заказы за месяц</span><strong>{data.used_orders_month} / {_limit(data.tier.max_orders_per_month)}</strong>
            <span>SKU</span><strong>{data.used_products} / {_limit(data.tier.max_products)}</strong>
          </div>
        </section>
        <section class="band">
          <h2>Доступные функции</h2>
          <ul>{feature_rows}</ul>
        </section>
      </section>
      <section class="dashboard-grid">
        {tier_cards}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>История платежей</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Дата</th><th>Сумма</th><th>Статус</th><th>Провайдер</th></tr></thead>
          <tbody>{payment_rows}</tbody>
        </table></div>
      </section>
    """


def _profile_content(user: User, subscription: SubscriptionPageData) -> str:
    checked = " checked" if user.notifications_enabled else ""
    active = subscription.active_subscription
    raw_status = subscription_status(active)
    status_map = {
        "ACTIVE": "Активен",
        "EXPIRED": "Истёк",
        "CANCELLED": "Отменён",
        "TRIAL": "Пробный",
        "PENDING": "Ожидает оплаты",
        "FREE": "Бесплатный тариф",
        "REPLACED": "Заменён",
    }
    status_label = status_map.get(raw_status.upper(), raw_status)
    expires = (
        format_datetime_for_user(active.expires_at, user.timezone, "%d.%m.%Y")
        if active and active.expires_at
        else "бессрочно"
    )
    max_orders = subscription.tier.max_orders_per_month
    max_orders_label = str(max_orders) if max_orders else "без ограничений"
    max_products = subscription.tier.max_products
    max_products_label = str(max_products) if max_products else "без ограничений"
    return f"""
      {_page_header("Профиль", "Управляйте настройками пользователя, уведомлениями и подпиской.", "/web/settings?tab=subscription", "Подписка")}
      <section class="detail-grid">
        <section class="band">
          <h2>Данные Telegram</h2>
          <div class="kv">
            <span>Имя</span><strong>{escape(user.first_name or "н/д")}</strong>
            <span>Username</span><strong>{escape("@" + user.username if user.username else "н/д")}</strong>
            <span>Telegram ID</span><strong>{user.telegram_id}</strong>
            <span>Язык</span><strong>{escape(user.language)}</strong>
            <span>Статус</span><strong>{escape(user.status.value)}</strong>
            <span>Регистрация</span><strong>{_dt(user.created_at, user.timezone)}</strong>
          </div>
        </section>
        <section class="band">
          <h2>Текущий тариф</h2>
          <div class="kv">
            <span>Тариф</span><strong>{escape(subscription.tier.name)}</strong>
            <span>Статус</span><strong>{escape(status_label)}</strong>
            <span>Действует до</span><strong>{escape(expires)}</strong>
            <span>Кабинеты</span><strong>{subscription.used_accounts} / {subscription.tier.max_marketplace_accounts}</strong>
            <span>Заказы за месяц</span><strong>{subscription.used_orders_month} / {max_orders_label}</strong>
            <span>SKU</span><strong>{subscription.used_products} / {max_products_label}</strong>
            <span>Уведомления</span><strong>{"включены" if user.notifications_enabled else "выключены"}</strong>
          </div>
          <p><a class="button primary" href="/web/settings?tab=subscription">Управление подпиской</a></p>
        </section>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Настройки профиля</h2>
        <form class="filters" method="post" action="/web/settings/profile">
          <div>
            <label for="timezone">Часовой пояс</label>
            <input id="timezone" name="timezone" value="{escape(user.timezone)}">
          </div>
          <div>
            <label for="low_margin_threshold_percent">Порог низкой маржи, %</label>
            <input id="low_margin_threshold_percent" name="low_margin_threshold_percent" type="number" step="0.01" value="{user.low_margin_threshold_percent}">
          </div>
          <div>
            <label for="notifications_enabled">Уведомления</label>
            <label class="status-chip"><input id="notifications_enabled" name="notifications_enabled" type="checkbox"{checked}> включены</label>
          </div>
          <button class="button primary" type="submit">Сохранить</button>
        </form>
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


def _control_content(data: ControlPageData) -> str:
    accounts = (
        "".join(
            f"<li>{escape(account.name)}: {escape(account.last_error_message or 'ошибка синхронизации')}</li>"
            for account in data.error_accounts
        )
        or "<li>Критичных ошибок кабинетов сейчас нет.</li>"
    )
    alerts = (
        "".join(
            f"<li>{escape(alert.title)} — {escape(alert.message)}</li>"
            for alert in data.open_alerts
        )
        or "<li>Открытых алертов сейчас нет.</li>"
    )
    return f"""
      {_page_header("Контроль ошибок", "Что требует внимания прямо сейчас.", "/web/data-quality", "Качество данных")}
      <section class="kpi-grid">
        {_simple_kpi("Качество данных", str(data.report.score), "good" if data.report.score >= 80 else "warn")}
        {_simple_kpi("Без себестоимости", str(data.missing_cost_products), "warn" if data.missing_cost_products else "neutral")}
        {_simple_kpi("Предварительная экономика", str(data.preliminary_orders), "warn" if data.preliminary_orders else "neutral")}
        {_simple_kpi("Низкие остатки", str(data.low_stock_products), "bad" if data.low_stock_products else "neutral")}
      </section>
      <section class="detail-grid" style="margin-top:14px">
        <section class="band"><h2>Ошибки синхронизации</h2><ul>{accounts}</ul></section>
        <section class="band"><h2>Актуальные алерты</h2><ul>{alerts}</ul></section>
      </section>
    """


def _settings_content(user: User) -> str:
    threshold = user.low_margin_threshold_percent or Decimal("10")
    checked = "включены" if user.notifications_enabled else "выключены"
    return f"""
      {_page_header("Настройки", "Финансовый контроль, локализация, уведомления и быстрые переходы.", "/web/settings?tab=profile", "Профиль")}
      <section class="detail-grid">
        <section class="band">
          <h2>Финансовый контроль</h2>
          <form class="filters" method="post" action="/web/settings/low-margin">
            <div>
              <label for="threshold">Порог низкой маржи, %</label>
              <input id="threshold" name="threshold" type="number" min="0" max="100" step="0.01"
                     value="{threshold}">
            </div>
            <button class="button primary" type="submit">Сохранить</button>
          </form>
          <p class="muted">Порог используется в отчётах, алертах и контрольных web-экранах.</p>
        </section>
        <section class="band">
          <h2>Локализация</h2>
          <div class="kv">
            <span>Часовой пояс</span><strong>{escape(user.timezone)}</strong>
            <span>Язык</span><strong>{escape(user.language)}</strong>
          </div>
          <p><a class="button" href="/web/settings?tab=profile">Изменить в профиле</a></p>
        </section>
        <section class="band">
          <h2>Уведомления</h2>
          <p>Статус Telegram-уведомлений: <span class="badge">{checked}</span></p>
          <p class="muted">Тонкая настройка уведомлений по кабинетам доступна в Telegram-боте.</p>
        </section>
        <section class="band">
          <h2>Подписка и доступ</h2>
          <p class="muted">Проверьте текущий тариф, лимиты и доступные возможности.</p>
          <p><a class="button primary" href="/web/settings?tab=subscription">Открыть подписку</a></p>
        </section>
      </section>
    """


def _data_quality_content(report: DataQualityReport) -> str:
    tone = "good" if report.score >= 80 else "warn" if report.score >= 50 else "bad"
    metrics = "".join(
        "<tr>"
        f"<td>{escape(metric.title)}</td>"
        f'<td class="num">{metric.value}</td>'
        f"<td>{escape(metric.status)}</td>"
        f"<td>{escape(metric.description)}</td>"
        "</tr>"
        for metric in report.metrics
    )
    recommendations = "".join(f"<li>{escape(item)}</li>" for item in report.recommendations)
    return f"""
      {_section_subnav("data_quality")}
      <section class="kpi-grid">
        {_simple_kpi("Индекс качества данных", str(report.score), tone)}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Качество данных</h2>
        <div class="table-wrap">
          <table class="table">
        <thead>
          <tr>
            <th>Проверка</th><th class="num">Значение</th><th>Статус</th><th>Комментарий</th>
          </tr>
        </thead>
            <tbody>{metrics}</tbody>
          </table>
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Что сделать</h2>
        <ul>{recommendations}</ul>
      </section>
    """


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
        row_html.append(
            "<tr>"
            f"{title_cell}"
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f"<td>{escape(row.sale_model.value if row.sale_model else 'н/д')}</td>"
            f'<td class="num">{row.orders}</td>'
            f'<td class="num">{row.sales}</td>'
            f'<td class="num">{_rub(row.revenue)}</td>'
            f'<td class="num">{_rub(row.cost)}</td>'
            f'<td class="num">{_rub(row.marketplace_costs)}</td>'
            f'<td class="num">{_rub(row.estimated_profit)}</td>'
            f'<td class="num">{_rub(row.actual_profit)}</td>'
            f'<td class="num">{row.margin_percent.quantize(Decimal("0.1"))}%</td>'
            f'<td class="num">{roi}</td>'
            "</tr>"
        )
    body = (
        "".join(row_html)
        if row_html
        else (
            '<tr><td colspan="12" class="muted">'
            "Данных по прибыли за выбранный период пока нет.</td></tr>"
        )
    )
    estimated_tone = "good" if summary.estimated_profit >= 0 else "bad"
    deviation_tone = "bad" if summary.deviation < 0 else "good"
    roi_value = f"{summary.roi_percent}%" if summary.roi_percent is not None else "н/д"
    return f"""
      {_section_subnav("profit")}
      {_profit_filters(data.filters)}
      <section class="kpi-grid">
        {_simple_kpi("Плановая прибыль", _rub(summary.estimated_profit), estimated_tone)}
        {_simple_kpi("Фактическая прибыль", _rub(summary.actual_profit))}
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
                <th class="num">Продаж</th><th class="num">Выручка</th>
                <th class="num">Себестоимость</th><th class="num">Расходы МП</th>
                <th class="num">Плановая прибыль</th><th class="num">Фактическая прибыль</th>
                <th class="num">Маржа</th><th class="num">ROI</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
    """


def _section_subnav(active: str) -> str:
    items = {
        "orders": ("Заказы", "/web/orders"),
        "profit": ("Прибыль", "/web/profit"),
        "plan_fact": ("План/факт", "/web/plan-fact"),
        "break_even": ("Безубыточность", "/web/break-even"),
        "products": ("Товары", "/web/products"),
        "product_matching": ("Сопоставление", "/web/product-matching"),
        "stocks": ("Остатки", "/web/stocks"),
        "alerts": ("Алерты", "/web/alerts"),
        "data_quality": ("Качество данных", "/web/data-quality"),
    }
    return (
        '<div class="subnav">'
        + "".join(
            f'<a class="{"active" if key == active else ""}" href="{href}">{label}</a>'
            for key, (label, href) in items.items()
        )
        + "</div>"
    )


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


def _metric_by_label(data: DashboardData, label: str) -> KpiMetric | None:
    return next((metric for metric in data.metrics if metric.label == label), None)


def _metric_value(data: DashboardData, label: str) -> str:
    metric = _metric_by_label(data, label)
    return _format_metric_value(metric.value, metric.suffix) if metric else "н/д"


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
        f'{"<span class=\"muted\" style=\"font-size:12px\">" + escape(hint_text) + "</span>" if hint_text else ""}'
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


def _orders_filters(filters: OrderWebFilters) -> str:
    return _shared_order_filters(filters, "/web/orders", include_status=True)


def _profit_filters(filters: OrderWebFilters) -> str:
    return _shared_order_filters(filters, "/web/profit", include_status=False)


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
            },
            filters.status,
        )
        if include_status
        else ""
    )
    date_from_value = filters.local_date_from.isoformat()
    date_to_value = filters.local_date_to.isoformat()
    return f"""
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


def _page_header(title: str, description: str, href: str, action: str) -> str:
    return (
        '<section class="page-header">'
        f'<div><h2>{escape(title)}</h2><p class="muted">{escape(description)}</p></div>'
        f'<div class="page-actions"><a class="button" href="{escape(href)}">{escape(action)}</a></div>'
        "</section>"
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


def _limit(value: int | None) -> str:
    return "без ограничений" if value is None else str(value)


def _dt(value: datetime | None, timezone: str = "Europe/Moscow") -> str:
    return format_datetime_for_user(value, timezone)


def _user_display_name(user: User) -> str:
    return user.first_name or user.username or str(user.telegram_id)


def _form_value(form: dict[str, list[str]], name: str, default: str) -> str:
    return (form.get(name) or [default])[0]


def _datetime_from_form(value: str, timezone: str = "Europe/Moscow") -> datetime:
    if not value:
        return datetime.now(tz=UTC)
    local_day = datetime.fromisoformat(value).date()
    return user_day_bounds_utc(local_day, timezone)[0]


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


def _percent_optional(value: Decimal | None) -> str:
    if value is None:
        return "н/д"
    return f"{value.quantize(Decimal('0.1'))}%"


def _marketplace_label(value: Marketplace | str | None) -> str:
    css_class = marketplace_css_class(value)
    logo = {"wb": "WB", "ozon": "OZ"}.get(css_class)
    logo_html = f'<span class="mp-logo">{logo}</span>' if logo else ""
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


def _plan_marketplace(raw: str | None) -> Marketplace | None:
    if not raw or raw == "all":
        return None
    try:
        return Marketplace(raw)
    except ValueError:
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
