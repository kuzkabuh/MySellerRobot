"""Admin support ticket routes."""

# ruff: noqa: E501

import logging
from datetime import datetime
from html import escape
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.main import create_bot
from app.models.domain import SupportTicket, User
from app.services.admin.support_service import (
    SUPPORT_PRIORITIES,
    SUPPORT_STATUSES,
    TICKET_PRIORITY,
    TICKET_STATUS_LABELS,
    SupportService,
)
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY, is_admin_user
from app.web.rendering import page

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_admin(user: User) -> None:
    if not is_admin_user(user):
        logger.warning(
            "support_admin_unauthorized_access",
            extra={"user_id": user.id, "telegram_id": user.telegram_id},
        )
        raise HTTPException(status_code=403, detail="Доступно только администраторам")


def _h(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _name(user: User) -> str:
    return user.first_name or user.username or str(user.telegram_id)


def _dt(value: datetime | None) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value else "-"


def _admin_page(title: str, user: User, content: str, active_path: str) -> str:
    return page(title, f"{_name(user)} (admin)", content, active_path=active_path)


def _status_options(selected: str) -> str:
    return "".join(
        f'<option value="{_h(status)}" {"selected" if selected == status else ""}>{_h(TICKET_STATUS_LABELS.get(status, status))}</option>'
        for status in ["new", "in_progress", "answered", "closed", "rejected"]
    )


def _priority_options(selected: str) -> str:
    labels = dict(TICKET_PRIORITY)
    return "".join(
        f'<option value="{_h(priority)}" {"selected" if selected == priority else ""}>{_h(labels.get(priority, priority))}</option>'
        for priority in ["low", "normal", "high", "urgent"]
    )


def _badge(value: str, labels: dict[str, str]) -> str:
    cls = (
        "good"
        if value in {"answered", "closed"}
        else "bad" if value == "urgent" else "warn" if value in {"new", "high"} else "action"
    )
    return f'<span class="badge {cls}">{_h(labels.get(value, value))}</span>'


@router.get("/admin/support", response_class=HTMLResponse)
async def admin_support_list_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    status: str = Query(default=""),
    priority: str = Query(default=""),
    q: str = Query(default=""),
) -> str:
    _require_admin(user)
    service = SupportService(session)
    tickets = await service.list_tickets(
        status=status if status in SUPPORT_STATUSES else None,
        priority=priority if priority in SUPPORT_PRIORITIES else None,
        search=q.strip() or None,
    )
    priority_labels = dict(TICKET_PRIORITY)
    rows = "".join(
        f"<tr><td><a href='/web/admin/support/{t.id}'>#{t.id}</a></td><td>{_dt(t.created_at)}</td><td>{_h(t.full_name or 'н/д')}<div class='muted'>{_h('@' + t.username if t.username else '')} {t.telegram_id or ''}</div></td><td>{_h(t.subject)}</td><td>{_badge(t.status, TICKET_STATUS_LABELS)}</td><td>{_badge(t.priority, priority_labels)}</td><td>{_h((t.message or '')[:140])}</td></tr>"
        for t in tickets
    )
    status_filter_options = '<option value="">Все</option>' + _status_options(status)
    priority_filter_options = '<option value="">Все</option>' + _priority_options(priority)
    content = f"""
    <div class="page-header"><div><h2>Обращения пользователей</h2><div class="summary-strip"><span>Показано: <strong>{len(tickets)}</strong></span></div></div></div>
    <form class="filters" method="get">
      <div><label>Статус</label><select name="status">{status_filter_options}</select></div>
      <div><label>Приоритет</label><select name="priority">{priority_filter_options}</select></div>
      <div><label>Поиск</label><input name="q" value="{_h(q)}" placeholder="Текст, имя, username, Telegram ID"></div>
      <button class="btn btn-primary">Применить</button>
      <a class="btn" href="/web/admin/support">Сбросить</a>
    </form>
    <div class="table-wrap"><table class="table"><thead><tr><th>Номер</th><th>Дата</th><th>Пользователь</th><th>Тема</th><th>Статус</th><th>Приоритет</th><th>Текст</th></tr></thead><tbody>{rows or '<tr><td colspan="7"><div class="empty-state">Обращения не найдены</div></td></tr>'}</tbody></table></div>
    """
    return _admin_page("Обращения пользователей", user, content, "/web/admin/support")


@router.get("/admin/support-tickets", response_class=HTMLResponse)
async def admin_support_tickets_alias(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    status: str = Query(default=""),
    priority: str = Query(default=""),
    q: str = Query(default=""),
) -> str:
    return await admin_support_list_page(
        user=user,
        session=session,
        status=status,
        priority=priority,
        q=q,
    )


@router.get("/admin/support/{ticket_id}", response_class=HTMLResponse)
async def admin_support_detail_page(
    ticket_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    ticket = await SupportService(session).get_ticket_model(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    return await _render_ticket_detail(user, session, ticket)


@router.post("/admin/support/{ticket_id}/update")
async def admin_support_update(
    ticket_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    status: str = Form(""),
    priority: str = Form(""),
    admin_comment: str = Form(""),
    assigned_admin_id: str = Form(default=""),
) -> RedirectResponse:
    _require_admin(user)
    assigned_id = int(assigned_admin_id) if assigned_admin_id.strip().isdigit() else None
    await SupportService(session).update_admin_fields(
        ticket_id,
        admin_id=user.id,
        status=status,
        priority=priority,
        admin_comment=admin_comment,
        assigned_admin_id=assigned_id,
    )
    return RedirectResponse(f"/web/admin/support/{ticket_id}", status_code=303)


@router.post("/admin/support/{ticket_id}/reply", response_class=HTMLResponse)
async def admin_support_reply(
    ticket_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    response_text: str = Form(""),
) -> Any:
    _require_admin(user)
    service = SupportService(session)
    ticket = await service.get_ticket_model(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    text = response_text.strip()
    if not text:
        return await _render_ticket_detail(
            user,
            session,
            ticket,
            alert="Введите текст ответа.",
            draft_response=response_text,
        )
    try:
        telegram_id = ticket.telegram_id
        if telegram_id is None:
            target_user = await session.get(User, ticket.user_id)
            telegram_id = target_user.telegram_id if target_user else None
        if telegram_id is None:
            raise RuntimeError("У обращения нет Telegram ID пользователя")
        bot = create_bot()
        try:
            await bot.send_message(
                telegram_id,
                f"📩 <b>Ответ по обращению #{ticket.id}</b>\n\nТекст ответа:\n{escape(text)}",
                parse_mode="HTML",
            )
        finally:
            await bot.session.close()
    except Exception:
        logger.exception(
            "support_ticket_reply_send_failed",
            extra={"ticket_id": ticket.id, "telegram_id": ticket.telegram_id},
        )
        return await _render_ticket_detail(
            user,
            session,
            ticket,
            alert="Не удалось отправить ответ пользователю. Текст ответа сохранён в поле ниже.",
            draft_response=response_text,
        )
    await service.respond_ticket(ticket.id, admin_id=user.id, response=text)
    logger.info("support_ticket_reply_sent", extra={"ticket_id": ticket.id, "admin_id": user.id})
    return RedirectResponse(f"/web/admin/support/{ticket_id}", status_code=303)


@router.post("/admin/support/{ticket_id}/close")
async def admin_support_close(
    ticket_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    await SupportService(session).close_ticket(ticket_id, admin_id=user.id)
    return RedirectResponse(f"/web/admin/support/{ticket_id}", status_code=303)


async def _render_ticket_detail(
    user: User,
    session: AsyncSession,
    ticket: SupportTicket,
    *,
    alert: str = "",
    draft_response: str = "",
) -> str:
    events = await SupportService(session).get_events(ticket.id)
    priority_labels = dict(TICKET_PRIORITY)
    event_rows = "".join(
        f"<tr><td>{_dt(e.created_at)}</td><td>{_h(e.actor_type)}</td><td>{_h(e.actor_id)}</td><td>{_h(e.action)}</td><td>{_h(e.old_value)}</td><td>{_h(e.new_value)}</td><td>{_h(e.comment)}</td></tr>"
        for e in events
    )
    alert_html = f'<div class="error-state"><p>{_h(alert)}</p></div>' if alert else ""
    content = f"""
    <div class="page-header"><div><h2>Обращение #{ticket.id}</h2><div class="summary-strip"><span>Статус: <strong>{_h(TICKET_STATUS_LABELS.get(ticket.status, ticket.status))}</strong></span><span>Приоритет: <strong>{_h(priority_labels.get(ticket.priority, ticket.priority))}</strong></span><span>Создано: <strong>{_dt(ticket.created_at)}</strong></span></div></div><div class="page-actions"><a class="btn" href="/web/admin/support">К списку</a></div></div>
    {alert_html}
    <div class="detail-grid">
      <div class="band"><h3>Пользователь</h3><div class="kv"><span>Имя</span><strong>{_h(ticket.full_name or "н/д")}</strong><span>Telegram ID</span><strong>{ticket.telegram_id or "-"}</strong><span>Username</span><strong>{_h("@" + ticket.username if ticket.username else "н/д")}</strong><span>User ID</span><strong>{ticket.user_id}</strong></div></div>
      <div class="band"><h3>Состояние</h3><div class="kv"><span>Статус</span><strong>{_badge(ticket.status, TICKET_STATUS_LABELS)}</strong><span>Приоритет</span><strong>{_badge(ticket.priority, priority_labels)}</strong><span>Обновлено</span><strong>{_dt(ticket.updated_at)}</strong><span>Решено</span><strong>{_dt(ticket.resolved_at)}</strong></div></div>
    </div>
    <div class="band"><h3>{_h(ticket.subject)}</h3><div class="mono">{_h(ticket.message)}</div></div>
    <div class="band"><h3>Управление</h3><form method="post" action="/web/admin/support/{ticket.id}/update" class="filters">
      <div><label>Статус</label><select name="status">{_status_options(ticket.status)}</select></div>
      <div><label>Приоритет</label><select name="priority">{_priority_options(ticket.priority)}</select></div>
      <div><label>Ответственный admin ID</label><input name="assigned_admin_id" value="{_h(ticket.assigned_admin_id or "")}"></div>
      <div class="wide"><label>Внутренний комментарий</label><textarea name="admin_comment" rows="4">{_h(ticket.admin_comment or "")}</textarea></div>
      <button class="btn btn-primary">Сохранить</button>
    </form></div>
    <div class="band"><h3>Ответ пользователю</h3><form method="post" action="/web/admin/support/{ticket.id}/reply"><textarea name="response_text" rows="6" placeholder="Текст ответа пользователю">{_h(draft_response or ticket.admin_response or "")}</textarea><div style="display:flex;gap:8px;margin-top:10px;"><button class="btn btn-primary">Отправить в Telegram</button></div></form><form method="post" action="/web/admin/support/{ticket.id}/close" style="margin-top:8px;"><button class="btn">Закрыть обращение</button></form></div>
    <div class="band"><h3>История действий</h3><div class="table-wrap"><table class="table"><thead><tr><th>Дата</th><th>Actor</th><th>Actor ID</th><th>Действие</th><th>Было</th><th>Стало</th><th>Комментарий</th></tr></thead><tbody>{event_rows or '<tr><td colspan="7"><div class="empty-state">История пока пуста</div></td></tr>'}</tbody></table></div></div>
    """
    return _admin_page(f"Обращение #{ticket.id}", user, content, "/web/admin/support")
