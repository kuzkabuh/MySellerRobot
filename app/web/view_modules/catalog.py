"""version: 1.1.0
description: Catalog, stock, alert, and product cost HTML view helpers.
updated: 2026-06-11
"""

# ruff: noqa: E501, F401, E402, F811, I001

from decimal import Decimal
from html import escape
from datetime import UTC, datetime, timedelta

from app.models.domain import AlertEvent
from app.models.enums import Marketplace
from app.services.common.data_quality_service import DataQualityReport
from app.services.common.marketplace_presentation import (
    marketplace_css_class,
    marketplace_title,
)
from app.services.unit_economics.master_product_service import (
    CostHistoryPoint,
    MasterProductAnalyticsRow,
    MasterProductDetail,
    PriceHistoryPoint,
    ProductMatchingCandidate,
    StockHistoryPoint,
)
from app.services.unit_economics.stock_forecast_service import (
    StockForecastRow,
    stock_status_label,
    stock_status_tone,
)
from app.services.account.web_cabinet_service import (
    CostsPageData,
    ProductCostDetail,
)
from app.utils.datetime import format_datetime_for_user

from app.web.view_modules.common import _page_header, _section_subnav_products
from app.web.view_modules.components import _simple_kpi
from app.web.view_modules.formatting import (
    _alert_delivery_badge,
    _alert_type_badge,
    _cost_status_badge,
    _dt,
    _marketplace_label,
    _percent_optional,
    _rub,
    _sale_model_badge,
)
from app.web.view_modules.forms import _select

ZERO = Decimal("0")

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
    "_product_issues_content",
]


def _status_badge(status: str, level: str) -> str:
    return f'<span class="badge {escape(level)}">{escape(status)}</span>'


def _mp_badge_short(mp: str) -> str:
    css = marketplace_css_class(mp)
    return f'<span class="marketplace-badge {css}"><span class="mp-logo">{mp[:2].upper()}</span></span>'


def _filter_rows(
    rows: list[MasterProductAnalyticsRow],
    *,
    search: str = "",
    sku: str = "",
    marketplace: str = "all",
    status_filter: str = "all",
    brand: str = "",
    category: str = "",
    sort: str = "profit_desc",
) -> list[MasterProductAnalyticsRow]:
    q = search.strip().lower()
    if q:
        rows = [r for r in rows if q in (r.title or "").lower() or q in (r.brand or "").lower() or q in (r.category or "")]
    if sku:
        sku_q = sku.strip().lower()
        rows = [r for r in rows if sku_q in r.canonical_sku.lower()]
    if marketplace != "all":
        if marketplace == "wb":
            rows = [r for r in rows if r.wb_products]
        elif marketplace == "ozon":
            rows = [r for r in rows if r.ozon_products]
        elif marketplace == "both":
            rows = [r for r in rows if r.wb_products and r.ozon_products]
    if status_filter != "all":
        sm = {
            "ok": "\u0412 \u043d\u043e\u0440\u043c\u0435",
            "loss": "\u0412 \u043c\u0438\u043d\u0443\u0441\u0435",
            "no_cost": "\u041d\u0435\u0442 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438",
            "no_stock": "\u041d\u0435\u0442 \u043e\u0441\u0442\u0430\u0442\u043a\u043e\u0432",
            "unmatched": "\u041d\u0435 \u0441\u043e\u043f\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d",
        }
        target = sm.get(status_filter, "")
        if target:
            rows = [r for r in rows if r.status == target]
    if brand:
        bq = brand.strip().lower()
        rows = [r for r in rows if bq in (r.brand or "").lower()]
    if category:
        cq = category.strip().lower()
        rows = [r for r in rows if cq in (r.category or "").lower()]
    sk = {
        "profit_desc": lambda r: (-r.estimated_profit, r.title or ""),
        "profit_asc": lambda r: (r.estimated_profit, r.title or ""),
        "revenue": lambda r: (-r.revenue, r.title or ""),
        "orders": lambda r: (-r.orders, r.title or ""),
        "stock": lambda r: (-r.stock_quantity, r.title or ""),
        "margin": lambda r: (-(r.estimated_profit / r.revenue * 100 if r.revenue else ZERO), r.title or ""),
        "updated": lambda r: (-(r.updated_at.timestamp() if r.updated_at else 0), r.title or ""),
    }.get(sort, lambda r: (-r.estimated_profit, r.title or ""))
    rows.sort(key=sk)
    return rows


def _kpi_cards(rows: list[MasterProductAnalyticsRow]) -> str:
    total = len(rows)
    matched = sum(1 for r in rows if r.wb_products and r.ozon_products)
    no_cost = sum(1 for r in rows if r.status == "\u041d\u0435\u0442 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438")
    neg = sum(1 for r in rows if r.estimated_profit < 0)
    no_st = sum(1 for r in rows if r.stock_quantity <= 0)
    attn = sum(1 for r in rows if r.status_level in {"bad", "warn"})
    return f"""      <section class="kpi-grid">
        {_simple_kpi("\u0412\u0441\u0435\u0433\u043e \u0442\u043e\u0432\u0430\u0440\u043e\u0432", str(total), "neutral")}
        {_simple_kpi("\u0421\u043e\u043f\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d\u043e", str(matched), "good" if matched else "neutral")}
        {_simple_kpi("\u0411\u0435\u0437 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438", str(no_cost), "warn" if no_cost else "neutral")}
        {_simple_kpi("\u0412 \u043c\u0438\u043d\u0443\u0441\u0435", str(neg), "bad" if neg else "neutral")}
        {_simple_kpi("\u041d\u0435\u0442 \u043e\u0441\u0442\u0430\u0442\u043a\u043e\u0432", str(no_st), "warn" if no_st else "neutral")}
        {_simple_kpi("\u0422\u0440\u0435\u0431\u0443\u044e\u0442 \u0432\u043d\u0438\u043c\u0430\u043d\u0438\u044f", str(attn), "warn" if attn else "good")}
      </section>
"""



def _product_filters(search: str, sku: str, mp: str, st: str) -> str:
    return f"""      <form class="filters" method="get" action="/web/products">
        <div><label>\u041f\u043e\u0438\u0441\u043a</label><input type="text" name="search" placeholder="\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435, \u0431\u0440\u0435\u043d\u0434..." value="{escape(search)}"></div>
        <div><label>SKU</label><input type="text" name="sku" placeholder="\u0410\u0440\u0442\u0438\u043a\u0443\u043b..." value="{escape(sku)}"></div>
        {_select("marketplace", "\u041f\u043b\u043e\u0449\u0430\u0434\u043a\u0430", {"all": "\u0412\u0441\u0435", "wb": "WB", "ozon": "Ozon", "both": "WB+Ozon"}, mp)}
        {_select("status", "\u0421\u0442\u0430\u0442\u0443\u0441", {"all": "\u0412\u0441\u0435", "ok": "\u0412 \u043d\u043e\u0440\u043c\u0435", "loss": "\u0412 \u043c\u0438\u043d\u0443\u0441\u0435", "no_cost": "\u041d\u0435\u0442 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438", "no_stock": "\u041d\u0435\u0442 \u043e\u0441\u0442\u0430\u0442\u043a\u043e\u0432", "unmatched": "\u041d\u0435 \u0441\u043e\u043f\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d"}, st)}
        {_select("sort", "\u0421\u043e\u0440\u0442\u0438\u0440\u043e\u0432\u043a\u0430", {"profit_desc": "\u041f\u0440\u0438\u0431\u044b\u043b\u044c \u2193", "profit_asc": "\u041f\u0440\u0438\u0431\u044b\u043b\u044c \u2191", "revenue": "\u0412\u044b\u0440\u0443\u0447\u043a\u0430", "orders": "\u0417\u0430\u043a\u0430\u0437\u044b", "stock": "\u041e\u0441\u0442\u0430\u0442\u043a\u0438", "margin": "\u041c\u0430\u0440\u0436\u0430", "updated": "\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435"}, "profit_desc")}
        <button class="button primary" type="submit">\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c</button>
      </form>
"""


def _product_table_row(row: MasterProductAnalyticsRow) -> str:
    img = (
        f'<img src="{escape(row.image_url)}" alt="" style="width:40px;height:40px;object-fit:cover;border-radius:6px" onerror="this.style.display=\'none\'">'
        if row.image_url
        else '<div class="product-thumb" style="width:40px;height:40px">\u2014</div>'
    )
    badges = ""
    if row.wb_products:
        badges += _mp_badge_short("wb")
    if row.ozon_products:
        badges += _mp_badge_short("ozon")
    buyout_value = (
        Decimal(str(row.sales)) / Decimal(str(row.orders)) * Decimal("100")
        if row.orders
        else None
    )
    buyout = _percent_optional(buyout_value)
    profit_tone = "tone-bad" if row.estimated_profit < 0 else "tone-good" if row.estimated_profit > 0 else ""
    margin = (
        _percent_optional((row.estimated_profit / row.revenue * Decimal("100")).quantize(Decimal("0.1")))
        if row.revenue
        else "\u2014"
    )
    return (
        "<tr>"
        f'<td style="min-width:200px"><div style="display:flex;align-items:center;gap:8px">'
        f'{img}<div>'
        f'<a href="/web/products/{row.master_product_id}" style="font-weight:600;text-decoration:none">{escape(row.title or "\u0411\u0435\u0437 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u044f")}</a>'
        f'<div style="display:flex;gap:4px;margin-top:2px">'
        f'<span class="muted" style="font-size:11px">{escape(row.brand or "\u2014")}</span>'
        f'<span class="muted" style="font-size:11px"> \u00b7 {escape(row.category or "\u2014")}</span>'
        f"</div></div></div></td>"
        f'<td style="white-space:nowrap">{escape(row.canonical_sku)}</td>'
        f"<td>{badges}</td>"
        f'<td class="num">{row.orders}</td>'
        f'<td class="num">{buyout}</td>'
        f'<td class="num">{_rub(row.revenue)}</td>'
        f'<td class="num"><span class="{profit_tone}">{_rub(row.estimated_profit)}</span></td>'
        f'<td class="num" style="font-size:12px">{margin}</td>'
        f'<td class="num">{row.stock_quantity}</td>'
        f'<td>{_status_badge(row.status, row.status_level)}</td>'
        "</tr>"
    )


def _products_content(
    rows: list[MasterProductAnalyticsRow],
    *,
    search: str = "",
    sku: str = "",
    marketplace: str = "all",
    status_filter: str = "all",
    brand: str = "",
    category: str = "",
    sort: str = "profit_desc",
) -> str:
    filtered = _filter_rows(rows, search=search, sku=sku, marketplace=marketplace, status_filter=status_filter, brand=brand, category=category, sort=sort)
    body = "".join(_product_table_row(r) for r in filtered)
    if not body:
        body = '<tr><td colspan="10" class="muted" style="text-align:center;padding:40px">\u0422\u043e\u0432\u0430\u0440\u044b \u043f\u043e\u043a\u0430 \u043d\u0435 \u0438\u043c\u043f\u043e\u0440\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u044b.</td></tr>'
    return f"""      {_section_subnav_products("products")}
      {_kpi_cards(rows)}
      {_product_filters(search, sku, marketplace, status_filter)}
      <section class="band">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <h2 style="margin:0">\u0421\u043f\u0438\u0441\u043e\u043a \u0442\u043e\u0432\u0430\u0440\u043e\u0432</h2>
          <span class="muted" style="font-size:12px">{len(filtered)} \u0438\u0437 {len(rows)}</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr>
              <th>\u0422\u043e\u0432\u0430\u0440</th><th>SKU</th><th>\u041f\u043b\u043e\u0449\u0430\u0434\u043a\u0438</th>
              <th class="num">\u0417\u0430\u043a\u0430\u0437\u044b</th><th class="num">\u0412\u044b\u043a\u0443\u043f</th>
              <th class="num">\u0412\u044b\u0440\u0443\u0447\u043a\u0430</th><th class="num">\u041f\u0440\u0438\u0431\u044b\u043b\u044c</th>
              <th class="num">\u041c\u0430\u0440\u0436\u0430</th><th class="num">\u041e\u0441\u0442\u0430\u0442\u043e\u043a</th><th>\u0421\u0442\u0430\u0442\u0443\u0441</th>
            </tr></thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>
"""



def _product_tabs(active: str, pid: int) -> str:
    tabs = [
        ("overview", "\u041e\u0431\u0437\u043e\u0440"),
        ("marketplaces", "\u041c\u0430\u0440\u043a\u0435\u0442\u043f\u043b\u0435\u0439\u0441\u044b"),
        ("finances", "\u0424\u0438\u043d\u0430\u043d\u0441\u044b"),
        ("prices", "\u0426\u0435\u043d\u044b"),
        ("stocks", "\u041e\u0441\u0442\u0430\u0442\u043a\u0438"),
        ("orders", "\u0417\u0430\u043a\u0430\u0437\u044b"),
        ("costs", "\u0421\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c"),
        ("history", "\u0418\u0441\u0442\u043e\u0440\u0438\u044f"),
        ("issues", "\u041f\u0440\u043e\u0431\u043b\u0435\u043c\u044b \u0434\u0430\u043d\u043d\u044b\u0445"),
    ]
    return '<div class="subnav">' + "".join(
        f'<a class="{"active" if k == active else ""}" href="/web/products/{pid}?tab={k}">{l}</a>'
        for k, l in tabs
    ) + "</div>"


def _detail_header(d: MasterProductDetail) -> str:
    img = (
        f'<img src="{escape(d.image_url)}" alt="" style="width:80px;height:80px;object-fit:cover;border-radius:10px" onerror="this.style.display=\'none\'">'
        if d.image_url
        else '<div class="product-thumb" style="width:80px;height:80px;font-size:12px">\u043d\u0435\u0442 \u0444\u043e\u0442\u043e</div>'
    )
    updated = f'<span class="muted" style="font-size:12px">\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u043e: {_dt(d.updated_at)}</span>' if d.updated_at else ""
    return f"""      <div style="display:flex;align-items:center;gap:16px;margin-bottom:16px">
        {img}
        <div style="flex:1;min-width:0">
          <h2 style="margin:0 0 4px">{escape(d.title)}</h2>
          <div style="display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;color:var(--text-secondary)">
            <span>\u0411\u0440\u0435\u043d\u0434: <strong>{escape(d.brand or "\u2014")}</strong></span>
            <span>\u041a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044f: <strong>{escape(d.category or "\u2014")}</strong></span>
            <span>\u0415\u0434\u0438\u043d\u044b\u0439 SKU: <strong>{escape(d.canonical_sku)}</strong></span>
          </div>
          <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
            {_status_badge(d.status, d.status_level)}{updated}
          </div>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <a class="button" href="/web/products" style="font-size:12px">\u2190 \u041d\u0430\u0437\u0430\u0434</a>
        </div>
      </div>
"""


def _summary_kpis(d: MasterProductDetail) -> str:
    total_orders = sum(c.orders for c in d.marketplace_comparison)
    total_sales = sum(c.sales for c in d.marketplace_comparison)
    total_revenue = sum(c.revenue for c in d.marketplace_comparison)
    total_profit = sum(c.estimated_profit for c in d.marketplace_comparison)
    total_stock = sum(c.stock_quantity for c in d.marketplace_comparison)
    buyout_value = (
        Decimal(str(total_sales)) / Decimal(str(total_orders)) * Decimal("100")
        if total_orders
        else None
    )
    buyout = _percent_optional(buyout_value)
    margin = _percent_optional((total_profit / total_revenue * Decimal("100")).quantize(Decimal("0.1"))) if total_revenue else "\u2014"
    avg_price = _rub(total_revenue / total_orders) if total_orders else "\u2014"
    return f"""      <section class="kpi-grid" style="grid-template-columns:repeat(4,1fr)">
        {_simple_kpi("\u0417\u0430\u043a\u0430\u0437\u044b", str(total_orders), "neutral")}
        {_simple_kpi("\u041f\u0440\u043e\u0434\u0430\u0436\u0438", str(total_sales), "good" if total_sales else "neutral")}
        {_simple_kpi("\u0412\u044b\u043a\u0443\u043f", buyout, "neutral")}
        {_simple_kpi("\u0412\u044b\u0440\u0443\u0447\u043a\u0430", _rub(total_revenue), "good" if total_revenue else "neutral")}
        {_simple_kpi("\u041f\u0440\u0438\u0431\u044b\u043b\u044c", _rub(total_profit), "good" if total_profit > 0 else "bad")}
        {_simple_kpi("\u041c\u0430\u0440\u0436\u0430", margin, "good" if total_profit > 0 else "warn")}
        {_simple_kpi("\u041e\u0441\u0442\u0430\u0442\u043e\u043a", str(total_stock), "warn" if total_stock <= 3 else "neutral")}
        {_simple_kpi("\u0421\u0440\u0435\u0434\u043d\u044f\u044f \u0446\u0435\u043d\u0430", avg_price, "neutral")}
      </section>
"""


def _comparison_table(d: MasterProductDetail) -> str:
    rows = "".join(
        "<tr>" + f"<td>{_marketplace_label(c.marketplace)}</td>"
        + f'<td class="num">{c.orders}</td>'
        + f'<td class="num">{c.sales}</td>'
        + f'<td class="num">{_rub(c.revenue)}</td>'
        + f'<td class="num">{_rub(c.estimated_profit)}</td>'
        + f'<td class="num">{_percent_optional(c.margin_percent)}</td>'
        + f'<td class="num">{c.stock_quantity}</td>'
        + "</tr>"
        for c in d.marketplace_comparison
    )
    if not rows:
        return ""
    return f"""      <section class="band">
        <h2>\u0421\u0440\u0430\u0432\u043d\u0435\u043d\u0438\u0435 WB / Ozon</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>\u041c\u041f</th><th class="num">\u0417\u0430\u043a\u0430\u0437\u044b</th><th class="num">\u041f\u0440\u043e\u0434\u0430\u0436\u0438</th><th class="num">\u0412\u044b\u0440\u0443\u0447\u043a\u0430</th><th class="num">\u041f\u0440\u0438\u0431\u044b\u043b\u044c</th><th class="num">\u041c\u0430\u0440\u0436\u0430</th><th class="num">\u041e\u0441\u0442\u0430\u0442\u043e\u043a</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
"""


def _price_history_section(h: tuple[PriceHistoryPoint, ...]) -> str:
    if not h:
        return ""
    rows = "".join(
        "<tr>" + f"<td>{_marketplace_label(p.marketplace)}</td>"
        + f'<td class="num">{_rub(p.price)}</td>'
        + f'<td class="num">{_rub(p.discounted_price)}</td>'
        + f"<td>{escape(p.date)}</td></tr>"
        for p in h
    )
    return f"""      <section class="band" style="margin-top:14px">
        <h2>\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u0446\u0435\u043d</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>\u041c\u041f</th><th class="num">\u0426\u0435\u043d\u0430</th><th class="num">\u0421\u043e \u0441\u043a\u0438\u0434\u043a\u043e\u0439</th><th>\u0414\u0430\u0442\u0430</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
"""


def _cost_history_section(h: tuple[CostHistoryPoint, ...]) -> str:
    if not h:
        return '<div class="empty-state" style="margin-top:14px">\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438 \u043f\u043e\u043a\u0430 \u043d\u0435 \u0437\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0430.</div>'
    rows = "".join(
        "<tr>" + f"<td>{escape(c.valid_from)}</td>" + f"<td>{escape(c.valid_to or '\u0442\u0435\u043a\u0443\u0449\u0430\u044f')}</td>"
        + f'<td class="num">{_rub(c.cost_price)}</td>'
        + f'<td class="num">{_rub(c.package_cost)}</td>'
        + f'<td class="num">{_rub(c.additional_cost)}</td>'
        + f'<td class="num">{_rub(c.cost_price + c.package_cost + c.additional_cost)}</td>'
        + f"<td>{escape(c.comment or '')}</td></tr>"
        for c in h
    )
    return f"""      <section class="band" style="margin-top:14px">
        <h2>\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>\u0421</th><th>\u041f\u043e</th><th class="num">\u0417\u0430\u043a\u0443\u043f\u043a\u0430</th><th class="num">\u0423\u043f\u0430\u043a\u043e\u0432\u043a\u0430</th><th class="num">\u0414\u043e\u043f.</th><th class="num">\u0418\u0442\u043e\u0433\u043e</th><th>\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
"""


def _stock_history_section(h: tuple[StockHistoryPoint, ...]) -> str:
    if not h:
        return ""
    rows = "".join(
        "<tr>" + f"<td>{escape(s.date)}</td>" + f"<td>{escape(s.warehouse) if s.warehouse else '\u0432\u0441\u0435'}</td>"
        + f'<td class="num">{s.quantity}</td>'
        + f'<td class="num">{_rub(s.avg_daily_sales) if s.avg_daily_sales else "\u2014"}</td></tr>'
        for s in h
    )
    return f"""      <section class="band" style="margin-top:14px">
        <h2>\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u043e\u0441\u0442\u0430\u0442\u043a\u043e\u0432</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>\u0414\u0430\u0442\u0430</th><th>\u0421\u043a\u043b\u0430\u0434</th><th class="num">\u041e\u0441\u0442\u0430\u0442\u043e\u043a</th><th class="num">\u041f\u0440\u043e\u0434\u0430\u0436\u0438/\u0434\u0435\u043d\u044c</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
"""


def _linked_products(d: MasterProductDetail) -> str:
    if not d.marketplace_products:
        return ""
    rows = "".join(
        "<tr>" + f"<td>{_marketplace_label(p.marketplace)}</td>"
        + f"<td>{escape(p.seller_article)}</td>"
        + f"<td>{escape(p.marketplace_article)}</td>"
        + f"<td>{escape(p.title)}</td></tr>"
        for p in d.marketplace_products
    )
    return f"""      <section class="band" style="margin-top:14px">
        <h2>\u0421\u0432\u044f\u0437\u0430\u043d\u043d\u044b\u0435 \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0438</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>\u041c\u041f</th><th>\u0410\u0440\u0442\u0438\u043a\u0443\u043b \u043f\u0440\u043e\u0434\u0430\u0432\u0446\u0430</th><th>\u0410\u0440\u0442\u0438\u043a\u0443\u043b \u041c\u041f</th><th>\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
"""


def _recommendations_block(recs: tuple[str, ...]) -> str:
    if not recs:
        return ""
    return f"""      <section class="band" style="margin-top:14px">
        <h2>\u0427\u0442\u043e \u0432\u0430\u0436\u043d\u043e</h2>
        <ul>{"".join(f"<li>{escape(r)}</li>" for r in recs)}</ul>
      </section>
"""



def _tab_overview(d: MasterProductDetail) -> str:
    return "".join([
        _summary_kpis(d),
        _comparison_table(d),
        _price_history_section(d.price_history),
        _recommendations_block(d.recommendations),
        _linked_products(d),
    ])

def _tab_marketplaces(d: MasterProductDetail, mp_filter: str) -> str:
    parts = []
    for pi in d.marketplace_products:
        if mp_filter != "all" and mp_filter != pi.marketplace.value:
            continue
        parts.append(f"""      <section class="band" style="margin-top:14px">
            <h2>{_marketplace_label(pi.marketplace)} \u2014 {escape(pi.title)}</h2>
            <div class="kv">
              <span>\u0412\u043d\u0435\u0448\u043d\u0438\u0439 ID</span><strong>{escape(pi.marketplace_article)}</strong>
              <span>\u0410\u0440\u0442\u0438\u043a\u0443\u043b \u043f\u0440\u043e\u0434\u0430\u0432\u0446\u0430</span><strong>{escape(pi.seller_article)}</strong>
            </div>
          </section>""")
    return "".join(parts) if parts else '<div class="empty-state">\u041d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445 \u043f\u043e \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u043e\u0439 \u043f\u043b\u043e\u0449\u0430\u0434\u043a\u0435.</div>'

def _tab_finances(d: MasterProductDetail) -> str:
    total_revenue = sum(c.revenue for c in d.marketplace_comparison)
    total_profit = sum(c.estimated_profit for c in d.marketplace_comparison)
    margin = _percent_optional((total_profit / total_revenue * Decimal("100")).quantize(Decimal("0.1"))) if total_revenue else "\u2014"
    return f"""      <section class="band">
        <h2>\u0424\u0438\u043d\u0430\u043d\u0441\u044b</h2>
        <div class="kv" style="grid-template-columns:minmax(180px,200px) minmax(0,1fr)">
          <span>\u041e\u0431\u0449\u0430\u044f \u0432\u044b\u0440\u0443\u0447\u043a\u0430</span><strong>{_rub(total_revenue)}</strong>
          <span>\u041e\u0431\u0449\u0430\u044f \u043f\u0440\u0438\u0431\u044b\u043b\u044c</span><strong>{_rub(total_profit)}</strong>
          <span>\u041c\u0430\u0440\u0436\u0430</span><strong>{margin}</strong>
        </div>
      </section>
      {_comparison_table(d)}
"""

def _tab_prices(d: MasterProductDetail) -> str:
    return _price_history_section(d.price_history) or '<div class="empty-state">\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u0446\u0435\u043d \u043f\u043e\u043a\u0430 \u043d\u0435 \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043d\u0430.</div>'

def _tab_stocks_tab(d: MasterProductDetail) -> str:
    return _stock_history_section(d.stock_history) or '<div class="empty-state">\u0414\u0430\u043d\u043d\u044b\u0435 \u043e\u0431 \u043e\u0441\u0442\u0430\u0442\u043a\u0430\u0445 \u043f\u043e\u043a\u0430 \u043d\u0435 \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043d\u044b.</div>'

def _tab_orders_tab(d: MasterProductDetail) -> str:
    return '<div class="empty-state">\u0420\u0430\u0437\u0434\u0435\u043b \u0437\u0430\u043a\u0430\u0437\u043e\u0432 \u043f\u043e \u0442\u043e\u0432\u0430\u0440\u0443 \u0431\u0443\u0434\u0435\u0442 \u0434\u043e\u0440\u0430\u0431\u043e\u0442\u0430\u043d.</div>'

def _tab_costs_tab(d: MasterProductDetail) -> str:
    return _cost_history_section(d.cost_history)

def _tab_history_tab(d: MasterProductDetail) -> str:
    return '<div class="empty-state">\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0439 \u0431\u0443\u0434\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430 \u0432 \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0439 \u0432\u0435\u0440\u0441\u0438\u0438.</div>'

def _tab_issues_tab(d: MasterProductDetail) -> str:
    issues = []
    if not any(c.cost_price > 0 for c in d.cost_history):
        issues.append(('\u041d\u0435\u0442 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438', 'warn', '\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u0437\u0430\u043a\u0443\u043f\u043e\u0447\u043d\u0443\u044e \u0446\u0435\u043d\u0443 \u0434\u043b\u044f \u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u043e\u0433\u043e \u0440\u0430\u0441\u0447\u0451\u0442\u0430 \u043f\u0440\u0438\u0431\u044b\u043b\u0438.', '/web/costs'))
    total_profit = sum(c.estimated_profit for c in d.marketplace_comparison)
    if total_profit < 0:
        issues.append(('\u041e\u0442\u0440\u0438\u0446\u0430\u0442\u0435\u043b\u044c\u043d\u0430\u044f \u043f\u0440\u0438\u0431\u044b\u043b\u044c', 'bad', '\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c, \u043a\u043e\u043c\u0438\u0441\u0441\u0438\u0438 \u0438 \u043b\u043e\u0433\u0438\u0441\u0442\u0438\u043a\u0443.', ''))
    total_stock = sum(c.stock_quantity for c in d.marketplace_comparison)
    if total_stock <= 0:
        issues.append(('\u041d\u0435\u0442 \u043e\u0441\u0442\u0430\u0442\u043a\u043e\u0432', 'warn', '\u0422\u043e\u0432\u0430\u0440 \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442 \u043d\u0430 \u0441\u043a\u043b\u0430\u0434\u0430\u0445. \u041f\u043e\u043f\u043e\u043b\u043d\u0438\u0442\u0435 \u0437\u0430\u043f\u0430\u0441\u044b.', '/web/stocks'))
    if not d.has_wb or not d.has_ozon:
        issues.append(('\u041d\u0435 \u0441\u043e\u043f\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d', 'warn', '\u0422\u043e\u0432\u0430\u0440 \u043f\u0440\u0438\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442 \u0442\u043e\u043b\u044c\u043a\u043e \u043d\u0430 \u043e\u0434\u043d\u043e\u0439 \u043f\u043b\u043e\u0449\u0430\u0434\u043a\u0435.', '/web/product-matching'))
    if not issues:
        return '<div class="empty-state"><span class="badge good">\u041a\u0440\u0438\u0442\u0438\u0447\u043d\u044b\u0445 \u043f\u0440\u043e\u0431\u043b\u0435\u043c \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e</span></div>'
    items = "".join(
        f'<div class="attention-item {lvl}" style="margin-bottom:8px"><div><span class="badge {lvl}">{escape(title)}</span><p>{escape(desc)}</p></div>'
        + (f'<a class="button-tiny" href="{escape(url)}">\u0418\u0441\u043f\u0440\u0430\u0432\u0438\u0442\u044c</a>' if url else "")
        + "</div>"
        for title, lvl, desc, url in issues
    )
    return f'<div class="attention-list">{items}</div>'


_TAB_RENDERERS = {
    "overview": _tab_overview,
    "marketplaces": lambda d, **kw: _tab_marketplaces(d, kw.get("mp_filter", "all")),
    "finances": _tab_finances,
    "prices": _tab_prices,
    "stocks": _tab_stocks_tab,
    "orders": _tab_orders_tab,
    "costs": _tab_costs_tab,
    "history": _tab_history_tab,
    "issues": _tab_issues_tab,
}


def _master_product_detail_content(detail: MasterProductDetail, active_tab: str = "overview", mp_filter: str = "all") -> str:
    if active_tab not in _TAB_RENDERERS:
        active_tab = "overview"
    renderer = _TAB_RENDERERS[active_tab]
    tab_content = renderer(detail, mp_filter=mp_filter) if active_tab == "marketplaces" else renderer(detail)
    return f"""      {_section_subnav_products("products")}
      <section class="band">{_detail_header(detail)}</section>
      {_product_tabs(active_tab, detail.master_product_id)}
      {tab_content}
"""



def _product_issues_content(rows: list[MasterProductAnalyticsRow], report: DataQualityReport) -> str:
    no_cost = sum(1 for r in rows if r.status == "\u041d\u0435\u0442 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438")
    neg = sum(1 for r in rows if r.estimated_profit < 0)
    no_st = sum(1 for r in rows if r.stock_quantity <= 0)
    unm = sum(1 for r in rows if r.status == "\u041d\u0435 \u0441\u043e\u043f\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d")
    return f"""      {_section_subnav_products("data_quality")}
      <section class="kpi-grid">
        {_simple_kpi("\u0411\u0435\u0437 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438", str(no_cost), "warn" if no_cost else "neutral")}
        {_simple_kpi("\u0412 \u043c\u0438\u043d\u0443\u0441\u0435", str(neg), "bad" if neg else "neutral")}
        {_simple_kpi("\u041d\u0435\u0442 \u043e\u0441\u0442\u0430\u0442\u043a\u043e\u0432", str(no_st), "warn" if no_st else "neutral")}
        {_simple_kpi("\u041d\u0435 \u0441\u043e\u043f\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d\u044b", str(unm), "warn" if unm else "neutral")}
        {_simple_kpi("\u041e\u0446\u0435\u043d\u043a\u0430 \u043a\u0430\u0447\u0435\u0441\u0442\u0432\u0430", f"{report.score}/100", "good" if report.score >= 80 else "warn")}
      </section>
      <section class="band">
        <h2>\u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u0438</h2>
        <ul>{"".join(f"<li>{escape(r)}</li>" for r in report.recommendations)}</ul>
      </section>
"""


def _product_matching_content(candidates: list[ProductMatchingCandidate]) -> str:
    rows = "".join(
        "<tr>" + f'<td><input type="checkbox" name="product_ids" value="{c.product_id}"></td>'
        + f"<td>{_marketplace_label(c.marketplace)}</td>"
        + f"<td>{escape(c.seller_article)}</td>"
        + f"<td>{escape(c.marketplace_article)}</td>"
        + f"<td>{escape(c.title)}</td>"
        + f"<td>{escape(c.current_group or '\u043d\u0435\u0442 \u0433\u0440\u0443\u043f\u043f\u044b')}</td>"
        + f'<td><form method="post" action="/web/product-matching/unlink"><input type="hidden" name="product_id" value="{c.product_id}"><button class="button-tiny" type="submit">\u0418\u0441\u043a\u043b\u044e\u0447\u0438\u0442\u044c</button></form></td>'
        + "</tr>"
        for c in candidates
    )
    if not rows:
        rows = '<tr><td colspan="7" class="muted" style="text-align:center;padding:40px">\u0422\u043e\u0432\u0430\u0440\u044b \u0434\u043b\u044f \u0441\u043e\u043f\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d\u0438\u044f \u043f\u043e\u043a\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u044b.</td></tr>'
    return f"""      {_section_subnav_products("product_matching")}
      <section class="band">
        <h2>\u0421\u043e\u043f\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0442\u043e\u0432\u0430\u0440\u043e\u0432</h2>
        <p class="muted">\u041e\u0442\u043c\u0435\u0442\u044c\u0442\u0435 \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0438 WB/Ozon \u043e\u0434\u043d\u043e\u0433\u043e \u0442\u043e\u0432\u0430\u0440\u0430 \u0438 \u0441\u043e\u0437\u0434\u0430\u0439\u0442\u0435 \u0440\u0443\u0447\u043d\u0443\u044e \u0433\u0440\u0443\u043f\u043f\u0443.</p>
        <form method="post" action="/web/product-matching/create">
          <div class="table-wrap"><table class="table">
            <thead><tr><th></th><th>\u041c\u041f</th><th>\u0410\u0440\u0442\u0438\u043a\u0443\u043b \u043f\u0440\u043e\u0434\u0430\u0432\u0446\u0430</th><th>\u0410\u0440\u0442\u0438\u043a\u0443\u043b \u041c\u041f</th><th>\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435</th><th>\u0413\u0440\u0443\u043f\u043f\u0430</th><th>\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u0435</th></tr></thead>
            <tbody>{rows}</tbody>
          </table></div>
          <button class="button primary" type="submit" style="margin-top:10px">\u0421\u043e\u0437\u0434\u0430\u0442\u044c \u0440\u0443\u0447\u043d\u0443\u044e MasterProduct-\u0433\u0440\u0443\u043f\u043f\u0443</button>
        </form>
      </section>
"""


def _stocks_forecast_content(rows: list[StockForecastRow], *, marketplace: str = "all", sale_model: str = "all", stock_status: str = "all") -> str:
    body_rows = []
    cr, wa, ou, cfbs, tq = 0, 0, 0, 0, 0
    for row in rows:
        tq += row.quantity
        cfbs += int(row.is_common_fbs)
        if row.status == "out_of_stock": ou += 1
        elif row.status == "critical": cr += 1
        elif row.status == "warning": wa += 1
        dso = str(row.days_until_stockout) if row.days_until_stockout is not None else "\u043d/\u0434"
        mc = '<span class="marketplace-badge neutral"><span class="mp-logo">FBS</span>\u041e\u0431\u0449\u0438\u0439 FBS</span>' if row.is_common_fbs else _marketplace_label(row.marketplace)
        st = stock_status_label(row.status)
        tn = stock_status_tone(row.status)
        body_rows.append("<tr>" + f'<td>{escape(row.title)}<div class="muted">{escape(row.seller_article)}</div></td>' + f"<td>{mc}</td>" + f"<td>{_sale_model_badge(row.sale_model)}</td>" + f"<td>{escape(row.warehouse)}</td>" + f'<td class="num">{row.quantity}</td>' + f'<td class="num">{row.average_daily_sales}</td>' + f'<td class="num">{dso}</td>' + f'<td class="num">{_rub(row.lost_revenue_30d)}</td>' + f'<td><span class="badge {tn}">{escape(st)}</span></td>' + f"<td>{escape(row.recommendation)}</td>" + "</tr>")
    body = "".join(body_rows) or '<tr><td colspan="10"><div class="empty-state">\u041e\u0441\u0442\u0430\u0442\u043a\u043e\u0432 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442.</div></td></tr>'
    return f"""      {_section_subnav_products("stocks")}
      {_stock_filters(marketplace, sale_model, stock_status)}
      <section class="kpi-grid">
        {_simple_kpi("\u0412\u0441\u0435\u0433\u043e \u043f\u043e\u0437\u0438\u0446\u0438\u0439", str(len(rows)))}
        {_simple_kpi("\u0421\u0443\u043c\u043c\u0430\u0440\u043d\u044b\u0439 \u043e\u0441\u0442\u0430\u0442\u043e\u043a", str(tq))}
        {_simple_kpi("\u041d\u0435\u0442 \u0432 \u043d\u0430\u043b\u0438\u0447\u0438\u0438", str(ou), "bad" if ou else "neutral")}
        {_simple_kpi("\u041d\u0438\u0437\u043a\u0438\u0439 \u043e\u0441\u0442\u0430\u0442\u043e\u043a", str(cr + wa), "warn" if cr + wa else "neutral")}
        {_simple_kpi("\u041e\u0431\u0449\u0438\u0439 FBS", str(cfbs), "action" if cfbs else "neutral")}
      </section>
      <section class="band">
        <h2>\u041e\u0441\u0442\u0430\u0442\u043a\u0438, out-of-stock \u0438 \u043f\u043e\u0442\u0435\u0440\u0438 \u0432\u044b\u0440\u0443\u0447\u043a\u0438</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>\u0422\u043e\u0432\u0430\u0440</th><th>\u041c\u041f</th><th>\u041c\u043e\u0434\u0435\u043b\u044c</th><th>\u0421\u043a\u043b\u0430\u0434</th><th class="num">\u041e\u0441\u0442\u0430\u0442\u043e\u043a</th><th class="num">\u041f\u0440\u043e\u0434\u0430\u0436/\u0434\u0435\u043d\u044c</th><th class="num">\u0414\u043d\u0435\u0439 \u0437\u0430\u043f\u0430\u0441\u0430</th><th class="num">\u041f\u043e\u0442\u0435\u0440\u0438 30\u0434</th><th>\u0421\u0442\u0430\u0442\u0443\u0441</th><th>\u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u044f</th></tr></thead>
          <tbody>{body}</tbody>
        </table></div>
      </section>
"""


def _filter_stock_rows(rows, marketplace, sale_model, stock_status):
    filtered = rows
    if marketplace in {Marketplace.WB.value, Marketplace.OZON.value}:
        parsed = Marketplace(marketplace)
        filtered = [r for r in filtered if r.marketplace == parsed or (r.is_common_fbs and sale_model in {"all", "FBS"})]
    if sale_model in {"FBO", "FBS"}:
        filtered = [r for r in filtered if r.sale_model == sale_model]
    if stock_status == "out":
        filtered = [r for r in filtered if r.status == "out_of_stock"]
    elif stock_status == "low":
        filtered = [r for r in filtered if r.status in {"critical", "warning"}]
    return filtered


def _stock_filters(marketplace, sale_model, stock_status):
    return f"""      <form class="filters" method="get" action="/web/stocks">
        {_select("marketplace", "\u041c\u0430\u0440\u043a\u0435\u0442\u043f\u043b\u0435\u0439\u0441", {"all": "\u0412\u0441\u0435", Marketplace.WB.value: "Wildberries", Marketplace.OZON.value: "Ozon"}, marketplace)}
        {_select("sale_model", "\u041c\u043e\u0434\u0435\u043b\u044c", {"all": "\u0412\u0441\u0435", "FBO": "FBO", "FBS": "FBS"}, sale_model)}
        {_select("stock_status", "\u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435", {"all": "\u0412\u0441\u0435", "out": "\u041d\u0435\u0442 \u0432 \u043d\u0430\u043b\u0438\u0447\u0438\u0438", "low": "\u041d\u0438\u0437\u043a\u0438\u0439 \u043e\u0441\u0442\u0430\u0442\u043e\u043a"}, stock_status)}
        <button class="button primary" type="submit">\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c</button>
      </form>
"""


def _alerts_content(events: list[AlertEvent], timezone: str = "Europe/Moscow") -> str:
    pending = sum(1 for e in events if not e.sent_at)
    sent = len(events) - pending
    critical = sum(1 for e in events if e.alert_type.value in {"LOSS_ORDER", "LOW_STOCK", "STOCKOUT_FORECAST"})
    body = "".join(
        "<tr>" + f"<td>{escape(_dt(e.created_at, timezone))}</td>"
        + f"<td>{_alert_type_badge(e.alert_type.value)}</td>"
        + f"<td>{escape(e.title)}</td>"
        + f"<td>{escape(e.message)}</td>"
        + f"<td>{_alert_delivery_badge(e.sent_at is not None)}</td></tr>"
        for e in events
    )
    if not body:
        body = '<tr><td colspan="5"><div class="empty-state">\u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u0430\u043b\u0435\u0440\u0442\u043e\u0432 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442.</div></td></tr>'
    return f"""      {_section_subnav_products("alerts")}
      <section class="kpi-grid">
        {_simple_kpi("\u0412\u0441\u0435\u0433\u043e \u0430\u043b\u0435\u0440\u0442\u043e\u0432", str(len(events)))}
        {_simple_kpi("\u041d\u043e\u0432\u044b\u0435", str(pending), "action" if pending else "neutral")}
        {_simple_kpi("\u041a\u0440\u0438\u0442\u0438\u0447\u043d\u044b\u0435", str(critical), "bad" if critical else "neutral")}
        {_simple_kpi("\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u044b", str(sent), "good" if sent else "neutral")}
      </section>
      <section class="band">
        <h2>\u0420\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u043d\u044b\u0435 \u0430\u043b\u0435\u0440\u0442\u044b</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>\u0414\u0430\u0442\u0430</th><th>\u0422\u0438\u043f</th><th>\u0417\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a</th><th>\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435</th><th>\u0421\u0442\u0430\u0442\u0443\u0441</th></tr></thead>
          <tbody>{body}</tbody>
        </table></div>
      </section>
"""


def _costs_content(data: CostsPageData, timezone: str = "Europe/Moscow") -> str:
    rows = "".join(
        "<tr>" + f"<td>{escape(row.product.title or '\u0411\u0435\u0437 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u044f')}<div class=\"muted\">{escape(row.product.seller_article or '\u043d/\u0434')}</div></td>"
        + f"<td>{_marketplace_label(row.product.marketplace)}<div class=\"muted\">{escape(row.account_name)}</div></td>"
        + f'<td class="num">{_rub(row.cost.cost_price) if row.cost else "\u043d\u0435 \u0437\u0430\u0434\u0430\u043d\u0430"}</td>'
        + f'<td class="num">{_rub(row.cost.package_cost) if row.cost else "\u043d/\u0434"}</td>'
        + f'<td class="num">{_rub(row.cost.additional_cost) if row.cost else "\u043d/\u0434"}</td>'
        + f'<td class="num">{(row.cost.tax_rate * Decimal("100")).quantize(Decimal("0.01")) if row.cost else "\u043d/\u0434"}%</td>'
        + f"<td>{format_datetime_for_user(row.cost.valid_from, timezone, '%d.%m.%Y') if row.cost else '\u043d/\u0434'}</td>"
        + f"<td>{_cost_status_badge(row.cost is not None and row.cost.cost_price > 0)}</td>"
        + f'<td><a class="button-tiny" href="/web/costs/{row.product.id}">\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c</a></td></tr>'
        for row in data.rows
    )
    if not rows:
        rows = '<tr><td colspan="10"><div class="empty-state">\u0422\u043e\u0432\u0430\u0440\u044b \u0435\u0449\u0451 \u043d\u0435 \u0441\u0438\u043d\u0445\u0440\u043e\u043d\u0438\u0437\u0438\u0440\u043e\u0432\u0430\u043d\u044b.</div></td></tr>'
    return f"""      {_page_header("\u0421\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c", "\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u0438\u0440\u0443\u0439\u0442\u0435 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c, \u0443\u043f\u0430\u043a\u043e\u0432\u043a\u0443, \u0434\u043e\u043f. \u0440\u0430\u0441\u0445\u043e\u0434\u044b.", "/web/products", "\u0422\u043e\u0432\u0430\u0440\u044b")}
      <section class="kpi-grid">
        {_simple_kpi("\u0421\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c \u0437\u0430\u0434\u0430\u043d\u0430", str(data.configured_count), "good")}
        {_simple_kpi("\u0411\u0435\u0437 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438", str(data.missing_count), "warn" if data.missing_count else "neutral")}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>\u0422\u043e\u0432\u0430\u0440\u044b \u0438 \u0442\u0435\u043a\u0443\u0449\u0430\u044f \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>\u0422\u043e\u0432\u0430\u0440</th><th>\u041a\u0430\u0431\u0438\u043d\u0435\u0442</th><th class="num">\u0421\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c</th><th class="num">\u0423\u043f\u0430\u043a\u043e\u0432\u043a\u0430</th><th class="num">\u0414\u043e\u043f. \u0440\u0430\u0441\u0445\u043e\u0434\u044b</th><th class="num">\u041d\u0430\u043b\u043e\u0433</th><th>\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u043e</th><th>\u0421\u0442\u0430\u0442\u0443\u0441</th><th>\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u0435</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
"""


def _cost_edit_content(detail: ProductCostDetail, timezone: str = "Europe/Moscow") -> str:
    latest = detail.history[0] if detail.history else None
    history = "".join(
        "<tr>" + f"<td>{format_datetime_for_user(r.valid_from, timezone, '%d.%m.%Y')}</td>"
        + f"<td>{format_datetime_for_user(r.valid_to, timezone, '%d.%m.%Y') if r.valid_to else '\u0441\u0435\u0439\u0447\u0430\u0441'}</td>"
        + f'<td class="num">{_rub(r.cost_price)}</td>'
        + f'<td class="num">{_rub(r.package_cost)}</td>'
        + f'<td class="num">{_rub(r.additional_cost)}</td>'
        + f'<td class="num">{(r.tax_rate * Decimal("100")).quantize(Decimal("0.01"))}%</td>'
        + f"<td>{escape(r.comment or '')}</td></tr>"
        for r in detail.history
    ) or '<tr><td colspan="7" class="muted">\u0418\u0441\u0442\u043e\u0440\u0438\u0438 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442.</td></tr>'
    return f"""      {_page_header("\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435 \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438", escape(detail.product.title or "\u0411\u0435\u0437 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u044f"), "/web/costs", "\u041a \u0441\u043f\u0438\u0441\u043a\u0443")}
      <section class="detail-grid">
        <section class="band">
          <h2>\u041d\u043e\u0432\u0430\u044f \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c</h2>
          <form method="post" action="/web/costs/{detail.product.id}">
            <label for="cost_price">\u0421\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c</label>
            <input id="cost_price" name="cost_price" type="number" step="0.01" value="{latest.cost_price if latest else 0}">
            <label for="package_cost">\u0423\u043f\u0430\u043a\u043e\u0432\u043a\u0430</label>
            <input id="package_cost" name="package_cost" type="number" step="0.01" value="{latest.package_cost if latest else 0}">
            <label for="additional_cost">\u0414\u043e\u043f. \u0440\u0430\u0441\u0445\u043e\u0434\u044b</label>
            <input id="additional_cost" name="additional_cost" type="number" step="0.01" value="{latest.additional_cost if latest else 0}">
            <label for="tax_rate">\u041d\u0430\u043b\u043e\u0433, %</label>
            <input id="tax_rate" name="tax_rate" type="number" step="0.01" value="{(latest.tax_rate * Decimal("100")).quantize(Decimal("0.01")) if latest else 0}">
            <label for="valid_from">\u0414\u0430\u0442\u0430 \u043d\u0430\u0447\u0430\u043b\u0430 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f</label>
            <input id="valid_from" name="valid_from" type="date" value="{datetime.now(tz=UTC).date().isoformat()}">
            <label for="comment">\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439</label>
            <input id="comment" name="comment" type="text" value="WEB-\u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435">
            <p><button class="button primary" type="submit">\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c</button></p>
          </form>
        </section>
        <section class="band">
          <h2>\u0422\u043e\u0432\u0430\u0440</h2>
          <div class="kv">
            <span>\u041c\u0430\u0440\u043a\u0435\u0442\u043f\u043b\u0435\u0439\u0441</span><strong>{_marketplace_label(detail.product.marketplace)}</strong>
            <span>\u041a\u0430\u0431\u0438\u043d\u0435\u0442</span><strong>{escape(detail.account_name)}</strong>
            <span>\u0410\u0440\u0442\u0438\u043a\u0443\u043b \u043f\u0440\u043e\u0434\u0430\u0432\u0446\u0430</span><strong>{escape(detail.product.seller_article or "\u043d/\u0434")}</strong>
            <span>\u0410\u0440\u0442\u0438\u043a\u0443\u043b \u041c\u041f</span><strong>{escape(detail.product.marketplace_article or detail.product.external_product_id)}</strong>
          </div>
        </section>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>\u0421</th><th>\u041f\u043e</th><th class="num">\u0421\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c</th><th class="num">\u0423\u043f\u0430\u043a\u043e\u0432\u043a\u0430</th><th class="num">\u0414\u043e\u043f. \u0440\u0430\u0441\u0445\u043e\u0434\u044b</th><th class="num">\u041d\u0430\u043b\u043e\u0433</th><th>\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439</th></tr></thead>
          <tbody>{history}</tbody>
        </table></div>
      </section>
"""
