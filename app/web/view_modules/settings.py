"""version: 1.2.0
description: Settings, account, profile, subscription, and control HTML view helpers.
updated: 2026-06-11
"""

# ruff: noqa: E501, F401, E402, F811, I001

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html import escape
from typing import Any
from urllib.parse import parse_qs

from fastapi import HTTPException, Request

from app.models.domain import AlertEvent, MarketplaceAccount, User
from app.models.enums import Marketplace
from app.models.subscriptions import SubscriptionTier
from app.services.common.data_quality_service import DataQualityReport
from app.services.common.marketplace_presentation import (
    marketplace_css_class,
    marketplace_title,
    order_status_tone,
    sale_model_title,
    source_event_label,
)
from app.services.common.marketplace_presentation import (
    order_status_label as presentation_order_status_label,
)
from app.services.unit_economics.master_product_service import (
    MasterProductAnalyticsRow,
    MasterProductDetail,
    ProductMatchingCandidate,
)
from app.services.unit_economics.plan_fact_service import PlanFactPageData
from app.services.unit_economics.stock_forecast_service import (
    StockForecastRow,
    stock_status_label,
    stock_status_tone,
)
from app.services.unit_economics.unit_economics_service import BreakEvenRow
from app.services.account.web_cabinet_service import (
    AccountsPageData,
    ControlPageData,
    CostsPageData,
    ProductCostDetail,
    ReturnsPageData,
    SalesPageData,
    SubscriptionPageData,
    subscription_status,
)
from app.services.common.web_dashboard_service import (
    DailyPoint,
    DashboardData,
    DashboardEvent,
    DashboardFilters,
    KpiMetric,
)
from app.services.common.web_orders_profit_service import (
    OrderDetail,
    OrderRow,
    OrderWebFilters,
    ProfitPageData,
    localized_order_date,
    order_state_label,
)
from app.utils.datetime import format_datetime_for_user, get_user_timezone, user_day_bounds_utc
from app.web.rendering import page

ZERO = Decimal("0")

SYNC_FRESHNESS_ORDERS_MINUTES = 30
SYNC_FRESHNESS_SALES_MINUTES = 60
SYNC_FRESHNESS_STOCKS_HOURS = 24
SYNC_FRESHNESS_PRODUCTS_HOURS = 48
SYNC_FRESHNESS_PROFILE_HOURS = 48

from app.web.view_modules.common import _page_header, _section_subnav_products, _web_tier_card
from app.web.view_modules.components import _simple_kpi
from app.web.view_modules.formatting import _account_status_badge, _dt, _get_user_display_name, _get_telegram_username, _limit, _marketplace_label, _rub
from app.web.view_modules.reports import _wb_reports_web

__all__ = [
    "_accounts_content",
    "_sync_detail_cell",
    "_sync_actions",
    "_seller_name_hint",
    "_seller_profile_web",
    "_subscription_content",
    "_profile_content",
    "_control_content",
    "_settings_content",
    "_data_quality_content",
]


def _accounts_content(data: AccountsPageData, timezone: str = "Europe/Moscow") -> str:
    rows = "".join(
        "<tr>"
        f'<td>{escape(row.account.name)}<div class="muted">#{row.account.id}'
        f"{_seller_name_hint(row.account)}</div></td>"
        f"<td>{_marketplace_label(row.account.marketplace)}</td>"
        f"<td>{_account_status_badge(row.account.status.value, row.account.is_active)}</td>"
        f"<td>{_seller_profile_web(row.account, row.latest_balance)}</td>"
        f"<td>{_wb_reports_web(row.latest_daily_report, row.latest_weekly_report, row.report_states or [])}</td>"
        f"<td>{_sync_detail_cell(row.account, timezone)}</td>"
        f'<td>{_dt(row.account.last_error_at, timezone)}<div class="muted">{escape(row.account.last_error_message or row.latest_job_error or "")}</div></td>'
        f'<td class="num">{row.products_count}</td>'
        f'<td class="num">{row.orders_30d}</td>'
        f"<td>{escape(row.latest_job_status or 'нет задач')}</td>"
        "</tr>"
        for row in data.rows
    )
    if not rows:
        rows = (
            '<tr><td colspan="10"><div class="empty-state">'
            "Кабинеты ещё не подключены. Подключение нового кабинета выполняется через Telegram-бота."
            "</div></td></tr>"
        )
    return f"""
      {_page_header("Кабинеты маркетплейсов", "Проверяйте подключённые кабинеты, статусы синхронизации и ошибки доступа.", "/web/settings?tab=profile", "Профиль")}
      {_sync_actions()}
      <section class="kpi-grid">
        {_simple_kpi("Подключено кабинетов", f"{data.active_accounts} из {data.tier.max_marketplace_accounts}")}
        {_simple_kpi("Тариф", escape(data.tier.name))}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Wildberries и Ozon</h2>
        <p class="muted">Подключение нового кабинета сейчас выполняется через Telegram-бота: откройте настройки и выберите подключение WB или Ozon.</p>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Кабинет</th><th>МП</th><th>Статус</th><th>Продавец и баланс</th>
          <th>Отчёты WB</th><th>Синхронизации</th>
          <th>Последняя ошибка</th><th class="num">Товаров</th><th class="num">Заказов 30д</th><th>Последняя задача</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
    """

def _sync_detail_cell(account: MarketplaceAccount, timezone: str) -> str:
    items = [
        ("Заказы", account.last_orders_sync_at),
        ("Продажи", account.last_sales_sync_at),
        ("Остатки", account.last_stocks_sync_at),
        ("Товары", account.last_products_sync_at),
        ("Профиль", account.last_profile_sync_at),
    ]
    if account.marketplace.value == "ozon":
        items.append(("Ozon каталог", account.last_ozon_enrichment_sync_at))
    if account.marketplace.value == "wb":
        items.append(("Отчёты WB", account.last_wb_reports_sync_at))
    parts = []
    for label, ts in items:
        if ts is None:
            parts.append(f'<div class="muted">{escape(label)}: ещё не запускалась</div>')
        else:
            parts.append(f"<div>{escape(label)}: {_dt(ts, timezone)}</div>")
    return "".join(parts)

def _sync_actions() -> str:
    actions = [
        ("orders", "Заказы"),
        ("sales", "Продажи"),
        ("stocks", "Остатки"),
        ("products", "Товары"),
        ("wb-reports", "Отчёты WB"),
        ("ozon-enrichment", "Ozon каталог"),
        ("ozon-balance", "Баланс Ozon"),
    ]
    buttons = "".join(
        f'<form method="post" action="/web/sync/{key}">'
        f'<button class="button" type="submit">{label}</button></form>'
        for key, label in actions
    )
    return (
        '<section class="band"><h2>Запустить синхронизацию</h2>'
        f'<div class="page-actions">{buttons}</div></section>'
    )

def _seller_name_hint(account: MarketplaceAccount) -> str:
    if not account.seller_name and not account.seller_external_id:
        return ""
    label = account.seller_name or account.seller_external_id or ""
    return f" · продавец: {escape(label)}"

def _seller_profile_web(account: MarketplaceAccount, balance: object | None) -> str:
    payload = account.seller_info_payload or {}
    parts = [
        escape(account.seller_name or account.seller_legal_name or "н/д"),
        f'<div class="muted">ИНН: {escape(str(payload.get("tin") or "н/д"))}</div>',
    ]
    if balance is None:
        parts.append('<div class="muted">Баланс не загружен</div>')
    elif getattr(balance, "status", "") == "OK":
        currency = getattr(balance, "currency", "RUB")
        current = getattr(balance, "current", None)
        if account.marketplace == Marketplace.WB:
            for_withdraw = getattr(balance, "for_withdraw", None)
            parts.append(f'<div class="muted">Баланс: {_rub(current)} {escape(currency)}</div>')
            parts.append(
                f'<div class="muted">К выводу: {_rub(for_withdraw)} {escape(currency)}</div>'
            )
        else:
            parts.append(
                f'<div class="muted">💰 Баланс Ozon: {_rub(current)} {escape(currency)}</div>'
            )
            period_from = getattr(balance, "period_from", None)
            period_to = getattr(balance, "period_to", None)
            if period_from and period_to:
                parts.append(
                    f'<div class="muted">Период: {escape(str(period_from))} — {escape(str(period_to))}</div>'
                )
            accrued = getattr(balance, "accrued", None)
            if accrued is not None:
                parts.append(
                    f'<div class="muted">Начислено: {_rub(accrued)} {escape(currency)}</div>'
                )
            opening = getattr(balance, "opening_balance", None)
            if opening is not None:
                parts.append(
                    f'<div class="muted">На начало периода: {_rub(opening)} {escape(currency)}</div>'
                )
            payments = getattr(balance, "payments_total", None)
            if payments is not None:
                parts.append(
                    f'<div class="muted">Выплаты: {_rub(payments)} {escape(currency)}</div>'
                )
    else:
        error_msg = getattr(balance, "error_message", None)
        if account.marketplace == Marketplace.WB:
            parts.append('<div class="muted">Для баланса нужен Finance-доступ WB</div>')
        else:
            parts.append('<div class="muted">💰 Баланс Ozon: не удалось обновить</div>')
            if error_msg:
                user_msg = _ozon_balance_user_message(str(error_msg))
                parts.append(f'<div class="muted">{escape(user_msg)}</div>')
    return "".join(parts)

def _ozon_balance_user_message(error_code: str) -> str:
    if "auth" in error_code.lower() or "401" in error_code or "403" in error_code:
        return "Проверьте ключи доступа Ozon"
    if "rate" in error_code.lower() or "429" in error_code:
        return "Слишком много запросов, повторим позже"
    if "invalid_response" in error_code.lower():
        return "Нет данных"
    if "http" in error_code.lower():
        return "Временно недоступен"
    return "Ошибка синхронизации"

def _subscription_content(
    data: SubscriptionPageData,
    tiers: list[SubscriptionTier],
    timezone: str = "Europe/Moscow",
) -> str:
    active = data.active_subscription
    raw_status = subscription_status(active)
    status_map = {
        "ACTIVE": "Активен",
        "EXPIRED": "Истёк",
        "CANCELLED": "Отменён",
        "TRIAL": "Пробный",
        "PENDING": "Ожидает оплаты",
        "FREE": "Бесплатный тариф",
        "REPLACED": "Заменён",
    }
    status = status_map.get(raw_status.upper(), raw_status)
    expires = (
        format_datetime_for_user(active.expires_at, timezone, "%d.%m.%Y")
        if active and active.expires_at
        else "бессрочно"
    )
    feature_rows = "".join(
        f"<li>{'✅' if enabled else '❌'} {escape(label)}</li>"
        for label, enabled in [
            ("Web-кабинет", data.tier.feature_web_cabinet),
            ("Расширенная аналитика", data.tier.feature_analytics),
            ("План/факт", data.tier.feature_plan_fact),
            ("Безубыточность", data.tier.feature_break_even),
            ("Прогноз остатков", data.tier.feature_stock_forecast),
            ("Алерты", data.tier.feature_alerts),
            ("API-доступ", data.tier.feature_api_access),
        ]
    )
    tier_cards = "".join(_web_tier_card(tier, data.tier.code) for tier in tiers)
    payment_rows = (
        "".join(
            "<tr>"
            f"<td>{format_datetime_for_user(payment.created_at, timezone, '%d.%m.%Y')}</td>"
            f"<td>{_rub(payment.amount)}</td>"
            f"<td>{escape(payment.status.value)}</td>"
            f"<td>{escape(payment.provider)}</td>"
            "</tr>"
            for payment in data.payments
        )
        or '<tr><td colspan="4" class="muted">Платежей пока нет.</td></tr>'
    )
    return f"""
      {_page_header("Подписка и тариф", "Следите за лимитами, функциями и историей платежей.", "/web/settings?tab=marketplaces", "Кабинеты МП")}
      <section class="detail-grid">
        <section class="band">
          <h2>Текущая подписка</h2>
          <div class="kv">
            <span>Тариф</span><strong>{escape(data.tier.name)}</strong>
            <span>Статус</span><strong>{escape(status)}</strong>
            <span>Действует до</span><strong>{escape(expires)}</strong>
            <span>Кабинеты</span><strong>{data.used_accounts} / {data.tier.max_marketplace_accounts}</strong>
            <span>Заказы за месяц</span><strong>{data.used_orders_month} / {_limit(data.tier.max_orders_per_month)}</strong>
            <span>SKU</span><strong>{data.used_products} / {_limit(data.tier.max_products)}</strong>
          </div>
        </section>
        <section class="band">
          <h2>Доступные функции</h2>
          <ul>{feature_rows}</ul>
        </section>
      </section>
      <section class="dashboard-grid">
        {tier_cards}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>История платежей</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Дата</th><th>Сумма</th><th>Статус</th><th>Провайдер</th></tr></thead>
          <tbody>{payment_rows}</tbody>
        </table></div>
      </section>
    """

def _profile_content(user: User, subscription: SubscriptionPageData) -> str:
    checked = " checked" if user.notifications_enabled else ""
    active = subscription.active_subscription
    raw_status = subscription_status(active)
    status_map = {
        "ACTIVE": "Активен",
        "EXPIRED": "Истёк",
        "CANCELLED": "Отменён",
        "TRIAL": "Пробный",
        "PENDING": "Ожидает оплаты",
        "FREE": "Бесплатный тариф",
        "REPLACED": "Заменён",
    }
    status_label = status_map.get(raw_status.upper(), raw_status)
    expires = (
        format_datetime_for_user(active.expires_at, user.timezone, "%d.%m.%Y")
        if active and active.expires_at
        else "бессрочно"
    )
    max_orders = subscription.tier.max_orders_per_month
    max_orders_label = str(max_orders) if max_orders else "без ограничений"
    max_products = subscription.tier.max_products
    max_products_label = str(max_products) if max_products else "без ограничений"
    
    # Format last activity
    last_activity = _dt(user.last_activity_at, user.timezone) if user.last_activity_at else "н/д"
    registration_date = _dt(user.created_at, user.timezone) if user.created_at else "н/д"
    
    # Display name and username using unified functions
    display_name = _get_user_display_name(user)
    telegram_username = _get_telegram_username(user)
    username_display = telegram_username if telegram_username else "Username не указан"
    
    # Determine if username is from Telegram
    if not user.username:
        username_display = "Не получен из Telegram"
    
    # Account status
    account_status = "Активен" if user.status.value == "ACTIVE" else user.status.value
    
    # Tariff and limits
    tier_name = subscription.tier.name
    tier_status = status_label
    tariff_expires = expires
    
    # Fast actions
    fast_actions = (
        '<div class="button-group">'
        f'<a class="button primary" href="/web/settings?tab=marketplaces">Маркетплейсы</a>'
        f'<a class="button" href="/web/settings?tab=subscription">Тариф</a>'
        f'<a class="button" href="/web/settings?tab=notifications">Уведомления</a>'
        f'<a class="button" href="/web/settings?tab=sync">Синхронизация</a>'
        f'<a class="button" href="/web/settings?tab=company">Данные компании</a>'
        f'<a class="button" href="/web/settings?tab=security">Безопасность</a>'
        f'<a class="button" href="/web/support">Поддержка</a>'
        '</div>'
    )
    
    return f"""
      {_page_header("Профиль", "Управляйте настройками пользователя, уведомлениями и подпиской.", "/web/settings?tab=subscription", "Подписка")}
      <section class="detail-grid">
        <section class="card">
          <div class="card-header">
            <div class="avatar">
              <div class="avatar-initials">{display_name[0].upper() if display_name else '?'}</div>
            </div>
            <div class="user-info">
              <h2>{display_name}</h2>
              <div class="user-meta">
                <span class="meta-item">Telegram ID: {user.telegram_id}</span>
                <span class="meta-item">Username: {username_display}</span>
                <span class="meta-item">Статус: {account_status}</span>
                <span class="meta-item">Тариф: {tier_name}</span>
                <span class="meta-item">Регистрация: {registration_date}</span>
                <span class="meta-item">Последняя активность: {last_activity}</span>
              </div>
            </div>
          </div>
          <div class="card-actions">
            <button class="button primary" onclick="saveProfile()">Сохранить профиль</button>
            <button class="button" onclick="openNotifications()">Уведомления</button>
            <button class="button" onclick="openSecurity()">Безопасность</button>
          </div>
        </section>
        
        <section class="card">
          <h2>Личные данные</h2>
          <div class="form-grid">
            <div class="form-group">
              <label for="first_name">Имя</label>
              <input id="first_name" name="first_name" type="text" 
                     value="{escape(user.first_name or '')}" 
                     placeholder="Введите ваше имя">
            </div>
            <div class="form-group">
              <label for="last_name">Фамилия</label>
              <input id="last_name" name="last_name" type="text" 
                     value="{escape(user.last_name or '')}" 
                     placeholder="Введите вашу фамилию">
            </div>
            <div class="form-group">
              <label for="phone">Телефон</label>
              <input id="phone" name="phone" type="tel" 
                     value="{escape(user.phone or '')}" 
                     placeholder="+7 900 123-45-67">
            </div>
            <div class="form-group">
              <label for="email">Email</label>
              <input id="email" name="email" type="email" 
                     value="{escape(user.email or '')}" 
                     placeholder="example@mail.com">
            </div>
            <div class="form-group">
              <label for="timezone">Часовой пояс</label>
              <select id="timezone" name="timezone">
                <option value="Europe/Moscow" {"selected" if user.timezone == "Europe/Moscow" else ""}>Москва</option>
                <option value="Europe/Samara" {"selected" if user.timezone == "Europe/Samara" else ""}>Самара</option>
                <option value="Asia/Yekaterinburg" {"selected" if user.timezone == "Asia/Yekaterinburg" else ""}>Екатеринбург</option>
                <option value="Asia/Omsk" {"selected" if user.timezone == "Asia/Omsk" else ""}>Омск</option>
                <option value="Asia/Krasnoyarsk" {"selected" if user.timezone == "Asia/Krasnoyarsk" else ""}>Красноярск</option>
                <option value="Asia/Irkutsk" {"selected" if user.timezone == "Asia/Irkutsk" else ""}>Иркутск</option>
                <option value="Asia/Yakutsk" {"selected" if user.timezone == "Asia/Yakutsk" else ""}>Якутск</option>
                <option value="Asia/Vladivostok" {"selected" if user.timezone == "Asia/Vladivostok" else ""}>Владивосток</option>
              </select>
            </div>
          </div>
          <div class="form-actions">
            <button class="button primary" onclick="saveProfile()">Сохранить</button>
            <div id="profile-save-notification" class="notification" style="display: none;"></div>
          </div>
        </section>
        
        <section class="card">
          <h2>Данные компании</h2>
          <div class="company-info">
            <div class="company-field">
              <label>Название компании / ИП:</label>
              <div class="field-value">{escape(user.company_name or "Не указано")}</div>
            </div>
            <div class="company-field">
              <label>ИНН:</label>
              <div class="field-value">{escape(user.inn or "Не указан")}</div>
            </div>
            <div class="company-field">
              <label>ОГРН / ОГРНИП:</label>
              <div class="field-value">{escape(user.ogrn or "Не указан")}</div>
            </div>
            <div class="company-field">
              <label>Юридический статус:</label>
              <div class="field-value">ИП</div>
            </div>
            <div class="company-field">
              <label>Налоговый режим:</label>
              <div class="field-value">ОСНО</div>
            </div>
            <div class="company-field">
              <label>Регион:</label>
              <div class="field-value">Московская область</div>
            </div>
          </div>
          <div class="company-actions">
            <button class="button" onclick="openCompanySettings()">Редактировать</button>
          </div>
        </section>
        
        <section class="card">
          <h2>Тариф и лимиты</h2>
          <div class="tariff-info">
            <div class="tariff-header">
              <h3>{tier_name}</h3>
              <span class="status-badge {"good" if status_label == "Активен" else "warn"}">{tier_status}</span>
            </div>
            <div class="tariff-details">
              <div class="limit-item">
                <div class="limit-header">
                  <span>Кабинеты</span>
                  <span class="limit-value">{subscription.used_accounts} / {subscription.tier.max_marketplace_accounts}</span>
                </div>
                <div class="progress-bar">
                  <div class="progress-fill" style="width: {subscription.used_accounts / subscription.tier.max_marketplace_accounts * 100 if subscription.tier.max_marketplace_accounts > 0 else 0}%"></div>
                </div>
              </div>
              <div class="limit-item">
                <div class="limit-header">
                  <span>Заказы за месяц</span>
                  <span class="limit-value">{subscription.used_orders_month} / {max_orders_label}</span>
                </div>
                <div class="progress-bar">
                  <div class="progress-fill" style="width: {subscription.used_orders_month / max(int(max_orders) if max_orders and max_orders != "без ограничений" else 1000) * 100 if max_orders and max_orders != "без ограничений" else 0}%"></div>
                </div>
              </div>
              <div class="limit-item">
                <div class="limit-header">
                  <span>SKU</span>
                  <span class="limit-value">{subscription.used_products} / {max_products_label}</span>
                </div>
                <div class="progress-bar">
                  <div class="progress-fill" style="width: {subscription.used_products / max(int(max_products) if max_products and max_products != "без ограничений" else 1000) * 100 if max_products and max_products != "без ограничений" else 0}%"></div>
                </div>
              </div>
              <div class="limit-item">
                <div class="limit-header">
                  <span>Уведомления</span>
                  <span class="limit-value">{"включены" if user.notifications_enabled else "выключены"}</span>
                </div>
              </div>
            </div>
          </div>
          <div class="tariff-actions">
            <button class="button primary" onclick="openTariffManagement()">Управление тарифом</button>
          </div>
        </section>
        
        <section class="card">
          <h2>Безопасность аккаунта</h2>
          <div class="security-info">
            <div class="security-field">
              <label>Telegram ID:</label>
              <div class="field-value">{user.telegram_id}</div>
            </div>
            <div class="security-field">
              <label>Последний IP:</label>
              <div class="field-value" id="last-login-ip">{_dt(getattr(user, 'last_login_ip', None) or 'н/д', user.timezone)}</div>
            </div>
            <div class="security-field">
              <label>Последняя активность:</label>
              <div class="field-value">{last_activity}</div>
            </div>
            <div class="security-field">
              <label>Дата регистрации:</label>
              <div class="field-value">{registration_date}</div>
            </div>
            <div class="security-field">
              <label>Статус аккаунта:</label>
              <div class="field-value">{account_status}</div>
            </div>
          </div>
          <div class="security-actions">
            <button class="button" onclick="openSecuritySettings()">Открыть настройки безопасности</button>
          </div>
        </section>
      </section>
      
      <section class="card">
        <h2>Быстрые действия</h2>
        {fast_actions}
      </section>
      
      <div id="save-notification" class="notification-container"></div>
      
      <script>
        // Profile save notification
        function showSaveNotification(message, isSuccess = true) {
          const container = document.getElementById('save-notification');
          const notification = document.createElement('div');
          notification.className = `notification ${isSuccess ? 'success' : 'error'}${isSuccess ? 'show' : ''}`;
          notification.textContent = message;
          container.innerHTML = '';
          container.appendChild(notification);
          if (isSuccess) {
            setTimeout(() => {
              notification.classList.remove('show');
              setTimeout(() => container.innerHTML = '', 300);
            }, 3000);
          }
        }
        
        // Profile saving
        async function saveProfile() {
          const formData = {
            first_name: document.getElementById('first_name').value,
            last_name: document.getElementById('last_name').value,
            phone: document.getElementById('phone').value,
            email: document.getElementById('email').value,
            company_name: '{escape(user.company_name or '')}',
            inn: '{escape(user.inn or '')}',
            ogrn: '{escape(user.ogrn or '')}',
            timezone: document.getElementById('timezone').value,
          };
          
          try {
            const response = await fetch('/web/settings/profile', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(formData)
            });
            
            if (response.ok) {
              showSaveNotification('Профиль успешно сохранен');
            } else {
              const error = await response.text();
              showSaveNotification(`Ошибка при сохранении: ${error}`, false);
            }
          } catch (error) {
            showSaveNotification(`Ошибка при сохранении: ${error}`, false);
          }
        }
        
        // Navigation functions
        function openNotifications() {
          window.location.href = '/web/settings?tab=notifications';
        }
        
        function openSecurity() {
          window.location.href = '/web/settings?tab=security';
        }
        
        function openCompanySettings() {
          window.location.href = '/web/settings?tab=company';
        }
        
        function openTariffManagement() {
          window.location.href = '/web/settings?tab=subscription';
        }
        
        function openSecuritySettings() {
          window.location.href = '/web/settings?tab=security';
        }
        
        function openNotifications() {
          window.location.href = '/web/settings?tab=notifications';
        }
        
        function openCompanySettings() {
          window.location.href = '/web/settings?tab=company';
        }
        
        function openTariffManagement() {
          window.location.href = '/web/settings?tab=subscription';
        }
        
        function openSecuritySettings() {
          window.location.href = '/web/settings?tab=security';
        }
      </script>
    """

def _control_content(data: ControlPageData) -> str:
    accounts = (
        "".join(
            f"<li>{escape(account.name)}: {escape(account.last_error_message or 'ошибка синхронизации')}</li>"
            for account in data.error_accounts
        )
        or "<li>Критичных ошибок кабинетов сейчас нет.</li>"
    )
    alerts = (
        "".join(
            f"<li>{escape(alert.title)} — {escape(alert.message)}</li>"
            for alert in data.open_alerts
        )
        or "<li>Открытых алертов сейчас нет.</li>"
    )
    return f"""
      {_page_header("Контроль ошибок", "Что требует внимания прямо сейчас.", "/web/data-quality", "Проблемы данных")}
      <section class="kpi-grid">
        {_simple_kpi("Качество данных", str(data.report.score), "good" if data.report.score >= 80 else "warn")}
        {_simple_kpi("Без себестоимости", str(data.missing_cost_products), "warn" if data.missing_cost_products else "neutral")}
        {_simple_kpi("Предварительная экономика", str(data.preliminary_orders), "warn" if data.preliminary_orders else "neutral")}
        {_simple_kpi("Низкие остатки", str(data.low_stock_products), "bad" if data.low_stock_products else "neutral")}
      </section>
      <section class="detail-grid" style="margin-top:14px">
        <section class="band"><h2>Ошибки синхронизации</h2><ul>{accounts}</ul></section>
        <section class="band"><h2>Актуальные алерты</h2><ul>{alerts}</ul></section>
      </section>
    """

def _settings_content(user: User) -> str:
    threshold = user.low_margin_threshold_percent or Decimal("10")
    checked = "включены" if user.notifications_enabled else "выключены"
    return f"""
      {_page_header("Настройки", "Финансовый контроль, локализация, уведомления и быстрые переходы.", "/web/settings?tab=profile", "Профиль")}
      <section class="detail-grid">
        <section class="band">
          <h2>Финансовый контроль</h2>
          <form class="filters" method="post" action="/web/settings/low-margin">
            <div>
              <label for="threshold">Порог низкой маржи, %</label>
              <input id="threshold" name="threshold" type="number" min="0" max="100" step="0.01"
                     value="{threshold}">
            </div>
            <button class="button primary" type="submit">Сохранить</button>
          </form>
          <p class="muted">Порог используется в отчётах, алертах и контрольных web-экранах.</p>
        </section>
        <section class="band">
          <h2>Локализация</h2>
          <div class="kv">
            <span>Часовой пояс</span><strong>{escape(user.timezone)}</strong>
            <span>Язык</span><strong>{escape(user.language)}</strong>
          </div>
          <p><a class="button" href="/web/settings?tab=profile">Изменить в профиле</a></p>
        </section>
        <section class="band">
          <h2>Уведомления</h2>
          <p>Статус Telegram-уведомлений: <span class="badge">{checked}</span></p>
          <p class="muted">Тонкая настройка уведомлений по кабинетам доступна в Telegram-боте.</p>
        </section>
        <section class="band">
          <h2>Подписка и доступ</h2>
          <p class="muted">Проверьте текущий тариф, лимиты и доступные возможности.</p>
          <p><a class="button primary" href="/web/settings?tab=subscription">Открыть подписку</a></p>
        </section>
      </section>
    """

def _data_quality_content(report: DataQualityReport) -> str:
    tone = "good" if report.score >= 80 else "warn" if report.score >= 50 else "bad"
    metrics = "".join(
        "<tr>"
        f"<td>{escape(metric.title)}</td>"
        f'<td class="num">{metric.value}</td>'
        f"<td>{escape(metric.status)}</td>"
        f"<td>{escape(metric.description)}</td>"
        "</tr>"
        for metric in report.metrics
    )
    recommendations = "".join(f"<li>{escape(item)}</li>" for item in report.recommendations)
    return f"""
      {_section_subnav_products("data_quality")}
      <section class="kpi-grid">
        {_simple_kpi("Индекс качества данных", str(report.score), tone)}
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Проблемы данных</h2>
        <div class="table-wrap">
          <table class="table">
        <thead>
          <tr>
            <th>Проверка</th><th class="num">Значение</th><th>Статус</th><th>Комментарий</th>
          </tr>
        </thead>
            <tbody>{metrics}</tbody>
          </table>
        </div>
      </section>
      <section class="band" style="margin-top:14px">
        <h2>Что сделать</h2>
        <ul>{recommendations}</ul>
      </section>
    """
