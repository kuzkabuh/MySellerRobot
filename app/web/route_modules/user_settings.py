# ruff: noqa: E501, F841
"""version: 1.0.0
description: User settings web routes with tabs.
"""

import logging
from datetime import datetime
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, User
from app.models.enums import Marketplace
from app.services.company_lookup_service import (
    INN_ERROR_MESSAGE,
    LOOKUP_UNAVAILABLE_MESSAGE,
    CompanyLookupError,
    CompanyLookupService,
    CompanyProfileDTO,
    normalize_inn,
)
from app.services.profile_service import ProfileService, ProfileUpdateData, ProfileValidationError
from app.services.subscription_service import SubscriptionService
from app.services.support_service import TICKET_CATEGORIES, TICKET_STATUS_LABELS, SupportService
from app.services.user_activity_service import UserActivityService, action_label
from app.services.user_sync_status_service import SYNC_STATUS_LABELS, UserSyncStatusService
from app.services.web_cabinet_service import WebCabinetService
from app.services.web_password_auth_service import WebPasswordAuthError, WebPasswordAuthService
from app.utils.datetime import format_datetime_for_user
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.rendering import page

logger = logging.getLogger(__name__)
router = APIRouter()


def _dt(dt_value: datetime | None, timezone: str) -> str:
    if dt_value is None:
        return "н/д"
    return format_datetime_for_user(dt_value, timezone, "%d.%m.%Y %H:%M")


def _url_quote(value: str) -> str:
    return quote(value, safe="")


def _settings_tabs(active_tab: str) -> str:
    tabs = [
        ("profile", "Профиль", "/web/settings"),
        ("marketplaces", "Маркетплейсы", "/web/settings/marketplaces"),
        ("tariff", "Тариф", "/web/settings/tariff"),
        ("notifications", "Уведомления", "/web/settings/notifications"),
        ("sync", "Синхронизация", "/web/settings/sync"),
        ("company", "Данные компании", "/web/settings/company"),
        ("security", "Безопасность", "/web/settings/security"),
        ("support", "Поддержка", "/web/settings/support"),
    ]
    links = []
    for code, label, href in tabs:
        cls = ' class="active"' if code == active_tab else ""
        links.append(f'<a{cls} href="{href}">{escape(label)}</a>')
    return f'<nav class="subnav">{"".join(links)}</nav>'


def _profile_tab(user: User) -> str:
    first_name = getattr(user, "first_name", None)
    last_name = getattr(user, "last_name", None)
    username = getattr(user, "username", None)
    timezone = getattr(user, "timezone", "Europe/Moscow")
    display_name = first_name or last_name or username or str(user.telegram_id)
    return f"""
      {_settings_tabs("profile")}
      <section class="detail-grid">
        <section class="band">
          <h2>Данные профиля</h2>
          <form method="post" action="/web/settings/profile">
            <div class="kv" style="margin-bottom:14px">
              <span>Telegram ID</span><strong>{user.telegram_id}</strong>
              <span>Username</span><strong>{escape("@" + username if username else "н/д")}</strong>
              <span>Дата регистрации</span><strong>{_dt(getattr(user, "created_at", None), timezone)}</strong>
              <span>Последняя активность</span><strong>{_dt(getattr(user, "last_activity_at", None), timezone)}</strong>
            </div>
            <div class="filters">
              <div>
                <label for="first_name">Имя</label>
                <input id="first_name" name="first_name" value="{escape(first_name or "")}">
              </div>
              <div>
                <label for="last_name">Фамилия</label>
                <input id="last_name" name="last_name" value="{escape(last_name or "")}">
              </div>
              <div>
                <label for="phone">Телефон</label>
                <input id="phone" name="phone" value="{escape(getattr(user, "phone", None) or "")}" placeholder="+7 900 123-45-67">
              </div>
              <div>
                <label for="email">Email</label>
                <input id="email" name="email" type="email" value="{escape(getattr(user, "email", None) or "")}">
              </div>
              <div>
                <label for="company_name">Компания</label>
                <input id="company_name" name="company_name" value="{escape(getattr(user, "company_name", None) or "")}">
              </div>
              <div>
                <label for="inn">ИНН</label>
                <input id="inn" name="inn" value="{escape(getattr(user, "inn", None) or "")}" placeholder="10 или 12 цифр">
              </div>
              <div>
                <label for="ogrn">ОГРН / ОГРНИП</label>
                <input id="ogrn" name="ogrn" value="{escape(getattr(user, "ogrn", None) or "")}" placeholder="13 или 15 цифр">
              </div>
              <div>
                <label for="timezone">Часовой пояс</label>
                <input id="timezone" name="timezone" value="{escape(timezone)}">
              </div>
            </div>
            <button class="btn btn-primary" type="submit">Сохранить</button>
          </form>
        </section>
        <section class="band">
          <h2>Текущий тариф</h2>
          <div class="kv">
            <span>Тариф</span><strong>{escape(getattr(user, "tariff", "free"))}</strong>
            <span>Статус</span><strong>{escape(getattr(getattr(user, "status", None), "value", "ACTIVE"))}</strong>
            <span>Уведомления</span><strong>{"включены" if getattr(user, "notifications_enabled", True) else "выключены"}</strong>
          </div>
          <p style="margin-top:14px"><a class="btn btn-primary" href="/web/settings/tariff">Управление тарифом</a></p>
          <p><a class="btn" href="/web/settings/notifications">Настроить уведомления</a></p>
        </section>
      </section>
    """


def _company_tab(
    user: User,
    profile: object | None,
    *,
    preview: CompanyProfileDTO | None = None,
    message: str | None = None,
    error: str | None = None,
    warning: str | None = None,
) -> str:
    current_inn = (
        (preview.inn if preview else None)
        or getattr(profile, "inn", None)
        or getattr(user, "inn", None)
        or ""
    )
    status_message = ""
    if message:
        status_message += f'<div class="notice success">{escape(message)}</div>'
    if error:
        status_message += f'<div class="notice danger">{escape(error)}</div>'
    if warning:
        status_message += f'<div class="notice warning">{escape(warning)}</div>'

    preview_html = _company_preview(preview) if preview else ""
    saved_html = _company_saved_card(profile)
    clear_button = (
        '<button class="btn btn-danger" type="submit">Очистить данные компании</button>'
        if profile
        else ""
    )
    refresh_button = (
        """
        <form method="post" action="/web/settings/company/refresh">
          <button class="btn" type="submit">Обновить данные</button>
        </form>
        """
        if profile
        else ""
    )
    return f"""
      {_settings_tabs("company")}
      <section class="detail-grid">
        <section class="band">
          <h2>Данные компании</h2>
          {status_message}
          <form method="post" action="/web/settings/company/lookup" class="filters">
            <div>
              <label for="company_lookup_inn">ИНН</label>
              <input id="company_lookup_inn" name="inn" value="{escape(current_inn)}" placeholder="10 или 12 цифр">
            </div>
            <button class="btn btn-primary" type="submit">Загрузить данные по ИНН</button>
          </form>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
            {refresh_button}
            <form method="post" action="/web/settings/company/clear">{clear_button}</form>
          </div>
        </section>
        {preview_html}
        {saved_html}
      </section>
    """


def _company_preview(company: CompanyProfileDTO | None) -> str:
    if company is None:
        return ""
    rows = _company_kv_rows(company)
    warning = (
        f'<div class="notice warning">{escape(company.status_warning)}</div>'
        if company.status_warning
        else ""
    )
    return f"""
      <section class="band">
        <h2>Найденные данные</h2>
        {warning}
        <div class="kv">{rows}</div>
        <form method="post" action="/web/settings/company/save" style="margin-top:14px">
          <input type="hidden" name="inn" value="{escape(company.inn)}">
          <button class="btn btn-primary" type="submit">Сохранить</button>
        </form>
      </section>
    """


def _company_saved_card(profile: object | None) -> str:
    if profile is None:
        return """
        <section class="band">
          <h2>Сохранённые данные</h2>
          <div class="empty-state">Данные компании ещё не сохранены.</div>
        </section>
        """
    return f"""
      <section class="band">
        <h2>Сохранённые данные</h2>
        <div class="kv">{_company_kv_rows(profile)}</div>
      </section>
    """


def _company_kv_rows(company: object) -> str:
    updated_at = getattr(company, "updated_at", None)
    registration_date = getattr(company, "registration_date", None)
    source = getattr(company, "source", None)
    rows = [
        ("ИНН", getattr(company, "inn", None)),
        ("КПП", getattr(company, "kpp", None)),
        ("ОГРН/ОГРНИП", getattr(company, "ogrn", None)),
        ("Полное наименование", getattr(company, "name_full", None)),
        ("Краткое наименование", getattr(company, "name_short", None)),
        ("Тип", getattr(company, "company_type", None)),
        ("Статус", getattr(company, "status", None)),
        ("Юридический адрес", getattr(company, "address", None)),
        ("ОКВЭД", getattr(company, "okved", None)),
        ("ОКВЭД название", getattr(company, "okved_name", None)),
        ("Руководитель", getattr(company, "director_name", None)),
        ("Дата регистрации", _dt(registration_date, "Europe/Moscow") if registration_date else None),
        ("Источник данных", source),
        ("Дата последнего обновления", _dt(updated_at, "Europe/Moscow") if updated_at else None),
    ]
    return "".join(
        f"<span>{escape(label)}</span><strong>{escape(str(value) if value else 'н/д')}</strong>"
        for label, value in rows
    )


def _marketplaces_tab(user: User, accounts: list[MarketplaceAccount], timezone: str) -> str:
    if not accounts:
        rows = '<tr><td colspan="6"><div class="empty-state">Кабинеты ещё не подключены. Подключение выполняется через Telegram-бота.</div></td></tr>'
    else:
        row_parts = []
        for acc in accounts:
            mp_label = "Wildberries" if acc.marketplace == Marketplace.WB else "Ozon"
            mp_cls = "wb" if acc.marketplace == Marketplace.WB else "ozon"
            status_label = acc.status.value
            status_cls = "good" if acc.status.value == "ACTIVE" else "bad" if acc.status.value == "ERROR" else "warn"
            api_status = acc.api_key_status or "unchecked"
            api_cls = "good" if api_status == "active" else "bad" if api_status in ("auth_error", "expired") else "warn"
            api_status_labels = {
                "active": "Активен",
                "auth_error": "Ошибка авторизации",
                "insufficient_permissions": "Недостаточно прав",
                "expired": "Истёк",
                "unchecked": "Не проверен",
                "pending_check": "Ожидает проверки",
            }
            api_label = api_status_labels.get(api_status, api_status)
            row_parts.append(
                "<tr>"
                f'<td>{escape(acc.name)}<div class="muted">#{acc.id}</div></td>'
                f'<td><span class="badge {mp_cls}">{mp_label}</span></td>'
                f'<td><span class="badge {status_cls}">{status_label}</span></td>'
                f'<td><span class="badge {api_cls}">{api_label}</span>'
                f'<div class="muted">Проверен: {_dt(acc.api_key_checked_at, timezone)}</div></td>'
                f'<td>{_dt(acc.last_success_sync_at, timezone)}</td>'
                f'<td>{_dt(acc.last_error_at, timezone)}<div class="muted">{escape(acc.last_error_message or "")}</div></td>'
                "</tr>"
            )
        rows = "".join(row_parts)

    return f"""
      {_settings_tabs("marketplaces")}
      <section class="band">
        <h2>Подключённые кабинеты</h2>
        <p class="muted">Подключение нового кабинета выполняется через Telegram-бота. API-ключи хранятся в зашифрованном виде и не отображаются полностью.</p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Кабинет</th><th>Маркетплейс</th><th>Статус</th>
                <th>API-ключ</th><th>Последняя синхронизация</th><th>Последняя ошибка</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Как получить API-ключ</h2>
        <div class="detail-grid">
          <div class="band">
            <h3>Wildberries</h3>
            <ol class="muted">
              <li>Войдите в личный кабинет WB: <strong>sellers.wildberries.ru</strong></li>
              <li>Перейдите в раздел «Настройки» → «Доступ к API»</li>
              <li>Создайте новый токен с нужными правами</li>
              <li>Скопируйте ключ и отправьте боту</li>
            </ol>
          </div>
          <div class="band">
            <h3>Ozon</h3>
            <ol class="muted">
              <li>Войдите в кабинет Ozon Seller: <strong>seller.ozon.ru</strong></li>
              <li>Перейдите в «Настройки» → «API-ключи»</li>
              <li>Создайте ключ с правами на чтение</li>
              <li>Скопируйте Client-Id и Api-Key, отправьте боту</li>
            </ol>
          </div>
        </div>
      </section>
    """


def _notifications_tab(user: User) -> str:
    checked_global = " checked" if user.notifications_enabled else ""
    return f"""
      {_settings_tabs("notifications")}
      <section class="band">
        <h2>Глобальные уведомления</h2>
        <form method="post" action="/web/settings/notifications">
          <div class="filters">
            <div>
              <label class="status-chip">
                <input type="checkbox" name="notifications_enabled"{checked_global}>
                Telegram-уведомления
              </label>
            </div>
          </div>
          <button class="btn btn-primary" type="submit">Сохранить</button>
        </form>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Типы уведомлений</h2>
        <p class="muted">Тонкая настройка по типам событий и кабинетам доступна в Telegram-боте через меню «Уведомления».</p>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Событие</th><th>Описание</th><th>Канал</th></tr></thead>
            <tbody>
              <tr><td>Новые заказы</td><td>FBS/FBO/rFBS заказы</td><td>Telegram</td></tr>
              <tr><td>Продажи и выкупы</td><td>Завершённые продажи</td><td>Telegram</td></tr>
              <tr><td>Возвраты</td><td>Возвраты от покупателей</td><td>Telegram</td></tr>
              <tr><td>Низкие остатки</td><td>Алерты по остаткам</td><td>Telegram</td></tr>
              <tr><td>Ошибки синхронизации</td><td>Проблемы с API</td><td>Telegram</td></tr>
              <tr><td>Ежедневный отчёт</td><td>Сводка за день</td><td>Telegram</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    """


def _sync_tab(sync_statuses: list, timezone: str) -> str:
    if not sync_statuses:
        rows = '<tr><td colspan="5"><div class="empty-state">Синхронизации ещё не запускались.</div></td></tr>'
    else:
        row_parts = []
        for s in sync_statuses:
            status_label = SYNC_STATUS_LABELS.get(s.status, s.status)
            status_cls = "good" if s.status == "success" else "bad" if s.status == "error" else "warn"
            row_parts.append(
                "<tr>"
                f"<td>{escape(s.sync_type_label)}</td>"
                f'<td><span class="badge {status_cls}">{status_label}</span></td>'
                f"<td>{_dt(s.last_run_at, timezone)}</td>"
                f"<td>{_dt(s.last_success_at, timezone)}</td>"
                f"<td>{escape(s.last_error_message or '—')}</td>"
                "</tr>"
            )
        rows = "".join(row_parts)

    return f"""
      {_settings_tabs("sync")}
      <section class="band">
        <h2>Статус синхронизаций</h2>
        <p class="muted">Частота синхронизации зависит от вашего тарифа. Ручной запуск доступен через Telegram-бота или страницу «Кабинеты МП».</p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>Тип данных</th><th>Статус</th><th>Последний запуск</th><th>Последний успех</th><th>Последняя ошибка</th></tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
      </section>
    """


def _security_tab(user: User, activity_logs: list, timezone: str) -> str:
    if not activity_logs:
        log_rows = '<tr><td colspan="4"><div class="empty-state">Действий пока не зафиксировано.</div></td></tr>'
    else:
        log_rows = "".join(
            "<tr>"
            f"<td>{_dt(log.created_at, timezone)}</td>"
            f"<td>{escape(action_label(log.action))}</td>"
            f"<td>{escape(log.entity_type or '—')}</td>"
            f"<td>{escape(log.ip_address or '—')}</td>"
            "</tr>"
            for log in activity_logs[:30]
        )

    password_enabled = bool(getattr(user, "web_password_enabled", False))
    password_status = "включён" if password_enabled else "выключен"
    password_updated = _dt(getattr(user, "web_password_updated_at", None), timezone)
    password_login = escape(getattr(user, "web_login", None) or "")
    return f"""
      {_settings_tabs("security")}
      <section class="detail-grid">
        <section class="band">
          <h2>Последний вход</h2>
          <div class="kv">
            <span>Дата</span><strong>{_dt(getattr(user, "last_login_at", None), timezone)}</strong>
            <span>IP-адрес</span><strong>{escape(getattr(user, "last_login_ip", None) or "н/д")}</strong>
            <span>User-Agent</span><strong style="word-break:break-all;font-size:12px">{escape((getattr(user, "last_login_user_agent", None) or "н/д")[:120])}</strong>
            <span>Вход по паролю</span><strong>{password_status}</strong>
            <span>Пароль обновлён</span><strong>{password_updated}</strong>
          </div>
        </section>
        <section class="band">
          <h2>Активные сессии</h2>
          <p class="muted">Web-сессии управляются через cookie. При выходе сессия аннулируется.</p>
          <p><a class="btn btn-danger" href="/web/logout">Выйти из всех сессий</a></p>
        </section>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Вход по логину и паролю</h2>
        <p class="muted">Telegram-вход продолжит работать. Пароль хранится только в виде hash.</p>
        <form method="post" action="/web/settings/password-login">
          <div class="filters">
            <div>
              <label for="web_login">Логин</label>
              <input id="web_login" name="web_login" value="{password_login}" placeholder="seller.login">
            </div>
            <div>
              <label for="web_password">Новый пароль</label>
              <input id="web_password" name="web_password" type="password" autocomplete="new-password">
            </div>
            <div>
              <label for="web_password_confirm">Повторите новый пароль</label>
              <input id="web_password_confirm" name="web_password_confirm" type="password" autocomplete="new-password">
            </div>
            <div>
              <label class="status-chip">
                <input type="checkbox" name="web_password_enabled" {"checked" if password_enabled else ""}>
                Разрешить вход по логину и паролю
              </label>
            </div>
          </div>
          <button class="btn btn-primary" type="submit">Сохранить</button>
        </form>
        {'<form method="post" action="/web/settings/password-login/disable" style="margin-top:10px"><button class="btn btn-danger" type="submit">Отключить вход по паролю</button></form>' if password_enabled else ''}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>История действий</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Дата</th><th>Действие</th><th>Объект</th><th>IP</th></tr></thead>
            <tbody>{log_rows}</tbody>
          </table>
        </div>
      </section>
    """


def _support_tab(tickets: list, timezone: str) -> str:
    if not tickets:
        ticket_rows = '<tr><td colspan="5"><div class="empty-state">Обращений в поддержку пока нет.</div></td></tr>'
    else:
        ticket_rows = "".join(
            "<tr>"
            f"<td>{_dt(t.created_at, timezone)}</td>"
            f"<td>{escape(t.subject)}</td>"
            f'<td><span class="badge {"good" if t.status == "closed" else "warn" if t.status == "responded" else "action"}">{TICKET_STATUS_LABELS.get(t.status, t.status)}</span></td>'
            f"<td>{escape(t.category or "—")}</td>"
            f'<td>{escape((t.admin_response or "—")[:100])}</td>'
            "</tr>"
            for t in tickets
        )

    category_options = "".join(
        f'<option value="{code}">{escape(label)}</option>' for code, label in TICKET_CATEGORIES
    )

    return f"""
      {_settings_tabs("support")}
      <section class="band">
        <h2>Создать обращение</h2>
        <form method="post" action="/web/settings/support">
          <div class="filters">
            <div>
              <label for="subject">Тема</label>
              <input id="subject" name="subject" required placeholder="Кратко опишите проблему">
            </div>
            <div>
              <label for="category">Категория</label>
              <select id="category" name="category">{category_options}</select>
            </div>
          </div>
          <div style="margin-top:10px">
            <label for="message">Сообщение</label>
            <textarea id="message" name="message" rows="4" required placeholder="Подробно опишите проблему или вопрос"></textarea>
          </div>
          <button class="btn btn-primary" type="submit" style="margin-top:10px">Отправить</button>
        </form>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Мои обращения</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Дата</th><th>Тема</th><th>Статус</th><th>Категория</th><th>Ответ</th></tr></thead>
            <tbody>{ticket_rows}</tbody>
          </table>
        </div>
      </section>
    """


@router.get("/settings", response_class=HTMLResponse)
async def settings_profile_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    return page(
        "Настройки — Профиль",
        user.first_name or user.username or str(user.telegram_id),
        _profile_tab(user),
        active_path="/web/settings",
    )


@router.post("/settings/password-login")
async def save_password_login_settings(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    form = await request.form()
    enabled = form.get("web_password_enabled") == "on"
    try:
        await WebPasswordAuthService(session).update_password_login(
            user,
            login=str(form.get("web_login") or ""),
            password=str(form.get("web_password") or ""),
            password_confirm=str(form.get("web_password_confirm") or ""),
            enabled=enabled,
        )
        await UserActivityService(session).log_activity(
            user.id,
            "web_password_settings_updated",
            ip_address=request.client.host if request.client else None,
        )
        await session.commit()
    except WebPasswordAuthError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/web/settings/security?saved=1", status_code=303)


@router.post("/settings/password-login/disable")
async def disable_password_login_settings(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    await WebPasswordAuthService(session).disable_password_login(user)
    await UserActivityService(session).log_activity(
        user.id,
        "web_password_login_disabled",
        ip_address=request.client.host if request.client else None,
    )
    await session.commit()
    return RedirectResponse(url="/web/settings/security?saved=1", status_code=303)


@router.post("/settings/profile")
async def save_profile(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    form = await request.form()
    try:
        await ProfileService(session).update_profile(
            user.id,
            ProfileUpdateData(
                first_name=form.get("first_name"),
                last_name=form.get("last_name"),
                phone=form.get("phone"),
                email=form.get("email"),
                company_name=form.get("company_name"),
                inn=form.get("inn"),
                ogrn=form.get("ogrn"),
                timezone=form.get("timezone"),
            ),
        )
        await UserActivityService(session).log_activity(
            user.id, "profile_update", ip_address=request.client.host if request.client else None
        )
    except ProfileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/web/settings?saved=1", status_code=303)


@router.get("/settings/marketplaces", response_class=HTMLResponse)
async def settings_marketplaces_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    from sqlalchemy import select
    stmt = select(MarketplaceAccount).where(
        MarketplaceAccount.user_id == user.id,
        MarketplaceAccount.is_active.is_(True),
    )
    result = await session.execute(stmt)
    accounts = list(result.scalars().all())
    return page(
        "Настройки — Маркетплейсы",
        user.first_name or user.username or str(user.telegram_id),
        _marketplaces_tab(user, accounts, user.timezone),
        active_path="/web/settings",
    )


@router.get("/settings/tariff", response_class=HTMLResponse)
async def settings_tariff_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    data = await WebCabinetService(session).subscription_page(user.id, user.timezone)
    tiers = await SubscriptionService(session).get_all_tiers()
    from app.web.views import _subscription_content
    content = _settings_tabs("tariff") + _subscription_content(data, tiers, user.timezone)
    return page(
        "Настройки — Тариф",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/settings",
    )


@router.get("/settings/notifications", response_class=HTMLResponse)
async def settings_notifications_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> str:
    return page(
        "Настройки — Уведомления",
        user.first_name or user.username or str(user.telegram_id),
        _notifications_tab(user),
        active_path="/web/settings",
    )


@router.post("/settings/notifications")
async def save_notifications(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    form = await request.form()
    db_user = await session.get(User, user.id)
    if db_user is not None:
        db_user.notifications_enabled = form.get("notifications_enabled") == "on"
        await session.commit()
        await UserActivityService(session).log_activity(
            user.id, "notification_settings_update",
            ip_address=request.client.host if request.client else None,
        )
    return RedirectResponse(url="/web/settings/notifications?saved=1", status_code=303)


@router.get("/settings/sync", response_class=HTMLResponse)
async def settings_sync_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    statuses = await UserSyncStatusService(session).get_statuses(user.id)
    return page(
        "Настройки — Синхронизация",
        user.first_name or user.username or str(user.telegram_id),
        _sync_tab(statuses, user.timezone),
        active_path="/web/settings",
    )


@router.get("/settings/company", response_class=HTMLResponse)
async def settings_company_page(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    profile = await CompanyLookupService(session).get_user_company_profile(user.id)
    content = _company_tab(
        user,
        profile,
        message=request.query_params.get("saved"),
        error=request.query_params.get("error"),
    )
    return page(
        "Настройки — Данные компании",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/settings/company",
    )


@router.post("/settings/company/lookup", response_class=HTMLResponse)
async def settings_company_lookup(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    inn: str = Form(...),
) -> str:
    service = CompanyLookupService(session)
    profile = await service.get_user_company_profile(user.id)
    try:
        result = await service.fetch_company_by_inn(inn)
    except CompanyLookupError as exc:
        logger.warning(
            "company_lookup_web_failed",
            extra={"user_id": user.id, "inn": normalize_inn(inn), "error": str(exc)},
        )
        content = _company_tab(user, profile, error=str(exc) or INN_ERROR_MESSAGE)
        return page(
            "Настройки — Данные компании",
            user.first_name or user.username or str(user.telegram_id),
            content,
            active_path="/web/settings/company",
        )
    content = _company_tab(
        user,
        profile,
        preview=result.company,
        message="Данные найдены. Проверьте их и нажмите «Сохранить».",
        warning=result.warning,
    )
    return page(
        "Настройки — Данные компании",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/settings/company",
    )


@router.post("/settings/company/save")
async def settings_company_save(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    inn: str = Form(...),
) -> RedirectResponse:
    service = CompanyLookupService(session)
    try:
        result = await service.fetch_company_by_inn(inn)
        await service.save_company_profile(user, result.company)
        await UserActivityService(session).log_activity(
            user.id,
            "company_profile_saved",
            ip_address=request.client.host if request.client else None,
        )
        await session.commit()
    except CompanyLookupError as exc:
        await session.rollback()
        logger.warning(
            "company_profile_save_failed",
            extra={"user_id": user.id, "inn": normalize_inn(inn), "error": str(exc)},
        )
        return RedirectResponse(
            f"/web/settings/company?error={_url_quote(str(exc) or INN_ERROR_MESSAGE)}",
            status_code=303,
        )
    return RedirectResponse(
        "/web/settings/company?saved=Данные компании сохранены",
        status_code=303,
    )


@router.post("/settings/company/refresh")
async def settings_company_refresh(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    service = CompanyLookupService(session)
    profile = await service.get_user_company_profile(user.id)
    inn = getattr(profile, "inn", None) or getattr(user, "inn", None)
    if not inn:
        return RedirectResponse(
            f"/web/settings/company?error={_url_quote('Сначала укажите ИНН')}",
            status_code=303,
        )
    try:
        result = await service.fetch_company_by_inn(inn)
        await service.save_company_profile(user, result.company)
        await UserActivityService(session).log_activity(
            user.id,
            "company_profile_refreshed",
            ip_address=request.client.host if request.client else None,
        )
        await session.commit()
    except CompanyLookupError as exc:
        await session.rollback()
        logger.warning(
            "company_profile_refresh_failed",
            extra={"user_id": user.id, "inn": normalize_inn(inn), "error": str(exc)},
        )
        return RedirectResponse(
            f"/web/settings/company?error={_url_quote(str(exc) or LOOKUP_UNAVAILABLE_MESSAGE)}",
            status_code=303,
        )
    return RedirectResponse(
        "/web/settings/company?saved=Данные компании обновлены",
        status_code=303,
    )


@router.post("/settings/company/clear")
async def settings_company_clear(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    try:
        await CompanyLookupService(session).clear_company_profile(user)
        await UserActivityService(session).log_activity(
            user.id,
            "company_profile_cleared",
            ip_address=request.client.host if request.client else None,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("company_profile_clear_failed", extra={"user_id": user.id})
        return RedirectResponse(
            f"/web/settings/company?error={_url_quote('Не удалось очистить данные компании')}",
            status_code=303,
        )
    return RedirectResponse(
        "/web/settings/company?saved=Данные компании очищены",
        status_code=303,
    )


@router.get("/settings/security", response_class=HTMLResponse)
async def settings_security_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    logs = await UserActivityService(session).get_recent_activity(user.id)
    return page(
        "Настройки — Безопасность",
        user.first_name or user.username or str(user.telegram_id),
        _security_tab(user, logs, user.timezone),
        active_path="/web/settings",
    )


@router.get("/settings/support", response_class=HTMLResponse)
async def settings_support_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    tickets = await SupportService(session).get_user_tickets(user.id)
    return page(
        "Настройки — Поддержка",
        user.first_name or user.username or str(user.telegram_id),
        _support_tab(tickets, user.timezone),
        active_path="/web/settings",
    )


@router.post("/settings/support")
async def create_support_ticket(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    form = await request.form()
    subject = (form.get("subject") or "").strip()
    message = (form.get("message") or "").strip()
    category = form.get("category")
    if not subject or not message:
        raise HTTPException(status_code=400, detail="Заполните тему и сообщение")
    await SupportService(session).create_ticket(
        user_id=user.id,
        subject=subject,
        message=message,
        category=category,
    )
    await UserActivityService(session).log_activity(
        user.id, "support_ticket_created",
        details={"subject": subject},
        ip_address=request.client.host if request.client else None,
    )
    return RedirectResponse(url="/web/settings/support?created=1", status_code=303)
