"""version: 2.0.0
description: FastAPI routes for web cabinet login, sessions, and dashboard.
updated: 2026-05-15
"""

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
from app.web.rendering import page

router = APIRouter(prefix="/web", tags=["web"])
SESSION_DEPENDENCY = Depends(get_session)


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
    token: str,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> Response:
    web_session = await WebAuthService(session).consume_login_token(
        token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    if web_session is None:
        await session.rollback()
        return HTMLResponse(
            "<h1>Ссылка недействительна</h1><p>Запросите новую ссылку в Telegram-боте.</p>",
            status_code=400,
        )
    await session.commit()
    response = RedirectResponse(url="/web/", status_code=303)
    response.set_cookie(
        WEB_SESSION_COOKIE,
        web_session.token,
        expires=web_session.expires_at,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    await WebAuthService(session).revoke_session(request.cookies.get(WEB_SESSION_COOKIE))
    await session.commit()
    response = RedirectResponse(url="/web/login-required", status_code=303)
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
