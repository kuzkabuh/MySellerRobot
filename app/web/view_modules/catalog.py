"""version: 1.0.0
description: Catalog, stock, alert, and product cost HTML view helpers.
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

from app.web.view_modules.common import _page_header, _section_subnav
from app.web.view_modules.components import _simple_kpi
from app.web.view_modules.formatting import _alert_delivery_badge, _alert_type_badge, _cost_status_badge, _dt, _marketplace_label, _percent_optional, _rub, _sale_model_badge
from app.web.view_modules.forms import _select
from app.web.view_modules.pricing import _ozon_price_label

__all__ = [
    "_products_content",
    "_master_product_detail_content",
    "_product_matching_content",
    "_stocks_forecast_content",
    "_filter_stock_rows",
    "_stock_filters",
    "_alerts_content",
    "_costs_content",
    "_cost_edit_content",
]


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
