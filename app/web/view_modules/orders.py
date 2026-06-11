"""version: 3.0.0
description: Professional order list, order detail, sales, and returns HTML views.
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
from app.models.enums import Marketplace, ReconciliationStatus
from app.models.subscriptions import SubscriptionTier
from app.services.common.data_quality_service import DataQualityReport
from app.services.common.marketplace_presentation import (
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
    OrderSummaryDTO,
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


def _economy_tone(profit: Decimal | None) -> str:
    if profit is None:
        return ""
    if profit > 0:
        return "good"
    if profit == 0:
        return ""
    return "bad"


def _profit_status_badge(profit: Decimal | None, missing_cost: bool) -> str:
    if missing_cost:
        return '<span class="badge warn" title="Не задана себестоимость товара">Нет себестоимости</span>'
    if profit is not None and profit < 0:
        return '<span class="badge bad" title="Убыточный заказ">Убыток</span>'
    if profit is not None:
        return '<span class="badge good" title="Прибыльный заказ">Прибыль</span>'
    return '<span class="badge" title="Нет данных">н/д</span>'


def _margin_tone(margin: Decimal | None) -> str:
    if margin is None:
        return ""
    if margin >= 10:
        return "good"
    if margin >= 0:
        return ""
    return "bad"


def _orders_kpi_html(summary: OrderSummaryDTO) -> str:
    revenue_tone = "good" if summary.total_revenue > 0 else ""
    profit_tone = _economy_tone(summary.total_estimated_profit)
    margin_tone = _margin_tone(summary.average_margin)
    missing_tone = "bad" if summary.missing_cost_count > 0 else "neutral"
    loss_tone = "bad" if summary.loss_count > 0 else "neutral"
    cancelled_tone = "warn" if summary.cancelled_count > 0 else "neutral"

    return f"""
      <section class="kpi-grid orders-kpi">
        <article class="kpi {revenue_tone}">
          <span>Всего заказов</span>
          <strong>{summary.total_orders}</strong>
        </article>
        <article class="kpi {revenue_tone}">
          <span>Выручка</span>
          <strong>{_rub(summary.total_revenue)}</strong>
        </article>
        <article class="kpi {profit_tone}">
          <span>Плановая прибыль</span>
          <strong>{_rub(summary.total_estimated_profit)}</strong>
        </article>
        <article class="kpi {margin_tone}">
          <span>Средняя маржа</span>
          <strong>{_percent_optional(summary.average_margin)}</strong>
        </article>
        <article class="kpi {missing_tone}">
          <span>Без себестоимости</span>
          <strong>{summary.missing_cost_count}</strong>
        </article>
        <article class="kpi {loss_tone}">
          <span>Убыточные</span>
          <strong>{summary.loss_count}</strong>
        </article>
        <article class="kpi {cancelled_tone}">
          <span>Отменённые</span>
          <strong>{summary.cancelled_count}</strong>
        </article>
      </section>"""


def _sync_freshness_bar(
    last_poll_info: dict[str, object] | None,
    sync_stats: dict[str, object] | None,
    timezone: str,
) -> str:
    if not last_poll_info:
        return '<div class="sync-bar warn">Синхронизация: не выполнялась</div>'

    last_poll_at = last_poll_info.get("last_poll_at")
    now = datetime.now(tz=UTC)

    if not last_poll_at:
        return '<div class="sync-bar warn">Синхронизация: не выполнялась</div>'

    poll_dt = last_poll_at
    if not isinstance(poll_dt, datetime):
        return ""
    if poll_dt.tzinfo is None:
        poll_dt = poll_dt.replace(tzinfo=UTC)
    age_minutes = int((now - poll_dt).total_seconds() / 60)
    tone = "good" if age_minutes < 10 else "warn" if age_minutes < 30 else "bad"
    last_update_str = format_datetime_for_user(poll_dt, timezone)

    wb_stats = sync_stats.get("WB", {"count": 0, "last_poll": None}) if sync_stats else {"count": 0, "last_poll": None}
    ozon_stats = sync_stats.get("OZON", {"count": 0, "last_poll": None}) if sync_stats else {"count": 0, "last_poll": None}

    wb_count = int(wb_stats.get("count", 0))
    ozon_count = int(ozon_stats.get("count", 0))

    wb_last = wb_stats.get("last_poll")
    ozon_last = ozon_stats.get("last_poll")

    wb_str = ""
    if wb_last and isinstance(wb_last, datetime):
        if wb_last.tzinfo is None:
            wb_last = wb_last.replace(tzinfo=UTC)
        wb_str = format_datetime_for_user(wb_last, timezone)
    ozon_str = ""
    if ozon_last and isinstance(ozon_last, datetime):
        if ozon_last.tzinfo is None:
            ozon_last = ozon_last.replace(tzinfo=UTC)
        ozon_str = format_datetime_for_user(ozon_last, timezone)

    wb_info = f"WB: загружено <strong>{wb_count}</strong>"
    if wb_str:
        wb_info += f", последнее обновление <span class=\"muted\">{wb_str}</span>"

    ozon_info = f"Ozon: загружено <strong>{ozon_count}</strong>"
    if ozon_str:
        ozon_info += f", последнее обновление <span class=\"muted\">{ozon_str}</span>"

    return f"""
      <div class="sync-bar {tone}" style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:10px 16px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg-card);margin-bottom:14px">
        <span class="badge {tone}" style="flex-shrink:0">{age_minutes} мин назад</span>
        <div style="font-size:13px;display:flex;gap:16px;flex-wrap:wrap">
          <span>{wb_info}</span>
          <span>{ozon_info}</span>
        </div>
        <div style="margin-left:auto;display:flex;gap:6px">
          <a class="button-tiny" href="/web/sync-center?tab=sync">Синхронизировать</a>
          <a class="button-tiny" href="/web/sync-center?tab=history">Центр синхронизации</a>
        </div>
      </div>"""


def _orders_content(
    result: Any,
    timezone: str,
    *,
    summary: OrderSummaryDTO | None = None,
    last_poll_info: dict[str, object] | None = None,
    sync_stats: dict[str, object] | None = None,
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
        profit_tone = "bad" if profit is not None and profit < 0 else "good" if profit is not None and profit > 0 else ""
        margin_tone = _margin_tone(row.margin_percent)
        profit_cell = (
            f'<td class="num"><span class="badge {profit_tone}">'
            f"{_rub_optional(profit)}</span></td>"
        )
        margin_cell = (
            f'<td class="num {margin_tone}">'
            f"{_percent_optional(row.margin_percent)}</td>"
        )

        problem_badges = []
        if row.missing_cost:
            problem_badges.append('<span class="badge warn" title="Нет себестоимости">$</span>')
        if profit is not None and profit < 0:
            problem_badges.append('<span class="badge bad" title="Убыток">!</span>')
        problems = "".join(problem_badges)

        table_rows.append(
            "<tr>"
            f"<td class=\"cell-date\">{localized_order_date(row.order_date, timezone)}</td>"
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f"<td>{_sale_model_badge(row.sale_model)}</td>"
            f"<td class=\"cell-order-id\">"
            f"  <a href=\"/web/orders/{row.order_id}\" class=\"order-link\">{escape(row.order_external_id)}</a>"
            f"</td>"
            f"<td class=\"cell-title\">"
            f"  <a href=\"/web/orders/{row.order_id}\">{escape(row.title or 'Без названия')}</a>"
            f"  <div class=\"muted\">{escape(row.seller_article or row.marketplace_article or '')}</div>"
            f"</td>"
            f"<td class=\"num\">{row.quantity}</td>"
            f"<td class=\"num\">{_rub(row.revenue)}</td>"
            f"{profit_cell}"
            f"{margin_cell}"
            f"<td>{_order_status_badge(row.status, row.requires_action)}</td>"
            f"<td>{problems}</td>"
            f"<td><a class=\"button-tiny\" href=\"/web/orders/{row.order_id}\">Подробнее</a></td>"
            f"</tr>"
        )

    body = "".join(table_rows) if table_rows else ""

    range_start = (page - 1) * per_page + 1 if total_count > 0 else 0
    range_end = min(page * per_page, total_count)
    range_text = (
        f"Показано {range_start}–{range_end} из {total_count}" if total_count > 0 else "Нет заказов"
    )

    pagination_html = _render_pagination(filters, page, total_pages, per_page, total_count)
    sync_html = _sync_freshness_bar(last_poll_info, sync_stats, timezone)
    kpi_html = _orders_kpi_html(summary) if summary else ""

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
      {kpi_html}
      {_orders_filters(filters)}
      <section class="band">
        <div class="orders-toolbar" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <h2 style="margin:0;font-size:16px">Операции</h2>
          <div class="orders-toolbar-right" style="display:flex;align-items:center;gap:8px">
            <span class="muted" style="font-size:13px">{range_text}</span>
            <a class="button-tiny" href="/web/sync-center?tab=sync">Обновить</a>
          </div>
        </div>
        {empty_html}
        {_orders_table_html(body, rows)}
        {pagination_html}
      </section>
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
                <th>Дата</th><th>МП</th><th>Модель</th><th>Заказ</th>
                <th>Товар</th><th class="num">Кол-во</th>
                <th class="num">Цена</th><th class="num">План. прибыль</th>
                <th class="num">Маржа</th><th>Статус</th>
                <th>Проблемы</th><th></th>
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


def _wb_assembly_id(order: Any) -> str | None:
    if order.assembly_id:
        return order.assembly_id
    payload_id = getattr(order, "raw_payload", {}).get("id")
    if payload_id:
        return str(payload_id)
    if order.order_external_id:
        return str(order.order_external_id)
    return None


def _order_main_id(order: Any) -> str:
    if order.marketplace == Marketplace.WB:
        aid = _wb_assembly_id(order)
        if aid:
            return escape(aid)
    return escape(order.order_external_id)


def _marketplace_id_label(marketplace: Marketplace) -> str:
    return "Заказ WB" if marketplace == Marketplace.WB else "Заказ Ozon"


def _marketplace_posting_label(marketplace: Marketplace) -> str:
    return "Отправление" if marketplace == Marketplace.WB else "Отправление Ozon"


def _wb_fact_income_row(detail: OrderDetail) -> str:
    income = getattr(detail, "wb_fact_income", None)
    if income is None:
        return ""
    return f'<span>Факт к получению от WB</span><strong>{_rub(income)}</strong>'


def _order_extra_ids(order: Any) -> str:
    parts = []
    aid = _wb_assembly_id(order) if order.marketplace == Marketplace.WB else None
    if aid:
        srid_text = order.srid or order.order_external_id
        if srid_text != aid:
            parts.append(f'<div class="muted">SRID: {escape(srid_text)}</div>')
    if order.posting_number:
        label = "Отправление" if order.marketplace == Marketplace.WB else "Отправление Ozon"
        parts.append(f'<div class="muted">{label}: {escape(order.posting_number)}</div>')
    return "".join(parts)


def _economy_status_badge(economy_confidence: str | None, missing_cost: bool, profit: Decimal | None) -> str:
    if missing_cost:
        return '<span class="badge bad">Нет себестоимости</span>'
    if economy_confidence == "EXACT":
        return '<span class="badge good">Факт</span>'
    if economy_confidence == "ESTIMATED":
        return '<span class="badge warn">Оценка</span>'
    return '<span class="badge">План (предв.)</span>'
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


def _order_detail_item_economics_rows(detail: OrderDetail) -> str:
    rows_html = []
    for item_detail in detail.items:
        item = item_detail.item
        estimated = item_detail.estimated_snapshot
        actual = item_detail.actual_snapshot
        estimated_profit = estimated.profit if estimated else item.profit_estimated
        actual_profit = (
            item_detail.corrected_actual_profit
            if item_detail.corrected_actual_profit is not None
            else actual.profit if actual else None
        )
        revenue = item.discounted_price * item.quantity
        total_costs = (
            (item.commission_estimated or ZERO)
            + (item.logistics_estimated or ZERO)
            + (item.cost_price_used or ZERO)
            + (item.package_cost_used or ZERO)
            + (item.tax_amount_estimated or ZERO)
        )
        margin_val = None
        if revenue > 0 and estimated_profit is not None:
            margin_val = (estimated_profit / revenue * Decimal("100")).quantize(Decimal("0.1"))

        rows_html.append("<tr>")
        rows_html.append(f"<td>{escape(item.title or 'Без названия')}</td>")
        rows_html.append(f"<td class=\"num\">{item.quantity}</td>")
        rows_html.append(f"<td class=\"num\">{_rub(revenue)}</td>")
        rows_html.append(f"<td class=\"num\">{_rub_optional(item.commission_estimated)}</td>")
        rows_html.append(f"<td class=\"num\">{_rub_optional(item.logistics_estimated)}</td>")
        rows_html.append(f"<td class=\"num\">{_rub_optional(item.cost_price_used)}</td>")
        cost_tone = "warn" if item.cost_price_used is None or item.cost_price_used == 0 else ""
        rows_html.append(f"<td class=\"num\">{_rub_optional(item.package_cost_used)}</td>")
        rows_html.append(f"<td class=\"num\">{_rub_optional(item.tax_amount_estimated)}</td>")
        rows_html.append(f"<td class=\"num {_economy_tone(estimated_profit)}\">{_rub_optional(estimated_profit)}</td>")
        rows_html.append(f"<td class=\"num {_economy_tone(actual_profit)}\">{_rub_optional(actual_profit)}</td>")
        rows_html.append(f"<td class=\"num\">{_percent_optional(margin_val)}</td>")
        rows_html.append(f"<td>{_confidence_badge(str(item.economy_confidence or 'PRELIMINARY'))}</td>")
        rows_html.append("</tr>")

    return "".join(rows_html)


def _order_detail_header(detail: OrderDetail, timezone: str) -> str:
    order = detail.order
    order_date = localized_order_date(order.order_date, timezone)
    deadline = (
        localized_order_date(order.processing_deadline_at, timezone)
        if order.processing_deadline_at
        else "—"
    )
    sync_at = localized_order_date(order.updated_at, timezone) if hasattr(order, 'updated_at') and order.updated_at else "—"

    indicators = []
    indicators.append('<span class="badge good" title="Заказ создан">✓ Создан</span>')
    indicators.append(f'<span class="badge" title="Обновлён">{sync_at}</span>')
    if detail.actual_profit is not None:
        indicators.append('<span class="badge good" title="Есть финансовые данные">💰 Финансы</span>')
    if detail.has_missing_cost_price:
        indicators.append('<span class="badge warn" title="Себестоимость не задана">⚠ Себестоимость</span>')
    else:
        indicators.append('<span class="badge good" title="Себестоимость задана">✓ Себестоимость</span>')
    if detail.reconciliation_status in (ReconciliationStatus.FACT_MATCHED, ReconciliationStatus.FACT_PARTIAL):
        indicators.append('<span class="badge good" title="Экономика рассчитана">✓ Экономика</span>')
    else:
        indicators.append('<span class="badge warn" title="Экономика не рассчитана">○ Экономика</span>')
    if detail.reconciliation_status in (ReconciliationStatus.FACT_AMBIGUOUS, ReconciliationStatus.MANUAL_REVIEW, ReconciliationStatus.ERROR_STATUS):
        indicators.append('<span class="badge bad" title="Есть ошибки">✗ Ошибки</span>')

    model_str = order.sale_model.value if order.sale_model else "—"
    status_str = order_state_label(order.normalized_status or order.status, order.requires_seller_action)
    source_str = source_event_label(order.source_event_type) if order.source_event_type else "—"

    return f"""
      <div class="detail-header" style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:20px">
        <div>
          <h1 style="margin:0 0 6px 0;font-size:22px">
            {'Заказ' if order.marketplace == Marketplace.WB else 'Заказ'} №{escape(order.order_external_id)}
          </h1>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            {_marketplace_label(order.marketplace)}
            <span class="badge">{model_str}</span>
            <span class="badge">{escape(source_str)}</span>
            <span class="muted" style="font-size:12px">от {order_date}</span>
          </div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:4px;align-items:center">
          {" ".join(indicators)}
        </div>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:16px;margin-bottom:16px;font-size:13px;background:var(--bg-card);padding:12px 16px;border:1px solid var(--border);border-radius:var(--radius)">
        <div><span class="muted">Статус:</span> <strong>{_order_status_badge(order.normalized_status or order.status, order.requires_seller_action)}</strong></div>
        <div><span class="muted">Дедлайн:</span> <strong>{deadline}</strong></div>
        <div><span class="muted">Синхронизация:</span> <strong>{sync_at}</strong></div>
        <div><span class="muted">Позиций:</span> <strong>{len(order.items)}</strong></div>
      </div>
    """


def _order_detail_economics(detail: OrderDetail) -> str:
    order = detail.order
    total_revenue = ZERO
    total_commission = ZERO
    total_logistics = ZERO
    total_cost_price = ZERO
    total_package = ZERO
    total_tax = ZERO
    total_other_mp = ZERO
    for item_detail in detail.items:
        item = item_detail.item
        qty = item.quantity
        total_revenue += item.discounted_price * qty
        total_commission += item.commission_estimated or ZERO
        total_logistics += item.logistics_estimated or ZERO
        total_cost_price += (item.cost_price_used or ZERO) * qty
        total_package += (item.package_cost_used or ZERO) * qty
        total_tax += item.tax_amount_estimated or ZERO
        total_other_mp += item.other_marketplace_expenses_estimated or ZERO

    total_mp_costs = total_commission + total_logistics + total_other_mp
    total_seller_costs = total_cost_price + total_package + total_tax
    estimated_profit = detail.estimated_profit

    margin_val = None
    if total_revenue > 0:
        margin_val = (estimated_profit / total_revenue * Decimal("100")).quantize(Decimal("0.1"))

    cost_price = total_cost_price / max(len(detail.items), 1)

    roi_val = None
    if cost_price > 0:
        roi_val = (estimated_profit / cost_price * Decimal("100")).quantize(Decimal("0.1"))

    row = lambda label, value, tone="": f"<tr><td>{escape(label)}</td><td class=\"num {tone}\">{value}</td></tr>"

    rows = []
    rows.append(row("Цена продажи", _rub(total_revenue)))
    rows.append(row("Комиссия маркетплейса", _rub(total_commission), "muted"))
    rows.append(row("Логистика", _rub(total_logistics), "muted"))
    if total_other_mp > 0:
        rows.append(row("Прочие расходы МП", _rub(total_other_mp), "muted"))
    rows.append(row("---", "---"))
    rows.append(row("Расходы МП", _rub(total_mp_costs), "muted"))
    rows.append(row("Себестоимость", _rub(total_cost_price), "warn" if detail.has_missing_cost_price else ""))
    rows.append(row("Упаковка", _rub(total_package)))
    rows.append(row("Налог", _rub(total_tax)))
    if detail.actual_profit is not None:
        rows.append(row("Фактическая прибыль", _rub(detail.actual_profit), _economy_tone(detail.actual_profit)))
        if detail.deviation is not None:
            dev_tone = "good" if detail.deviation >= 0 else "bad"
            rows.append(row("Отклонение", _rub(detail.deviation), dev_tone))
    rows.append(row("Плановая прибыль", _rub(estimated_profit), _economy_tone(estimated_profit)))
    rows.append(row("Маржа", _percent_optional(margin_val), _margin_tone(margin_val)))
    if roi_val is not None:
        rows.append(row("ROI", _percent_optional(roi_val)))

    if detail.has_missing_cost_price:
        warning = '<div class="band warn" style="margin-top:12px;padding:10px;font-size:13px">⚠ Не задана себестоимость для некоторых товаров. Плановая прибыль может быть завышена.</div>'
    else:
        warning = ""

    return f"""
      <section class="band" style="margin-top:16px">
        <h2 style="font-size:15px;margin-bottom:10px">Экономика заказа</h2>
        {warning}
        <div class="table-wrap">
          <table class="table economics-table" style="max-width:500px">
            <tbody>{"".join(rows)}</tbody>
          </table>
        </div>
      </section>
    """


def _order_detail_financial_rows(detail: OrderDetail, timezone_name: str | None = None) -> str:
    rows = detail.ozon_fact.rows if detail.ozon_fact else []
    if detail.wb_fact and (detail.wb_fact.linked_rows or detail.wb_fact.unlinked_product_rows):
        all_wb_rows = list(detail.wb_fact.linked_rows)
        if detail.order.srid:
            srid_filtered = [r for r in detail.wb_fact.unlinked_product_rows if r.srid == detail.order.srid]
            all_wb_rows.extend(srid_filtered)
        else:
            all_wb_rows.extend(detail.wb_fact.unlinked_product_rows)

        if all_wb_rows:
            wb_table_rows = []
            for r in all_wb_rows:
                sale_dt = getattr(r, "sale_dt", None)
                wb_table_rows.append(
                    "<tr>"
                    f"<td>{escape(format_datetime_for_user(sale_dt, timezone_name) if sale_dt else '—')}</td>"
                    f"<td>Отчёт WB</td>"
                    f"<td>—</td>"
                    f"<td class=\"num\">{_rub(getattr(r, 'retail_amount', None))}</td>"
                    f"<td class=\"num\">{_rub(getattr(r, 'commission_rub', None))}</td>"
                    f"<td class=\"num\">{_rub(getattr(r, 'delivery_rub', None))}</td>"
                    f"<td class=\"num\">{_rub(getattr(r, 'penalty', None))}</td>"
                    f"<td class=\"num\">{_rub(getattr(r, 'for_pay', None))}</td>"
                    f"<td class=\"muted\">API WB</td>"
                    f"<td class=\"muted\">{escape(str(getattr(r, 'srid', 'н/д')))}</td>"
                    "</tr>"
                )

            if rows or wb_table_rows:
                fin_rows = "".join(wb_table_rows)
                return f"""
                  <section class="band" style="margin-top:16px">
                    <h2 style="font-size:15px;margin-bottom:10px">Финансовые проводки</h2>
                    <div class="table-wrap">
                      <table class="table">
                        <thead>
                          <tr>
                            <th>Дата</th><th>Тип</th><th>Категория</th>
                            <th class="num">Сумма</th><th class="num">Комиссия</th>
                            <th class="num">Логистика</th><th class="num">Штрафы</th>
                            <th class="num">К перечислению</th><th>Источник</th><th>ID</th>
                          </tr>
                        </thead>
                        <tbody>{fin_rows}</tbody>
                      </table>
                    </div>
                  </section>
                """

    if rows:
        ozon_rows = "".join(
            "<tr>"
            f"<td>{escape(format_datetime_for_user(r.operation_date, timezone_name) if r.operation_date else '—')}</td>"
            f"<td>{escape(r.operation_type or '—')}</td>"
            f"<td>{escape(r.operation_category or '—')}</td>"
            f"<td class=\"num\">{_rub(r.amount)}</td>"
            f"<td>—</td><td>—</td><td>—</td><td>—</td>"
            f"<td>API Ozon</td>"
            f"<td class=\"muted\">{escape(r.external_row_id or 'н/д')}</td>"
            "</tr>"
            for r in rows
        )
        return f"""
          <section class="band" style="margin-top:16px">
            <h2 style="font-size:15px;margin-bottom:10px">Финансовые проводки</h2>
            <div class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th>Дата</th><th>Тип</th><th>Категория</th>
                    <th class="num">Сумма</th><th class="num">Комиссия</th>
                    <th class="num">Логистика</th><th class="num">Штрафы</th>
                    <th class="num">К перечислению</th><th>Источник</th><th>ID</th>
                  </tr>
                </thead>
                <tbody>{ozon_rows}</tbody>
              </table>
            </div>
          </section>
        """

    return ""


def _order_detail_marketplace_data(detail: OrderDetail, is_admin: bool = False) -> str:
    order = detail.order
    raw_payload = escape(json.dumps(order.raw_payload or {}, ensure_ascii=False, indent=2))

    # Common fields
    common_fields = [
        ("ID заказа", str(order.id)),
        ("Внешний ID", str(order.order_external_id) if order.order_external_id else "—"),
        ("SRID", str(order.srid) if order.srid else "—"),
        ("Posting Number", str(order.posting_number) if order.posting_number else "—"),
        ("Статус", str(order.normalized_status or order.status)),
        ("Модель продаж", order.sale_model.value if order.sale_model else "—"),
        ("Дата заказа", localized_order_date(order.order_date, "Europe/Moscow")),
        ("Создан", str(order.created_at) if hasattr(order, 'created_at') and order.created_at else "—"),
        ("Обновлён", str(order.updated_at) if hasattr(order, 'updated_at') and order.updated_at else "—"),
        ("Тип события", order.source_event_type.value if order.source_event_type else "—"),
        ("Склад", str(order.warehouse) if order.warehouse else "—"),
        ("Требует действий", "Да" if order.requires_seller_action else "Нет"),
    ]

    common_rows = "".join(f"<tr><td>{escape(k)}</td><td>{escape(str(v))}</td></tr>" for k, v in common_fields)

    # WB-specific fields
    wb_rows = ""
    if order.marketplace == Marketplace.WB:
        wb_fields = [
            ("nmId", str(order.raw_payload.get("nmId", "—")) if order.raw_payload else "—"),
            ("barcode", str(order.raw_payload.get("barcode", "—")) if order.raw_payload else "—"),
            ("supplierArticle", str(order.raw_payload.get("supplierArticle", "—")) if order.raw_payload else "—"),
            ("saleDt", str(order.raw_payload.get("saleDt", "—")) if order.raw_payload else "—"),
            ("orderDt", str(order.raw_payload.get("orderDt", "—")) if order.raw_payload else "—"),
            ("forPay", str(order.raw_payload.get("forPay", "—")) if order.raw_payload else "—"),
            ("finishedPrice", str(order.raw_payload.get("finishedPrice", "—")) if order.raw_payload else "—"),
            ("priceWithDisc", str(order.raw_payload.get("priceWithDisc", "—")) if order.raw_payload else "—"),
            ("spp", str(order.raw_payload.get("spp", "—")) if order.raw_payload else "—"),
            ("warehouseName", str(order.raw_payload.get("warehouseName", "—")) if order.raw_payload else "—"),
            ("countryName", str(order.raw_payload.get("countryName", "—")) if order.raw_payload else "—"),
            ("regionName", str(order.raw_payload.get("regionName", "—")) if order.raw_payload else "—"),
            ("oblastOkrugName", str(order.raw_payload.get("oblastOkrugName", "—")) if order.raw_payload else "—"),
        ]
        wb_rows = "".join(f"<tr><td>{escape(k)}</td><td>{escape(str(v))}</td></tr>" for k, v in wb_fields)

    # Ozon-specific fields
    ozon_rows = ""
    if order.marketplace == Marketplace.OZON:
        ozon_fields = [
            ("posting_number", str(order.posting_number) if order.posting_number else "—"),
            ("offer_id", str(order.raw_payload.get("offer_id", "—")) if order.raw_payload else "—"),
            ("product_id", str(order.raw_payload.get("product_id", "—")) if order.raw_payload else "—"),
            ("sku", str(order.raw_payload.get("sku", "—")) if order.raw_payload else "—"),
            ("delivery_method", str(order.raw_payload.get("delivery_method", "—")) if order.raw_payload else "—"),
            ("warehouse", str(order.raw_payload.get("warehouse", "—")) if order.raw_payload else "—"),
            ("region", str(order.raw_payload.get("region", "—")) if order.raw_payload else "—"),
        ]
        ozon_rows = "".join(f"<tr><td>{escape(k)}</td><td>{escape(str(v))}</td></tr>" for k, v in ozon_fields)

    return f"""
      <section class="band" style="margin-top:16px">
        <h2 style="font-size:15px;margin-bottom:10px">Данные маркетплейса</h2>
        <div style="display:flex;flex-wrap:wrap;gap:16px">
          <div style="flex:1;min-width:300px">
            <h3 style="font-size:13px;margin-bottom:6px">Общее</h3>
            <div class="table-wrap">
              <table class="table compact">
                <tbody>{common_rows}</tbody>
              </table>
            </div>
          </div>
          {f'<div style="flex:1;min-width:300px"><h3 style="font-size:13px;margin-bottom:6px">Wildberries</h3><div class="table-wrap"><table class="table compact"><tbody>{wb_rows}</tbody></table></div></div>' if wb_rows else ''}
          {f'<div style="flex:1;min-width:300px"><h3 style="font-size:13px;margin-bottom:6px">Ozon</h3><div class="table-wrap"><table class="table compact"><tbody>{ozon_rows}</tbody></table></div></div>' if ozon_rows else ''}
        </div>
        {f'<details style="margin-top:16px"><summary style="cursor:pointer;font-size:13px;color:var(--muted)">📄 Исходные данные маркетплейса</summary><pre class="mono" style="margin-top:8px;font-size:11px;max-height:400px;overflow:auto;background:var(--bg-card);padding:12px;border:1px solid var(--border);border-radius:var(--radius)">{raw_payload}</pre></details>' if is_admin else ''}
      </section>
    """


def _order_detail_content(detail: OrderDetail, timezone: str, is_admin: bool = False) -> str:
    order = detail.order
    is_financial_only = getattr(detail, "is_financial_only", False)
    financial_only_warning = (
        '<div class="band warn" style="margin:14px 0;padding:14px;font-size:13px">'
        "<strong>Внимание!</strong> Эта запись, вероятно, является строкой финансового отчёта, "
        "а не реальным заказом покупателя. "
        "Она не привязана к заказу и не должна учитываться в аналитике заказов."
        "</div>"
        if is_financial_only
        else ""
    )

    header = _order_detail_header(detail, timezone)

    # Product info block
    product_rows = []
    for item_detail in detail.items:
        item = item_detail.item
        product_rows.append(
            "<tr>"
            f"<td>{escape(item.title or 'Без названия')}</td>"
            f"<td>{escape(item.seller_article or '—')}</td>"
            f"<td>{escape(item.marketplace_article or '—')}</td>"
            f"<td class=\"num\">{item.quantity}</td>"
            f"<td class=\"num\">{_rub(item.discounted_price)}</td>"
            f"<td class=\"num\">{_rub(item.discounted_price * item.quantity)}</td>"
            f"<td><a class=\"button-tiny\" href=\"/web/orders/{order.id}\">Подробнее</a></td>"
            "</tr>"
        )
    product_section = f"""
      <section class="band" style="margin-top:16px">
        <h2 style="font-size:15px;margin-bottom:10px">Товары в заказе</h2>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Название</th><th>Артикул</th><th>Артикул МП</th>
                <th class="num">Кол-во</th><th class="num">Цена</th>
                <th class="num">Сумма</th><th></th>
              </tr>
            </thead>
            <tbody>{"".join(product_rows)}</tbody>
          </table>
        </div>
      </section>
    """

    # Economics block
    economics = _order_detail_economics(detail)

    # Item-level economics table
    item_rows = _order_detail_item_economics_rows(detail)
    item_economics = f"""
      <section class="band" style="margin-top:16px">
        <h2 style="font-size:15px;margin-bottom:10px">Экономика позиций</h2>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Товар</th><th class="num">Кол-во</th><th class="num">Выручка</th>
                <th class="num">Комиссия</th><th class="num">Логистика</th>
                <th class="num">Себестоимость</th><th class="num">Упаковка</th>
                <th class="num">Налог</th><th class="num">Прибыль план</th>
                <th class="num">Прибыль факт</th><th class="num">Маржа</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>{item_rows}</tbody>
          </table>
        </div>
      </section>
    """

    # Financial rows
    fin_rows = _order_detail_financial_rows(detail, timezone)

    # Marketplace data (with tabs)
    mp_data = _order_detail_marketplace_data(detail, is_admin=is_admin)

    return f"""
      {financial_only_warning}
      {header}
      {product_section}
      {economics}
      {item_economics}
      {fin_rows}
      {mp_data}
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
