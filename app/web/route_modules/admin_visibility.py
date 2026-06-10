"""Admin visibility and cabinet health routes."""

# ruff: noqa: E501

from datetime import UTC, datetime, time
from html import escape

from arq.connections import create_pool
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import redis_settings_from_url
from app.models.domain import (
    ApiRequestLog,
    AuditLog,
    MarketplaceAccount,
    Order,
    Product,
    SyncTaskRun,
    User,
    UserCompanyProfile,
)
from app.models.enums import PaymentStatus, UserStatus
from app.models.subscriptions import Payment, SubscriptionTier
from app.services.admin.audit_log_service import AuditLogService
from app.services.alerts.notification_event_service import NotificationEventService
from app.services.payments.payment_service import PaymentService
from app.services.account.profile_service import ProfileService, ProfileValidationError
from app.services.subscriptions.subscription_service import SubscriptionService
from app.services.common.sync_status_service import SyncStatusService
from app.services.common.task_registry import (
    TASK_REGISTRY,
    format_duration,
    get_task_info,
    status_color,
    translate_category,
    translate_counters,
    translate_error,
    translate_status,
)
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


def _date_value(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


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
    subscriptions = await SubscriptionService(session).get_users_current_subscriptions(
        [row.id for row in rows]
    )
    body = "".join(
        (
            f"<tr><td><a href='/web/admin/users/{u.id}'>{u.id}</a></td>"
            f"<td>{u.telegram_id}</td>"
            f"<td>{_h(_name(u))}<div class='muted'>{_h('@' + u.username if u.username else '')}</div></td>"
            f"<td>{_h(u.email)}<div class='muted'>{_h(u.phone)}</div></td>"
            f"<td>{_h(subscriptions[u.id].tier.name)}</td>"
            f"<td>{_badge(subscriptions[u.id].status)}</td>"
            f"<td>{_dt(subscriptions[u.id].expires_at)}</td>"
            f"<td>{'вкл' if u.notifications_enabled else 'выкл'}</td>"
            f"<td>{_h(u.role)}</td>"
            f"<td>{_dt(u.created_at)}<div class='muted'>Активность: {_dt(u.last_activity_at)}</div></td>"
            f"<td><a class='btn btn-sm' href='/web/admin/users/{u.id}'>Открыть</a></td></tr>"
        )
        for u in rows
    )
    content = f"""
    <div class="page-header"><div><h2>Пользователи</h2><div class="summary-strip"><span>Показано: <strong>{len(rows)}</strong></span></div></div></div>
    <form class="filters" method="get"><div><label>Поиск</label><input name="q" value="{_h(q)}" placeholder="Telegram ID или username"></div><button class="btn btn-primary">Найти</button></form>
    <div class="table-wrap"><table class="table"><thead><tr><th>ID</th><th>Telegram ID</th><th>Имя</th><th>Email / телефон</th><th>Тариф</th><th>Подписка</th><th>До</th><th>Увед.</th><th>Роль</th><th>Регистрация</th><th></th></tr></thead><tbody>{body or '<tr><td colspan="11"><div class="empty-state">Пользователи не найдены</div></td></tr>'}</tbody></table></div>
    """
    return _admin_page("Пользователи", user, content, "/web/admin/users")


@router.get("/admin", response_class=HTMLResponse)
async def admin_root_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> str:
    _require_admin(user)
    content = """
    <div class="page-header"><div><h2>Панель администратора</h2><div class="summary-strip"><span>Разделы управления MP Control</span></div></div></div>
    <div class="shortcut-grid">
      <a class="shortcut-card" href="/web/admin/users"><strong>Пользователи</strong><p>Статусы, кабинеты, уведомления</p></a>
      <a class="shortcut-card" href="/web/admin/tariffs"><strong>Тарифы</strong><p>Планы подписок и лимиты</p></a>
      <a class="shortcut-card" href="/web/admin/promocodes"><strong>Промокоды</strong><p>Скидки и бесплатные периоды</p></a>
      <a class="shortcut-card" href="/web/admin/support"><strong>Обращения</strong><p>Поддержка и ответы</p></a>
      <a class="shortcut-card" href="/web/admin/logs"><strong>Логи</strong><p>Просмотр и скачивание логов</p></a>
      <a class="shortcut-card" href="/web/admin/backups"><strong>Бэкапы</strong><p>Статус ежедневных резервных копий</p></a>
      <a class="shortcut-card" href="/web/admin/sync-status"><strong>Синхронизации</strong><p>Фоновые задачи</p></a>
    </div>
    """
    return _admin_page("Панель администратора", user, content, "/web/admin")


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
    company_profile = (
        await session.execute(
            select(UserCompanyProfile).where(UserCompanyProfile.user_id == target.id)
        )
    ).scalar_one_or_none()
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
    current_subscription = await SubscriptionService(session).get_user_current_subscription(
        target.id
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
        f"<option value='{_h(t.code)}' {'selected' if t.code.lower() == current_subscription.tier.code.lower() else ''}>{_h(t.name)} ({_h(t.code)})</option>"
        for t in tiers
    )
    status_options = "".join(
        f"<option value='{status.value}' {'selected' if target.status == status else ''}>{status.value}</option>"
        for status in UserStatus
    )
    role_options = "".join(
        f"<option value='{role}' {'selected' if target.role == role else ''}>{role}</option>"
        for role in ("user", "admin")
    )
    block_action = "unblock" if target.status == UserStatus.BLOCKED else "block"
    block_label = "Разблокировать" if target.status == UserStatus.BLOCKED else "Заблокировать"

    content = f"""
    <div class="page-header"><div><h2>Пользователь #{target.id}</h2><div class="summary-strip"><span>Telegram: <strong>{target.telegram_id}</strong></span><span>Username: <strong>{_h(target.username) or "-"}</strong></span><span>Статус: <strong>{_h(target.status.value)}</strong></span><span>Тариф: <strong>{_h(current_subscription.tier.name)}</strong></span><span>Подписка: <strong>{_h(current_subscription.status)}</strong></span><span>До: <strong>{_dt(current_subscription.expires_at)}</strong></span></div></div><div class="page-actions"><a class="btn" href="/web/admin/users">К списку</a></div></div>
    <div class="band"><h3>Профиль и тариф</h3>
      <form method="post" action="/web/admin/users/{target.id}/update">
        <div class="filters">
          <div><label>Telegram ID</label><input value="{target.telegram_id}" disabled></div>
          <div><label>Username</label><input name="username" value="{_h(target.username)}"></div>
          <div><label>Имя</label><input name="first_name" value="{_h(target.first_name)}"></div>
          <div><label>Фамилия</label><input name="last_name" value="{_h(target.last_name)}"></div>
          <div><label>Email</label><input name="email" type="email" value="{_h(target.email)}"></div>
          <div><label>Телефон</label><input name="phone" value="{_h(target.phone)}"></div>
          <div><label>Компания</label><input name="company_name" value="{_h(target.company_name)}"></div>
          <div><label>ИНН</label><input name="inn" value="{_h(target.inn)}"></div>
          <div><label>ОГРН / ОГРНИП</label><input name="ogrn" value="{_h(target.ogrn)}"></div>
          <div><label>Часовой пояс</label><input name="timezone" value="{_h(target.timezone)}"></div>
          <div><label>Статус</label><select name="status">{status_options}</select></div>
          <div><label>Роль</label><select name="role">{role_options}</select></div>
          <div><label>Тариф</label><select name="tier_code">{tier_options}</select></div>
          <div><label>Дата окончания тарифа</label><input name="subscription_expires_at" type="date" value="{_date_value(current_subscription.expires_at)}"></div>
          <div><label class="status-chip"><input type="checkbox" name="notifications_enabled" {"checked" if target.notifications_enabled else ""}> Telegram-уведомления</label></div>
        </div>
        <button class="btn btn-primary" type="submit">Сохранить</button>
      </form>
    </div>
    <div class="band"><h3>Действия</h3><div style="display:flex;gap:8px;flex-wrap:wrap;">
      <form method="post" action="/web/admin/users/{target.id}/grant-tariff"><select name="tier_code">{tier_options}</select><input name="days" type="number" value="30" min="1" style="width:90px"><button class="btn btn-primary">Выдать тариф</button></form>
      <form method="post" action="/web/admin/users/{target.id}/status/{block_action}"><button class="btn btn-danger">{block_label}</button></form>
      <form method="post" action="/web/admin/users/{target.id}/restart-sync"><button class="btn">Перезапустить синхронизацию</button></form>
    </div><form method="post" action="/web/admin/users/{target.id}/send-message" style="margin-top:10px;"><textarea name="message" rows="2" placeholder="Сообщение пользователю"></textarea><button class="btn">Отправить сообщение</button></form></div>
    {_company_profile_admin_card(company_profile)}
    {_table("Кабинеты WB/Ozon", ["МП", "Название", "Статус", "Последний sync", "Ошибка"], account_rows)}
    {_table("Последние заказы", ["Дата", "МП", "Номер", "Статус"], order_rows)}
    {_table("Платежи", ["Дата", "Provider ID", "Сумма", "Статус", "Оплачен"], payment_rows)}
    {_table("Ошибки", ["Дата", "Путь", "Ошибка"], error_rows)}
    {_table("Уведомления", ["Дата", "Тип", "Статус", "Ошибка"], notification_rows)}
    {_table("Аудит действий", ["Дата", "Действие", "Сущность", "Детали"], audit_rows)}
    """
    return _admin_page(f"Пользователь {target.id}", user, content, "/web/admin/users")


def _table(title: str, headers: list[str], rows: str) -> str:
    th = "".join(f"<th>{_h(h)}</th>" for h in headers)
    empty = f'<tr><td colspan="{len(headers)}"><div class="empty-state">Нет данных</div></td></tr>'
    return f"<div class='band'><h3>{_h(title)}</h3><div class='table-wrap'><table class='table'><thead><tr>{th}</tr></thead><tbody>{rows or empty}</tbody></table></div></div>"


def _company_profile_admin_card(profile: UserCompanyProfile | None) -> str:
    if profile is None:
        return "<div class='band'><h3>Данные компании</h3><div class='empty-state'>Данные компании не сохранены</div></div>"
    rows = [
        ("ИНН", profile.inn),
        ("КПП", profile.kpp),
        ("ОГРН/ОГРНИП", profile.ogrn),
        ("Название", profile.name_short or profile.name_full),
        ("Тип", profile.company_type),
        ("Статус", profile.status),
        ("Адрес", profile.address),
        ("ОКВЭД", profile.okved),
        ("Дата обновления", _dt(profile.updated_at)),
    ]
    body = "".join(
        f"<span>{_h(label)}</span><strong>{_h(value) if value else 'н/д'}</strong>"
        for label, value in rows
    )
    return f"<div class='band'><h3>Данные компании</h3><div class='kv'>{body}</div></div>"


def _clean_optional(value: object, max_length: int) -> str | None:
    text = str(value or "").strip()
    return text[:max_length] if text else None


def _normalize_role(value: object) -> str:
    role = str(value or "user").strip().lower()
    return role if role in {"user", "admin"} else "user"


def _parse_subscription_expires_at(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некорректная дата окончания тарифа") from exc
    return datetime.combine(parsed, time.max, tzinfo=UTC)


def _admin_user_profile_snapshot(user: User) -> dict[str, object]:
    return {
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "phone": user.phone,
        "company_name": user.company_name,
        "inn": user.inn,
        "ogrn": user.ogrn,
        "timezone": user.timezone,
        "status": user.status.value,
        "role": user.role,
        "notifications_enabled": user.notifications_enabled,
    }


def _tariff_changed(
    current_subscription: object,
    tier_code: str,
    expires_at: datetime | None,
) -> bool:
    current_tier = getattr(getattr(current_subscription, "tier", None), "code", "")
    current_expires_at = getattr(current_subscription, "expires_at", None)
    if current_tier.lower() != tier_code.lower():
        return True
    if current_expires_at is None or expires_at is None:
        return current_expires_at is not expires_at
    return bool(current_expires_at.date() != expires_at.date())


@router.post("/admin/users/{target_user_id}/update")
async def admin_update_user(
    target_user_id: int,
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    target = await session.get(User, target_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    form = await request.form()
    service = ProfileService(session)
    phone = str(form.get("phone") or "")
    email = str(form.get("email") or "")
    inn = str(form.get("inn") or "")
    ogrn = str(form.get("ogrn") or "")
    try:
        service._validate_phone(phone)
        service._validate_email(email)
        service._validate_inn(inn)
        service._validate_ogrn(ogrn)
    except ProfileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    subscription_service = SubscriptionService(session)
    old_subscription = await subscription_service.get_user_current_subscription(target.id)
    old_profile = _admin_user_profile_snapshot(target)

    target.username = _clean_optional(form.get("username"), 255)
    target.first_name = _clean_optional(form.get("first_name"), 255)
    target.last_name = _clean_optional(form.get("last_name"), 255)
    target.email = email.strip().lower() if email.strip() else None
    target.phone = phone.strip() if phone.strip() else None
    target.company_name = _clean_optional(form.get("company_name"), 255)
    target.inn = inn.strip() if inn.strip() else None
    target.ogrn = ogrn.strip() if ogrn.strip() else None
    target.timezone = (str(form.get("timezone") or target.timezone or "Europe/Moscow").strip())[:64]
    try:
        target.status = UserStatus(str(form.get("status") or UserStatus.ACTIVE.value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некорректный статус пользователя") from exc
    target.role = _normalize_role(form.get("role"))
    target.notifications_enabled = form.get("notifications_enabled") == "on"

    tier_code = str(form.get("tier_code") or old_subscription.tier.code).strip()
    expires_at = _parse_subscription_expires_at(form.get("subscription_expires_at"))
    tariff_changed = _tariff_changed(old_subscription, tier_code, expires_at)
    if tariff_changed:
        new_subscription = await subscription_service.assign_admin_subscription(
            user_id=target.id,
            tier_code=tier_code,
            expires_at=expires_at,
            admin_user_id=user.id,
        )
    else:
        new_subscription = old_subscription.active_subscription

    await AuditLogService(session).log(
        "admin_user_updated",
        user_id=target.id,
        actor_user_id=user.id,
        entity_type="user",
        entity_id=target.id,
        details={
            "old_profile": old_profile,
            "new_profile": _admin_user_profile_snapshot(target),
            "old_tier": old_subscription.tier.code,
            "new_tier": tier_code,
            "old_expires_at": (
                old_subscription.expires_at.isoformat() if old_subscription.expires_at else None
            ),
            "new_expires_at": (
                new_subscription.expires_at.isoformat()
                if new_subscription and new_subscription.expires_at
                else None
            ),
            "subscription_id": new_subscription.id if new_subscription else None,
            "tariff_changed": tariff_changed,
        },
    )
    await session.commit()
    return RedirectResponse(f"/web/admin/users/{target_user_id}?saved=1", status_code=303)


@router.post("/admin/users/{target_user_id}/grant-tariff")
async def admin_grant_tariff(
    target_user_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    tier_code: str = Form(...),
    days: int = Form(30),
) -> RedirectResponse:
    _require_admin(user)
    subscription_service = SubscriptionService(session)
    old_subscription = await subscription_service.get_user_current_subscription(target_user_id)
    sub = await subscription_service.assign_admin_subscription(
        user_id=target_user_id,
        tier_code=tier_code,
        days=max(days, 1),
        admin_user_id=user.id,
    )
    await AuditLogService(session).log(
        "tariff_changed",
        user_id=target_user_id,
        actor_user_id=user.id,
        entity_type="subscription",
        entity_id=sub.id if sub else None,
        details={
            "old_tier": old_subscription.tier.code,
            "new_tier": tier_code,
            "old_expires_at": (
                old_subscription.expires_at.isoformat() if old_subscription.expires_at else None
            ),
            "days": days,
        },
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
    return _admin_page("Платежи", user, content, "/web/admin/payments")


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
    return _admin_page("Уведомления", user, content, "/web/admin/notifications")


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
        "Аудит действий",
        user,
        _table(
            "Аудит действий",
            ["Дата", "Пользователь", "Администратор", "Действие", "Сущность", "Детали"],
            body,
        ),
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
    content = f"<div class='page-header'><div><h2>Статус фоновых задач</h2></div><div class='page-actions'>{buttons}</div></div>{_table('Последние запуски', ['Задача', 'Статус', 'Старт', 'Финиш', 'мс', 'records', 'success', 'failed', 'Ошибка'], rows)}"
    return _admin_page("Статус синхронизаций", user, content, "/web/admin/sync-status")


_MANUAL_TASKS = {
    "poll_new_orders": "Заказы",
    "sync_sale_events": "Продажи",
    "sync_products": "Товары",
    "sync_wb_product_prices": "Цены WB",
    "check_auto_promo_prices": "Автоакции",
    "reconcile_pending_payments": "Платежи",
    "backfill_wb_daily_financial_details": "Дозагрузка финансов WB",
}


_FILTER_LABELS: dict[str, str] = {
    "all": "Все",
    "errors": "Только ошибки",
    "warnings": "Только предупреждения",
    "success": "Только успешные",
    "wb": "Wildberries",
    "ozon": "Ozon",
    "system": "Системные задачи",
    "finance": "Финансы",
    "notifications": "Уведомления",
}

_FILTER_VALUES = {
    "all": lambda info: True,
    "errors": lambda info: info.get("status_text") in ("error", "failed"),
    "warnings": lambda info: info.get("status_text") == "warning",
    "success": lambda info: info.get("status_text") == "success",
    "wb": lambda info: info.get("category") == "wb",
    "ozon": lambda info: info.get("category") == "ozon",
    "system": lambda info: info.get("category") == "system",
    "finance": lambda info: info.get("category") == "finance",
    "notifications": lambda info: info.get("category") == "notifications",
}


def _status_badge(status: str | None) -> str:
    text = translate_status(status)
    color = status_color(status)
    return f'<span class="badge" style="background:{color}15;color:{color};border-color:{color}40">{_h(text)}</span>'


def _duration_str(duration_ms: int | None) -> str:
    return _h(format_duration(duration_ms))


def _counters_str(counters: dict[str, int] | None) -> str:
    items = translate_counters(counters)
    if not items:
        return '<span class="muted">—</span>'
    parts = "".join(f"<div>{_h(label)}: {value}</div>" for label, value in items)
    return f"<div style='font-size:12px;line-height:1.6'>{parts}</div>"


def _error_str(error: str | None) -> str:
    if not error:
        return '<span class="muted">—</span>'
    return _h(translate_error(error))


@router.get("/admin/worker-diagnostics", response_class=HTMLResponse)
async def admin_worker_diagnostics_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    filter: str = Query(default="all"),
) -> str:
    _require_admin(user)
    svc = SyncStatusService(session)

    # Collect all task names: from DB + registry
    db_task_names = await svc.all_task_names()
    all_names_set = set(db_task_names) | set(TASK_REGISTRY.keys())
    all_task_names = sorted(all_names_set)

    # Get latest run for each task
    latest_runs = await svc.latest_by_task(limit=5000)

    # Build per-task display info
    task_infos: list[dict] = []
    for task_name in all_task_names:
        info = dict(get_task_info(task_name))
        run = latest_runs.get(task_name)
        stats: dict[str, int] = {}
        if run and isinstance(run.run_metadata, dict):
            s = run.run_metadata.get("stats") or {}
            if isinstance(s, dict):
                stats = {str(k): int(v) if v is not None else 0 for k, v in s.items()}

        status_text = run.status if run else "no_runs"
        info["task_name"] = task_name
        info["run"] = run
        info["stats"] = stats
        info["status_text"] = status_text
        info["category"] = info.get("category", "unknown")
        task_infos.append(info)

    # Apply filter
    filter_fn = _FILTER_VALUES.get(filter, _FILTER_VALUES["all"])
    filtered = [t for t in task_infos if filter_fn(t)]

    # Compute per-task totals for counters
    total_tasks = len(filtered)
    success_count = sum(
        1 for t in filtered if t.get("status_text") == "success"
    )
    warning_count = sum(
        1 for t in filtered if t.get("status_text") == "warning"
    )
    error_count = sum(
        1 for t in filtered if t.get("status_text") in ("error", "failed")
    )
    no_runs_count = sum(
        1 for t in filtered if t.get("status_text") == "no_runs"
    )

    # Build filter bar
    filter_items = "".join(
        f'<a class="btn {"btn-primary" if filter == key else ""}" href="?filter={key}">{label}</a>'
        for key, label in _FILTER_LABELS.items()
    )

    # Build KPI cards
    last_update = max(
        (
            t["run"].finished_at or t["run"].started_at
            for t in filtered
            if t.get("run") and (t["run"].finished_at or t["run"].started_at)
        ),
        default=None,
    )
    last_update_str = _dt(last_update) if last_update else "—"

    kpi_cards = f"""
    <div class="kpi-grid">
      <div class="kpi action"><span>Фоновых задач</span><strong>{total_tasks}</strong></div>
      <div class="kpi good"><span>Успешно</span><strong>{success_count}</strong></div>
      <div class="kpi warn"><span>Предупреждения</span><strong>{warning_count}</strong></div>
      <div class="kpi bad"><span>Ошибки</span><strong>{error_count}</strong></div>
      <div class="kpi neutral"><span>Не запускались</span><strong>{no_runs_count}</strong></div>
      <div class="kpi"><span>Последнее обновление</span><strong style="font-size:14px">{last_update_str}</strong></div>
    </div>"""

    # Build table rows
    rows = ""
    for t_info in filtered:
        task_name = t_info["task_name"]
        title = t_info.get("title", task_name)
        category = t_info.get("category", "unknown")
        category_title = translate_category(category)
        run = t_info.get("run")
        status_text = t_info.get("status_text", "no_runs")
        stats = t_info.get("stats", {})

        started = _dt(run.started_at if run else None)
        finished = _dt(run.finished_at if run else None)
        if run and run.started_at and not run.finished_at:
            finished = '<span class="muted">ещё выполняется</span>'

        duration = _duration_str(run.duration_ms if run else None)
        success_val = run.success_count if run else 0
        failed_val = run.failed_count if run else 0

        counters_html = _counters_str(stats)
        error_html = _error_str(run.last_error if run else None)
        badge = _status_badge(status_text)

        # Detail section: task description + last 10 runs
        info = get_task_info(task_name)
        description = info.get("description", "")
        last_10_runs = ""
        if task_name in db_task_names:
            recent = await svc.recent_runs_by_task(task_name, limit=10)
            if recent:
                sub_rows = ""
                for sub in recent:
                    sub_status = _status_badge(sub.status)
                    sub_started = _dt(sub.started_at)
                    sub_finished = _dt(sub.finished_at)
                    sub_dur = _duration_str(sub.duration_ms)
                    sub_success = sub.success_count
                    sub_failed = sub.failed_count
                    sub_error = _h(sub.last_error or "")
                    sub_rows += (
                        f"<tr><td>{sub_status}</td>"
                        f"<td>{sub_started}</td>"
                        f"<td>{sub_finished}</td>"
                        f"<td>{sub_dur}</td>"
                        f"<td>{sub_success}</td>"
                        f"<td>{sub_failed}</td>"
                        f"<td style='max-width:300px;overflow:hidden;text-overflow:ellipsis'>{sub_error}</td></tr>"
                    )
                last_10_runs = f"""
                <div style="margin-top:12px">
                  <strong style="font-size:13px">Последние 10 запусков:</strong>
                  <div class="table-wrap" style="margin-top:6px">
                    <table class="table" style="font-size:12px">
                      <thead><tr><th>Состояние</th><th>Начало</th><th>Завершение</th><th>Длительность</th><th>Успешно</th><th>Ошибок</th><th>Ошибка</th></tr></thead>
                      <tbody>{sub_rows}</tbody>
                    </table>
                  </div>
                </div>"""

        detail_html = f"""
        <details style="margin-top:4px">
          <summary class="button-tiny" style="cursor:pointer">Подробнее</summary>
          <div style="margin-top:8px;padding:12px;background:var(--bg-muted);border-radius:var(--radius-sm);font-size:13px;line-height:1.6">
            <div class="kv">
              <span>Техническое имя</span><strong><code>{_h(task_name)}</code></strong>
              <span>Описание</span><strong>{_h(description)}</strong>
              <span>Категория</span><strong>{category_title}</strong>
              <span>Состояние</span><strong>{badge}</strong>
              <span>Начало</span><strong>{started}</strong>
              <span>Завершение</span><strong>{finished}</strong>
              <span>Длительность</span><strong>{duration}</strong>
              <span>Успешных операций</span><strong>{success_val}</strong>
              <span>Ошибок</span><strong>{failed_val}</strong>
              <span>Итоги выполнения</span><strong>{counters_html}</strong>
              <span>Последняя ошибка</span><strong>{error_html}</strong>
            </div>
            {last_10_runs}
          </div>
        </details>"""

        rows += (
            f"<tr>"
            f"<td><strong>{_h(title)}</strong><div class='muted' style='font-size:11px'>{_h(task_name)}</div></td>"
            f"<td>{_h(category_title)}</td>"
            f"<td>{badge}</td>"
            f"<td>{started}</td>"
            f"<td>{finished}</td>"
            f"<td>{duration}</td>"
            f"<td class='num'>{success_val}</td>"
            f"<td class='num'>{failed_val}</td>"
            f"<td style='max-width:200px'>{counters_html}</td>"
            f"<td style='max-width:200px;overflow-wrap:break-word'>{error_html}</td>"
            f"<td>{detail_html}</td>"
            f"</tr>"
        )

    if not rows:
        rows = f'<tr><td colspan="11"><div class="empty-state" style="min-height:80px">Нет данных для выбранного фильтра</div></td></tr>'

    section_title = "Все фоновые задачи"
    has_key = any(t.get("is_key") for t in filtered)
    has_non_key = any(not t.get("is_key") for t in filtered)
    if has_key and has_non_key:
        section_title = "Ключевые и остальные фоновые задачи"

    info_block = """
    <div class="notice" style="margin-bottom:16px">
      <strong>Фоновые задачи</strong> — это автоматические процессы MP Control, которые загружают заказы, продажи, возвраты, цены, финансовые операции и выполняют системные проверки. Здесь отображается последнее состояние каждой задачи.
    </div>"""

    content = f"""
    <div class="page-header">
      <div>
        <h2>Диагностика фоновых задач</h2>
        <div class="summary-strip">
          <span>Источник данных: <strong>sync_task_runs</strong></span>
          <span>Всего задач в реестре: <strong>{len(TASK_REGISTRY)}</strong></span>
        </div>
      </div>
    </div>
    {info_block}
    {kpi_cards}
    <div class="filters" style="grid-template-columns:repeat(auto-fit, minmax(100px, auto))">
      {filter_items}
    </div>
    <div class="band">
      <h3 style="margin-bottom:12px">{section_title}</h3>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th style="min-width:180px">Фоновая задача</th>
              <th>Категория</th>
              <th>Состояние</th>
              <th>Начало</th>
              <th>Завершение</th>
              <th>Длительность</th>
              <th class="num">Успешных операций</th>
              <th class="num">Ошибок</th>
              <th>Итоги выполнения</th>
              <th>Последняя ошибка</th>
              <th></th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>"""

    return _admin_page("Диагностика фоновых задач", user, content, "/web/admin/worker-diagnostics")


@router.post("/admin/sync-status/run/{task_name}")
async def admin_run_sync_task(
    task_name: str,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    if task_name not in _MANUAL_TASKS:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    try:
        queue = await create_pool(redis_settings_from_url(get_settings().redis_url))
        try:
            job = await queue.enqueue_job(
                task_name,
                triggered_by_user_id=user.id,
                source="web_admin",
            )
        finally:
            await queue.close()
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Не удалось поставить задачу в очередь"
        ) from exc
    await AuditLogService(session).log(
        "sync_started",
        actor_user_id=user.id,
        entity_type="sync_task",
        entity_id=task_name,
        details={"job_id": job.job_id if job else None},
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
    <div class="page-header"><div><h2>Здоровье кабинетов</h2><div class="summary-strip"><span>WB API: <strong>{"OK" if wb_ok else "нет активного OK"}</strong></span><span>Ozon API: <strong>{"OK" if ozon_ok else "нет активного OK"}</strong></span><span>Товары: <strong>{products_count}</strong></span><span>Заказы: <strong>{orders_count}</strong></span><span>Подписка: <strong>{"активна до " + _dt(active_sub.expires_at) if active_sub else "нет активной"}</strong></span></div></div></div>
    {_table("Кабинеты и последние синхронизации", ["МП", "Название", "API", "Заказы", "Продажи", "Товары", "Остатки", "Ошибка"], account_rows)}
    {_table("Фоновые задачи", ["Задача", "Статус", "Последний запуск", "Ошибка"], run_rows)}
    """
    return page("Здоровье кабинетов", _name(user), content, active_path="/web/health")
