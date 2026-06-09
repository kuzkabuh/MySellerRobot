"""version: 1.0.0
description: Order, sale, return, and order reconciliation HTML view helpers.
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
            f"<td><strong>Заказ WB:</strong> {escape(row.order_external_id)}"
            f'<div class="muted">Отправление: {escape(row.posting_number or "н/д")}</div></td>'
            f'<td class="num">{row.quantity}</td>'
            f'<td class="num">{_rub(row.revenue)}</td>'
            f"{profit_cell}"
            f'<td class="num">{_percent_optional(row.margin_percent)}</td>'
            f"<td>{_order_status_badge(row.status, row.requires_action)}"
            f"<div>{_reconciliation_badge(getattr(row, 'reconciliation_status', None))}</div>"
            f"<div>{confidence_badge}</div></td>"
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
      {_section_subnav_orders("orders")}
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
                <th>Идентификаторы</th><th class="num">Кол-во</th>
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
            f'<div class="muted">nm_id: {escape(item.marketplace_article or "н/д")}</div>'
            f'<div class="muted">product_id: {escape(str(item.product_id or "н/д"))}</div></td>'
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
    is_financial_only = getattr(detail, "is_financial_only", False)
    financial_only_warning = (
        '<div class="band warn" style="margin:14px 0;padding:14px">'
        "<strong>Внимание!</strong> Эта запись, вероятно, является строкой финансового отчёта, "
        "а не реальным заказом покупателя. "
        "Она не привязана к заказу и не должна учитываться в аналитике заказов."
        "</div>"
        if is_financial_only
        else ""
    )
    return f"""
      {_section_subnav_orders("orders")}
      {financial_only_warning}
      <section class="detail-grid">
        <section class="band">
          <h2>Информация</h2>
          <div class="kv">
            <span>Маркетплейс</span><strong>{_marketplace_label(order.marketplace)}</strong>
            <span>Модель</span><strong>{sale_model}</strong>
            <span>Статус</span><strong>{_order_status_badge(order.normalized_status or order.status, order.requires_seller_action)}</strong>
            <span>Дата заказа</span><strong>{order_date}</strong>
            <span>Дедлайн</span><strong>{deadline}</strong>
            <span>Заказ WB</span><strong>{escape(order.order_external_id)}</strong>
            <span>Srid</span><strong>{escape(order.srid or "н/д")}</strong>
            <span>ШК / posting</span><strong>{escape(order.posting_number or "н/д")}</strong>
            <span>Действие</span><strong>{order_state}</strong>
          </div>
        </section>
        <section class="band">
          <h2>План / факт</h2>
          <div class="kv">
            <span>Плановая прибыль</span><strong>{_rub(detail.estimated_profit)}</strong>
            <span>Фактическая прибыль</span><strong>{_rub_optional(detail.actual_profit)}</strong>
            <span>Отклонение</span><strong>{_rub_optional(detail.deviation)}</strong>
            <span>Статус сверки</span><strong>{_reconciliation_badge(getattr(detail, "reconciliation_status", None))}</strong>
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
      {wb_fact_html}
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
        f'  <div class="muted">{_nm_barcode(row.nm_id, row.barcode)}</div>'
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

def _nm_barcode(nm_id: int | None, barcode: str | None) -> str:
    parts = []
    if nm_id:
        parts.append(f"NM {nm_id}")
    if barcode:
        parts.append(f"ШК {barcode}")
    return " / ".join(parts) if parts else ""

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
