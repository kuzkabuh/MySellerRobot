"""version: 2.3.0
description: FastAPI routes for web login, cabinet dashboard, orders, and profit pages.
updated: 2026-05-15
"""

import json
import logging
from decimal import Decimal
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.domain import User
from app.models.enums import Marketplace
from app.repositories.web_auth import WebAuthRepository
from app.services.web_auth_service import WEB_SESSION_COOKIE, WebAuthService
from app.services.web_dashboard_service import (
    DailyPoint,
    DashboardData,
    KpiMetric,
    WebDashboardService,
)
from app.services.web_orders_profit_service import (
    OrderDetail,
    OrderRow,
    OrderWebFilters,
    ProfitPageData,
    WebOrdersProfitService,
    localized_order_date,
    order_state_label,
)
from app.web.rendering import page

router = APIRouter(prefix="/web", tags=["web"])
SESSION_DEPENDENCY = Depends(get_session)
WEB_DASHBOARD_PATH = "/web/"
WEB_LOGIN_REQUIRED_PATH = "/web/login-required"
logger = logging.getLogger(__name__)


async def current_web_user(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> User:
    raw_session = request.cookies.get(WEB_SESSION_COOKIE)
    if not raw_session:
        raise HTTPException(status_code=401, detail="Требуется вход в web-кабинет")
    user = await WebAuthRepository(session).get_active_session_user(
        WebAuthService.hash_secret(raw_session)
    )
    await session.commit()
    if user is None:
        raise HTTPException(status_code=401, detail="Сессия истекла")
    return user


CURRENT_WEB_USER_DEPENDENCY = Depends(current_web_user)


@router.get("/login")
async def login(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
    token: str | None = Query(default=None),
) -> Response:
    if not token:
        logger.info("web_login_missing_token", extra={"path": _request_path(request)})
        return HTMLResponse(
            "<h1>Ссылка недействительна</h1>"
            "<p>В ссылке входа отсутствует токен. Запросите новую ссылку в Telegram-боте.</p>",
            status_code=400,
        )
    masked_token = _mask_token(token)
    logger.info(
        "web_login_attempt",
        extra={"path": _request_path(request), "token": masked_token},
    )
    web_session = await WebAuthService(session).consume_login_token(
        token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    if web_session is None:
        await session.rollback()
        logger.info(
            "web_login_failed",
            extra={"path": _request_path(request), "token": masked_token},
        )
        return HTMLResponse(
            "<h1>Ссылка для входа недействительна</h1>"
            "<p>Срок действия ссылки истёк, ссылка уже использована или токен повреждён. "
            "Получите новую ссылку в Telegram-боте.</p>",
            status_code=400,
        )
    await session.commit()
    logger.info(
        "web_login_success",
        extra={"path": _request_path(request), "target": WEB_DASHBOARD_PATH},
    )
    response = RedirectResponse(url=WEB_DASHBOARD_PATH, status_code=303)
    response.set_cookie(
        WEB_SESSION_COOKIE,
        web_session.token,
        expires=web_session.expires_at,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/web/login")
async def login_compat(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
    token: str | None = Query(default=None),
) -> Response:
    return await login(request=request, session=session, token=token)


@router.get("/logout")
async def logout(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    await WebAuthService(session).revoke_session(request.cookies.get(WEB_SESSION_COOKIE))
    await session.commit()
    response = RedirectResponse(url=WEB_LOGIN_REQUIRED_PATH, status_code=303)
    response.delete_cookie(WEB_SESSION_COOKIE)
    return response


@router.get("/login-required", response_class=HTMLResponse)
async def login_required() -> str:
    return (
        "<h1>Вход в web-кабинет</h1>"
        "<p>Откройте Telegram-бота и нажмите «🌐 Web-кабинет», чтобы получить новую ссылку.</p>"
    )


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="today"),
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    service = WebDashboardService(session)
    data = await service.dashboard(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
    )
    content = _dashboard_content(data)
    return page("Главная", user.first_name or user.username or str(user.telegram_id), content)


@router.get("/web", response_class=HTMLResponse, include_in_schema=False)
@router.get("/web/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_compat(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="today"),
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    """Render cabinet dashboard for legacy double-/web upstream paths."""

    return await dashboard(
        user=user,
        session=session,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/orders", response_class=HTMLResponse)
async def orders_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="today"),
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    economy: str = Query(default="all"),
    status: str = Query(default="all"),
    sku: str = Query(default=""),
    sort: str = Query(default="date"),
    direction: str = Query(default="desc"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    filters, rows = await WebOrdersProfitService(session).list_orders(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
        economy=economy,
        status=status,
        sku=sku,
        sort=sort,
        direction=direction,
    )
    content = _orders_content(filters, rows, user.timezone)
    return page(
        "Заказы",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/orders",
    )


@router.get("/orders/{order_id}", response_class=HTMLResponse)
async def order_detail_page(
    order_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    detail = await WebOrdersProfitService(session).order_detail(user_id=user.id, order_id=order_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    content = _order_detail_content(detail, user.timezone)
    return page(
        "Карточка заказа",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/orders",
    )


@router.get("/profit", response_class=HTMLResponse)
async def profit_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="7d"),
    marketplace: str = Query(default="all"),
    sale_model: str = Query(default="all"),
    economy: str = Query(default="all"),
    sku: str = Query(default=""),
    sort: str = Query(default="profit"),
    direction: str = Query(default="desc"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> str:
    data = await WebOrdersProfitService(session).profit_by_sku(
        user_id=user.id,
        timezone=user.timezone,
        period=period,
        marketplace=marketplace,
        sale_model=sale_model,
        date_from=date_from,
        date_to=date_to,
        economy=economy,
        sku=sku,
        sort=sort,
        direction=direction,
    )
    content = _profit_content(data)
    return page(
        "Прибыль",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/profit",
    )


@router.get("/{section}", response_class=HTMLResponse)
async def placeholder(
    section: str,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> str:
    titles = {
        "orders": "Заказы",
        "profit": "Прибыль",
        "products": "Товары",
        "stocks": "Остатки",
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
        '<p class="muted">Раздел подготовлен в навигации и будет наполнен в следующих этапах.</p>'
        "</section>"
    )
    return page(
        title,
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path=f"/web/{section}",
    )


def _orders_content(filters: OrderWebFilters, rows: list[OrderRow], timezone: str) -> str:
    table_rows = []
    for row in rows:
        profit = row.estimated_profit
        profit_badge = "bad" if profit is not None and profit < 0 else "good"
        cost_badge = '<span class="badge warn">без себестоимости</span>' if row.missing_cost else ""
        action_badge = (
            '<span class="badge action">требует действия</span>'
            if row.requires_action
            else '<span class="badge">инфо</span>'
        )
        profit_cell = (
            f'<td class="num"><span class="badge {profit_badge}">'
            f"{_rub_optional(profit)}</span></td>"
        )
        table_rows.append(
            "<tr>"
            f"<td>{localized_order_date(row.order_date, timezone)}</td>"
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f"<td>{escape(row.sale_model.value if row.sale_model else 'н/д')}</td>"
            f'<td><a href="/web/orders/{row.order_id}">{escape(row.title)}</a>'
            f'<div class="muted">{escape(row.seller_article)}</div>{cost_badge}</td>'
            f"<td>{escape(row.order_external_id)}"
            f"<div class=\"muted\">{escape(row.posting_number or '')}</div></td>"
            f'<td class="num">{row.quantity}</td>'
            f'<td class="num">{_rub(row.revenue)}</td>'
            f"{profit_cell}"
            f'<td class="num">{_percent_optional(row.margin_percent)}</td>'
            f"<td>{escape(row.status)}<div>{action_badge}</div></td>"
            f"<td>{escape(row.source_event_type)}</td>"
            "</tr>"
        )
    body = (
        "".join(table_rows)
        if table_rows
        else '<tr><td colspan="11" class="muted">Заказов по выбранным фильтрам пока нет.</td></tr>'
    )
    return f"""
      {_section_subnav("orders")}
      {_orders_filters(filters)}
      <section class="band">
        <h2>Заказы и позиции</h2>
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
        item_rows.append(
            "<tr>"
            f"<td>{escape(item.title or 'Без названия')}"
            f"<div class=\"muted\">{escape(item.seller_article or 'н/д')}</div></td>"
            f'<td class="num">{item.quantity}</td>'
            f'<td class="num">{_rub(item.discounted_price * item.quantity)}</td>'
            f'<td class="num">{_rub_optional(item.commission_estimated)}</td>'
            f'<td class="num">{_rub_optional(item.logistics_estimated)}</td>'
            f'<td class="num">{_rub_optional(item.cost_price_used)}</td>'
            f'<td class="num">{_rub_optional(item.package_cost_used)}</td>'
            f'<td class="num">{_rub_optional(item.tax_amount_estimated)}</td>'
            f'<td class="num">{_rub_optional(estimated_profit)}</td>'
            f'<td class="num">{_rub_optional(actual_profit)}</td>'
            "</tr>"
        )
    raw_payload = escape(json.dumps(order.raw_payload or {}, ensure_ascii=False, indent=2))
    deadline = (
        localized_order_date(order.processing_deadline_at, timezone)
        if order.processing_deadline_at
        else "н/д"
    )
    sale_model = escape(order.sale_model.value if order.sale_model else "н/д")
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
            <span>Статус</span><strong>{escape(order.normalized_status or order.status)}</strong>
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
        title_cell = (
            f"<td>{escape(row.title)}"
            f'<div class="muted">{escape(row.seller_article)}</div>{missing}</td>'
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
    return f"""
      {_filters(data)}
      <section class="kpi-grid">
        {"".join(_kpi(metric) for metric in data.metrics)}
      </section>
      <section class="dashboard-grid">
        <section class="band wide">
          <h2>Пульс бизнеса</h2>
          <p class="muted">Заказы, выручка и плановая прибыль за выбранный период.</p>
          {_line_chart(data.points, "revenue", "Выручка по дням", "#0f6f8f")}
        </section>
        <section class="band">
          <h2>Плановая прибыль</h2>
          {_bar_chart(data.points, "estimated_profit", "Плановая прибыль по дням", "#147d4a")}
        </section>
        <section class="band">
          <h2>Заказы vs продажи</h2>
          {_grouped_bar_chart(data.points)}
        </section>
        <section class="band">
          <h2>Возвраты и отмены</h2>
          {_returns_chart(data.points)}
        </section>
        <section class="band">
          <h2>FBO / FBS / rFBS</h2>
          {_sale_model_chart(data.points)}
        </section>
        <section class="band">
          <h2>Wildberries / Ozon</h2>
          {_marketplace_table(data)}
        </section>
      </section>
    """


def _filters(data: DashboardData) -> str:
    filters = data.filters
    selected_marketplace = filters.marketplace.value if filters.marketplace else "all"
    selected_sale_model = filters.sale_model.value if filters.sale_model else "all"
    date_from = filters.local_date_from.isoformat()
    date_to = filters.local_date_to.isoformat()
    return f"""
      <form class="filters" method="get" action="/web/">
        {_select("period", "Период", {
            "today": "Сегодня",
            "yesterday": "Вчера",
            "7d": "7 дней",
            "30d": "30 дней",
            "custom": "Произвольный",
        }, filters.period)}
        {_select("marketplace", "Маркетплейс", {
            "all": "Все",
            Marketplace.WB.value: "Wildberries",
            Marketplace.OZON.value: "Ozon",
        }, selected_marketplace)}
        {_select("sale_model", "Модель", {
            "all": "Все",
            "FBO": "FBO",
            "FBS": "FBS",
            "rFBS": "rFBS",
        }, selected_sale_model)}
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


def _orders_filters(filters: OrderWebFilters) -> str:
    return _shared_order_filters(filters, "/web/orders", include_status=True)


def _profit_filters(filters: OrderWebFilters) -> str:
    return _shared_order_filters(filters, "/web/profit", include_status=False)


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
        {_select("period", "Период", {
            "today": "Сегодня",
            "yesterday": "Вчера",
            "7d": "7 дней",
            "30d": "30 дней",
            "custom": "Произвольный",
        }, filters.period)}
        {_select("marketplace", "Маркетплейс", {
            "all": "Все",
            Marketplace.WB.value: "Wildberries",
            Marketplace.OZON.value: "Ozon",
        }, selected_marketplace)}
        {_select("sale_model", "Модель", {
            "all": "Все",
            "FBO": "FBO",
            "FBS": "FBS",
            "rFBS": "rFBS",
        }, selected_sale_model)}
        {_select("economy", "Экономика", {
            "all": "Все",
            "profit": "Прибыльные",
            "loss": "Убыточные",
            "missing_cost": "Без себестоимости",
        }, filters.economy)}
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
        {_select("sort", "Сортировка", {
            "date": "Дата",
            "profit": "Прибыль",
            "revenue": "Выручка",
            "margin": "Маржа",
            "orders": "Заказы",
            "roi": "ROI",
        }, filters.sort)}
        {_select("direction", "Порядок", {
            "desc": "По убыванию",
            "asc": "По возрастанию",
        }, filters.direction)}
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


def _kpi(metric: KpiMetric) -> str:
    change = ""
    if metric.change_percent is not None:
        css = "up" if metric.change_percent > 0 else "down" if metric.change_percent < 0 else ""
        sign = "+" if metric.change_percent > 0 else ""
        change = (
            f'<span class="change {css}">'
            f"{sign}{metric.change_percent}% к прошлому периоду</span>"
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


def _line_chart(points: list[DailyPoint], attr: str, title: str, color: str) -> str:
    values = [_point_value(point, attr) for point in points]
    if not any(values):
        return _empty_chart()
    width = 720
    height = 220
    max_value = max(values) or Decimal("1")
    coords = []
    step = width / max(len(points) - 1, 1)
    for index, value in enumerate(values):
        x = Decimal(str(index * step))
        y = Decimal(height - 30) - (value / max_value * Decimal(height - 60))
        coords.append(f"{float(x):.1f},{float(y):.1f}")
    labels = _x_labels(points, width, height)
    return f"""
      <div class="chart" role="img" aria-label="{escape(title)}">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          <line x1="0" y1="{height - 30}" x2="{width}" y2="{height - 30}" stroke="#d9e0e8"/>
          <polyline fill="none" stroke="{color}" stroke-width="4" points="{" ".join(coords)}"/>
          {labels}
        </svg>
      </div>
    """


def _bar_chart(points: list[DailyPoint], attr: str, title: str, color: str) -> str:
    values = [_point_value(point, attr) for point in points]
    if not any(values):
        return _empty_chart()
    width = 720
    height = 220
    max_value = max(abs(value) for value in values) or Decimal("1")
    bar_width = max(width / max(len(points), 1) * 0.58, 4)
    bars = []
    for index, value in enumerate(values):
        x = index * (width / max(len(points), 1)) + bar_width * 0.35
        bar_height = abs(value) / max_value * Decimal(height - 60)
        y = Decimal(height - 30) - bar_height if value >= 0 else Decimal(height - 30)
        tone = color if value >= 0 else "#b42318"
        bars.append(
            f'<rect x="{x:.1f}" y="{float(y):.1f}" width="{bar_width:.1f}" '
            f'height="{float(bar_height):.1f}" rx="3" fill="{tone}"/>'
        )
    labels = _x_labels(points, width, height)
    return f"""
      <div class="chart" role="img" aria-label="{escape(title)}">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          <line x1="0" y1="{height - 30}" x2="{width}" y2="{height - 30}" stroke="#d9e0e8"/>
          {"".join(bars)}
          {labels}
        </svg>
      </div>
    """


def _grouped_bar_chart(points: list[DailyPoint]) -> str:
    if not any(point.orders or point.sales for point in points):
        return _empty_chart()
    width = 720
    height = 220
    max_value = max([point.orders for point in points] + [point.sales for point in points] + [1])
    group = width / max(len(points), 1)
    bars = []
    for index, point in enumerate(points):
        x = index * group + group * 0.25
        order_h = point.orders / max_value * (height - 60)
        sales_h = point.sales / max_value * (height - 60)
        bars.append(
            f'<rect x="{x:.1f}" y="{height - 30 - order_h:.1f}" width="{group * 0.18:.1f}" '
            f'height="{order_h:.1f}" rx="3" fill="#0f6f8f"/>'
            f'<rect x="{x + group * 0.22:.1f}" y="{height - 30 - sales_h:.1f}" '
            f'width="{group * 0.18:.1f}" height="{sales_h:.1f}" rx="3" fill="#147d4a"/>'
        )
    return f"""
      <div class="chart" role="img" aria-label="Заказы и продажи по дням">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          <line x1="0" y1="{height - 30}" x2="{width}" y2="{height - 30}" stroke="#d9e0e8"/>
          {"".join(bars)}
          {_x_labels(points, width, height)}
        </svg>
        <div class="legend"><span><i class="dot" style="background:#0f6f8f"></i>Заказы</span>
        <span><i class="dot" style="background:#147d4a"></i>Продажи</span></div>
      </div>
    """


def _returns_chart(points: list[DailyPoint]) -> str:
    if not any(point.returns or point.cancellations for point in points):
        return _empty_chart()
    width = 720
    height = 220
    max_value = max(
        [point.returns for point in points] + [point.cancellations for point in points] + [1]
    )
    group = width / max(len(points), 1)
    bars = []
    for index, point in enumerate(points):
        x = index * group + group * 0.25
        returns_h = point.returns / max_value * (height - 60)
        cancel_h = point.cancellations / max_value * (height - 60)
        bars.append(
            f'<rect x="{x:.1f}" y="{height - 30 - returns_h:.1f}" '
            f'width="{group * 0.18:.1f}" height="{returns_h:.1f}" rx="3" fill="#b42318"/>'
            f'<rect x="{x + group * 0.22:.1f}" y="{height - 30 - cancel_h:.1f}" '
            f'width="{group * 0.18:.1f}" height="{cancel_h:.1f}" rx="3" fill="#a65f00"/>'
        )
    return f"""
      <div class="chart" role="img" aria-label="Возвраты и отмены по дням">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
          <line x1="0" y1="{height - 30}" x2="{width}" y2="{height - 30}" stroke="#d9e0e8"/>
          {"".join(bars)}
          {_x_labels(points, width, height)}
        </svg>
        <div class="legend"><span><i class="dot" style="background:#b42318"></i>Возвраты</span>
        <span><i class="dot" style="background:#a65f00"></i>Отмены</span></div>
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
        bar_style = (
            f"height:12px;width:{width:.1f}%;" f"background:{colors[label]};border-radius:4px"
        )
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
        label = "Wildberries" if item.marketplace == Marketplace.WB else "Ozon"
        rows.append(
            "<tr>"
            f"<td>{label}</td>"
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
            f'<text x="{x:.1f}" y="{height - 8}" fill="#667085" font-size="11" '
            f'text-anchor="middle">{escape(point.label)}</text>'
        )
    return "".join(labels)


def _point_value(point: DailyPoint, attr: str) -> Decimal:
    value = getattr(point, attr)
    if isinstance(value, Decimal):
        return value
    return Decimal(value)


def _empty_chart() -> str:
    return '<div class="chart-empty">Данных за выбранный период пока нет</div>'


def _rub(value: Decimal) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def _rub_optional(value: Decimal | None) -> str:
    if value is None:
        return "н/д"
    return _rub(value)


def _percent_optional(value: Decimal | None) -> str:
    if value is None:
        return "н/д"
    return f"{value.quantize(Decimal('0.1'))}%"


def _marketplace_label(value: Marketplace) -> str:
    return "Wildberries" if value == Marketplace.WB else "Ozon"


def _mask_token(token: str) -> str:
    if len(token) <= 12:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def _request_path(request: Request) -> str:
    url = getattr(request, "url", None)
    return str(getattr(url, "path", "unknown"))
