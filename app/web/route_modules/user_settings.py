# ruff: noqa: E501, F841
"""version: 1.0.0
description: User settings web routes with tabs.
"""

import logging
from datetime import datetime, time as datetime_time
from html import escape
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, User
from app.models.enums import Marketplace, NotificationType
from app.services.account.api_key_validation_service import ApiKeyValidationService
from app.services.account.company_lookup_service import (
    INN_ERROR_MESSAGE,
    LOOKUP_UNAVAILABLE_MESSAGE,
    CompanyLookupError,
    CompanyLookupService,
    CompanyProfileDTO,
    normalize_inn,
)
from app.services.alerts.notification_settings_service import (
    TYPE_DESCRIPTIONS,
    TYPE_LABELS,
    NotificationSettingsService,
)
from app.services.account.profile_service import ProfileService, ProfileUpdateData, ProfileValidationError
from app.services.subscriptions.subscription_service import SubscriptionService
from app.services.admin.support_service import TICKET_CATEGORIES, TICKET_STATUS_LABELS, SupportService
from app.services.admin.user_activity_service import UserActivityService, action_label
from app.services.common.user_sync_status_service import SYNC_STATUS_LABELS, UserSyncStatusService
from app.services.account.web_cabinet_service import WebCabinetService
from app.services.account.web_password_auth_service import WebPasswordAuthError, WebPasswordAuthService
from app.utils.client_ip import get_client_ip
from app.utils.datetime import format_datetime_for_user
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.rendering import page
from app.web.view_modules.formatting import _get_user_display_name, _get_telegram_username

logger = logging.getLogger(__name__)
router = APIRouter()


def _form_str(form: Any, key: str) -> str | None:
    value = form.get(key)
    return value if isinstance(value, str) else None


def _dt(dt_value: datetime | None, timezone: str) -> str:
    if dt_value is None:
        return "н/д"
    return format_datetime_for_user(dt_value, timezone, "%d.%m.%Y %H:%M")


def _url_quote(value: str) -> str:
    return quote(value, safe="")


def _settings_tabs(active_tab: str) -> str:
    tabs = [
        ("profile", "Профиль", "/web/settings?tab=profile"),
        ("marketplaces", "Маркетплейсы", "/web/settings?tab=marketplaces"),
        ("subscription", "Тариф", "/web/settings?tab=subscription"),
        ("notifications", "Уведомления", "/web/settings?tab=notifications"),
        ("sync", "Синхронизация", "/web/settings?tab=sync"),
        ("company", "Данные компании", "/web/settings?tab=company"),
        ("security", "Безопасность", "/web/settings?tab=security"),
        ("support", "Поддержка", "/web/settings?tab=support"),
    ]
    links = []
    for code, label, href in tabs:
        cls = ' class="active"' if code == active_tab else ""
        links.append(f'<a{cls} href="{href}">{escape(label)}</a>')
    return f'<nav class="subnav">{"".join(links)}</nav>'


def _subscription_status_russian(status_value: str) -> str:
    mapping = {
        "ACTIVE": "Активен",
        "EXPIRED": "Истёк",
        "CANCELLED": "Отменён",
        "TRIAL": "Пробный",
        "PENDING": "Ожидает оплаты",
        "FREE": "Бесплатный тариф",
        "REPLACED": "Заменён",
    }
    return mapping.get(status_value.upper(), status_value)


def _profile_tab(
    user: User,
    subscription_data: object | None = None,
    *,
    saved_message: str | None = None,
    error_message: str | None = None,
) -> str:
    # ── User display helpers (use getattr for test compatibility) ──
    tz = getattr(user, "timezone", "Europe/Moscow")
    display_name = _get_user_display_name(user)
    tg_username = _get_telegram_username(user)
    user_id = getattr(user, "telegram_id", "?")
    uname = getattr(user, "username", None)
    tg_uname = getattr(user, "telegram_username", None)
    first_name = getattr(user, "first_name", None) or ''
    last_name = getattr(user, "last_name", None) or ''
    phone = getattr(user, "phone", None) or ''
    email = getattr(user, "email", None) or ''
    company_name = getattr(user, "company_name", None) or ''
    user_inn = getattr(user, "inn", None) or ''
    user_ogrn = getattr(user, "ogrn", None) or ''
    user_timezone = getattr(user, "timezone", "Europe/Moscow") or "Europe/Moscow"
    notifications_enabled = getattr(user, "notifications_enabled", True)
    status_attr = getattr(user, "status", None)
    status_raw = status_attr.value if hasattr(status_attr, "value") else (status_attr or "ACTIVE")
    created_at = getattr(user, "created_at", None)
    last_activity_at = getattr(user, "last_activity_at", None)
    last_login_at = getattr(user, "last_login_at", None)
    last_login_ip = getattr(user, "last_login_ip", None)

    # ── Username display ──
    if uname:
        username_display = f"@{escape(uname)}"
    elif tg_uname:
        username_display = f"@{escape(tg_uname)}"
    else:
        username_display = "Username не указан"

    # ── Avatar initials ──
    avatar_letter = (display_name[0] if display_name else "?").upper()

    # ── Status ──
    account_status_label = "Активен" if status_raw == "ACTIVE" else str(status_raw)
    account_status_cls = "good" if status_raw == "ACTIVE" else "warn"

    # ── Registration & activity ──
    reg_date = _dt(created_at, tz)
    last_activity = _dt(last_activity_at, tz)

    # ── Subscription / Tariff ──
    if subscription_data is not None:
        tier = getattr(subscription_data, "tier", None)
        tier_name = getattr(tier, "name", "Free") if tier else "Free"
        tier_code = getattr(tier, "code", "free") if tier else "free"
        active_sub = getattr(subscription_data, "active_subscription", None)
        from app.services.account.web_cabinet_service import subscription_status
        raw_sub_status = subscription_status(active_sub)
        sub_status_label = _subscription_status_russian(raw_sub_status)
        sub_status_cls = "good" if raw_sub_status == "ACTIVE" else "warn" if raw_sub_status in ("TRIAL", "PENDING") else "bad"
        expires_at = getattr(active_sub, "expires_at", None) if active_sub else None
        expires_label = (
            format_datetime_for_user(expires_at, tz, "%d.%m.%Y")
            if expires_at else "бессрочно"
        )
        used_accounts = getattr(subscription_data, "used_accounts", 0)
        max_accounts = getattr(tier, "max_marketplace_accounts", 1) if tier else 1
        used_orders = getattr(subscription_data, "used_orders_month", 0)
        max_orders = getattr(tier, "max_orders_per_month", None) if tier else None
        max_orders_label = "без ограничений" if max_orders is None else str(max_orders)
        used_products = getattr(subscription_data, "used_products", 0)
        max_products = getattr(tier, "max_products", None) if tier else None
        max_products_label = "без ограничений" if max_products is None else str(max_products)
        notif_label = "включены" if notifications_enabled else "выключены"
    else:
        tier_name = "Free"
        tier_code = "free"
        sub_status_label = "Активен"
        sub_status_cls = "good"
        expires_label = "бессрочно"
        used_accounts = max_accounts = 0
        used_orders = 0
        max_orders_label = "без ограничений"
        used_products = 0
        max_products_label = "без ограничений"
        notif_label = "включены"

    # ── Limit progress helpers ──
    def _limit_progress(current: int, maximum: int | None) -> str:
        if maximum is None or maximum <= 0:
            return '<span class="profile-unlimited-badge">Без ограничений</span>'
        pct = min(current / maximum * 100, 100)
        cls = "bad" if pct >= 90 else "warn" if pct >= 70 else ""
        return f'<div class="profile-progress"><div class="profile-progress-fill {cls}" style="width:{pct:.0f}%"></div></div>'

    def _limit_row(label: str, current: int, maximum: int | None) -> str:
        max_str = "∞" if maximum is None else str(maximum)
        return f"""
        <div class="profile-limit-item">
          <div class="profile-limit-header">
            <span class="limit-label">{escape(label)}</span>
            <span class="limit-value">{current} / {max_str}</span>
          </div>
          {_limit_progress(current, maximum)}
        </div>"""

    def _unlimited_badge() -> str:
        return '<span class="profile-unlimited-badge">Без ограничений</span>'

    # ── Last Login IP ──
    last_ip = getattr(user, "last_login_ip", None)
    if last_ip and last_ip.startswith(("172.", "10.", "192.168.", "127.")):
        last_ip = "IP скрыт (внутренняя сеть)"
    elif last_ip:
        last_ip = escape(last_ip)
    else:
        last_ip = "н/д"

    last_login = _dt(getattr(user, "last_login_at", None), tz)

    # ── Notification status ──
    saved_html = ""
    if saved_message:
        saved_html = f'<div class="notice success">{escape(saved_message)}</div>'
    if error_message:
        saved_html += f'<div class="notice danger">{escape(error_message)}</div>'

    return f"""
      {_settings_tabs("profile")}
      {saved_html}
      <div class="profile-grid">
        <!-- ── Block 1: Profile header ── -->
        <div class="profile-card" style="grid-column:1/-1">
          <div class="profile-card-header">
            <div class="profile-avatar profile-avatar-lg">{avatar_letter}</div>
            <div class="profile-user-info">
              <h2>{escape(display_name)}</h2>
              <div class="profile-user-meta">
                <span class="profile-meta-item">Telegram ID: <strong>{user_id}</strong></span>
                <span class="profile-meta-item">Username: <strong><span style="color:var(--text-muted);font-weight:400">{username_display}</span></strong></span>
                <span class="profile-meta-item">Статус: <span class="profile-badge {account_status_cls}">{account_status_label}</span></span>
                <span class="profile-meta-item">Тариф: <span class="profile-badge tier-{escape(tier_code)}">{escape(tier_name)}</span></span>
                <span class="profile-meta-item">Регистрация: <strong>{reg_date}</strong></span>
                <span class="profile-meta-item">Последняя активность: <strong>{last_activity}</strong></span>
              </div>
            </div>
          </div>
          <div class="profile-actions">
            <button class="button primary" onclick="saveProfile()">💾 Сохранить профиль</button>
            <button class="button" onclick="navigateTo('/web/settings?tab=notifications')">🔔 Уведомления</button>
            <button class="button" onclick="navigateTo('/web/settings?tab=security')">🔒 Безопасность</button>
          </div>
        </div>

        <!-- ── Block 2: Personal data ── -->
        <div class="profile-card">
          <h2>👤 Личные данные</h2>
          <div class="profile-form-grid">
            <div class="profile-form-group">
              <label for="pf_first_name">Имя</label>
              <input id="pf_first_name" name="first_name" type="text" value="{escape(first_name)}" placeholder="Введите ваше имя">
              <span class="field-hint">Как к вам обращаться</span>
            </div>
            <div class="profile-form-group">
              <label for="pf_last_name">Фамилия</label>
              <input id="pf_last_name" name="last_name" type="text" value="{escape(last_name)}" placeholder="Введите фамилию">
            </div>
            <div class="profile-form-group">
              <label for="pf_phone">Телефон</label>
              <input id="pf_phone" name="phone" type="tel" value="{escape(phone)}" placeholder="+7 900 123-45-67">
              <span class="field-hint">Для уведомлений и восстановления доступа</span>
            </div>
            <div class="profile-form-group">
              <label for="pf_email">Email</label>
              <input id="pf_email" name="email" type="email" value="{escape(email)}" placeholder="seller@example.com">
              <span class="field-hint">Для отправки отчётов</span>
            </div>
            <div class="profile-form-group">
              <label for="pf_timezone">Часовой пояс</label>
              <select id="pf_timezone" name="timezone">
                <option value="Europe/Kaliningrad" {"selected" if user_timezone == "Europe/Kaliningrad" else ""}>Калининград (UTC+2)</option>
                <option value="Europe/Moscow" {"selected" if user_timezone in ("Europe/Moscow", "") or not user_timezone else ""}>Москва (UTC+3)</option>
                <option value="Europe/Samara" {"selected" if user_timezone == "Europe/Samara" else ""}>Самара (UTC+4)</option>
                <option value="Asia/Yekaterinburg" {"selected" if user_timezone == "Asia/Yekaterinburg" else ""}>Екатеринбург (UTC+5)</option>
                <option value="Asia/Omsk" {"selected" if user_timezone == "Asia/Omsk" else ""}>Омск (UTC+6)</option>
                <option value="Asia/Krasnoyarsk" {"selected" if user_timezone == "Asia/Krasnoyarsk" else ""}>Красноярск (UTC+7)</option>
                <option value="Asia/Irkutsk" {"selected" if user_timezone == "Asia/Irkutsk" else ""}>Иркутск (UTC+8)</option>
                <option value="Asia/Yakutsk" {"selected" if user_timezone == "Asia/Yakutsk" else ""}>Якутск (UTC+9)</option>
                <option value="Asia/Vladivostok" {"selected" if user_timezone == "Asia/Vladivostok" else ""}>Владивосток (UTC+10)</option>
                <option value="Asia/Magadan" {"selected" if user_timezone == "Asia/Magadan" else ""}>Магадан (UTC+11)</option>
                <option value="Asia/Kamchatka" {"selected" if user_timezone == "Asia/Kamchatka" else ""}>Камчатка (UTC+12)</option>
              </select>
              <span class="field-hint">Даты и время будут отображаться в этом часовом поясе</span>
            </div>
          </div>
          <div class="profile-actions">
            <button class="button primary" onclick="saveProfile()">💾 Сохранить</button>
          </div>
        </div>

        <!-- ── Block 3: Tariff & Limits ── -->
        <div class="profile-card">
          <h2>📊 Тариф и лимиты</h2>
          <div class="profile-tariff-header">
            <h3>{escape(tier_name)}</h3>
            <span class="profile-badge {sub_status_cls}">{escape(sub_status_label)}</span>
            <span class="profile-meta-item" style="font-size:12px">Действует до: <strong>{escape(expires_label)}</strong></span>
          </div>
          <div class="profile-limit-list">
            {_limit_row("Кабинеты", used_accounts, max_accounts)}
            {_limit_row("Заказы за месяц", used_orders, max_orders if max_orders else None)}
            {_limit_row("SKU", used_products, max_products if max_products else None)}
            <div class="profile-limit-item">
              <div class="profile-limit-header">
                <span class="limit-label">Уведомления</span>
                <span class="limit-value">{notif_label}</span>
              </div>
            </div>
          </div>
          <div class="profile-actions">
            <a class="button primary" href="/web/settings?tab=subscription">⚙️ Управление тарифом</a>
          </div>
        </div>

        <!-- ── Block 4: Company data ── -->
        <div class="profile-card">
          <h2>🏢 Данные компании</h2>
          <div class="profile-company-detail">
            <div class="cd-item"><div class="cd-label">Компания / ИП</div><div class="cd-value">{escape(company_name or "Не указано")}</div></div>
            <div class="cd-item"><div class="cd-label">ИНН</div><div class="cd-value">{escape(user_inn or "Не указан")}</div></div>
            <div class="cd-item"><div class="cd-label">ОГРН / ОГРНИП</div><div class="cd-value">{escape(user_ogrn or "Не указан")}</div></div>
            <div class="cd-item"><div class="cd-label">Юридический статус</div><div class="cd-value">ИП / ООО</div></div>
          </div>
          <div class="profile-actions">
            <a class="button" href="/web/settings?tab=company">✏️ Редактировать данные компании</a>
          </div>
        </div>

        <!-- ── Block 5: Security ── -->
        <div class="profile-card">
          <h2>🔒 Безопасность аккаунта</h2>
          <div class="profile-security-grid">
            <div class="profile-security-item"><span class="sec-label">Telegram ID</span><span class="sec-value">{user_id}</span></div>
            <div class="profile-security-item"><span class="sec-label">Последний IP</span><span class="sec-value">{last_ip}</span></div>
            <div class="profile-security-item"><span class="sec-label">Последняя активность</span><span class="sec-value">{last_activity}</span></div>
            <div class="profile-security-item"><span class="sec-label">Дата регистрации</span><span class="sec-value">{reg_date}</span></div>
            <div class="profile-security-item" style="grid-column:1/-1"><span class="sec-label">Статус аккаунта</span><span class="sec-value"><span class="profile-badge {account_status_cls}">{account_status_label}</span></span></div>
          </div>
          <div class="profile-actions">
            <a class="button" href="/web/settings?tab=security">🔐 Открыть безопасность</a>
          </div>
        </div>

        <!-- ── Block 6: Quick actions ── -->
        <div class="profile-card" style="grid-column:1/-1">
          <h2>⚡ Быстрые действия</h2>
          <div class="profile-quick-actions">
            <a class="profile-quick-action" href="/web/settings?tab=marketplaces"><span class="qa-icon">🛒</span> Маркетплейсы</a>
            <a class="profile-quick-action" href="/web/settings?tab=subscription"><span class="qa-icon">📊</span> Тариф</a>
            <a class="profile-quick-action" href="/web/settings?tab=notifications"><span class="qa-icon">🔔</span> Уведомления</a>
            <a class="profile-quick-action" href="/web/settings?tab=sync"><span class="qa-icon">🔄</span> Синхронизация</a>
            <a class="profile-quick-action" href="/web/settings?tab=company"><span class="qa-icon">🏢</span> Данные компании</a>
            <a class="profile-quick-action" href="/web/settings?tab=security"><span class="qa-icon">🔒</span> Безопасность</a>
            <a class="profile-quick-action" href="/web/settings?tab=support"><span class="qa-icon">💬</span> Поддержка</a>
          </div>
        </div>
      </div>
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
        (
            "Дата регистрации",
            _dt(registration_date, "Europe/Moscow") if registration_date else None,
        ),
        ("Источник данных", source),
        ("Дата последнего обновления", _dt(updated_at, "Europe/Moscow") if updated_at else None),
    ]
    return "".join(
        f"<span>{escape(label)}</span><strong>{escape(str(value) if value else 'н/д')}</strong>"
        for label, value in rows
    )


def _marketplaces_tab(user: User, accounts: list[MarketplaceAccount], timezone: str) -> str:
    if not accounts:
        rows = '<tr><td colspan="7"><div class="empty-state">Кабинеты ещё не подключены. Подключение выполняется через Telegram-бота.</div></td></tr>'
    else:
        row_parts = []
        for acc in accounts:
            mp_label = "Wildberries" if acc.marketplace == Marketplace.WB else "Ozon"
            mp_cls = "wb" if acc.marketplace == Marketplace.WB else "ozon"
            status_label = acc.status.value
            status_cls = (
                "good"
                if acc.status.value == "ACTIVE"
                else "bad" if acc.status.value == "ERROR" else "warn"
            )
            api_status = acc.api_key_status or "unchecked"
            api_cls = (
                "good"
                if api_status == "active"
                else "bad" if api_status in ("auth_error", "expired") else "warn"
            )
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
                f"<td>{_dt(acc.last_success_sync_at, timezone)}</td>"
                f'<td>{_dt(acc.last_error_at, timezone)}<div class="muted">{escape(acc.last_error_message or "")}</div></td>'
                f'<td><form method="post" action="/web/settings/marketplaces/{acc.id}/verify" style="margin:0">'
                f'<button class="btn" type="submit">Проверить API-ключ</button></form></td>'
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
                <th>API-ключ</th><th>Последняя синхронизация</th><th>Последняя ошибка</th><th>Действие</th>
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


def _notifications_tab(
    user: User,
    type_settings: dict[NotificationType, bool],
    quiet_from: datetime_time | None = None,
    quiet_to: datetime_time | None = None,
) -> str:
    checked_global = " checked" if user.notifications_enabled else ""
    rows = "".join(
        "<tr>"
        f'<td><label class="status-chip">'
        f'<input type="checkbox" name="enabled_types" value="{t.value}"'
        f"{' checked' if type_settings.get(t, False) else ''}>"
        f" {escape(TYPE_LABELS[t])}</label></td>"
        f"<td>{escape(TYPE_DESCRIPTIONS.get(t, ''))}</td>"
        "<td>Telegram</td>"
        "</tr>"
        for t in NotificationType
    )
    quiet_from_val = quiet_from.strftime("%H:%M") if quiet_from else ""
    quiet_to_val = quiet_to.strftime("%H:%M") if quiet_to else ""
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
          <h3 style="margin-top:18px">Тихие часы</h3>
          <p class="muted">В указанный период уведомления отправляться не будут.</p>
          <div class="filters">
            <div>
              <label for="quiet_from">Не беспокоить с</label>
              <input id="quiet_from" name="quiet_from" type="time" value="{quiet_from_val}">
            </div>
            <div>
              <label for="quiet_to">до</label>
              <input id="quiet_to" name="quiet_to" type="time" value="{quiet_to_val}">
            </div>
          </div>
          <h3 style="margin-top:18px">Типы событий</h3>
          <p class="muted">Отключите чекбоксы тех событий, уведомления о которых вы не хотите получать. Настройки применяются ко всем вашим кабинетам.</p>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>Событие</th><th>Описание</th><th>Канал</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
          <button class="btn btn-primary" type="submit" style="margin-top:14px">Сохранить</button>
        </form>
      </section>
    """


def _sync_tab(sync_statuses: list[Any], timezone: str) -> str:
    if not sync_statuses:
        rows = '<tr><td colspan="5"><div class="empty-state">Синхронизации ещё не запускались.</div></td></tr>'
    else:
        row_parts = []
        for s in sync_statuses:
            status_label = SYNC_STATUS_LABELS.get(s.status, s.status)
            status_cls = (
                "good" if s.status == "success" else "bad" if s.status == "error" else "warn"
            )
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


def _format_ip(ip: str | None) -> str:
    if not ip:
        return "н/д"
    if ip.startswith(("172.", "10.", "192.168.", "127.", "0.")):
        return "IP скрыт (внутренняя сеть)"
    return escape(ip)


def _security_tab(user: User, activity_logs: list[Any], timezone: str) -> str:
    if not activity_logs:
        log_rows = '<tr><td colspan="4"><div class="empty-state">Действий пока не зафиксировано.</div></td></tr>'
    else:
        log_rows = "".join(
            "<tr>"
            f"<td>{_dt(log.created_at, timezone)}</td>"
            f"<td>{escape(action_label(log.action))}</td>"
            f"<td>{escape(log.entity_type or '—')}</td>"
            f"<td>{_format_ip(log.ip_address)}</td>"
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
            <span>IP-адрес</span><strong>{_format_ip(getattr(user, "last_login_ip", None))}</strong>
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
              <label for="web_current_password">Текущий пароль</label>
              <input id="web_current_password" name="web_current_password" type="password" autocomplete="current-password" placeholder="Нужен при смене пароля">
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
        {'<form method="post" action="/web/settings/password-login/disable" style="margin-top:10px"><button class="btn btn-danger" type="submit">Отключить вход по паролю</button></form>' if password_enabled else ""}
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


def _support_tab(tickets: list[Any], timezone: str) -> str:
    if not tickets:
        ticket_rows = '<tr><td colspan="5"><div class="empty-state">Обращений в поддержку пока нет.</div></td></tr>'
    else:
        ticket_rows = "".join(
            "<tr>"
            f"<td>{_dt(t.created_at, timezone)}</td>"
            f"<td>{escape(t.subject)}</td>"
            f'<td><span class="badge {"good" if t.status == "closed" else "warn" if t.status == "responded" else "action"}">{TICKET_STATUS_LABELS.get(t.status, t.status)}</span></td>'
            f"<td>{escape(t.category or '—')}</td>"
            f"<td>{escape((t.admin_response or '—')[:100])}</td>"
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
    request: Request,
    tab: str = Query("profile"),
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    active_tab = "subscription" if tab == "tariff" else tab
    active_path = f"/web/settings?tab={active_tab}"
    display_name = _get_user_display_name(user)
    if active_tab == "marketplaces":
        stmt = select(MarketplaceAccount).where(
            MarketplaceAccount.user_id == user.id,
            MarketplaceAccount.is_active.is_(True),
        )
        result = await session.execute(stmt)
        accounts = list(result.scalars().all())
        return page(
            "Настройки — Маркетплейсы",
            display_name,
            _marketplaces_tab(user, accounts, user.timezone),
            active_path=active_path,
        )
    if active_tab == "subscription":
        data = await WebCabinetService(session).subscription_page(user.id, user.timezone)
        tiers = await SubscriptionService(session).get_all_tiers()
        from app.web.views import _subscription_content

        content = _settings_tabs("subscription") + _subscription_content(data, tiers, user.timezone)
        return page("Настройки — Тариф", display_name, content, active_path=active_path)
    if active_tab == "notifications":
        nss = NotificationSettingsService(session)
        type_settings = await nss.get_user_settings(user.id)
        quiet_from, quiet_to = await nss.get_quiet_hours(user.id)
        return page(
            "Настройки — Уведомления",
            display_name,
            _notifications_tab(user, type_settings, quiet_from, quiet_to),
            active_path=active_path,
        )
    if active_tab == "sync":
        statuses = await UserSyncStatusService(session).get_statuses(user.id)
        return page(
            "Настройки — Синхронизация",
            display_name,
            _sync_tab(statuses, user.timezone),
            active_path=active_path,
        )
    if active_tab == "company":
        profile = await CompanyLookupService(session).get_user_company_profile(user.id)
        return page(
            "Настройки — Данные компании",
            display_name,
            _company_tab(
                user,
                profile,
                message=request.query_params.get("saved"),
                error=request.query_params.get("error"),
            ),
            active_path=active_path,
        )
    if active_tab == "security":
        logs = await UserActivityService(session).get_recent_activity(user.id)
        return page(
            "Настройки — Безопасность",
            display_name,
            _security_tab(user, logs, user.timezone),
            active_path=active_path,
        )
    if active_tab == "support":
        tickets = await SupportService(session).get_user_tickets(user.id)
        return page(
            "Настройки — Поддержка",
            display_name,
            _support_tab(tickets, user.timezone),
            active_path=active_path,
        )

    subscription_data = await WebCabinetService(session).subscription_page(user.id, user.timezone)
    saved_msg = request.query_params.get("saved")
    err_msg = request.query_params.get("error")
    return page(
        "Настройки — Профиль",
        display_name,
        _profile_tab(user, subscription_data, saved_message=saved_msg, error_message=err_msg),
        active_path="/web/settings?tab=profile",
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
            current_password=str(form.get("web_current_password") or ""),
        )
        await UserActivityService(session).log_activity(
            user.id,
            "web_password_settings_updated",
            ip_address=get_client_ip(request),
        )
        await session.commit()
    except WebPasswordAuthError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/web/settings?tab=security&saved=1", status_code=303)


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
        ip_address=get_client_ip(request),
    )
    await session.commit()
    return RedirectResponse(url="/web/settings?tab=security&saved=1", status_code=303)


@router.post("/settings/profile")
async def save_profile(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> Response:
    # Support both JSON (AJAX) and form-encoded submissions
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        data = ProfileUpdateData(
            first_name=body.get("first_name"),
            last_name=body.get("last_name"),
            phone=body.get("phone"),
            email=body.get("email"),
            company_name=body.get("company_name"),
            inn=body.get("inn"),
            ogrn=body.get("ogrn"),
            timezone=body.get("timezone"),
        )
        try:
            await ProfileService(session).update_profile(user.id, data)
            await UserActivityService(session).log_activity(
                user.id, "profile_update", ip_address=get_client_ip(request)
            )
            await session.commit()
            return Response(status_code=200, content="OK")
        except ProfileValidationError as exc:
            return Response(status_code=400, content=str(exc))
    else:
        form = await request.form()
        try:
            await ProfileService(session).update_profile(
                user.id,
                ProfileUpdateData(
                    first_name=_form_str(form, "first_name"),
                    last_name=_form_str(form, "last_name"),
                    phone=_form_str(form, "phone"),
                    email=_form_str(form, "email"),
                    company_name=_form_str(form, "company_name"),
                    inn=_form_str(form, "inn"),
                    ogrn=_form_str(form, "ogrn"),
                    timezone=_form_str(form, "timezone"),
                ),
            )
            await UserActivityService(session).log_activity(
                user.id, "profile_update", ip_address=get_client_ip(request)
            )
            await session.commit()
        except ProfileValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/web/settings?tab=profile&saved=1", status_code=303)


@router.get("/settings/marketplaces", response_class=HTMLResponse)
async def settings_marketplaces_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> RedirectResponse:
    return RedirectResponse(url="/web/settings?tab=marketplaces", status_code=302)


@router.post("/settings/marketplaces/{account_id}/verify")
async def verify_marketplace_api_key(
    account_id: int,
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    from app.core.security import TokenCipher

    account = await session.get(MarketplaceAccount, account_id)
    if account is None or account.user_id != user.id:
        return RedirectResponse(
            url="/web/settings?tab=marketplaces&error=" + _url_quote("Кабинет не найден"),
            status_code=303,
        )
    cipher = TokenCipher()
    check_result = await ApiKeyValidationService(session, cipher).check_account(account)
    await UserActivityService(session).log_activity(
        user.id,
        "api_key_checked",
        entity_type="marketplace_account",
        entity_id=account.id,
        details={"marketplace": account.marketplace.value, "result": check_result.status},
        ip_address=get_client_ip(request),
    )
    mp_label = "WB" if account.marketplace == Marketplace.WB else "Ozon"
    safe_result = _url_quote(f"{mp_label} #{account.id}: {check_result.message}")
    return RedirectResponse(
        url=f"/web/settings?tab=marketplaces&verify={safe_result}",
        status_code=303,
    )


@router.get("/settings/tariff", response_class=HTMLResponse)
async def settings_tariff_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> RedirectResponse:
    return RedirectResponse(url="/web/settings?tab=subscription", status_code=302)


@router.get("/settings/notifications", response_class=HTMLResponse)
async def settings_notifications_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> RedirectResponse:
    return RedirectResponse(url="/web/settings?tab=notifications", status_code=302)


def _parse_time(value: str | None) -> datetime_time | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parts = value.strip().split(":")
        return datetime_time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None


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
        enabled_values = form.getlist("enabled_types")
        enabled_types: list[NotificationType] = []
        for raw in enabled_values:
            if not isinstance(raw, str):
                continue
            try:
                enabled_types.append(NotificationType(raw))
            except ValueError:
                logger.warning("Unknown notification_type skipped: %s", raw)
        nss = NotificationSettingsService(session)
        await nss.update_user_settings(user.id, enabled_types=enabled_types)
        quiet_from = _parse_time(form.get("quiet_from"))
        quiet_to = _parse_time(form.get("quiet_to"))
        await nss.save_quiet_hours(user.id, quiet_from, quiet_to)
        await session.commit()
        await UserActivityService(session).log_activity(
            user.id,
            "notification_settings_update",
            ip_address=get_client_ip(request),
        )
    return RedirectResponse(url="/web/settings?tab=notifications&saved=1", status_code=303)


@router.get("/settings/sync", response_class=HTMLResponse)
async def settings_sync_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> RedirectResponse:
    return RedirectResponse(url="/web/settings?tab=sync", status_code=302)


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
        _get_user_display_name(user),
        content,
        active_path="/web/settings?tab=company",
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
            _get_user_display_name(user),
            content,
            active_path="/web/settings?tab=company",
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
        _get_user_display_name(user),
        content,
        active_path="/web/settings?tab=company",
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
            ip_address=get_client_ip(request),
        )
        await session.commit()
    except CompanyLookupError as exc:
        await session.rollback()
        logger.warning(
            "company_profile_save_failed",
            extra={"user_id": user.id, "inn": normalize_inn(inn), "error": str(exc)},
        )
        return RedirectResponse(
            f"/web/settings?tab=company&error={_url_quote(str(exc) or INN_ERROR_MESSAGE)}",
            status_code=303,
        )
    return RedirectResponse(
        "/web/settings?tab=company&saved=Данные компании сохранены",
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
            f"/web/settings?tab=company&error={_url_quote('Сначала укажите ИНН')}",
            status_code=303,
        )
    try:
        result = await service.fetch_company_by_inn(inn)
        await service.save_company_profile(user, result.company)
        await UserActivityService(session).log_activity(
            user.id,
            "company_profile_refreshed",
            ip_address=get_client_ip(request),
        )
        await session.commit()
    except CompanyLookupError as exc:
        await session.rollback()
        logger.warning(
            "company_profile_refresh_failed",
            extra={"user_id": user.id, "inn": normalize_inn(inn), "error": str(exc)},
        )
        return RedirectResponse(
            f"/web/settings?tab=company&error={_url_quote(str(exc) or LOOKUP_UNAVAILABLE_MESSAGE)}",
            status_code=303,
        )
    return RedirectResponse(
        "/web/settings?tab=company&saved=Данные компании обновлены",
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
            ip_address=get_client_ip(request),
        )
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("company_profile_clear_failed", extra={"user_id": user.id})
        return RedirectResponse(
            f"/web/settings?tab=company&error={_url_quote('Не удалось очистить данные компании')}",
            status_code=303,
        )
    return RedirectResponse(
        "/web/settings?tab=company&saved=Данные компании очищены",
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
        _get_user_display_name(user),
        _security_tab(user, logs, user.timezone),
        active_path="/web/settings?tab=security",
    )


@router.get("/settings/support", response_class=HTMLResponse)
async def settings_support_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    tickets = await SupportService(session).get_user_tickets(user.id)
    return page(
        "Настройки — Поддержка",
        _get_user_display_name(user),
        _support_tab(tickets, user.timezone),
        active_path="/web/settings?tab=support",
    )


@router.post("/settings/support")
async def create_support_ticket(
    request: Request,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    form = await request.form()
    subject = (_form_str(form, "subject") or "").strip()
    message = (_form_str(form, "message") or "").strip()
    category = _form_str(form, "category")
    if not subject or not message:
        raise HTTPException(status_code=400, detail="Заполните тему и сообщение")
    await SupportService(session).create_ticket(
        user_id=user.id,
        subject=subject,
        message=message,
        category=category,
    )
    await UserActivityService(session).log_activity(
        user.id,
        "support_ticket_created",
        details={"subject": subject},
        ip_address=get_client_ip(request),
    )
    return RedirectResponse(url="/web/settings?tab=support&created=1", status_code=303)
