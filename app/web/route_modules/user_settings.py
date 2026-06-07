# ruff: noqa: E501, F841
"""version: 1.0.0
description: User settings web routes with tabs.
"""

import logging
from datetime import datetime
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MarketplaceAccount, User
from app.models.enums import Marketplace, NotificationType
from app.services.api_key_validation_service import ApiKeyValidationService
from app.services.company_lookup_service import (
    INN_ERROR_MESSAGE,
    LOOKUP_UNAVAILABLE_MESSAGE,
    CompanyLookupError,
    CompanyLookupService,
    CompanyProfileDTO,
    normalize_inn,
)
from app.services.notification_settings_service import (
    TYPE_DESCRIPTIONS,
    TYPE_LABELS,
    NotificationSettingsService,
)
from app.services.profile_service import ProfileService, ProfileUpdateData, ProfileValidationError
from app.services.subscription_service import SubscriptionService
from app.services.support_service import TICKET_CATEGORIES, TICKET_STATUS_LABELS, SupportService
from app.services.user_activity_service import UserActivityService, action_label
from app.services.user_sync_status_service import SYNC_STATUS_LABELS, UserSyncStatusService
from app.services.web_cabinet_service import WebCabinetService
from app.services.web_password_auth_service import WebPasswordAuthError, WebPasswordAuthService
from app.utils.client_ip import get_client_ip
from app.utils.datetime import format_datetime_for_user
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.rendering import page

logger = logging.getLogger(__name__)
router = APIRouter()


def _dt(dt_value: datetime | None, timezone: str) -> str:
    if dt_value is None:
        return "РЅ/Рґ"
    return format_datetime_for_user(dt_value, timezone, "%d.%m.%Y %H:%M")


def _url_quote(value: str) -> str:
    return quote(value, safe="")


def _settings_tabs(active_tab: str) -> str:
    tabs = [
        ("profile", "РџСЂРѕС„РёР»СЊ", "/web/settings?tab=profile"),
        ("marketplaces", "РњР°СЂРєРµС‚РїР»РµР№СЃС‹", "/web/settings?tab=marketplaces"),
        ("subscription", "РўР°СЂРёС„", "/web/settings?tab=subscription"),
        ("notifications", "РЈРІРµРґРѕРјР»РµРЅРёСЏ", "/web/settings?tab=notifications"),
        ("sync", "РЎРёРЅС…СЂРѕРЅРёР·Р°С†РёСЏ", "/web/settings?tab=sync"),
        ("company", "Р”Р°РЅРЅС‹Рµ РєРѕРјРїР°РЅРёРё", "/web/settings?tab=company"),
        ("security", "Р‘РµР·РѕРїР°СЃРЅРѕСЃС‚СЊ", "/web/settings?tab=security"),
        ("support", "РџРѕРґРґРµСЂР¶РєР°", "/web/settings?tab=support"),
    ]
    links = []
    for code, label, href in tabs:
        cls = ' class="active"' if code == active_tab else ""
        links.append(f'<a{cls} href="{href}">{escape(label)}</a>')
    return f'<nav class="subnav">{"".join(links)}</nav>'


def _subscription_status_russian(status_value: str) -> str:
    mapping = {
        "ACTIVE": "РђРєС‚РёРІРµРЅ",
        "EXPIRED": "РСЃС‚С‘Рє",
        "CANCELLED": "РћС‚РјРµРЅС‘РЅ",
        "TRIAL": "РџСЂРѕР±РЅС‹Р№",
        "PENDING": "РћР¶РёРґР°РµС‚ РѕРїР»Р°С‚С‹",
        "FREE": "Р‘РµСЃРїР»Р°С‚РЅС‹Р№ С‚Р°СЂРёС„",
        "REPLACED": "Р—Р°РјРµРЅС‘РЅ",
    }
    return mapping.get(status_value.upper(), status_value)


def _profile_tab(user: User, subscription_data: object | None = None) -> str:
    first_name = getattr(user, "first_name", None)
    last_name = getattr(user, "last_name", None)
    username = getattr(user, "username", None)
    timezone = getattr(user, "timezone", "Europe/Moscow")
    display_name = first_name or last_name or username or str(user.telegram_id)

    if subscription_data is not None:
        tier = getattr(subscription_data, "tier", None)
        tier_name = getattr(tier, "name", "Free") if tier else "Free"
        active_sub = getattr(subscription_data, "active_subscription", None)
        from app.services.web_cabinet_service import subscription_status
        raw_status = subscription_status(active_sub)
        status_label = _subscription_status_russian(raw_status)
        expires_at = getattr(active_sub, "expires_at", None) if active_sub else None
        expires_label = (
            format_datetime_for_user(expires_at, timezone, "%d.%m.%Y")
            if expires_at
            else "Р±РµСЃСЃСЂРѕС‡РЅРѕ"
        )
        used_accounts = getattr(subscription_data, "used_accounts", 0)
        max_accounts = getattr(tier, "max_marketplace_accounts", 1) if tier else 1
        used_orders = getattr(subscription_data, "used_orders_month", 0)
        max_orders = getattr(tier, "max_orders_per_month", None) if tier else None
        max_orders_label = str(max_orders) if max_orders else "Р±РµР· РѕРіСЂР°РЅРёС‡РµРЅРёР№"
        used_products = getattr(subscription_data, "used_products", 0)
        max_products = getattr(tier, "max_products", None) if tier else None
        max_products_label = str(max_products) if max_products else "Р±РµР· РѕРіСЂР°РЅРёС‡РµРЅРёР№"
        tariff_block = f"""
            <span>РўР°СЂРёС„</span><strong>{escape(tier_name)}</strong>
            <span>РЎС‚Р°С‚СѓСЃ</span><strong>{escape(status_label)}</strong>
            <span>Р”РµР№СЃС‚РІСѓРµС‚ РґРѕ</span><strong>{escape(expires_label)}</strong>
            <span>РљР°Р±РёРЅРµС‚С‹</span><strong>{used_accounts} / {max_accounts}</strong>
            <span>Р—Р°РєР°Р·С‹ Р·Р° РјРµСЃСЏС†</span><strong>{used_orders} / {max_orders_label}</strong>
            <span>SKU</span><strong>{used_products} / {max_products_label}</strong>
            <span>РЈРІРµРґРѕРјР»РµРЅРёСЏ</span><strong>{"РІРєР»СЋС‡РµРЅС‹" if getattr(user, "notifications_enabled", True) else "РІС‹РєР»СЋС‡РµРЅС‹"}</strong>
        """
    else:
        tariff_block = f"""
            <span>РўР°СЂРёС„</span><strong>РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РіСЂСѓР·РёС‚СЊ РґР°РЅРЅС‹Рµ С‚Р°СЂРёС„Р°</strong>
            <span>РЈРІРµРґРѕРјР»РµРЅРёСЏ</span><strong>{"РІРєР»СЋС‡РµРЅС‹" if getattr(user, "notifications_enabled", True) else "РІС‹РєР»СЋС‡РµРЅС‹"}</strong>
        """

    return f"""
      {_settings_tabs("profile")}
      <section class="detail-grid">
        <section class="band">
          <h2>Р”Р°РЅРЅС‹Рµ РїСЂРѕС„РёР»СЏ</h2>
          <form method="post" action="/web/settings/profile">
            <div class="kv" style="margin-bottom:14px">
              <span>Telegram ID</span><strong>{user.telegram_id}</strong>
              <span>Username</span><strong>{escape("@" + username if username else "РЅ/Рґ")}</strong>
              <span>Р”Р°С‚Р° СЂРµРіРёСЃС‚СЂР°С†РёРё</span><strong>{_dt(getattr(user, "created_at", None), timezone)}</strong>
              <span>РџРѕСЃР»РµРґРЅСЏСЏ Р°РєС‚РёРІРЅРѕСЃС‚СЊ</span><strong>{_dt(getattr(user, "last_activity_at", None), timezone)}</strong>
            </div>
            <div class="filters">
              <div>
                <label for="first_name">РРјСЏ</label>
                <input id="first_name" name="first_name" value="{escape(first_name or "")}">
              </div>
              <div>
                <label for="last_name">Р¤Р°РјРёР»РёСЏ</label>
                <input id="last_name" name="last_name" value="{escape(last_name or "")}">
              </div>
              <div>
                <label for="phone">РўРµР»РµС„РѕРЅ</label>
                <input id="phone" name="phone" value="{escape(getattr(user, "phone", None) or "")}" placeholder="+7 900 123-45-67">
              </div>
              <div>
                <label for="email">Email</label>
                <input id="email" name="email" type="email" value="{escape(getattr(user, "email", None) or "")}">
              </div>
              <div>
                <label for="company_name">РљРѕРјРїР°РЅРёСЏ</label>
                <input id="company_name" name="company_name" value="{escape(getattr(user, "company_name", None) or "")}">
              </div>
              <div>
                <label for="inn">РРќРќ</label>
                <input id="inn" name="inn" value="{escape(getattr(user, "inn", None) or "")}" placeholder="10 РёР»Рё 12 С†РёС„СЂ">
              </div>
              <div>
                <label for="ogrn">РћР“Р Рќ / РћР“Р РќРРџ</label>
                <input id="ogrn" name="ogrn" value="{escape(getattr(user, "ogrn", None) or "")}" placeholder="13 РёР»Рё 15 С†РёС„СЂ">
              </div>
              <div>
                <label for="timezone">Р§Р°СЃРѕРІРѕР№ РїРѕСЏСЃ</label>
                <input id="timezone" name="timezone" value="{escape(timezone)}">
              </div>
            </div>
            <button class="btn btn-primary" type="submit">РЎРѕС…СЂР°РЅРёС‚СЊ</button>
          </form>
        </section>
        <section class="band">
          <h2>РўРµРєСѓС‰РёР№ С‚Р°СЂРёС„</h2>
          <div class="kv">
            {tariff_block}
          </div>
          <p style="margin-top:14px"><a class="btn btn-primary" href="/web/settings?tab=subscription">РЈРїСЂР°РІР»РµРЅРёРµ С‚Р°СЂРёС„РѕРј</a></p>
          <p><a class="btn" href="/web/settings?tab=notifications">РќР°СЃС‚СЂРѕРёС‚СЊ СѓРІРµРґРѕРјР»РµРЅРёСЏ</a></p>
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
        '<button class="btn btn-danger" type="submit">РћС‡РёСЃС‚РёС‚СЊ РґР°РЅРЅС‹Рµ РєРѕРјРїР°РЅРёРё</button>'
        if profile
        else ""
    )
    refresh_button = (
        """
        <form method="post" action="/web/settings/company/refresh">
          <button class="btn" type="submit">РћР±РЅРѕРІРёС‚СЊ РґР°РЅРЅС‹Рµ</button>
        </form>
        """
        if profile
        else ""
    )
    return f"""
      {_settings_tabs("company")}
      <section class="detail-grid">
        <section class="band">
          <h2>Р”Р°РЅРЅС‹Рµ РєРѕРјРїР°РЅРёРё</h2>
          {status_message}
          <form method="post" action="/web/settings/company/lookup" class="filters">
            <div>
              <label for="company_lookup_inn">РРќРќ</label>
              <input id="company_lookup_inn" name="inn" value="{escape(current_inn)}" placeholder="10 РёР»Рё 12 С†РёС„СЂ">
            </div>
            <button class="btn btn-primary" type="submit">Р—Р°РіСЂСѓР·РёС‚СЊ РґР°РЅРЅС‹Рµ РїРѕ РРќРќ</button>
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
        <h2>РќР°Р№РґРµРЅРЅС‹Рµ РґР°РЅРЅС‹Рµ</h2>
        {warning}
        <div class="kv">{rows}</div>
        <form method="post" action="/web/settings/company/save" style="margin-top:14px">
          <input type="hidden" name="inn" value="{escape(company.inn)}">
          <button class="btn btn-primary" type="submit">РЎРѕС…СЂР°РЅРёС‚СЊ</button>
        </form>
      </section>
    """


def _company_saved_card(profile: object | None) -> str:
    if profile is None:
        return """
        <section class="band">
          <h2>РЎРѕС…СЂР°РЅС‘РЅРЅС‹Рµ РґР°РЅРЅС‹Рµ</h2>
          <div class="empty-state">Р”Р°РЅРЅС‹Рµ РєРѕРјРїР°РЅРёРё РµС‰С‘ РЅРµ СЃРѕС…СЂР°РЅРµРЅС‹.</div>
        </section>
        """
    return f"""
      <section class="band">
        <h2>РЎРѕС…СЂР°РЅС‘РЅРЅС‹Рµ РґР°РЅРЅС‹Рµ</h2>
        <div class="kv">{_company_kv_rows(profile)}</div>
      </section>
    """


def _company_kv_rows(company: object) -> str:
    updated_at = getattr(company, "updated_at", None)
    registration_date = getattr(company, "registration_date", None)
    source = getattr(company, "source", None)
    rows = [
        ("РРќРќ", getattr(company, "inn", None)),
        ("РљРџРџ", getattr(company, "kpp", None)),
        ("РћР“Р Рќ/РћР“Р РќРРџ", getattr(company, "ogrn", None)),
        ("РџРѕР»РЅРѕРµ РЅР°РёРјРµРЅРѕРІР°РЅРёРµ", getattr(company, "name_full", None)),
        ("РљСЂР°С‚РєРѕРµ РЅР°РёРјРµРЅРѕРІР°РЅРёРµ", getattr(company, "name_short", None)),
        ("РўРёРї", getattr(company, "company_type", None)),
        ("РЎС‚Р°С‚СѓСЃ", getattr(company, "status", None)),
        ("Р®СЂРёРґРёС‡РµСЃРєРёР№ Р°РґСЂРµСЃ", getattr(company, "address", None)),
        ("РћРљР’Р­Р”", getattr(company, "okved", None)),
        ("РћРљР’Р­Р” РЅР°Р·РІР°РЅРёРµ", getattr(company, "okved_name", None)),
        ("Р СѓРєРѕРІРѕРґРёС‚РµР»СЊ", getattr(company, "director_name", None)),
        ("Р”Р°С‚Р° СЂРµРіРёСЃС‚СЂР°С†РёРё", _dt(registration_date, "Europe/Moscow") if registration_date else None),
        ("РСЃС‚РѕС‡РЅРёРє РґР°РЅРЅС‹С…", source),
        ("Р”Р°С‚Р° РїРѕСЃР»РµРґРЅРµРіРѕ РѕР±РЅРѕРІР»РµРЅРёСЏ", _dt(updated_at, "Europe/Moscow") if updated_at else None),
    ]
    return "".join(
        f"<span>{escape(label)}</span><strong>{escape(str(value) if value else 'РЅ/Рґ')}</strong>"
        for label, value in rows
    )


def _marketplaces_tab(user: User, accounts: list[MarketplaceAccount], timezone: str) -> str:
    if not accounts:
        rows = '<tr><td colspan="7"><div class="empty-state">РљР°Р±РёРЅРµС‚С‹ РµС‰С‘ РЅРµ РїРѕРґРєР»СЋС‡РµРЅС‹. РџРѕРґРєР»СЋС‡РµРЅРёРµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ С‡РµСЂРµР· Telegram-Р±РѕС‚Р°.</div></td></tr>'
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
                "active": "РђРєС‚РёРІРµРЅ",
                "auth_error": "РћС€РёР±РєР° Р°РІС‚РѕСЂРёР·Р°С†РёРё",
                "insufficient_permissions": "РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ РїСЂР°РІ",
                "expired": "РСЃС‚С‘Рє",
                "unchecked": "РќРµ РїСЂРѕРІРµСЂРµРЅ",
                "pending_check": "РћР¶РёРґР°РµС‚ РїСЂРѕРІРµСЂРєРё",
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
                f'<td><form method="post" action="/web/settings/marketplaces/{acc.id}/verify" style="margin:0">'
                f'<button class="btn" type="submit">Проверить API-ключ</button></form></td>'
                "</tr>"
            )
        rows = "".join(row_parts)

    return f"""
      {_settings_tabs("marketplaces")}
      <section class="band">
        <h2>РџРѕРґРєР»СЋС‡С‘РЅРЅС‹Рµ РєР°Р±РёРЅРµС‚С‹</h2>
        <p class="muted">РџРѕРґРєР»СЋС‡РµРЅРёРµ РЅРѕРІРѕРіРѕ РєР°Р±РёРЅРµС‚Р° РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ С‡РµСЂРµР· Telegram-Р±РѕС‚Р°. API-РєР»СЋС‡Рё С…СЂР°РЅСЏС‚СЃСЏ РІ Р·Р°С€РёС„СЂРѕРІР°РЅРЅРѕРј РІРёРґРµ Рё РЅРµ РѕС‚РѕР±СЂР°Р¶Р°СЋС‚СЃСЏ РїРѕР»РЅРѕСЃС‚СЊСЋ.</p>
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
        <h2>РљР°Рє РїРѕР»СѓС‡РёС‚СЊ API-РєР»СЋС‡</h2>
        <div class="detail-grid">
          <div class="band">
            <h3>Wildberries</h3>
            <ol class="muted">
              <li>Р’РѕР№РґРёС‚Рµ РІ Р»РёС‡РЅС‹Р№ РєР°Р±РёРЅРµС‚ WB: <strong>sellers.wildberries.ru</strong></li>
              <li>РџРµСЂРµР№РґРёС‚Рµ РІ СЂР°Р·РґРµР» В«РќР°СЃС‚СЂРѕР№РєРёВ» в†’ В«Р”РѕСЃС‚СѓРї Рє APIВ»</li>
              <li>РЎРѕР·РґР°Р№С‚Рµ РЅРѕРІС‹Р№ С‚РѕРєРµРЅ СЃ РЅСѓР¶РЅС‹РјРё РїСЂР°РІР°РјРё</li>
              <li>РЎРєРѕРїРёСЂСѓР№С‚Рµ РєР»СЋС‡ Рё РѕС‚РїСЂР°РІСЊС‚Рµ Р±РѕС‚Сѓ</li>
            </ol>
          </div>
          <div class="band">
            <h3>Ozon</h3>
            <ol class="muted">
              <li>Р’РѕР№РґРёС‚Рµ РІ РєР°Р±РёРЅРµС‚ Ozon Seller: <strong>seller.ozon.ru</strong></li>
              <li>РџРµСЂРµР№РґРёС‚Рµ РІ В«РќР°СЃС‚СЂРѕР№РєРёВ» в†’ В«API-РєР»СЋС‡РёВ»</li>
              <li>РЎРѕР·РґР°Р№С‚Рµ РєР»СЋС‡ СЃ РїСЂР°РІР°РјРё РЅР° С‡С‚РµРЅРёРµ</li>
              <li>РЎРєРѕРїРёСЂСѓР№С‚Рµ Client-Id Рё Api-Key, РѕС‚РїСЂР°РІСЊС‚Рµ Р±РѕС‚Сѓ</li>
            </ol>
          </div>
        </div>
      </section>
    """


def _notifications_tab(user: User, type_settings: dict[NotificationType, bool]) -> str:
    checked_global = " checked" if user.notifications_enabled else ""
    rows = "".join(
        "<tr>"
        f'<td><label class="status-chip">'
        f'<input type="checkbox" name="enabled_types" value="{t.value}"'
        f'{" checked" if type_settings.get(t, False) else ""}>'
        f" {escape(TYPE_LABELS[t])}</label></td>"
        f"<td>{escape(TYPE_DESCRIPTIONS.get(t, ''))}</td>"
        "<td>Telegram</td>"
        "</tr>"
        for t in NotificationType
    )
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


def _sync_tab(sync_statuses: list, timezone: str) -> str:
    if not sync_statuses:
        rows = '<tr><td colspan="5"><div class="empty-state">РЎРёРЅС…СЂРѕРЅРёР·Р°С†РёРё РµС‰С‘ РЅРµ Р·Р°РїСѓСЃРєР°Р»РёСЃСЊ.</div></td></tr>'
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
                f"<td>{escape(s.last_error_message or 'вЂ”')}</td>"
                "</tr>"
            )
        rows = "".join(row_parts)

    return f"""
      {_settings_tabs("sync")}
      <section class="band">
        <h2>РЎС‚Р°С‚СѓСЃ СЃРёРЅС…СЂРѕРЅРёР·Р°С†РёР№</h2>
        <p class="muted">Р§Р°СЃС‚РѕС‚Р° СЃРёРЅС…СЂРѕРЅРёР·Р°С†РёРё Р·Р°РІРёСЃРёС‚ РѕС‚ РІР°С€РµРіРѕ С‚Р°СЂРёС„Р°. Р СѓС‡РЅРѕР№ Р·Р°РїСѓСЃРє РґРѕСЃС‚СѓРїРµРЅ С‡РµСЂРµР· Telegram-Р±РѕС‚Р° РёР»Рё СЃС‚СЂР°РЅРёС†Сѓ В«РљР°Р±РёРЅРµС‚С‹ РњРџВ».</p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>РўРёРї РґР°РЅРЅС‹С…</th><th>РЎС‚Р°С‚СѓСЃ</th><th>РџРѕСЃР»РµРґРЅРёР№ Р·Р°РїСѓСЃРє</th><th>РџРѕСЃР»РµРґРЅРёР№ СѓСЃРїРµС…</th><th>РџРѕСЃР»РµРґРЅСЏСЏ РѕС€РёР±РєР°</th></tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
      </section>
    """


def _security_tab(user: User, activity_logs: list, timezone: str) -> str:
    if not activity_logs:
        log_rows = '<tr><td colspan="4"><div class="empty-state">Р”РµР№СЃС‚РІРёР№ РїРѕРєР° РЅРµ Р·Р°С„РёРєСЃРёСЂРѕРІР°РЅРѕ.</div></td></tr>'
    else:
        log_rows = "".join(
            "<tr>"
            f"<td>{_dt(log.created_at, timezone)}</td>"
            f"<td>{escape(action_label(log.action))}</td>"
            f"<td>{escape(log.entity_type or 'вЂ”')}</td>"
            f"<td>{escape(log.ip_address or 'вЂ”')}</td>"
            "</tr>"
            for log in activity_logs[:30]
        )

    password_enabled = bool(getattr(user, "web_password_enabled", False))
    password_status = "РІРєР»СЋС‡С‘РЅ" if password_enabled else "РІС‹РєР»СЋС‡РµРЅ"
    password_updated = _dt(getattr(user, "web_password_updated_at", None), timezone)
    password_login = escape(getattr(user, "web_login", None) or "")
    return f"""
      {_settings_tabs("security")}
      <section class="detail-grid">
        <section class="band">
          <h2>РџРѕСЃР»РµРґРЅРёР№ РІС…РѕРґ</h2>
          <div class="kv">
            <span>Р”Р°С‚Р°</span><strong>{_dt(getattr(user, "last_login_at", None), timezone)}</strong>
            <span>IP-Р°РґСЂРµСЃ</span><strong>{escape(getattr(user, "last_login_ip", None) or "РЅ/Рґ")}</strong>
            <span>User-Agent</span><strong style="word-break:break-all;font-size:12px">{escape((getattr(user, "last_login_user_agent", None) or "РЅ/Рґ")[:120])}</strong>
            <span>Р’С…РѕРґ РїРѕ РїР°СЂРѕР»СЋ</span><strong>{password_status}</strong>
            <span>РџР°СЂРѕР»СЊ РѕР±РЅРѕРІР»С‘РЅ</span><strong>{password_updated}</strong>
          </div>
        </section>
        <section class="band">
          <h2>РђРєС‚РёРІРЅС‹Рµ СЃРµСЃСЃРёРё</h2>
          <p class="muted">Web-СЃРµСЃСЃРёРё СѓРїСЂР°РІР»СЏСЋС‚СЃСЏ С‡РµСЂРµР· cookie. РџСЂРё РІС‹С…РѕРґРµ СЃРµСЃСЃРёСЏ Р°РЅРЅСѓР»РёСЂСѓРµС‚СЃСЏ.</p>
          <p><a class="btn btn-danger" href="/web/logout">Р’С‹Р№С‚Рё РёР· РІСЃРµС… СЃРµСЃСЃРёР№</a></p>
        </section>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Р’С…РѕРґ РїРѕ Р»РѕРіРёРЅСѓ Рё РїР°СЂРѕР»СЋ</h2>
        <p class="muted">Telegram-РІС…РѕРґ РїСЂРѕРґРѕР»Р¶РёС‚ СЂР°Р±РѕС‚Р°С‚СЊ. РџР°СЂРѕР»СЊ С…СЂР°РЅРёС‚СЃСЏ С‚РѕР»СЊРєРѕ РІ РІРёРґРµ hash.</p>
        <form method="post" action="/web/settings/password-login">
          <div class="filters">
            <div>
              <label for="web_login">Р›РѕРіРёРЅ</label>
              <input id="web_login" name="web_login" value="{password_login}" placeholder="seller.login">
            </div>
            <div>
              <label for="web_current_password">РўРµРєСѓС‰РёР№ РїР°СЂРѕР»СЊ</label>
              <input id="web_current_password" name="web_current_password" type="password" autocomplete="current-password" placeholder="РќСѓР¶РµРЅ РїСЂРё СЃРјРµРЅРµ РїР°СЂРѕР»СЏ">
            </div>
            <div>
              <label for="web_password">РќРѕРІС‹Р№ РїР°СЂРѕР»СЊ</label>
              <input id="web_password" name="web_password" type="password" autocomplete="new-password">
            </div>
            <div>
              <label for="web_password_confirm">РџРѕРІС‚РѕСЂРёС‚Рµ РЅРѕРІС‹Р№ РїР°СЂРѕР»СЊ</label>
              <input id="web_password_confirm" name="web_password_confirm" type="password" autocomplete="new-password">
            </div>
            <div>
              <label class="status-chip">
                <input type="checkbox" name="web_password_enabled" {"checked" if password_enabled else ""}>
                Р Р°Р·СЂРµС€РёС‚СЊ РІС…РѕРґ РїРѕ Р»РѕРіРёРЅСѓ Рё РїР°СЂРѕР»СЋ
              </label>
            </div>
          </div>
          <button class="btn btn-primary" type="submit">РЎРѕС…СЂР°РЅРёС‚СЊ</button>
        </form>
        {'<form method="post" action="/web/settings/password-login/disable" style="margin-top:10px"><button class="btn btn-danger" type="submit">РћС‚РєР»СЋС‡РёС‚СЊ РІС…РѕРґ РїРѕ РїР°СЂРѕР»СЋ</button></form>' if password_enabled else ''}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>РСЃС‚РѕСЂРёСЏ РґРµР№СЃС‚РІРёР№</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Р”Р°С‚Р°</th><th>Р”РµР№СЃС‚РІРёРµ</th><th>РћР±СЉРµРєС‚</th><th>IP</th></tr></thead>
            <tbody>{log_rows}</tbody>
          </table>
        </div>
      </section>
    """


def _support_tab(tickets: list, timezone: str) -> str:
    if not tickets:
        ticket_rows = '<tr><td colspan="5"><div class="empty-state">РћР±СЂР°С‰РµРЅРёР№ РІ РїРѕРґРґРµСЂР¶РєСѓ РїРѕРєР° РЅРµС‚.</div></td></tr>'
    else:
        ticket_rows = "".join(
            "<tr>"
            f"<td>{_dt(t.created_at, timezone)}</td>"
            f"<td>{escape(t.subject)}</td>"
            f'<td><span class="badge {"good" if t.status == "closed" else "warn" if t.status == "responded" else "action"}">{TICKET_STATUS_LABELS.get(t.status, t.status)}</span></td>'
            f"<td>{escape(t.category or "вЂ”")}</td>"
            f'<td>{escape((t.admin_response or "вЂ”")[:100])}</td>'
            "</tr>"
            for t in tickets
        )

    category_options = "".join(
        f'<option value="{code}">{escape(label)}</option>' for code, label in TICKET_CATEGORIES
    )

    return f"""
      {_settings_tabs("support")}
      <section class="band">
        <h2>РЎРѕР·РґР°С‚СЊ РѕР±СЂР°С‰РµРЅРёРµ</h2>
        <form method="post" action="/web/settings/support">
          <div class="filters">
            <div>
              <label for="subject">РўРµРјР°</label>
              <input id="subject" name="subject" required placeholder="РљСЂР°С‚РєРѕ РѕРїРёС€РёС‚Рµ РїСЂРѕР±Р»РµРјСѓ">
            </div>
            <div>
              <label for="category">РљР°С‚РµРіРѕСЂРёСЏ</label>
              <select id="category" name="category">{category_options}</select>
            </div>
          </div>
          <div style="margin-top:10px">
            <label for="message">РЎРѕРѕР±С‰РµРЅРёРµ</label>
            <textarea id="message" name="message" rows="4" required placeholder="РџРѕРґСЂРѕР±РЅРѕ РѕРїРёС€РёС‚Рµ РїСЂРѕР±Р»РµРјСѓ РёР»Рё РІРѕРїСЂРѕСЃ"></textarea>
          </div>
          <button class="btn btn-primary" type="submit" style="margin-top:10px">РћС‚РїСЂР°РІРёС‚СЊ</button>
        </form>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>РњРѕРё РѕР±СЂР°С‰РµРЅРёСЏ</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Р”Р°С‚Р°</th><th>РўРµРјР°</th><th>РЎС‚Р°С‚СѓСЃ</th><th>РљР°С‚РµРіРѕСЂРёСЏ</th><th>РћС‚РІРµС‚</th></tr></thead>
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
    display_name = user.first_name or user.username or str(user.telegram_id)
    if active_tab == "marketplaces":
        stmt = select(MarketplaceAccount).where(
            MarketplaceAccount.user_id == user.id,
            MarketplaceAccount.is_active.is_(True),
        )
        result = await session.execute(stmt)
        accounts = list(result.scalars().all())
        return page(
            "РќР°СЃС‚СЂРѕР№РєРё вЂ” РњР°СЂРєРµС‚РїР»РµР№СЃС‹",
            display_name,
            _marketplaces_tab(user, accounts, user.timezone),
            active_path=active_path,
        )
    if active_tab == "subscription":
        data = await WebCabinetService(session).subscription_page(user.id, user.timezone)
        tiers = await SubscriptionService(session).get_all_tiers()
        from app.web.views import _subscription_content

        content = _settings_tabs("subscription") + _subscription_content(data, tiers, user.timezone)
        return page("РќР°СЃС‚СЂРѕР№РєРё вЂ” РўР°СЂРёС„", display_name, content, active_path=active_path)
    if active_tab == "notifications":
        type_settings = await NotificationSettingsService(session).get_user_settings(user.id)
        return page(
            "Настройки — Уведомления",
            display_name,
            _notifications_tab(user, type_settings),
            active_path=active_path,
        )
    if active_tab == "sync":
        statuses = await UserSyncStatusService(session).get_statuses(user.id)
        return page(
            "РќР°СЃС‚СЂРѕР№РєРё вЂ” РЎРёРЅС…СЂРѕРЅРёР·Р°С†РёСЏ",
            display_name,
            _sync_tab(statuses, user.timezone),
            active_path=active_path,
        )
    if active_tab == "company":
        profile = await CompanyLookupService(session).get_user_company_profile(user.id)
        return page(
            "РќР°СЃС‚СЂРѕР№РєРё вЂ” Р”Р°РЅРЅС‹Рµ РєРѕРјРїР°РЅРёРё",
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
            "РќР°СЃС‚СЂРѕР№РєРё вЂ” Р‘РµР·РѕРїР°СЃРЅРѕСЃС‚СЊ",
            display_name,
            _security_tab(user, logs, user.timezone),
            active_path=active_path,
        )
    if active_tab == "support":
        tickets = await SupportService(session).get_user_tickets(user.id)
        return page(
            "РќР°СЃС‚СЂРѕР№РєРё вЂ” РџРѕРґРґРµСЂР¶РєР°",
            display_name,
            _support_tab(tickets, user.timezone),
            active_path=active_path,
        )

    subscription_data = await WebCabinetService(session).subscription_page(user.id, user.timezone)
    return page(
        "РќР°СЃС‚СЂРѕР№РєРё вЂ” РџСЂРѕС„РёР»СЊ",
        display_name,
        _profile_tab(user, subscription_data),
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
            try:
                enabled_types.append(NotificationType(raw))
            except ValueError:
                logger.warning("Unknown notification_type skipped: %s", raw)
        await NotificationSettingsService(session).update_user_settings(
            user.id, enabled_types=enabled_types
        )
        await session.commit()
        await UserActivityService(session).log_activity(
            user.id, "notification_settings_update",
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
        "РќР°СЃС‚СЂРѕР№РєРё вЂ” Р”Р°РЅРЅС‹Рµ РєРѕРјРїР°РЅРёРё",
        user.first_name or user.username or str(user.telegram_id),
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
            "РќР°СЃС‚СЂРѕР№РєРё вЂ” Р”Р°РЅРЅС‹Рµ РєРѕРјРїР°РЅРёРё",
            user.first_name or user.username or str(user.telegram_id),
            content,
            active_path="/web/settings?tab=company",
        )
    content = _company_tab(
        user,
        profile,
        preview=result.company,
        message="Р”Р°РЅРЅС‹Рµ РЅР°Р№РґРµРЅС‹. РџСЂРѕРІРµСЂСЊС‚Рµ РёС… Рё РЅР°Р¶РјРёС‚Рµ В«РЎРѕС…СЂР°РЅРёС‚СЊВ».",
        warning=result.warning,
    )
    return page(
        "РќР°СЃС‚СЂРѕР№РєРё вЂ” Р”Р°РЅРЅС‹Рµ РєРѕРјРїР°РЅРёРё",
        user.first_name or user.username or str(user.telegram_id),
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
        "/web/settings?tab=company&saved=Р”Р°РЅРЅС‹Рµ РєРѕРјРїР°РЅРёРё СЃРѕС…СЂР°РЅРµРЅС‹",
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
            f"/web/settings?tab=company&error={_url_quote('РЎРЅР°С‡Р°Р»Р° СѓРєР°Р¶РёС‚Рµ РРќРќ')}",
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
        "/web/settings?tab=company&saved=Р”Р°РЅРЅС‹Рµ РєРѕРјРїР°РЅРёРё РѕР±РЅРѕРІР»РµРЅС‹",
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
            f"/web/settings?tab=company&error={_url_quote('РќРµ СѓРґР°Р»РѕСЃСЊ РѕС‡РёСЃС‚РёС‚СЊ РґР°РЅРЅС‹Рµ РєРѕРјРїР°РЅРёРё')}",
            status_code=303,
        )
    return RedirectResponse(
        "/web/settings?tab=company&saved=Р”Р°РЅРЅС‹Рµ РєРѕРјРїР°РЅРёРё РѕС‡РёС‰РµРЅС‹",
        status_code=303,
    )


@router.get("/settings/security", response_class=HTMLResponse)
async def settings_security_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    logs = await UserActivityService(session).get_recent_activity(user.id)
    return page(
        "РќР°СЃС‚СЂРѕР№РєРё вЂ” Р‘РµР·РѕРїР°СЃРЅРѕСЃС‚СЊ",
        user.first_name or user.username or str(user.telegram_id),
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
        "РќР°СЃС‚СЂРѕР№РєРё вЂ” РџРѕРґРґРµСЂР¶РєР°",
        user.first_name or user.username or str(user.telegram_id),
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
    subject = (form.get("subject") or "").strip()
    message = (form.get("message") or "").strip()
    category = form.get("category")
    if not subject or not message:
        raise HTTPException(status_code=400, detail="Р—Р°РїРѕР»РЅРёС‚Рµ С‚РµРјСѓ Рё СЃРѕРѕР±С‰РµРЅРёРµ")
    await SupportService(session).create_ticket(
        user_id=user.id,
        subject=subject,
        message=message,
        category=category,
    )
    await UserActivityService(session).log_activity(
        user.id, "support_ticket_created",
        details={"subject": subject},
        ip_address=get_client_ip(request),
    )
    return RedirectResponse(url="/web/settings?tab=support&created=1", status_code=303)
