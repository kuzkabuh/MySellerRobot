"""version: 2.0.0
description: Modernized order, sale, return, and order reconciliation HTML view helpers.
updated: 2026-06-10
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
from app.models.enums import Marketplace, ReconciliationStatus
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

from app.web.view_modules.common import _page_header, _render_pagination, _render_sync_freshness, _section_subnav_orders
from app.web.view_modules.components import _simple_kpi
from app.web.view_modules.formatting import _confidence_badge, _fact_status_badge, _marketplace_label, _order_status_badge, _percent_optional, _rub, _rub_optional, _sale_model_badge
from app.web.view_modules.forms import _orders_filters, _sales_returns_filters

__all__ = [
    "_orders_content",
    "_order_detail_content",
    "_sales_content",
    "_returns_content",
]


def _marketplace_id_label(marketplace: Marketplace) -> str:
    return "Заказ WB" if marketplace == Marketplace.WB else "Заказ Ozon"


def _marketplace_posting_label(marketplace: Marketplace) -> str:
    return "Отправление" if marketplace == Marketplace.WB else "Отправление Ozon"


def _order_identifiers(row: OrderRow) -> str:
    mp = row.marketplace
    parts = []
    order_label = _marketplace_id_label(mp)
    if mp == Marketplace.WB and row.assembly_id:
        parts.append(f"<strong>{order_label}:</strong> {escape(row.assembly_id)}")
        if row.order_external_id and getattr(row, 'srid', None) != row.order_external_id:
            parts.append(f'<div class="muted">SRID: {escape(row.order_external_id)}</div>')
    else:
        parts.append(f"<strong>{order_label}:</strong> {escape(row.order_external_id)}")
    if row.posting_number:
        posting_label = _marketplace_posting_label(mp)
        parts.append(f'<div class="muted">{posting_label}: {escape(row.posting_number)}</div>')
    if mp == Marketplace.WB and hasattr(row, 'srid') and row.srid and row.srid != row.order_external_id:
        parts.append(f'<div class="muted">SRID: {escape(row.srid)}</div>')
    return "".join(parts)


def _order_main_id(order: Any) -> str:
    if order.marketplace == Marketplace.WB and order.assembly_id:
        return escape(order.assembly_id)
    return escape(order.order_external_id)


def _order_extra_ids(order: Any) -> str:
    parts = []
    if order.marketplace == Marketplace.WB and order.assembly_id:
        srid_text = order.srid or order.order_external_id
        if srid_text != order.assembly_id:
            parts.append(f'<div class="muted">SRID: {escape(srid_text)}</div>')
    if order.posting_number:
        label = "Отправление" if order.marketplace == Marketplace.WB else "Отправление Ozon"
        parts.append(f'<div class="muted">{label}: {escape(order.posting_number)}</div>')
    return "".join(parts)


def _wb_fact_income_row(detail: OrderDetail) -> str:
    income = getattr(detail, "wb_fact_income", None)
    if income is None:
        return ""
    return f'<span>Факт к получению от WB</span><strong>{_rub(income)}</strong>'


def _economy_status_badge(economy_confidence: str | None, missing_cost: bool, profit: Decimal | None) -> str:
    if missing_cost:
        return '<span class="badge bad">Нет себестоимости</span>'
    if economy_confidence == "EXACT":
        return '<span class="badge good">Факт</span>'
    if economy_confidence == "ESTIMATED":
        return '<span class="badge warn">Оценка</span>'
    return '<span class="badge">План (предв.)</span>'


def _problem_badges(row: OrderRow) -> str:
    badges = []
    if row.missing_cost:
        badges.append('<span class="badge bad">нет себестоимости</span>')
    profit_val = getattr(row, 'estimated_profit', None)
    if profit_val is not None and profit_val < 0:
        badges.append('<span class="badge bad">убыток</span>')
    if hasattr(row, 'reconciliation_status'):
        rs = row.reconciliation_status
        if rs in (ReconciliationStatus.FACT_AMBIGUOUS, ReconciliationStatus.FACT_CONFLICT):
            badges.append('<span class="badge warn">неоднозначно</span>')
    return "".join(badges)


def _orders_summary(rows: list[OrderRow]) -> str:
    total_orders = len(set(r.order_id for r in rows))
    total_qty = sum(r.quantity for r in rows)
    total_revenue = sum(r.revenue for r in rows)
    profits = [r.estimated_profit for r in rows if r.estimated_profit is not None]
    total_profit = sum(profits) if profits else ZERO
    missing_cost = sum(1 for r in rows if r.missing_cost)
    loss_count = sum(1 for r in rows if r.estimated_profit is not None and r.estimated_profit < 0)
    margin = (total_profit / total_revenue * Decimal("100")).quantize(Decimal("0.1")) if total_revenue > ZERO else None

    return f"""
      <section class="orders-summary">
        <article class="summary-card">
          <span class="summary-label">Заказов</span>
          <strong class="summary-value">{total_orders}</strong>
          <span class="summary-note">позиций: {total_qty}</span>
        </article>
        <article class="summary-card">
          <span class="summary-label">Выручка</span>
          <strong class="summary-value">{_rub(total_revenue)}</strong>
        </article>
        <article class="summary-card {'good' if total_profit >= 0 else 'bad'}">
          <span class="summary-label">Плановая прибыль</span>
          <strong class="summary-value">{_rub(total_profit)}</strong>
        </article>
        <article class="summary-card {'good' if margin and margin >= 5 else 'warn' if margin and margin >= 0 else 'bad'}">
          <span class="summary-label">Средняя маржа</span>
          <strong class="summary-value">{_percent_optional(margin) if margin else 'н/д'}</strong>
        </article>
        <article class="summary-card {'bad' if missing_cost > 0 else 'neutral'}">
          <span class="summary-label">Без себестоимости</span>
          <strong class="summary-value">{missing_cost}</strong>
        </article>
        <article class="summary-card {'bad' if loss_count > 0 else 'neutral'}">
          <span class="summary-label">Убыточные</span>
          <strong class="summary-value">{loss_count}</strong>
        </article>
      </section>"""


def _orders_content(
    result: Any, timezone: str, *, last_poll_info: dict[str, object] | None = None
) -> str:
    from app.services.common.web_orders_profit_service import OrderPageResult

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
        profit_tone = "bad" if profit is not None and profit < 0 else "good"
        profit_cell = (
            f'<td class="num"><span class="badge {profit_tone}">'
            f"{_rub_optional(profit)}</span></td>"
        )
        economy_badge = _economy_status_badge(row.economy_confidence, row.missing_cost, profit)
        problem_badges = _problem_badges(row)
        expand_id = f"order-detail-{row.order_id}-{row.item_id}"

        table_rows.append(
            "<tr class='order-row' data-order-id='{row.order_id}' onclick='toggleOrderDetail(this)'>"
            f"<td>{localized_order_date(row.order_date, timezone)}</td>"
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f"<td>{_sale_model_badge(row.sale_model)}</td>"
            f'<td class="cell-title"><a href="/web/orders/{row.order_id}">{escape(row.title or "Без названия")}</a>'
            f'<div class="muted">{escape(row.seller_article or "")}</div></td>'
            f"<td class='cell-ids'>{_order_identifiers(row)}</td>"
            f'<td class="num">{row.quantity}</td>'
            f'<td class="num">{_rub(row.revenue)}</td>'
            f"<td class='cell-costs muted'>{_rub_optional(None)}</td>"
            f"{profit_cell}"
            f'<td class="num">{_percent_optional(row.margin_percent)}</td>'
            f"<td class='cell-status'>"
            f"<div>{_order_status_badge(row.status, row.requires_action)}</div>"
            f"<div>{economy_badge}</div>"
            f"{problem_badges}"
            f"</td>"
            f"<td class='cell-source'>{escape(source_event_label(row.source_event_type))}</td>"
            f"<td><a class='button-tiny' href='/web/orders/{row.order_id}'>Подробнее</a></td>"
            f"</tr>"
            f"<tr class='order-detail-row' id='{expand_id}' style='display:none'>"
            f"<td colspan='13'><div class='order-detail-body'>"
            f"<div class='detail-grid-compact'>"
            f"<div><strong>Товар:</strong> {escape(row.title or 'Без названия')}</div>"
            f"<div><strong>Артикул:</strong> {escape(row.seller_article or 'н/д')}</div>"
            f"<div><strong>МП:</strong> {_marketplace_label(row.marketplace)}</div>"
            f"<div><strong>Модель:</strong> {_sale_model_badge(row.sale_model)}</div>"
            f"<div><strong>Цена:</strong> {_rub(row.revenue)}</div>"
            f"<div><strong>Прибыль:</strong> <span class='{'tone-bad' if profit is not None and profit < 0 else 'tone-good'}'>"
            f"{_rub_optional(profit)}</span></div>"
            f"<div><strong>Маржа:</strong> {_percent_optional(row.margin_percent)}</div>"
            f"<div><strong>Статус экономики:</strong> {economy_badge}</div>"
            f"</div>"
            f"<div class='detail-actions' style='margin-top:10px'>"
            f"<a class='button-tiny' href='/web/orders/{row.order_id}'>Карточка заказа</a>"
            f"</div>"
            f"</div></td>"
            f"</tr>"
        )

    body = "".join(table_rows) if table_rows else ''

    range_start = (page - 1) * per_page + 1 if total_count > 0 else 0
    range_end = min(page * per_page, total_count)
    range_text = (
        f"Показано {range_start}–{range_end} из {total_count}" if total_count > 0 else "Нет заказов"
    )

    pagination_html = _render_pagination(filters, page, total_pages, per_page, total_count)

    sync_html = _render_modern_sync(last_poll_info, timezone) if last_poll_info else ""
    summary_html = _orders_summary(rows) if rows else ""

    empty_html = ""
    if not rows:
        empty_html = '''
        <div class="empty-state">
          <strong>Заказы за выбранный период не найдены.</strong>
          <span>Попробуйте изменить фильтры или синхронизировать заказы.</span>
          <div style="margin-top:12px;display:flex;gap:8px;justify-content:center">
            <a class="button" href="/web/orders?period=30d">За 30 дней</a>
            <a class="button primary" href="/web/sync-center?tab=sync">Синхронизировать</a>
            <a class="button" href="/web/accounts">Настройки кабинетов</a>
          </div>
        </div>'''

    return f"""
      {sync_html}
      {summary_html}
      {_orders_filters(filters)}
      <section class="band">
        <div class="orders-toolbar">
          <h2 style="margin:0">Операции</h2>
          <div class="orders-toolbar-right">
            <span class="muted" style="font-size:13px">{range_text}</span>
            <a class="button-tiny" href="/web/orders?export=csv&{_export_params(filters)}">CSV</a>
            <a class="button-tiny" href="/web/sync-center?tab=sync">Обновить</a>
          </div>
        </div>
        {empty_html}
        {_orders_table_html(body, rows)}
        {pagination_html}
      </section>
      <script>
      function toggleOrderDetail(tr) {{
        var next = tr.nextElementSibling;
        if (next && next.classList.contains('order-detail-row')) {{
          next.style.display = next.style.display === 'none' ? 'table-row' : 'none';
        }}
      }}
      </script>
    """


def _export_params(filters: OrderWebFilters) -> str:
    from urllib.parse import urlencode
    params = {
        "period": filters.period,
        "marketplace": filters.marketplace.value if filters.marketplace else "all",
        "sale_model": filters.sale_model.value if filters.sale_model else "all",
        "economy": filters.economy,
        "sku": filters.sku,
    }
    if filters.period == "custom":
        params["date_from"] = filters.local_date_from.isoformat()
        params["date_to"] = filters.local_date_to.isoformat()
    return urlencode(params)


def _orders_table_html(body: str, rows: list) -> str:
    if not rows:
        return ""
    return f"""
        <div class="table-wrap">
          <table class="table orders-table">
            <thead>
              <tr>
                <th>Дата</th><th>МП</th><th>Модель</th><th>Товар</th>
                <th>Идентификаторы</th><th class="num">Кол-во</th>
                <th class="num">Цена</th><th class="num">Расходы</th>
                <th class="num">План. прибыль</th><th class="num">Маржа</th>
                <th>Статус</th><th>Источник</th><th></th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>"""


def _render_modern_sync(last_poll_info: dict[str, object], timezone: str) -> str:
    from datetime import UTC, datetime

    last_poll_at = last_poll_info.get("last_poll_at")
    if not last_poll_at:
        return '<div class="sync-bar warn">Синхронизация: не выполнялась</div>'

    now = datetime.now(tz=UTC)
    poll_dt = last_poll_at
    if not isinstance(poll_dt, datetime):
        return ""
    if poll_dt.tzinfo is None:
        poll_dt = poll_dt.replace(tzinfo=UTC)
    age_minutes = int((now - poll_dt).total_seconds() / 60)

    tone = "good" if age_minutes < 10 else "warn" if age_minutes < 30 else "bad"
    action_link = '<a class="button-tiny" href="/web/sync-center?tab=sync">Центр синхронизации</a>'

    accounts = last_poll_info.get("accounts", [])
    acc_details = []
    if isinstance(accounts, list):
        for acc in accounts[:4]:
            if not isinstance(acc, dict):
                continue
            mp = acc.get("marketplace", "?")
            ts = acc.get("last_poll_at")
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                acc_age = int((now - ts).total_seconds() / 60)
                acc_details.append(f"{mp}: {acc_age} мин")

    hint = " · ".join(acc_details) if acc_details else ""

    last_update_str = format_datetime_for_user(poll_dt, timezone) if hasattr(poll_dt, 'tzinfo') else str(poll_dt)

    return f"""
      <div class="sync-bar {tone}">
        <span class="sync-bar-main">
          <span class="badge {tone}">Синхронизация: {age_minutes} мин назад</span>
          <span class="muted" style="font-size:12px">Последнее обновление: {last_update_str}</span>
        </span>
        <span class="sync-bar-acc">
          {"<span class='muted' style='font-size:12px'>" + escape(hint) + "</span>" if hint else ""}
          {action_link}
        </span>
      </div>"""


def _order_detail_content(detail: OrderDetail, timezone: str, is_admin: bool = False) -> str:
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
        actual_tone = "good" if actual_profit and actual_profit >= 0 else "bad" if actual_profit else ""
        item_rows.append(
            "<tr>"
            f"<td>{escape(item.title or 'Без названия')}"
            f'<div class="muted">Артикул: {escape(item.seller_article or "н/д")}</div>'
            f'<div class="muted">{escape(str(item.marketplace_article or "н/д"))}</div></td>'
            f'<td class="num">{item.quantity}</td>'
            f'<td class="num">{_rub(item.discounted_price * item.quantity)}</td>'
            f'<td class="num">{_rub_optional(item.commission_estimated)}</td>'
            f'<td class="num">{_rub_optional(item.logistics_estimated)}</td>'
            f'<td class="num">{_rub_optional(item.cost_price_used)}</td>'
            f'<td class="num">{_rub_optional(item.package_cost_used)}</td>'
            f'<td class="num">{_rub_optional(item.tax_amount_estimated)}</td>'
            f'<td class="num">{_rub_optional(estimated_profit)}</td>'
            f'<td class="num"><span class="{"tone-" + actual_tone if actual_tone else ""}">{_rub_optional(actual_profit)}</span></td>'
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
    wb_fact_html = _wb_order_fact_html(getattr(detail, "wb_fact", None), timezone)
    ozon_fact_html = _ozon_order_fact_html(getattr(detail, "ozon_fact", None))
    fact_html = wb_fact_html or ozon_fact_html
    is_financial_only = getattr(detail, "is_financial_only", False)
    marketplace_id_label = _marketplace_id_label(order.marketplace)
    financial_only_warning = (
        '<div class="band warn" style="margin:14px 0;padding:14px">'
        "<strong>Внимание!</strong> Эта запись, вероятно, является строкой финансового отчёта, "
        "а не реальным заказом покупателя. "
        "Она не привязана к заказу и не должна учитываться в аналитике заказов."
        "</div>"
        if is_financial_only
        else ""
    )
    has_no_finance = not fact_html and not is_financial_only
    finance_section = ""
    if has_no_finance:
        finance_section = (
            '<section class="band" style="margin-top:14px">'
            '<div class="empty-state compact">'
            "Финансовые данные по этому заказу ещё не загружены."
            "</div></section>"
        )
    return f"""
      {financial_only_warning}
      <section class="detail-grid">
        <section class="band">
          <h2>Информация</h2>
          <div class="kv">
            <span>Маркетплейс</span><strong>{_marketplace_label(order.marketplace)}</strong>
            <span>Модель</span><strong>{sale_model}</strong>
            <span>Статус заказа</span><strong>{_order_status_badge(order.normalized_status or order.status, order.requires_seller_action)}</strong>
            <span>Статус экономики</span><strong>{_economy_status_badge(detail.economy_confidence, detail.has_missing_cost_price, detail.estimated_profit)}</strong>
            <span>Статус сверки</span><strong>{_reconciliation_badge(getattr(detail, "reconciliation_status", None))}</strong>
            <span>Дата заказа</span><strong>{order_date}</strong>
            <span>Дедлайн</span><strong>{deadline}</strong>
            <span>{marketplace_id_label}</span><strong>{_order_main_id(order)}</strong>
            {_order_extra_ids(order)}
          </div>
        </section>
        <section class="band">
          <h2>План / факт</h2>
          <div class="kv">
            <span>Плановая прибыль</span><strong>{_rub(detail.estimated_profit)}</strong>
            <span>Фактическая прибыль</span><strong>{_rub_optional(detail.actual_profit)}</strong>
            <span>Отклонение</span><strong>{_rub_optional(detail.deviation)}</strong>
            <span>Статус сверки</span><strong>{_reconciliation_badge(getattr(detail, "reconciliation_status", None))}</strong>
            {_wb_fact_income_row(detail)}
          </div>
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
                <th class="num">Налог</th><th class="num">Прибыль план</th><th class="num">Прибыль факт</th>
                <th>Достоверность</th>
              </tr>
            </thead>
            <tbody>{"".join(item_rows)}</tbody>
          </table>
        </div>
      </section>
      {fact_html}
      {finance_section}
      {'<section class="band" style="margin-top:14px"><details><summary style="cursor:pointer"><h2 style="display:inline">Технические данные</h2></summary><pre class="mono">' + raw_payload + '</pre></details></section>' if is_admin else ''}
    """


def _wb_order_fact_html(wb_fact: Any, timezone: str) -> str:
    if wb_fact is None:
        return ""
    status_value = getattr(getattr(wb_fact, "status", ""), "value", getattr(wb_fact, "status", ""))
    status_label = {
        "FACT_MATCHED": "Факт полный",
        "FACT_PARTIAL": "Факт частичный",
        "FACT_UNMATCHED": "Факт не привязан",
        "FACT_AMBIGUOUS": "Неоднозначная сверка",
        "FACT_CONFLICT": "Конфликт сумм",
        "MANUAL_REVIEW": "Нужна проверка",
        "MISSING_COST": "Нет себестоимости",
        "MISSING_REPORT": "Не загружен отчёт WB",
        "ERROR_STATUS": "Ошибка обработки",
        "PRELIMINARY": "Только план",
    }.get(status_value, "Только план")
    states = "".join(
        "<tr>"
        f"<td>{escape(state.label)}</td>"
        f"<td>{_wb_fact_state_badge(state.state)}</td>"
        f'<td class="num">{_rub(state.amount) if state.amount is not None else escape(_wb_fact_state_text(state.state))}</td>'
        "</tr>"
        for state in getattr(wb_fact, "article_states", [])
    )
    linked_rows = _wb_report_rows_table(
        getattr(wb_fact, "linked_rows", []),
        timezone,
        empty_text="Связанных строк WB-отчёта по заказу пока нет.",
    )
    unlinked_rows = _wb_report_rows_table(
        getattr(wb_fact, "unlinked_product_rows", []),
        timezone,
        empty_text="Непривязанных строк по товарам этого заказа не найдено.",
    )
    return f"""
      <section class="band" style="margin-top:14px">
        <h2>Факт по отчёту WB</h2>
        <p><span class="badge {_reconciliation_tone(status_value)}">{escape(status_label)}</span></p>
        <p class="muted">
          Строки отчёта WB могут быть связаны с товаром, но не связаны с конкретным заказом.
          Такие строки учитываются в аналитике товара и общей финансовой аналитике, но не
          включаются в факт заказа до точного сопоставления.
        </p>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Статья</th><th>Состояние</th><th class="num">Факт заказа</th></tr></thead>
            <tbody>{states}</tbody>
          </table>
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Связанные строки отчёта WB</h2>
        {linked_rows}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Непривязанные строки по этому товару</h2>
        {unlinked_rows}
      </section>
    """


def _ozon_order_fact_html(ozon_fact: Any) -> str:
    if ozon_fact is None:
        return ""
    status_value = getattr(getattr(ozon_fact, "status", ""), "value", getattr(ozon_fact, "status", ""))
    status_label = {
        "FACT_MATCHED": "Факт полный",
        "FACT_PARTIAL": "Факт частичный",
        "FACT_UNMATCHED": "Факт не привязан",
        "FACT_AMBIGUOUS": "Неоднозначная сверка",
        "MISSING_REPORT": "Не загружен отчёт Ozon",
        "PRELIMINARY": "Только план",
    }.get(status_value, "Только план")
    articles = "".join(
        "<tr>"
        f"<td>{escape(article.label)}</td>"
        f'<td class="num">{_rub(article.amount) if article.amount is not None else "—"}</td>'
        "</tr>"
        for article in getattr(ozon_fact, "articles", [])
    )
    rows_list = getattr(ozon_fact, "rows", [])
    rows_table = ""
    if rows_list:
        rows_table = "".join(
            "<tr>"
            f"<td>{escape(getattr(r, 'operation_type', '') or '')}</td>"
            f"<td>{escape(getattr(r, 'operation_category', '') or '')}</td>"
            f'<td class="num">{_rub(getattr(r, "amount", None) or ZERO)}</td>'
            f"<td class=\"num\">{escape(getattr(r, 'currency', 'RUB') or 'RUB')}</td>"
            "</tr>"
            for r in rows_list
        )
    return f"""
      <section class="band" style="margin-top:14px">
        <h2>Факт по данным Ozon</h2>
        <p><span class="badge {_reconciliation_tone(status_value)}">{escape(status_label)}</span></p>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Статья</th><th class="num">Сумма</th></tr></thead>
            <tbody>{articles}</tbody>
          </table>
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Строки фин. данных Ozon</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Тип операции</th><th>Категория</th><th class="num">Сумма</th><th class="num">Валюта</th></tr></thead>
            <tbody>{rows_table}</tbody>
          </table>
        </div>
      </section>
    """


def _reconciliation_tone(status: str) -> str:
    return {
        "FACT_MATCHED": "good",
        "FACT_PARTIAL": "warn",
        "FACT_UNMATCHED": "warn",
        "FACT_AMBIGUOUS": "warn",
        "FACT_CONFLICT": "bad",
        "MANUAL_REVIEW": "bad",
        "MISSING_COST": "bad",
        "MISSING_REPORT": "warn",
        "ERROR_STATUS": "bad",
    }.get(status, "")


def _wb_report_rows_table(rows: list[Any], timezone: str, *, empty_text: str) -> str:
    if not rows:
        return f'<div class="empty-state">{escape(empty_text)}</div>'
    body = "".join(_wb_report_row_html(row, timezone) for row in rows)
    return f"""
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Дата операции</th><th>Тип отчёта</th><th>Номер отчёта</th>
              <th>Обоснование</th><th>Статья</th><th>Тип операции</th><th>Товар</th>
              <th>Barcode</th><th>nm_id</th><th>Артикул</th><th>ШК</th><th>Srid</th>
              <th class="num">Сумма продажи</th><th class="num">Комиссия</th>
              <th class="num">Логистика</th><th class="num">Хранение</th>
              <th class="num">Штрафы</th><th class="num">Удержания</th>
              <th class="num">Приемка FBS</th><th class="num">Компенсации</th>
              <th class="num">К перечислению</th><th>Статус связи</th><th>Причина</th>
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    """


def _wb_report_row_html(row: Any, timezone: str) -> str:
    sale_dt = getattr(row, "sale_dt", None)
    return (
        "<tr>"
        f"<td>{escape(format_datetime_for_user(sale_dt, timezone) if sale_dt else 'н/д')}</td>"
        f"<td>{escape({'daily': 'ежедневный', 'weekly': 'еженедельный'}.get(getattr(row, 'report_type', ''), getattr(row, 'report_type', None) or 'н/д'))}</td>"
        f"<td>{escape(getattr(row, 'report_number', None) or 'н/д')}</td>"
        f"<td>{escape(getattr(row, 'payment_reason', None) or 'н/д')}</td>"
        f"<td>{escape(getattr(row, 'finance_category', None) or 'н/д')}</td>"
        f"<td>{escape(getattr(row, 'finance_operation_type', None) or 'н/д')}</td>"
        f"<td>{escape(getattr(row, 'product_name', None) or f'Товар #{getattr(row, "linked_product_id", None) or "н/д"}')}</td>"
        f"<td>{escape(getattr(row, 'barcode', None) or 'н/д')}</td>"
        f"<td>{escape(str(getattr(row, 'nm_id', None) or 'н/д'))}</td>"
        f"<td>{escape(getattr(row, 'supplier_article', None) or 'н/д')}</td>"
        f"<td>{escape(getattr(row, 'shk', None) or 'н/д')}</td>"
        f"<td>{escape(getattr(row, 'srid', None) or 'н/д')}</td>"
        f'<td class="num">{_rub(getattr(row, "retail_amount", None))}</td>'
        f'<td class="num">{_rub(getattr(row, "commission_rub", None))}</td>'
        f'<td class="num">{_rub(getattr(row, "delivery_rub", None))}</td>'
        f'<td class="num">{_rub(getattr(row, "storage_fee", None))}</td>'
        f'<td class="num">{_rub(getattr(row, "penalty", None))}</td>'
        f'<td class="num">{_rub(getattr(row, "deduction", None))}</td>'
        f'<td class="num">{_rub(getattr(row, "acceptance", None))}</td>'
        f'<td class="num">{_rub(getattr(row, "reimbursement_amount", None))}</td>'
        f'<td class="num">{_rub(getattr(row, "for_pay", None))}</td>'
        f"<td>{escape(_wb_link_status_text(row))}</td>"
        f"<td>{escape(getattr(row, 'skip_reason', None) or '—')}</td>"
        "</tr>"
    )


def _wb_fact_state_badge(state: str) -> str:
    label = _wb_fact_state_text(state)
    tone = {"present": "good", "unlinked": "warn", "missing": "warn"}.get(state, "")
    return f'<span class="badge {tone}">{escape(label)}</span>'


def _wb_fact_state_text(state: str) -> str:
    return {
        "present": "есть",
        "unlinked": "не связано",
        "missing": "не найдено в отчёте",
        "report_not_loaded": "отчёт WB ещё не загружен",
    }.get(state, "нет данных")


def _reconciliation_badge(status: Any) -> str:
    value = getattr(status, "value", status) or "PRELIMINARY"
    labels = {
        "PRELIMINARY": "Только план",
        "FACT_MATCHED": "Факт полный",
        "FACT_PARTIAL": "Факт частичный",
        "FACT_UNMATCHED": "Факт не привязан",
        "FACT_AMBIGUOUS": "Неоднозначно",
        "FACT_CONFLICT": "Конфликт",
        "MANUAL_REVIEW": "Проверка",
        "MISSING_COST": "Нет себестоимости",
        "MISSING_REPORT": "Нет отчёта",
        "ERROR_STATUS": "Ошибка",
    }
    tones = {
        "FACT_MATCHED": "good",
        "FACT_PARTIAL": "warn",
        "FACT_UNMATCHED": "warn",
        "FACT_AMBIGUOUS": "warn",
        "FACT_CONFLICT": "bad",
        "MANUAL_REVIEW": "bad",
        "MISSING_COST": "bad",
        "MISSING_REPORT": "warn",
        "ERROR_STATUS": "bad",
    }
    sv = str(value)
    label = labels.get(sv, sv)
    tone = tones.get(sv, "")
    return f'<span class="badge {tone}">{escape(label)}</span>'


def _wb_link_status_text(row: Any) -> str:
    if getattr(row, "linked_order_id", None):
        return "Связана с заказом"
    if getattr(row, "linked_product_id", None):
        return "Товар найден, заказ не связан"
    return "Не связано"


def _sales_content(data: SalesPageData, timezone: str, sku: str) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{localized_order_date(row.event_date, timezone)}</td>"
        f"<td>{_marketplace_label(row.marketplace)}</td>"
        f"<td>{_sale_model_badge(row.sale_model) if row.sale_model else '—'}</td>"
        f"<td>{escape(row.event_type)}</td>"
        f"<td>"
        f'  <div>{escape(row.product_name or row.seller_article)}</div>'
        f'  <div class="muted">{escape(row.marketplace_article)}</div>'
        f"</td>"
        f'<td class="num">{row.quantity}</td>'
        f'<td class="num">{_rub(row.amount)}</td>'
        f'<td class="num">{_rub_optional(row.estimated_profit)}</td>'
        f'<td class="num">{_rub_optional(row.actual_profit)}</td>'
        f"<td>{_fact_status_badge(row.fact_status, row.fact_status_label)}</td>"
        f"<td>{_order_link(row.order_id, row.order_external_id)}</td>"
        f"<td>{_wb_report_link(row.wb_report_number, row.wb_report_type, row.wb_report_import_id)}</td>"
        f"<td>{_sales_actions(row.order_id, row.wb_report_import_id)}</td>"
        "</tr>"
        for row in data.rows
    )
    if not rows:
        rows = (
            '<tr><td colspan="13"><div class="empty-state">'
            "Продаж за выбранный период пока нет. Дождитесь синхронизации выкупов WB/Ozon."
            "</div></td></tr>"
        )
    avg_check = data.total_amount / Decimal(data.total_quantity) if data.total_quantity else ZERO
    return f"""
      {_page_header("Продажи", "Отслеживайте выкупы и завершённые продажи WB/Ozon.", "/web/orders", "Заказы")}
      {_sales_returns_filters("/web/sales", data.filters, sku)}
      <section class="kpi-grid">
        {_simple_kpi("Продаж", str(data.total_quantity))}
        {_simple_kpi("Выручка", _rub(data.total_amount))}
        {_simple_kpi("Плановая прибыль", _rub(data.total_profit), "good" if data.total_profit >= 0 else "bad")}
        {_simple_kpi("Факт WB", _rub(data.total_actual_profit), "good" if data.total_actual_profit >= 0 else "bad")}
        {_simple_kpi("Средний чек", _rub(avg_check))}
        {_simple_kpi("Полный факт", str(data.full_fact_count), "good")}
        {_simple_kpi("Ожидают", str(data.pending_fact_count), "warn")}
        {_simple_kpi("Нет отчёта", str(data.no_report_count), "warn" if data.no_report_count else "neutral")}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>События продаж</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Дата</th><th>МП</th><th>Модель</th><th>Операция</th><th>Товар</th>
          <th class="num">Кол-во</th><th class="num">Цена</th><th class="num">План</th>
          <th class="num">Факт WB</th><th>Статус факта</th><th>Заказ</th><th>Отчёт WB</th>
          <th>Действия</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
    """


def _order_link(order_id: int | None, external_id: str | None) -> str:
    if order_id:
        return f'<a href="/web/orders/{order_id}">{escape(external_id or "Заказ")}</a>'
    if external_id:
        return escape(external_id)
    return "н/д"


def _wb_report_link(
    report_number: str | None,
    report_type: str | None,
    import_id: int | None,
) -> str:
    if not report_number:
        return '<span class="muted">нет отчёта</span>'
    label = f"{report_number}"
    if report_type:
        label += f" ({report_type})"
    if import_id:
        return f'<a href="/web/wb-reports/{import_id}">{escape(label)}</a>'
    return escape(label)


def _sales_actions(order_id: int | None, wb_report_import_id: int | None) -> str:
    links = []
    if order_id:
        links.append(f'<a class="button-tiny" href="/web/orders/{order_id}">Заказ</a>')
    if wb_report_import_id:
        links.append(
            f'<a class="button-tiny" href="/web/wb-reports/{wb_report_import_id}">Отчёт</a>'
        )
    return " ".join(links) if links else '<span class="muted">—</span>'


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
