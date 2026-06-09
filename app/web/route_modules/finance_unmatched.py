# ruff: noqa: E501

import logging
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import FinancialReportRow, Order, User
from app.models.enums import Marketplace
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.rendering import page

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/finances/unmatched", response_class=HTMLResponse)
async def unmatched_finance_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    category: str = Query(default="all"),
    marketplace: str = Query(default="all"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> str:
    try:
        rows = await _query_unmatched_rows(session, user.id, category, marketplace, limit)
        category_counts = await _category_counts(session, user.id)
        content = _unmatched_content(rows, category_counts, category, marketplace, user.timezone)
        return page(
            "Непривязанные финансовые операции",
            user.first_name or user.username or str(user.telegram_id),
            content,
            active_path="/web/finances",
        )
    except Exception:
        logger.exception("unmatched_finance_page_failed", extra={"user_id": user.id})
        return page(
            "Ошибка — Непривязанные операции",
            user.first_name or user.username or str(user.telegram_id),
            '<div class="band"><h2>Не удалось загрузить страницу</h2>'
            "<p>Ошибка уже записана в лог. Попробуйте обновить страницу позже.</p>"
            '<p><a href="/web/" class="button primary">На главную</a></p></div>',
        )


async def _query_unmatched_rows(
    session: AsyncSession,
    user_id: int,
    category: str,
    marketplace: str,
    limit: int,
) -> Sequence[FinancialReportRow]:
    stmt = select(FinancialReportRow).where(FinancialReportRow.user_id == user_id)
    if marketplace == "wb":
        stmt = stmt.where(FinancialReportRow.marketplace == Marketplace.WB)
    elif marketplace == "ozon":
        stmt = stmt.where(FinancialReportRow.marketplace == Marketplace.OZON)
    if category == "unlinked":
        stmt = stmt.where(
            FinancialReportRow.order_external_id.is_(None)
            | ~FinancialReportRow.order_external_id.in_(
                select(Order.srid).where(
                    Order.user_id == user_id, Order.srid.isnot(None)
                )
            )
        )
    elif category != "all":
        stmt = stmt.where(FinancialReportRow.operation_category == category)
    stmt = stmt.order_by(FinancialReportRow.operation_date.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _category_counts(
    session: AsyncSession, user_id: int
) -> dict[str, int]:
    result = await session.execute(
        text(
            "SELECT operation_category, COUNT(*) as cnt FROM financial_report_rows "
            "WHERE user_id = :uid AND operation_category IS NOT NULL "
            "GROUP BY operation_category ORDER BY cnt DESC"
        ),
        {"uid": user_id},
    )
    return {row.operation_category: row.cnt for row in result.mappings().all()}


def _unmatched_content(
    rows: Sequence[FinancialReportRow],
    category_counts: dict[str, int],
    active_category: str,
    marketplace: str,
    timezone: str,
) -> str:
    from html import escape
    from app.web.view_modules.formatting import _rub, _dt, _marketplace_label

    total = sum(category_counts.values())
    filter_links = [
        ('<a href="/web/finances/unmatched" class="button {}">Все ({})</a>').format(
            "primary" if active_category == "all" else "",
            total,
        ),
        ('<a href="/web/finances/unmatched?category=unlinked" class="button {}">Непривязанные</a>').format(
            "primary" if active_category == "unlinked" else "",
        ),
    ]
    for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        label = {"sale": "Продажи", "return": "Возвраты", "logistics": "Логистика",
                 "storage": "Хранение", "penalty": "Штрафы", "deduction": "Удержания",
                 "paid_acceptance": "Приемка", "compensation": "Компенсации",
                 "adjustment": "Корректировки", "acquiring": "Эквайринг",
                 "commission": "Комиссии", "other": "Прочее"}.get(cat, cat)
        filter_links.append(
            f'<a href="/web/finances/unmatched?category={cat}" '
            f'class="button {"primary" if active_category == cat else ""}">'
            f"{escape(label)} ({count})</a>"
        )

    mp_filter = f"""
    <div style="margin-top:10px">
      <a href="/web/finances/unmatched?category={active_category}" class="button {"primary" if marketplace == "all" else ""}">Все</a>
      <a href="/web/finances/unmatched?category={active_category}&marketplace=wb" class="button {"primary" if marketplace == "wb" else ""}">Wildberries</a>
      <a href="/web/finances/unmatched?category={active_category}&marketplace=ozon" class="button {"primary" if marketplace == "ozon" else ""}">Ozon</a>
    </div>"""

    if not rows:
        table_body = '<tr><td colspan="7"><div class="empty-state">Финансовых операций по выбранному фильтру нет.</div></td></tr>'
    else:
        table_body = "".join(
            "<tr>"
            f"<td>{_dt(row.operation_date, timezone) if row.operation_date else 'н/д'}</td>"
            f"<td>{_marketplace_label(row.marketplace)}</td>"
            f'<td><span class="badge">{escape(row.operation_category or row.operation_type or "?")}</span></td>'
            f"<td>{escape(row.operation_type or '?')}</td>"
            f'<td class="num">{_rub(row.amount)}</td>'
            f"<td>{escape(row.order_external_id or '—')}</td>"
            f'<td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{escape(str(row.id))}</td>'
            "</tr>"
            for row in rows
        )

    return f"""
    <div class="subnav">
      <a href="/web/finances">Финансовый обзор</a>
      <a class="active" href="/web/finances/unmatched">Непривязанные операции</a>
    </div>
    <section class="page-header">
      <div>
        <h2>Непривязанные финансовые операции</h2>
        <p class="muted">
          Операции из финансовых отчётов WB/Ozon, которые не привязаны к заказам
          (логистика, хранение, компенсации, штрафы и т.д.).
          Раньше такие строки могли ошибочно создавать фиктивные заказы.
        </p>
      </div>
    </section>
    <div style="margin-bottom:14px;display:flex;flex-wrap:wrap;gap:6px">{''.join(filter_links)}</div>
    {mp_filter}
    <section class="band" style="margin-top:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
        <h2 style="margin:0">Финансовые строки ({len(rows)})</h2>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Дата</th><th>МП</th><th>Категория</th><th>Тип операции</th>
              <th class="num">Сумма</th><th>ID заказа</th><th>ID строки</th>
            </tr>
          </thead>
          <tbody>{table_body}</tbody>
        </table>
      </div>
    </section>
    """
