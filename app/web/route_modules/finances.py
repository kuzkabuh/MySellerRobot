# ruff: noqa: E501

import logging
from decimal import Decimal

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User
from app.services.account.web_cabinet_service import WebCabinetService
from app.services.common.web_dashboard_service import WebDashboardService
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.rendering import page

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/finances", response_class=HTMLResponse)
async def finances_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    period: str = Query(default="30d"),
    marketplace: str = Query(default="all"),
) -> str:
    try:
        dashboard_data = await WebDashboardService(session).dashboard(
            user_id=user.id,
            timezone=user.timezone,
            period=period,
            marketplace=marketplace,
        )
        accounts_data = await WebCabinetService(session).accounts_page(
            user.id, user.timezone
        )
        content = _finances_content(dashboard_data, accounts_data, period, marketplace)
        return page(
            "Финансовый обзор",
            user.first_name or user.username or str(user.telegram_id),
            content,
            active_path="/web/finances",
        )
    except Exception:
        logger.exception("finances_page_failed", extra={"user_id": user.id})
        return page(
            "Ошибка — Финансовый обзор",
            user.first_name or user.username or str(user.telegram_id),
            '<div class="band"><h2>Не удалось загрузить страницу</h2>'
            "<p>Ошибка уже записана в лог. Попробуйте обновить страницу позже.</p>"
            '<p><a href="/web/" class="button primary">На главную</a></p></div>',
        )


def _finances_content(
    data: object,
    accounts: object,
    period: str,
    marketplace: str,
) -> str:
    from app.web.view_modules.common import _page_header
    from app.web.view_modules.components import _simple_kpi
    from app.web.view_modules.formatting import _rub, _marketplace_label

    d = data
    a = accounts

    revenue_summary = _extract_metric(d, "Выручка")
    profit_estimated = _extract_metric(d, "Плановая прибыль")
    profit_actual = _extract_metric(d, "Фактическая прибыль")
    payout = _extract_metric(d, "К выплате")
    orders = _extract_metric(d, "Заказы")
    sales = _extract_metric(d, "Продажи (выкупы)")
    returns = _extract_metric(d, "Возвраты")
    margin = _extract_metric(d, "Средняя маржа")

    kpi_grid = f"""
    <section class="kpi-grid">
        {_simple_kpi("Плановая прибыль", _rub(profit_estimated), "good" if profit_estimated >= 0 else "bad")}
        {_simple_kpi("Фактическая прибыль", _rub(profit_actual))}
        {_simple_kpi("Выручка", _rub(revenue_summary))}
        {_simple_kpi("К выплате", _rub(payout))}
        {_simple_kpi("Заказы", str(orders))}
        {_simple_kpi("Выкупы", str(sales))}
        {_simple_kpi("Возвраты", str(returns), "bad" if returns else "neutral")}
        {_simple_kpi("Средняя маржа", str(margin))}
    </section>"""

    accounts_section = _accounts_finance_table(a)

    return f"""
    {_page_header("Финансовый обзор", "Сводная финансовая картина по всем кабинетам и маркетплейсам.", "/web/profit", "Детальная прибыль")}
    <form class="filters" method="get" action="/web/finances">
        <div>
            <label for="period">Период</label>
            <select id="period" name="period">
                <option value="today" {"selected" if period == "today" else ""}>Сегодня</option>
                <option value="yesterday" {"selected" if period == "yesterday" else ""}>Вчера</option>
                <option value="7d" {"selected" if period == "7d" else ""}>7 дней</option>
                <option value="30d" {"selected" if period == "30d" else ""}>30 дней</option>
                <option value="month" {"selected" if period == "month" else ""}>Текущий месяц</option>
                <option value="prev_month" {"selected" if period == "prev_month" else ""}>Прошлый месяц</option>
                <option value="quarter" {"selected" if period == "quarter" else ""}>Квартал</option>
                <option value="year" {"selected" if period == "year" else ""}>Год</option>
            </select>
        </div>
        <div>
            <label for="marketplace">Маркетплейс</label>
            <select id="marketplace" name="marketplace">
                <option value="all" {"selected" if marketplace == "all" else ""}>Все</option>
                <option value="wb" {"selected" if marketplace == "wb" else ""}>Wildberries</option>
                <option value="ozon" {"selected" if marketplace == "ozon" else ""}>Ozon</option>
            </select>
        </div>
        <button class="button primary" type="submit">Показать</button>
    </form>
    {kpi_grid}
    <section class="band" style="margin-top:14px">
        <h2>Балансы кабинетов</h2>
        <div class="table-wrap">
            <table class="table">
                <thead>
                    <tr><th>Кабинет</th><th>МП</th><th>Статус</th><th class="num">Баланс</th><th class="num">К выводу / Начислено</th><th>Последняя синхронизация</th></tr>
                </thead>
                <tbody>{accounts_section}</tbody>
            </table>
        </div>
    </section>
    """


def _extract_metric(data: object, label: str) -> Decimal:
    try:
        if hasattr(data, "metrics"):
            for m in data.metrics:
                if hasattr(m, "label") and m.label == label and hasattr(m, "value"):
                    return Decimal(str(m.value))
    except Exception:
        pass
    return Decimal("0")


def _accounts_finance_table(accounts: object) -> str:
    from html import escape
    from app.web.view_modules.formatting import _rub, _dt

    rows_html = []
    try:
        for row in accounts.rows:
            acc = row.account
            mp_label = "Wildberries" if acc.marketplace.value == "wb" else "Ozon"
            mp_cls = "wb" if acc.marketplace.value == "wb" else "ozon"
            status_cls = "good" if acc.is_active else "bad"
            status_label = "Активен" if acc.is_active else "Неактивен"
            balance = row.latest_balance

            balance_str = "н/д"
            withdraw_str = "н/д"
            if balance:
                current = getattr(balance, "current", None)
                if current is not None:
                    balance_str = _rub(current)
                if acc.marketplace.value == "wb":
                    for_withdraw = getattr(balance, "for_withdraw", None)
                    if for_withdraw is not None:
                        withdraw_str = _rub(for_withdraw)
                else:
                    accrued = getattr(balance, "accrued", None)
                    if accrued is not None:
                        withdraw_str = _rub(accrued)

            sync_at = acc.last_success_sync_at
            sync_str = _dt(sync_at, "Europe/Moscow") if sync_at else "н/д"

            rows_html.append(
                "<tr>"
                f'<td>{escape(acc.name or "Без имени")}<div class="muted">#{acc.id}</div></td>'
                f'<td><span class="badge {mp_cls}">{mp_label}</span></td>'
                f'<td><span class="badge {status_cls}">{status_label}</span></td>'
                f'<td class="num">{balance_str}</td>'
                f'<td class="num">{withdraw_str}</td>'
                f"<td>{sync_str}</td>"
                "</tr>"
            )
    except Exception:
        pass

    if not rows_html:
        return '<tr><td colspan="6"><div class="empty-state">Нет подключённых кабинетов.</div></td></tr>'

    return "".join(rows_html)
