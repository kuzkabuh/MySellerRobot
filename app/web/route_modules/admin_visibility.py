"""Admin visibility and cabinet health routes."""

# ruff: noqa: E501

from datetime import UTC, datetime
from html import escape

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    ApiRequestLog,
    AuditLog,
    MarketplaceAccount,
    Order,
    Product,
    SyncTaskRun,
    User,
)
from app.models.enums import PaymentStatus, UserStatus
from app.models.subscriptions import Payment, SubscriptionTier
from app.services.audit_log_service import AuditLogService
from app.services.notification_event_service import NotificationEventService
from app.services.payment_service import PaymentService
from app.services.subscription_service import SubscriptionService
from app.services.sync_status_service import SyncStatusService
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY, is_admin_user
from app.web.rendering import page

router = APIRouter()


def _require_admin(user: User) -> None:
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Доступно только администраторам")


def _name(user: User) -> str:
    return user.first_name or user.username or str(user.telegram_id)


def _h(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _dt(value: datetime | None) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value else "-"


def _badge(status: object) -> str:
    text = _h(getattr(status, "value", status))
    cls = (
        "good"
        if str(text).lower() in {"active", "succeeded", "success", "sent"}
        else (
            "bad"
            if str(text).lower() in {"blocked", "failed", "cancelled", "permanent_failed"}
            else "warn"
        )
    )
    return f'<span class="badge {cls}">{text}</span>'


def _admin_page(title: str, user: User, content: str, active_path: str) -> str:
    return page(title, f"{_name(user)} (admin)", content, active_path=active_path)


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    q: str = Query(default=""),
) -> str:
    _require_admin(user)
    query = select(User).order_by(User.created_at.desc()).limit(200)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(
            (User.username.ilike(term)) | (cast(User.telegram_id, String).ilike(term))
        )
    rows = list((await session.execute(query)).scalars().all())
    body = "".join(
        f"<tr><td><a href='/web/admin/users/{u.id}'>{u.id}</a></td><td>{u.telegram_id}</td><td>{_h(u.username)}</td><td>{_badge(u.status)}</td><td>{_h(u.tariff)}</td><td>{_dt(u.created_at)}</td></tr>"
        for u in rows
    )
    content = f"""
    <div class="page-header"><div><h2>Пользователи</h2><div class="summary-strip"><span>Показано: <strong>{len(rows)}</strong></span></div></div></div>
    <form class="filters" method="get"><div><label>Поиск</label><input name="q" value="{_h(q)}" placeholder="Telegram ID или username"></div><button class="btn btn-primary">Найти</button></form>
    <div class="table-wrap"><table class="table"><thead><tr><th>ID</th><th>Telegram ID</th><th>Username</th><th>Статус</th><th>Тариф</th><th>Регистрация</th></tr></thead><tbody>{body or '<tr><td colspan="6"><div class="empty-state">Пользователи не найдены</div></td></tr>'}</tbody></table></div>
    """
    return _admin_page("Админка пользователей", user, content, "/web/admin/users")


@router.get("/admin", response_class=HTMLResponse)
async def admin_root_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> str:
    _require_admin(user)
    content = """
    <div class="page-header"><div><h2>Администрирование</h2><div class="summary-strip"><span>Разделы управления MP Control</span></div></div></div>
    <div class="shortcut-grid">
      <a class="shortcut-card" href="/web/admin/users"><strong>Пользователи</strong><p>Статусы, кабинеты, уведомления</p></a>
      <a class="shortcut-card" href="/web/admin/tariffs"><strong>Тарифы</strong><p>Планы подписок и лимиты</p></a>
      <a class="shortcut-card" href="/web/admin/promocodes"><strong>Промокоды</strong><p>Скидки и бесплатные периоды</p></a>
      <a class="shortcut-card" href="/web/admin/support"><strong>Обращения пользователей</strong><p>Поддержка и ответы</p></a>
      <a class="shortcut-card" href="/web/admin/logs"><strong>Логи</strong><p>Просмотр и скачивание логов</p></a>
      <a class="shortcut-card" href="/web/admin/sync-status"><strong>Синхронизации</strong><p>Фоновые задачи</p></a>
    </div>
    """
    return _admin_page("Администрирование", user, content, "/web/admin")


@router.get("/admin/users/{target_user_id}", response_class=HTMLResponse)
async def admin_user_detail_page(
    target_user_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    target = await session.get(User, target_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    accounts = list(
        (
            await session.execute(
                select(MarketplaceAccount).where(MarketplaceAccount.user_id == target.id)
            )
        )
        .scalars()
        .all()
    )
    orders = list(
        (
            await session.execute(
                select(Order)
                .where(Order.user_id == target.id)
                .order_by(Order.order_date.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    payments = list(
        (
            await session.execute(
                select(Payment)
                .where(Payment.user_id == target.id)
                .order_by(Payment.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    notifications = await NotificationEventService(session).recent(user_id=target.id, limit=10)
    audit = await AuditLogService(session).recent(user_id=target.id, limit=20)
    errors = list(
        (
            await session.execute(
                select(ApiRequestLog)
                .join(
                    MarketplaceAccount,
                    MarketplaceAccount.id == ApiRequestLog.marketplace_account_id,
                )
                .where(MarketplaceAccount.user_id == target.id)
                .where(ApiRequestLog.error_message.isnot(None))
                .order_by(ApiRequestLog.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    tiers = list(
        (
            await session.execute(
                select(SubscriptionTier)
                .where(SubscriptionTier.is_active.is_(True))
                .order_by(SubscriptionTier.sort_order)
            )
        )
        .scalars()
        .all()
    )

    account_rows = "".join(
        f"<tr><td>{_h(a.marketplace.value)}</td><td>{_h(a.name)}</td><td>{_badge(a.status)}</td><td>{_dt(a.last_success_sync_at)}</td><td>{_h(a.last_error_message)}</td></tr>"
        for a in accounts
    )
    order_rows = "".join(
        f"<tr><td>{_dt(o.order_date)}</td><td>{_h(o.marketplace.value)}</td><td>{_h(o.order_external_id)}</td><td>{_h(o.status)}</td></tr>"
        for o in orders
    )
    payment_rows = "".join(
        f"<tr><td>{_dt(p.created_at)}</td><td>{_h(p.provider_payment_id)}</td><td>{p.amount}</td><td>{_badge(p.status)}</td><td>{_dt(p.paid_at)}</td></tr>"
        for p in payments
    )
    notification_rows = "".join(
        f"<tr><td>{_dt(n.created_at)}</td><td>{_h(n.notification_type)}</td><td>{_badge(n.status)}</td><td>{_h(n.error_message)}</td></tr>"
        for n in notifications
    )
    audit_rows = "".join(
        f"<tr><td>{_dt(a.created_at)}</td><td>{_h(a.action)}</td><td>{_h(a.entity_type)}</td><td><code>{_h(a.details)}</code></td></tr>"
        for a in audit
    )
    error_rows = "".join(
        f"<tr><td>{_dt(e.created_at)}</td><td>{_h(e.url)}</td><td>{_h(e.error_message)}</td></tr>"
        for e in errors
    )
    tier_options = "".join(
        f"<option value='{_h(t.code)}'>{_h(t.name)} ({_h(t.code)})</option>" for t in tiers
    )
    block_action = "unblock" if target.status == UserStatus.BLOCKED else "block"
    block_label = "Разблокировать" if target.status == UserStatus.BLOCKED else "Заблокировать"

    content = f"""
    <div class="page-header"><div><h2>Пользователь #{target.id}</h2><div class="summary-strip"><span>Telegram: <strong>{target.telegram_id}</strong></span><span>Username: <strong>{_h(target.username) or '-'}</strong></span><span>Статус: <strong>{_h(target.status.value)}</strong></span></div></div><div class="page-actions"><a class="btn" href="/web/admin/users">К списку</a></div></div>
    <div class="band"><h3>Действия</h3><div style="display:flex;gap:8px;flex-wrap:wrap;">
      <form method="post" action="/web/admin/users/{target.id}/grant-tariff"><select name="tier_code">{tier_options}</select><input name="days" type="number" value="30" min="1" style="width:90px"><button class="btn btn-primary">Выдать тариф</button></form>
      <form method="post" action="/web/admin/users/{target.id}/status/{block_action}"><button class="btn btn-danger">{block_label}</button></form>
      <form method="post" action="/web/admin/users/{target.id}/restart-sync"><button class="btn">Перезапустить синхронизацию</button></form>
    </div><form method="post" action="/web/admin/users/{target.id}/send-message" style="margin-top:10px;"><textarea name="message" rows="2" placeholder="Сообщение пользователю"></textarea><button class="btn">Отправить сообщение</button></form></div>
    {_table('Кабинеты WB/Ozon', ['МП','Название','Статус','Последний sync','Ошибка'], account_rows)}
    {_table('Последние заказы', ['Дата','МП','Номер','Статус'], order_rows)}
    {_table('Платежи', ['Дата','Provider ID','Сумма','Статус','Оплачен'], payment_rows)}
    {_table('Ошибки', ['Дата','Путь','Ошибка'], error_rows)}
    {_table('Уведомления', ['Дата','Тип','Статус','Ошибка'], notification_rows)}
    {_table('Audit log', ['Дата','Действие','Сущность','Детали'], audit_rows)}
    """
    return _admin_page(f"Пользователь {target.id}", user, content, "/web/admin/users")


def _table(title: str, headers: list[str], rows: str) -> str:
    th = "".join(f"<th>{_h(h)}</th>" for h in headers)
    empty = f'<tr><td colspan="{len(headers)}"><div class="empty-state">Нет данных</div></td></tr>'
    return f"<div class='band'><h3>{_h(title)}</h3><div class='table-wrap'><table class='table'><thead><tr>{th}</tr></thead><tbody>{rows or empty}</tbody></table></div></div>"


@router.post("/admin/users/{target_user_id}/grant-tariff")
async def admin_grant_tariff(
    target_user_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    tier_code: str = Form(...),
    days: int = Form(30),
) -> RedirectResponse:
    _require_admin(user)
    sub = await SubscriptionService(session).create_bonus_subscription(
        user_id=target_user_id,
        tier_code=tier_code,
        days=max(days, 1),
        payment_provider="admin",
        payment_id=f"admin:{user.id}:{datetime.now(tz=UTC).isoformat()}",
    )
    await AuditLogService(session).log(
        "tariff_changed",
        user_id=target_user_id,
        actor_user_id=user.id,
        entity_type="subscription",
        entity_id=sub.id,
        details={"tier_code": tier_code, "days": days},
    )
    await session.commit()
    return RedirectResponse(f"/web/admin/users/{target_user_id}", status_code=303)


@router.post("/admin/users/{target_user_id}/status/{action}")
async def admin_user_status_action(
    target_user_id: int,
    action: str,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    target = await session.get(User, target_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if action == "block":
        target.status = UserStatus.BLOCKED
    elif action == "unblock":
        target.status = UserStatus.ACTIVE
    else:
        raise HTTPException(status_code=404, detail="Действие не найдено")
    await AuditLogService(session).log(f"user_{action}ed", user_id=target.id, actor_user_id=user.id)
    await session.commit()
    return RedirectResponse(f"/web/admin/users/{target_user_id}", status_code=303)


@router.post("/admin/users/{target_user_id}/restart-sync")
async def admin_restart_sync(
    target_user_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    await AuditLogService(session).log(
        "sync_started",
        user_id=target_user_id,
        actor_user_id=user.id,
        details={"source": "admin_user_detail"},
    )
    await session.commit()
    return RedirectResponse("/web/admin/sync-status?manual=queued", status_code=303)


@router.post("/admin/users/{target_user_id}/send-message")
async def admin_send_message(
    target_user_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    message: str = Form(""),
) -> RedirectResponse:
    _require_admin(user)
    target = await session.get(User, target_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    event = await NotificationEventService(session).create(
        user_id=target.id,
        telegram_id=target.telegram_id,
        notification_type="admin_message",
        subject=message[:255],
        payload={"text": message},
    )
    await AuditLogService(session).log(
        "admin_message_created",
        user_id=target.id,
        actor_user_id=user.id,
        entity_type="notification_event",
        entity_id=event.id,
    )
    await session.commit()
    return RedirectResponse(f"/web/admin/users/{target_user_id}", status_code=303)


@router.get("/admin/payments", response_class=HTMLResponse)
async def admin_payments_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    status: str = Query(default=""),
    user_id: int | None = Query(default=None),
) -> str:
    _require_admin(user)
    query = select(Payment).order_by(Payment.created_at.desc()).limit(200)
    if status:
        query = query.where(Payment.status == PaymentStatus(status))
    if user_id is not None:
        query = query.where(Payment.user_id == user_id)
    payments = list((await session.execute(query)).scalars().all())
    rows = "".join(
        f"<tr><td>{p.id}</td><td>{p.user_id}</td><td><code>{_h(p.provider_payment_id)}</code></td><td>{p.amount}</td><td>{_badge(p.status)}</td><td>{_dt(p.paid_at)}</td><td>{_dt(p.subscription_applied_at)}</td><td><form method='post' action='/web/admin/payments/{p.id}/check'><button class='btn btn-sm'>Проверить YooKassa</button></form></td></tr>"
        for p in payments
    )
    status_options = "".join(
        f'<option value="{s.value}" {"selected" if status == s.value else ""}>{s.value}</option>'
        for s in PaymentStatus
    )
    table = _table(
        "Платежи",
        [
            "ID",
            "User",
            "Provider payment ID",
            "Сумма",
            "Статус",
            "paid_at",
            "subscription_applied_at",
            "Действия",
        ],
        rows,
    )
    content = f"<div class='page-header'><div><h2>Платежи</h2></div></div><form class='filters'><div><label>Статус</label><select name='status'><option value=''>Все</option>{status_options}</select></div><div><label>User ID</label><input name='user_id' value='{_h(user_id or '')}'></div><button class='btn btn-primary'>Фильтр</button></form>{table}"
    return _admin_page("Админка платежей", user, content, "/web/admin/payments")


@router.post("/admin/payments/{payment_id}/check")
async def admin_check_payment(
    payment_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Платеж не найден")
    if payment.status != PaymentStatus.SUCCEEDED:
        await PaymentService(session).confirm_payment(payment.provider_payment_id, source="admin")
    await AuditLogService(session).log(
        "payment_status_checked",
        user_id=payment.user_id,
        actor_user_id=user.id,
        entity_type="payment",
        entity_id=payment.id,
    )
    await session.commit()
    return RedirectResponse("/web/admin/payments", status_code=303)


@router.get("/admin/notifications", response_class=HTMLResponse)
async def admin_notifications_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    status: str = Query(default=""),
) -> str:
    _require_admin(user)
    events = await NotificationEventService(session).recent(status=status or None, limit=200)
    rows = "".join(
        f"<tr><td>{e.id}</td><td>{_dt(e.created_at)}</td><td>{e.user_id}</td><td>{_h(e.notification_type)}</td><td>{_badge(e.status)}</td><td>{e.attempts}</td><td>{_h(e.error_message)}</td><td><form method='post' action='/web/admin/notifications/{e.id}/retry'><button class='btn btn-sm'>Повторить</button></form></td></tr>"
        for e in events
    )
    notification_status_options = "".join(
        f'<option value="{s}" {"selected" if status == s else ""}>{s}</option>'
        for s in ["pending", "sent", "failed", "permanent_failed"]
    )
    table = _table(
        "События уведомлений",
        ["ID", "Дата", "User", "Тип", "Статус", "Попытки", "Ошибка", "Действия"],
        rows,
    )
    content = f"<div class='page-header'><div><h2>Уведомления</h2></div></div><form class='filters'><div><label>Статус</label><select name='status'><option value=''>Все</option>{notification_status_options}</select></div><button class='btn btn-primary'>Фильтр</button></form>{table}"
    return _admin_page("Админка уведомлений", user, content, "/web/admin/notifications")


@router.post("/admin/notifications/{event_id}/retry")
async def admin_retry_notification(
    event_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    await NotificationEventService(session).retry(event_id)
    await AuditLogService(session).log(
        "notification_retry_requested",
        actor_user_id=user.id,
        entity_type="notification_event",
        entity_id=event_id,
    )
    await session.commit()
    return RedirectResponse("/web/admin/notifications", status_code=303)


@router.get("/admin/audit-log", response_class=HTMLResponse)
async def admin_audit_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    rows = list(
        (await session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    body = "".join(
        f"<tr><td>{_dt(a.created_at)}</td><td>{a.user_id}</td><td>{a.actor_user_id}</td><td>{_h(a.action)}</td><td>{_h(a.entity_type)}</td><td><code>{_h(a.details)}</code></td></tr>"
        for a in rows
    )
    return _admin_page(
        "Audit log",
        user,
        _table("Audit log", ["Дата", "User", "Actor", "Action", "Entity", "Details"], body),
        "/web/admin/audit-log",
    )


@router.get("/admin/sync-status", response_class=HTMLResponse)
async def admin_sync_status_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    runs = await SyncStatusService(session).recent_runs(limit=200)
    rows = "".join(
        f"<tr><td>{_h(r.task_name)}</td><td>{_badge(r.status)}</td><td>{_dt(r.started_at)}</td><td>{_dt(r.finished_at)}</td><td>{r.duration_ms or '-'}</td><td>{r.records_processed}</td><td>{r.success_count}</td><td>{r.failed_count}</td><td>{_h(r.last_error)}</td></tr>"
        for r in runs
    )
    buttons = "".join(
        f"<form method='post' action='/web/admin/sync-status/run/{task}'><button class='btn'>{label}</button></form>"
        for task, label in _MANUAL_TASKS.items()
    )
    content = f"<div class='page-header'><div><h2>Статус фоновых задач</h2></div><div class='page-actions'>{buttons}</div></div>{_table('Последние запуски', ['Задача','Статус','Старт','Финиш','мс','records','success','failed','Ошибка'], rows)}"
    return _admin_page("Статус синхронизаций", user, content, "/web/admin/sync-status")


_MANUAL_TASKS = {
    "poll_new_orders": "Заказы",
    "sync_sale_events": "Продажи",
    "sync_products": "Товары",
    "sync_wb_product_prices": "Цены WB",
    "check_auto_promo_prices": "Автоакции",
    "reconcile_pending_payments": "Платежи",
}


_WORKER_DIAGNOSTIC_TASKS = (
    "poll_new_orders",
    "sync_sale_events",
    "sync_wb_product_prices",
    "check_auto_promo_prices",
)


@router.get("/admin/worker-diagnostics", response_class=HTMLResponse)
async def admin_worker_diagnostics_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    latest_runs = await SyncStatusService(session).latest_by_task(limit=1000)
    counts = {
        row.task_name: (int(row.success_runs or 0), int(row.failed_runs or 0))
        for row in (
            await session.execute(
                select(
                    SyncTaskRun.task_name.label("task_name"),
                    func.sum(case((SyncTaskRun.status == "success", 1), else_=0)).label(
                        "success_runs"
                    ),
                    func.sum(case((SyncTaskRun.status == "failed", 1), else_=0)).label(
                        "failed_runs"
                    ),
                )
                .where(SyncTaskRun.task_name.in_(_WORKER_DIAGNOSTIC_TASKS))
                .group_by(SyncTaskRun.task_name)
            )
        ).all()
    }
    rows = ""
    for task_name in _WORKER_DIAGNOSTIC_TASKS:
        run = latest_runs.get(task_name)
        success_runs, failed_runs = counts.get(task_name, (0, 0))
        latest_stats = ""
        if run and isinstance(run.run_metadata, dict):
            latest_stats = ", ".join(
                f"{_h(key)}={_h(value)}"
                for key, value in (run.run_metadata.get("stats") or {}).items()
            )
        rows += (
            f"<tr><td>{_h(task_name)}</td>"
            f"<td>{_badge(run.status) if run else _badge('no_runs')}</td>"
            f"<td>{_dt(run.started_at if run else None)}</td>"
            f"<td>{_dt(run.finished_at if run else None)}</td>"
            f"<td>{run.duration_ms if run and run.duration_ms is not None else '-'}</td>"
            f"<td>{success_runs}</td><td>{failed_runs}</td>"
            f"<td>{latest_stats}</td><td>{_h(run.last_error if run else '')}</td></tr>"
        )
    content = (
        "<div class='page-header'><div><h2>Диагностика worker</h2>"
        "<div class='summary-strip'><span>Источник: <strong>sync_task_runs</strong></span>"
        "<span>Ключевые задачи: <strong>4</strong></span></div></div></div>"
        + _table(
            "Ключевые фоновые задачи",
            [
                "Задача",
                "Статус",
                "Старт",
                "Финиш",
                "мс",
                "Успешно",
                "Ошибки",
                "Счётчики",
                "last_error",
            ],
            rows,
        )
    )
    return _admin_page("Диагностика worker", user, content, "/web/admin/worker-diagnostics")


@router.post("/admin/sync-status/run/{task_name}")
async def admin_run_sync_task(
    task_name: str,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    if task_name not in _MANUAL_TASKS:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    from app.workers import tasks

    await getattr(tasks, task_name)({"triggered_by_user_id": user.id, "source": "web_admin"})
    await AuditLogService(session).log(
        "sync_started", actor_user_id=user.id, entity_type="sync_task", entity_id=task_name
    )
    await session.commit()
    return RedirectResponse("/web/admin/sync-status", status_code=303)


@router.get("/health", response_class=HTMLResponse)
async def cabinet_health_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    accounts = list(
        (
            await session.execute(
                select(MarketplaceAccount).where(
                    MarketplaceAccount.user_id == user.id, MarketplaceAccount.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    latest_runs = await SyncStatusService(session).latest_by_task()
    wb_ok = any(a.marketplace.value == "WB" and not a.last_error_message for a in accounts)
    ozon_ok = any(a.marketplace.value == "OZON" and not a.last_error_message for a in accounts)
    products_count = int(
        (
            await session.execute(select(func.count(Product.id)).where(Product.user_id == user.id))
        ).scalar_one()
        or 0
    )
    orders_count = int(
        (
            await session.execute(select(func.count(Order.id)).where(Order.user_id == user.id))
        ).scalar_one()
        or 0
    )
    active_sub = await SubscriptionService(session).get_active_subscription(user.id)
    account_rows = "".join(
        f"<tr><td>{_h(a.marketplace.value)}</td><td>{_h(a.name)}</td><td>{_badge('success' if not a.last_error_message else 'failed')}</td><td>{_dt(a.last_orders_sync_at)}</td><td>{_dt(a.last_sales_sync_at)}</td><td>{_dt(a.last_products_sync_at)}</td><td>{_dt(a.last_stocks_sync_at)}</td><td>{_h(a.last_error_message)}</td></tr>"
        for a in accounts
    )
    run_rows = "".join(
        f"<tr><td>{_h(name)}</td><td>{_badge(run.status)}</td><td>{_dt(run.finished_at or run.started_at)}</td><td>{_h(run.last_error)}</td></tr>"
        for name, run in latest_runs.items()
    )
    content = f"""
    <div class="page-header"><div><h2>Здоровье кабинета</h2><div class="summary-strip"><span>WB API: <strong>{'OK' if wb_ok else 'нет активного OK'}</strong></span><span>Ozon API: <strong>{'OK' if ozon_ok else 'нет активного OK'}</strong></span><span>Товары: <strong>{products_count}</strong></span><span>Заказы: <strong>{orders_count}</strong></span><span>Подписка: <strong>{'активна до ' + _dt(active_sub.expires_at) if active_sub else 'нет активной'}</strong></span></div></div></div>
    {_table('Кабинеты и последние синхронизации', ['МП','Название','API','Заказы','Продажи','Товары','Остатки','Ошибка'], account_rows)}
    {_table('Фоновые задачи', ['Задача','Статус','Последний запуск','Ошибка'], run_rows)}
    """
    return page("Здоровье кабинета", _name(user), content, active_path="/web/health")
