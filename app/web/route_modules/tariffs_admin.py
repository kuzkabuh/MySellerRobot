"""version: 2.0.0
description: Admin billing dashboard — полноценное управление тарифными планами.
updated: 2026-06-12

Роуты:
  GET  /admin/tariffs            — список тарифов с KPI, фильтрами, таблицей
  GET  /admin/tariffs/new        — форма создания
  POST /admin/tariffs/new        — создать тариф
  GET  /admin/tariffs/{id}/edit  — форма редактирования
  POST /admin/tariffs/{id}/edit  — обновить тариф
  POST /admin/tariffs/{id}/toggle         — вкл/выкл (is_active)
  POST /admin/tariffs/{id}/toggle-public  — публичный/скрытый
  POST /admin/tariffs/{id}/duplicate      — дублировать тариф
  POST /admin/tariffs/{id}/move           — переместить вверх/вниз
  POST /admin/tariffs/{id}/delete         — удалить (только без пользователей)
"""

# ruff: noqa: E501

import logging
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User
from app.models.subscriptions import SubscriptionTier
from app.services.subscriptions.tariff_service import TARIFF_FEATURE_FIELDS, TariffService
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY, is_admin_user
from app.web.rendering import page

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Вспомогательные функции ───────────────────────────────────────────────────


def _require_admin(user: User) -> None:
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Доступно только администраторам")


def _admin_page(title: str, user: User, content: str) -> str:
    return page(title, f"{user.first_name or user.username or 'admin'} (admin)", content, active_path="/web/admin/tariffs")


def _h(value: object) -> str:
    return escape(str(value), quote=True)


def _rub(amount: Decimal | None, *, zero_label: str = "0 ₽") -> str:
    if amount is None:
        return "—"
    if amount == 0:
        return zero_label
    formatted = f"{int(amount):,}".replace(",", " ")
    return f"{formatted} ₽"


def _lim(value: int | None) -> str:
    """Форматирует лимит: None → ∞, число → строка."""
    return "∞" if value is None else str(value)


def _savings_pct(monthly: Decimal | None, yearly: Decimal | None) -> str:
    """Процент экономии при годовой оплате относительно 12 месяцев."""
    if not monthly or not yearly or monthly <= 0:
        return ""
    annual_monthly = monthly * 12
    if annual_monthly <= yearly:
        return ""
    pct = int(round((annual_monthly - yearly) / annual_monthly * 100))
    return f"-{pct}%" if pct > 0 else ""


def _flash_redirect(url: str, level: str, msg: str) -> RedirectResponse:
    """Редирект с flash-параметрами в URL."""
    sep = "&" if "?" in url else "?"
    return RedirectResponse(f"{url}{sep}flash={level}&msg={quote(msg)}", status_code=303)


def _flash_script(flash: str, msg: str) -> str:
    """JavaScript-блок для показа toast-уведомления из URL-параметров."""
    if not flash or not msg:
        return ""
    level_map = {"ok": "success", "err": "error", "warn": "warning"}
    css_class = level_map.get(flash, "info")
    safe_msg = _h(msg)
    return f"""
<script>
(function() {{
  var container = document.getElementById('toast-container');
  if (!container) {{
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }}
  var t = document.createElement('div');
  t.className = 'toast {css_class}';
  t.textContent = '{safe_msg}';
  container.appendChild(t);
  setTimeout(function() {{
    t.style.animation = 'toast-out 0.3s ease forwards';
    setTimeout(function() {{ t.remove(); }}, 300);
  }}, 3500);
}})();
</script>"""



# ── Частичные HTML-фрагменты ──────────────────────────────────────────────────


def _tariff_badges_html(tariff: SubscriptionTier) -> str:
    """Бейджи статуса, видимости и типа тарифа."""
    parts: list[str] = []
    if tariff.is_active:
        parts.append('<span class="badge good">Активен</span>')
    else:
        parts.append('<span class="badge bad">Откл.</span>')
    if tariff.is_public:
        parts.append('<span class="badge action">Публ.</span>')
    else:
        parts.append('<span class="badge">Скрыт</span>')
    if tariff.is_featured:
        parts.append('<span class="badge warn">★ Рек.</span>')
    pm = getattr(tariff, "price_monthly", Decimal("0"))
    if pm == 0:
        parts.append('<span class="badge">Бесплатный</span>')
    elif getattr(tariff, "is_custom_price", False):
        parts.append('<span class="badge warn">Enterprise</span>')
    return " ".join(parts)


def _tariff_price_html(tariff: SubscriptionTier) -> str:
    """Блок цены: ежемесячная + годовая со скидкой."""
    pm = getattr(tariff, "price_monthly", None)
    py = getattr(tariff, "price_yearly", None)
    is_custom = getattr(tariff, "is_custom_price", False)
    if is_custom:
        return '<span style="color:var(--warning);font-weight:700;">По запросу</span>'
    monthly = _rub(pm, zero_label="Бесплатно")
    savings = _savings_pct(pm, py)
    if py:
        yearly_str = f'<div class="muted" style="font-size:12px;">{_rub(py)}/год'
        if savings:
            yearly_str += f' <span style="color:var(--success);font-weight:700;">{savings}</span>'
        yearly_str += "</div>"
    else:
        yearly_str = ""
    return f'<strong>{monthly}</strong>{yearly_str}'


def _tariff_limits_html(tariff: SubscriptionTier) -> str:
    """Компактный блок лимитов для таблицы."""
    items = [
        f'{_lim(tariff.max_marketplace_accounts)} кабинет',
        f'{_lim(tariff.max_products)} товаров',
        f'{_lim(tariff.max_orders_per_month)} зак./мес',
    ]
    if tariff.max_users is not None:
        items.append(f'{tariff.max_users} польз.')
    return '<div class="muted" style="font-size:12px;line-height:1.7;">' + '<br>'.join(items) + '</div>'


def _tariff_actions_html(tariff: SubscriptionTier, user_count: int, tariff_idx: int, total: int) -> str:
    """Кнопки действий для строки таблицы."""
    tid = tariff.id
    toggle_label = "Откл." if tariff.is_active else "Вкл."
    toggle_class = "btn-warning" if tariff.is_active else "btn-primary"
    # Добавляем confirm только если отключаем тариф с активными пользователями
    toggle_confirm = ""
    if tariff.is_active and user_count > 0:
        safe_name = tariff.name.replace("'", "\\'")
        toggle_confirm = f" onsubmit=\"return confirm('Отключить тариф «{safe_name}»?\\nНа нём {user_count} активных пользователей.')\""

    pub_label = "Скрыть" if tariff.is_public else "Показать"
    up_disabled = " disabled" if tariff_idx == 0 else ""
    down_disabled = " disabled" if tariff_idx >= total - 1 else ""

    # Кнопка удаления — только если нет пользователей
    if user_count == 0:
        safe_del_name = tariff.name.replace("'", "\\'")
        delete_btn = f"""
  <form method="post" action="/web/admin/tariffs/{tid}/delete"
        onsubmit="return confirm('Удалить тариф «{safe_del_name}»?\\nЭто действие необратимо.')">
    <button class="btn btn-sm btn-danger" type="submit" title="Удалить тариф">✕</button>
  </form>"""
    else:
        delete_btn = f'<button class="btn btn-sm" disabled title="Нельзя удалить: {user_count} активных пользователей" style="opacity:.35;cursor:not-allowed;">✕</button>'

    return f"""
<div style="display:flex;gap:4px;flex-wrap:wrap;">
  <a class="btn btn-sm" href="/web/admin/tariffs/{tid}/edit" title="Редактировать">✎ Ред.</a>

  <form method="post" action="/web/admin/tariffs/{tid}/duplicate">
    <button class="btn btn-sm" type="submit" title="Дублировать тариф">⊕</button>
  </form>

  <form method="post" action="/web/admin/tariffs/{tid}/toggle"{toggle_confirm}>
    <button class="btn btn-sm {toggle_class}" type="submit">{toggle_label}</button>
  </form>

  <form method="post" action="/web/admin/tariffs/{tid}/toggle-public">
    <button class="btn btn-sm" type="submit" title="Изменить видимость на витрине">{pub_label}</button>
  </form>

  <form method="post" action="/web/admin/tariffs/{tid}/move">
    <input type="hidden" name="direction" value="up">
    <button class="btn btn-sm btn-ghost" type="submit"{up_disabled} title="Вверх">↑</button>
  </form>

  <form method="post" action="/web/admin/tariffs/{tid}/move">
    <input type="hidden" name="direction" value="down">
    <button class="btn btn-sm btn-ghost" type="submit"{down_disabled} title="Вниз">↓</button>
  </form>

  {delete_btn}
</div>"""


# ── KPI-блок ──────────────────────────────────────────────────────────────────


def _kpi_cards_html(tariffs_with_counts: list[tuple[SubscriptionTier, int]], billing: dict[str, Any]) -> str:
    total = len(tariffs_with_counts)
    active = sum(1 for t, _ in tariffs_with_counts if t.is_active)
    public = sum(1 for t, _ in tariffs_with_counts if t.is_public)
    paid_users = billing.get("paid_users", 0)
    mrr = billing.get("mrr", Decimal("0"))
    arr = billing.get("arr", Decimal("0"))
    avg = billing.get("avg_price", Decimal("0"))

    def kpi(label: str, value: str, css: str = "", sub: str = "") -> str:
        sub_html = f'<small style="color:var(--text-muted);font-size:12px;margin-top:4px;display:block;">{sub}</small>' if sub else ""
        return f"""
    <div class="kpi {css}">
      <span>{label}</span>
      <strong>{value}</strong>
      {sub_html}
    </div>"""

    return f"""
<div class="kpi-grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr));margin-bottom:16px;">
  {kpi("Всего тарифов", str(total))}
  {kpi("Активных", str(active), "good" if active > 0 else "")}
  {kpi("Публичных", str(public), "action")}
  {kpi("Платных юзеров", str(paid_users), "neutral")}
  {kpi("MRR", _rub(mrr), "good" if mrr > 0 else "neutral", "в месяц")}
  {kpi("ARR", _rub(arr), "good" if arr > 0 else "neutral", "в год")}
  {kpi("Средний чек", _rub(avg), sub="среди платных")}
</div>"""


# ── Панель фильтров ────────────────────────────────────────────────────────────


def _filters_html(q: str, status: str, visibility: str, sort: str) -> str:
    def opt(val: str, label: str, current: str) -> str:
        sel = ' selected' if val == current else ''
        return f'<option value="{_h(val)}"{sel}>{_h(label)}</option>'

    return f"""
<form method="get" action="/web/admin/tariffs" class="filters">
  <div>
    <label>Поиск</label>
    <input type="text" name="q" value="{_h(q)}" placeholder="Название или код…">
  </div>
  <div>
    <label>Статус</label>
    <select name="status">
      {opt("", "Все", status)}
      {opt("active", "Активные", status)}
      {opt("inactive", "Отключённые", status)}
    </select>
  </div>
  <div>
    <label>Видимость</label>
    <select name="visibility">
      {opt("", "Все", visibility)}
      {opt("public", "Публичные", visibility)}
      {opt("hidden", "Скрытые", visibility)}
    </select>
  </div>
  <div>
    <label>Сортировка</label>
    <select name="sort">
      {opt("sort_order", "Порядок", sort)}
      {opt("price_asc", "Цена ↑", sort)}
      {opt("price_desc", "Цена ↓", sort)}
      {opt("users_desc", "Юзеров ↓", sort)}
      {opt("created_desc", "Новые", sort)}
    </select>
  </div>
  <div style="display:flex;gap:6px;align-items:flex-end;">
    <button class="btn btn-primary btn-sm" type="submit">Применить</button>
    <a class="btn btn-sm" href="/web/admin/tariffs">Сбросить</a>
  </div>
</form>"""


# ── Строка таблицы ────────────────────────────────────────────────────────────


def _table_row_html(tariff: SubscriptionTier, user_count: int, idx: int, total: int) -> str:
    badge_text = getattr(tariff, "badge_text", None)
    badge_html = f' <span class="badge warn" style="font-size:10px;">{_h(badge_text)}</span>' if badge_text else ""
    trial_days = getattr(tariff, "trial_days", None)
    trial_html = f'<div class="muted" style="font-size:11px;">Пробный: {trial_days} дн.</div>' if trial_days else ""

    return f"""
<tr>
  <td style="color:var(--text-muted);font-weight:600;text-align:center;width:48px;">
    {tariff.sort_order}
  </td>
  <td>
    <a href="/web/admin/tariffs/{tariff.id}/edit" style="font-weight:700;font-size:14px;">{_h(tariff.name)}</a>
    {badge_html}
    <div class="muted" style="font-family:var(--font-mono);font-size:11px;margin-top:2px;">{_h(tariff.code)}</div>
    {trial_html}
  </td>
  <td style="white-space:nowrap;">{_tariff_price_html(tariff)}</td>
  <td>
    {_tariff_limits_html(tariff)}
  </td>
  <td>
    {_tariff_badges_html(tariff)}
  </td>
  <td style="text-align:center;font-weight:700;font-size:15px;color:{'var(--success)' if user_count > 0 else 'var(--text-muted)'};">
    {user_count}
  </td>
  <td>
    {_tariff_actions_html(tariff, user_count, idx, total)}
  </td>
</tr>"""


# ── Список тарифов ────────────────────────────────────────────────────────────


@router.get("/admin/tariffs", response_class=HTMLResponse)
async def tariffs_list_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    q: str = "",
    status: str = "",
    visibility: str = "",
    sort: str = "sort_order",
    flash: str = "",
    msg: str = "",
) -> str:
    _require_admin(user)
    service = TariffService(session)

    tariffs_with_counts = await service.get_all_tariffs_with_user_counts()
    try:
        billing = await service.get_billing_stats()
    except Exception:
        billing = {"paid_users": 0, "mrr": Decimal("0"), "arr": Decimal("0"), "avg_price": Decimal("0")}

    # Применяем фильтры
    filtered = tariffs_with_counts
    if q:
        ql = q.lower()
        filtered = [(t, c) for t, c in filtered if ql in t.name.lower() or ql in t.code.lower()]
    if status == "active":
        filtered = [(t, c) for t, c in filtered if t.is_active]
    elif status == "inactive":
        filtered = [(t, c) for t, c in filtered if not t.is_active]
    if visibility == "public":
        filtered = [(t, c) for t, c in filtered if t.is_public]
    elif visibility == "hidden":
        filtered = [(t, c) for t, c in filtered if not t.is_public]

    # Сортировка
    if sort == "price_asc":
        filtered.sort(key=lambda x: x[0].price_monthly or Decimal("0"))
    elif sort == "price_desc":
        filtered.sort(key=lambda x: x[0].price_monthly or Decimal("0"), reverse=True)
    elif sort == "users_desc":
        filtered.sort(key=lambda x: x[1], reverse=True)
    elif sort == "created_desc":
        filtered.sort(key=lambda x: x[0].created_at, reverse=True)
    # sort_order — уже отсортировано из БД

    total = len(filtered)

    # Строки таблицы
    rows = "".join(_table_row_html(t, c, i, total) for i, (t, c) in enumerate(filtered))

    empty_state = """
    <tr><td colspan="7">
      <div class="empty-state" style="margin:16px;">
        <strong>Тарифы не найдены</strong>
        <span>Попробуйте изменить фильтры или создайте первый тариф</span>
        <a class="btn btn-primary" href="/web/admin/tariffs/new" style="margin-top:12px;">+ Создать тариф</a>
      </div>
    </td></tr>""" if not rows else ""

    # Подсчёт активных фильтров для индикации
    filters_active = any([q, status, visibility, sort != "sort_order"])
    filter_note = f' <span class="badge warn" style="margin-left:6px;">Фильтр: {total} из {len(tariffs_with_counts)}</span>' if filters_active and total != len(tariffs_with_counts) else ""

    content = f"""
{_flash_script(flash, msg)}

<div class="page-header">
  <div>
    <h2>Тарифы{filter_note}</h2>
    <p style="margin:4px 0 0;color:var(--text-secondary);font-size:13px;">
      Управление тарифными планами, лимитами, доступами и стоимостью подписок
    </p>
  </div>
  <div class="page-actions">
    <a class="btn btn-primary" href="/web/admin/tariffs/new">+ Создать тариф</a>
  </div>
</div>

{_kpi_cards_html(tariffs_with_counts, billing)}
{_filters_html(q, status, visibility, sort)}

<div class="table-wrap">
  <table class="table">
    <thead>
      <tr>
        <th style="width:48px;text-align:center;">#</th>
        <th>Тариф</th>
        <th>Цена</th>
        <th>Лимиты</th>
        <th>Статус</th>
        <th style="text-align:center;">Юзеров</th>
        <th>Действия</th>
      </tr>
    </thead>
    <tbody>
      {rows}{empty_state}
    </tbody>
  </table>
</div>
"""
    return _admin_page("Тарифы", user, content)


# ── Форма тарифа ──────────────────────────────────────────────────────────────


def _tariff_form_html(*, action_url: str, title: str, tariff: SubscriptionTier | None = None, user_count: int = 0) -> str:
    """Генерирует HTML-форму создания/редактирования тарифа."""

    def _val(field: str, default: str = "") -> str:
        if tariff is None:
            return _h(default)
        v = getattr(tariff, field, None)
        return _h(str(v)) if v is not None else _h(default)

    def _checked(field: str, default: bool = False) -> str:
        if tariff is None:
            return " checked" if default else ""
        return " checked" if getattr(tariff, field, default) else ""

    def _num(field: str, default: str = "") -> str:
        if tariff is None:
            return _h(default)
        v = getattr(tariff, field, None)
        return _h(str(v)) if v is not None else ""

    code_readonly = ""
    code_hint = ""
    if tariff and user_count > 0:
        code_readonly = " readonly"
        code_hint = f'<div class="muted" style="margin-top:4px;font-size:11px;">⚠ Код нельзя менять: на тарифе {user_count} активных пользователей</div>'

    # Чекбоксы функций
    feature_cols = ""
    for field, label in TARIFF_FEATURE_FIELDS:
        checked = _checked(field)
        feature_cols += f"""
      <label class="checkbox-label">
        <input type="checkbox" name="{field}"{checked}>
        {_h(label)}
      </label>"""

    # Расчёт экономии при годовой оплате (в форме — для подсказки)
    savings_note = ""
    if tariff and tariff.price_monthly and tariff.price_yearly:
        pct = _savings_pct(tariff.price_monthly, tariff.price_yearly)
        if pct:
            savings_note = f'<div class="muted" style="font-size:12px;margin-top:6px;">Экономия при годовой оплате: <strong style="color:var(--success);">{pct}</strong> (vs {_rub(tariff.price_monthly * 12)}/год)</div>'

    # Предупреждение о пользователях
    user_warn = ""
    if tariff and user_count > 0:
        user_warn = f"""
<div class="notice warning" style="margin-bottom:12px;">
  ⚠ На этом тарифе <strong>{user_count}</strong> активных пользователей.
  Изменения немедленно вступят в силу.
</div>"""

    # Кнопка назад: к редактированию нет смысла, используем список
    back_url = "/web/admin/tariffs"

    # Live-preview JavaScript
    preview_js = _preview_card_js()

    return f"""
<div class="page-header">
  <div>
    <h2>{_h(title)}</h2>
    {f'<div class="muted" style="font-size:12px;margin-top:4px;">ID: {tariff.id} · Код: {tariff.code}</div>' if tariff else ''}
  </div>
  <div class="page-actions">
    <a class="btn" href="{back_url}">← К списку тарифов</a>
  </div>
</div>

{user_warn}

<div style="display:grid;grid-template-columns:minmax(0,1.5fr) minmax(260px,0.5fr);gap:16px;align-items:start;">
<div>

<form method="post" action="{action_url}" id="tariff-form">

  <div class="band">
    <h3>📋 Основная информация</h3>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:12px;">
      <div>
        <label>Код тарифа *</label>
        <input type="text" name="code" value="{_val('code')}" required
               placeholder="pro" pattern="[a-zA-Z0-9_-]+"
               title="Только латиница, цифры, дефис и подчёркивание"{code_readonly}
               style="font-family:var(--font-mono);">
        {code_hint}
      </div>
      <div>
        <label>Название *</label>
        <input type="text" name="name" value="{_val('name')}" required placeholder="Профессиональный" id="prev-name">
      </div>
      <div>
        <label>Метка тарифа</label>
        <input type="text" name="badge_text" value="{_val('badge_text')}"
               placeholder="Популярный" maxlength="64" id="prev-badge">
      </div>
      <div>
        <label>Порядок отображения</label>
        <input type="number" name="sort_order" value="{_num('sort_order', '0')}" min="0">
      </div>
      <div>
        <label>Валюта</label>
        <input type="text" name="currency" value="{_val('currency', 'RUB')}" maxlength="3" style="text-transform:uppercase;">
      </div>
    </div>
    <div style="margin-top:12px;">
      <label>Описание</label>
      <textarea name="description" rows="3" placeholder="Для кого этот тариф?">{_val('description')}</textarea>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:16px;margin-top:12px;">
      <label class="checkbox-label">
        <input type="checkbox" name="is_active"{_checked('is_active', True)} id="prev-active"> Активен
      </label>
      <label class="checkbox-label">
        <input type="checkbox" name="is_public"{_checked('is_public', True)}> Публичный
      </label>
      <label class="checkbox-label">
        <input type="checkbox" name="is_featured"{_checked('is_featured')} id="prev-featured"> Рекомендуемый ★
      </label>
      <label class="checkbox-label">
        <input type="checkbox" name="is_custom_price"{_checked('is_custom_price')} id="prev-custom"> По запросу
      </label>
    </div>
  </div>

  <div class="band">
    <h3>💰 Цены</h3>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-top:12px;">
      <div>
        <label>Цена за месяц *</label>
        <input type="number" name="price_monthly" value="{_num('price_monthly', '0')}"
               step="0.01" min="0" id="prev-price-monthly">
      </div>
      <div>
        <label>Цена за 3 месяца</label>
        <input type="number" name="price_3_months" value="{_num('price_3_months')}"
               step="0.01" min="0" placeholder="Без скидки">
      </div>
      <div>
        <label>Цена за 6 месяцев</label>
        <input type="number" name="price_6_months" value="{_num('price_6_months')}"
               step="0.01" min="0" placeholder="Без скидки">
      </div>
      <div>
        <label>Цена за год</label>
        <input type="number" name="price_yearly" value="{_num('price_yearly')}"
               step="0.01" min="0" placeholder="Без скидки" id="prev-price-yearly">
      </div>
      <div>
        <label>Пробный период (дней)</label>
        <input type="number" name="trial_days" value="{_num('trial_days')}"
               min="0" max="365" placeholder="Нет">
      </div>
    </div>
    {savings_note}
  </div>

  <div class="band">
    <h3>📊 Лимиты</h3>
    <div class="muted" style="font-size:12px;margin-bottom:10px;">Пустое поле = без ограничений (∞)</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;">
      <div>
        <label>Кабинеты маркетплейсов</label>
        <input type="number" name="max_marketplace_accounts"
               value="{_num('max_marketplace_accounts', '1')}" min="1">
      </div>
      <div>
        <label>Заказов в месяц</label>
        <input type="number" name="max_orders_per_month"
               value="{_num('max_orders_per_month')}" min="0" placeholder="∞">
      </div>
      <div>
        <label>Товаров / SKU</label>
        <input type="number" name="max_products"
               value="{_num('max_products')}" min="0" placeholder="∞">
      </div>
      <div>
        <label>Пользователей / сотрудников</label>
        <input type="number" name="max_users"
               value="{_num('max_users')}" min="0" placeholder="∞">
      </div>
      <div>
        <label>Интервал синхронизации (мин)</label>
        <input type="number" name="sync_interval_minutes"
               value="{_num('sync_interval_minutes', '180')}" min="1">
      </div>
      <div>
        <label>Глубина аналитики (дней)</label>
        <input type="number" name="analytics_depth_days"
               value="{_num('analytics_depth_days', '30')}" min="1">
      </div>
    </div>
  </div>

  <div class="band">
    <h3>⚙ Доступные функции</h3>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:4px 24px;margin-top:12px;">
      {feature_cols}
    </div>
  </div>

  <div class="band">
    <h3>🔒 Административные настройки</h3>
    <div style="margin-top:10px;">
      <label>Внутренняя заметка (видна только администраторам)</label>
      <textarea name="internal_note" rows="3"
                placeholder="Для чего этот тариф, особые условия…">{_val('internal_note')}</textarea>
    </div>
  </div>

  <div style="display:flex;gap:8px;margin-top:4px;">
    <button type="submit" class="btn btn-primary">💾 Сохранить</button>
    <a class="btn" href="{back_url}">Отмена</a>
  </div>

</form>
</div>

<!-- ── Preview-карточка ───────────────────────────────────── -->
<div>
  <div class="band" style="position:sticky;top:72px;">
    <h3>👁 Предпросмотр</h3>
    <div id="tariff-preview-card" style="margin-top:12px;">
      {_preview_card_static(tariff)}
    </div>
    <div class="muted" style="font-size:11px;margin-top:8px;text-align:center;">
      Обновляется автоматически при изменении полей
    </div>
  </div>
</div>
</div>

{_inline_form_css()}
{preview_js}
"""


def _preview_card_static(tariff: SubscriptionTier | None) -> str:
    """Статическая preview-карточка для первичного рендера."""
    name = tariff.name if tariff else "Новый тариф"
    price = _rub(getattr(tariff, "price_monthly", None), zero_label="Бесплатно") if tariff else "—"
    badge = getattr(tariff, "badge_text", "") or ""
    featured = getattr(tariff, "is_featured", False) if tariff else False
    return _preview_card_html(name, price, badge, featured)


def _preview_card_html(name: str, price: str, badge: str, featured: bool) -> str:
    border = "border: 2px solid var(--accent);" if featured else ""
    badge_html = f'<div style="display:inline-block;background:var(--warning-soft);color:#92400e;border:1px solid var(--warning-border);border-radius:var(--radius-full);padding:2px 10px;font-size:11px;font-weight:700;margin-bottom:8px;">{_h(badge)}</div>' if badge else ""
    featured_star = '<div style="font-size:11px;font-weight:700;color:var(--accent);margin-bottom:4px;">★ Рекомендуемый</div>' if featured else ""
    return f"""
<div style="border:1px solid var(--border);{border}border-radius:var(--radius);padding:20px;background:var(--bg-card);box-shadow:var(--shadow-sm);text-align:center;">
  {featured_star}
  {badge_html}
  <div style="font-size:20px;font-weight:800;margin-bottom:6px;color:var(--text);" id="prev-display-name">{_h(name)}</div>
  <div style="font-size:28px;font-weight:800;color:var(--accent);line-height:1;" id="prev-display-price">{price}</div>
  <div style="color:var(--text-muted);font-size:12px;margin-top:4px;">/месяц</div>
  <div style="margin-top:16px;padding-top:16px;border-top:1px solid var(--border);">
    <a href="#" style="display:block;width:100%;text-align:center;background:linear-gradient(135deg,var(--accent),#1d4ed8);color:#fff;padding:10px;border-radius:var(--radius-sm);font-weight:700;font-size:14px;text-decoration:none;">Выбрать тариф</a>
  </div>
</div>"""


def _preview_card_js() -> str:
    """JavaScript для live-обновления preview-карточки."""
    return """
<script>
(function() {
  function updatePreview() {
    var name = document.querySelector('[name="name"]')?.value || 'Новый тариф';
    var priceRaw = parseFloat(document.querySelector('[name="price_monthly"]')?.value) || 0;
    var badge = document.querySelector('[name="badge_text"]')?.value || '';
    var featured = document.querySelector('[name="is_featured"]')?.checked || false;
    var custom = document.querySelector('[name="is_custom_price"]')?.checked || false;
    var active = document.querySelector('[name="is_active"]')?.checked !== false;

    var price = custom ? 'По запросу' : (priceRaw === 0 ? 'Бесплатно' : priceRaw.toLocaleString('ru-RU') + ' ₽');

    var card = document.getElementById('tariff-preview-card');
    if (!card) return;

    var featuredHtml = featured ? '<div style="font-size:11px;font-weight:700;color:var(--accent);margin-bottom:4px;">★ Рекомендуемый</div>' : '';
    var badgeHtml = badge ? '<div style="display:inline-block;background:var(--warning-soft);color:#92400e;border:1px solid var(--warning-border);border-radius:var(--radius-full);padding:2px 10px;font-size:11px;font-weight:700;margin-bottom:8px;">' + escHtml(badge) + '</div>' : '';
    var border = featured ? 'border: 2px solid var(--accent);' : '';
    var opacity = active ? '' : 'opacity:0.5;';

    card.innerHTML = '<div style="border:1px solid var(--border);' + border + 'border-radius:var(--radius);padding:20px;background:var(--bg-card);box-shadow:var(--shadow-sm);text-align:center;' + opacity + '">' +
      featuredHtml + badgeHtml +
      '<div style="font-size:20px;font-weight:800;margin-bottom:6px;color:var(--text);">' + escHtml(name) + '</div>' +
      '<div style="font-size:28px;font-weight:800;color:var(--accent);line-height:1;">' + price + '</div>' +
      '<div style="color:var(--text-muted);font-size:12px;margin-top:4px;">/месяц</div>' +
      '<div style="margin-top:16px;padding-top:16px;border-top:1px solid var(--border);">' +
        '<a href="#" style="display:block;width:100%;text-align:center;background:linear-gradient(135deg,var(--accent),#1d4ed8);color:#fff;padding:10px;border-radius:var(--radius-sm);font-weight:700;font-size:14px;text-decoration:none;">Выбрать тариф</a>' +
      '</div></div>';
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  document.addEventListener('DOMContentLoaded', function() {
    var form = document.getElementById('tariff-form');
    if (!form) return;
    form.addEventListener('input', updatePreview);
    form.addEventListener('change', updatePreview);
    updatePreview();
  });
})();
</script>"""


def _inline_form_css() -> str:
    """Дополнительный CSS для форм тарифа."""
    return """
<style>
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  text-transform: none;
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  letter-spacing: 0;
}
.checkbox-label input[type="checkbox"] {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  cursor: pointer;
}
.btn-warning {
  background: linear-gradient(135deg, var(--warning), #b45309);
  border-color: var(--warning);
  color: #fff;
}
.btn-warning:hover {
  background: linear-gradient(135deg, #b45309, #92400e);
  border-color: #b45309;
  box-shadow: 0 2px 6px rgb(217 119 6 / 0.3);
}
</style>"""


# ── Роуты создания / редактирования ──────────────────────────────────────────


@router.get("/admin/tariffs/new", response_class=HTMLResponse)
async def tariff_new_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    content = _tariff_form_html(action_url="/web/admin/tariffs/new", title="Создание тарифа")
    return _admin_page("Новый тариф", user, content)


@router.post("/admin/tariffs/new")
async def tariff_create(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    code: str = Form(""),
    name: str = Form(""),
    description: str = Form(""),
    price_monthly: str = Form("0"),
    price_3_months: str = Form(""),
    price_6_months: str = Form(""),
    price_yearly: str = Form(""),
    currency: str = Form("RUB"),
    max_marketplace_accounts: str = Form("1"),
    max_orders_per_month: str = Form(""),
    max_products: str = Form(""),
    max_users: str = Form(""),
    sync_interval_minutes: str = Form("180"),
    analytics_depth_days: str = Form("30"),
    sort_order: str = Form("0"),
    trial_days: str = Form(""),
    badge_text: str = Form(""),
    internal_note: str = Form(""),
    is_active: str = Form(""),
    is_public: str = Form(""),
    is_featured: str = Form(""),
    is_custom_price: str = Form(""),
    feature_web_cabinet: str = Form(""),
    feature_analytics: str = Form(""),
    feature_plan_fact: str = Form(""),
    feature_break_even: str = Form(""),
    feature_stock_forecast: str = Form(""),
    feature_alerts: str = Form(""),
    feature_api_access: str = Form(""),
    feature_priority_support: str = Form(""),
    feature_mrc_pricing: str = Form(""),
    feature_auto_promotions: str = Form(""),
    feature_telegram_notifications: str = Form(""),
) -> Any:
    _require_admin(user)
    service = TariffService(session)

    errors = _validate_form(code=code, name=name, price_monthly=price_monthly)
    if code.strip() and await service.code_exists(code.strip()):
        errors.append(f"Тариф с кодом «{code.strip()}» уже существует")

    if errors:
        return _admin_page("Ошибка", user, _error_html(errors, "/web/admin/tariffs/new"))

    data = _parse_form(
        code=code, name=name, description=description,
        price_monthly=price_monthly, price_3_months=price_3_months,
        price_6_months=price_6_months, price_yearly=price_yearly,
        currency=currency, max_marketplace_accounts=max_marketplace_accounts,
        max_orders_per_month=max_orders_per_month, max_products=max_products,
        max_users=max_users, sync_interval_minutes=sync_interval_minutes,
        analytics_depth_days=analytics_depth_days, sort_order=sort_order,
        trial_days=trial_days, badge_text=badge_text, internal_note=internal_note,
        is_active=is_active, is_public=is_public, is_featured=is_featured,
        is_custom_price=is_custom_price,
        feature_web_cabinet=feature_web_cabinet, feature_analytics=feature_analytics,
        feature_plan_fact=feature_plan_fact, feature_break_even=feature_break_even,
        feature_stock_forecast=feature_stock_forecast, feature_alerts=feature_alerts,
        feature_api_access=feature_api_access, feature_priority_support=feature_priority_support,
        feature_mrc_pricing=feature_mrc_pricing, feature_auto_promotions=feature_auto_promotions,
        feature_telegram_notifications=feature_telegram_notifications,
    )
    tariff = await service.create_tariff(**data)
    await session.commit()
    logger.info("admin_tariff_created", extra={"admin_id": user.id, "tariff_id": tariff.id, "code": tariff.code})
    return _flash_redirect("/web/admin/tariffs", "ok", f"Тариф «{tariff.name}» создан")


@router.get("/admin/tariffs/{tariff_id}/edit", response_class=HTMLResponse)
async def tariff_edit_page(
    tariff_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    service = TariffService(session)
    tariff = await service.get_tariff_by_id(tariff_id)
    if not tariff:
        raise HTTPException(status_code=404, detail="Тариф не найден")
    user_count = await service.get_tariff_user_count(tariff_id)
    content = _tariff_form_html(
        action_url=f"/web/admin/tariffs/{tariff_id}/edit",
        title=f"Редактирование: {tariff.name}",
        tariff=tariff,
        user_count=user_count,
    )
    return _admin_page(f"Тариф: {tariff.name}", user, content)


@router.post("/admin/tariffs/{tariff_id}/edit")
async def tariff_update(
    tariff_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    code: str = Form(""),
    name: str = Form(""),
    description: str = Form(""),
    price_monthly: str = Form("0"),
    price_3_months: str = Form(""),
    price_6_months: str = Form(""),
    price_yearly: str = Form(""),
    currency: str = Form("RUB"),
    max_marketplace_accounts: str = Form("1"),
    max_orders_per_month: str = Form(""),
    max_products: str = Form(""),
    max_users: str = Form(""),
    sync_interval_minutes: str = Form("180"),
    analytics_depth_days: str = Form("30"),
    sort_order: str = Form("0"),
    trial_days: str = Form(""),
    badge_text: str = Form(""),
    internal_note: str = Form(""),
    is_active: str = Form(""),
    is_public: str = Form(""),
    is_featured: str = Form(""),
    is_custom_price: str = Form(""),
    feature_web_cabinet: str = Form(""),
    feature_analytics: str = Form(""),
    feature_plan_fact: str = Form(""),
    feature_break_even: str = Form(""),
    feature_stock_forecast: str = Form(""),
    feature_alerts: str = Form(""),
    feature_api_access: str = Form(""),
    feature_priority_support: str = Form(""),
    feature_mrc_pricing: str = Form(""),
    feature_auto_promotions: str = Form(""),
    feature_telegram_notifications: str = Form(""),
) -> Any:
    _require_admin(user)
    service = TariffService(session)
    tariff = await service.get_tariff_by_id(tariff_id)
    if not tariff:
        raise HTTPException(status_code=404, detail="Тариф не найден")

    errors = _validate_form(code=code, name=name, price_monthly=price_monthly)
    new_code = code.strip()
    if new_code != tariff.code:
        if await service.code_exists(new_code, exclude_id=tariff_id):
            errors.append(f"Тариф с кодом «{new_code}» уже существует")
        if await service.has_active_subscribers(tariff_id):
            errors.append("Нельзя менять код тарифа, пока на нём есть активные пользователи")

    if errors:
        return _admin_page("Ошибка", user, _error_html(errors, f"/web/admin/tariffs/{tariff_id}/edit"))

    data = _parse_form(
        code=code, name=name, description=description,
        price_monthly=price_monthly, price_3_months=price_3_months,
        price_6_months=price_6_months, price_yearly=price_yearly,
        currency=currency, max_marketplace_accounts=max_marketplace_accounts,
        max_orders_per_month=max_orders_per_month, max_products=max_products,
        max_users=max_users, sync_interval_minutes=sync_interval_minutes,
        analytics_depth_days=analytics_depth_days, sort_order=sort_order,
        trial_days=trial_days, badge_text=badge_text, internal_note=internal_note,
        is_active=is_active, is_public=is_public, is_featured=is_featured,
        is_custom_price=is_custom_price,
        feature_web_cabinet=feature_web_cabinet, feature_analytics=feature_analytics,
        feature_plan_fact=feature_plan_fact, feature_break_even=feature_break_even,
        feature_stock_forecast=feature_stock_forecast, feature_alerts=feature_alerts,
        feature_api_access=feature_api_access, feature_priority_support=feature_priority_support,
        feature_mrc_pricing=feature_mrc_pricing, feature_auto_promotions=feature_auto_promotions,
        feature_telegram_notifications=feature_telegram_notifications,
    )
    await service.update_tariff(tariff_id, **data)
    await session.commit()
    logger.info("admin_tariff_updated", extra={"admin_id": user.id, "tariff_id": tariff_id})
    return _flash_redirect("/web/admin/tariffs", "ok", f"Тариф «{name.strip()}» обновлён")


# ── Действия над тарифом ──────────────────────────────────────────────────────


@router.post("/admin/tariffs/{tariff_id}/toggle")
async def tariff_toggle(
    tariff_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    service = TariffService(session)
    tariff = await service.toggle_tariff(tariff_id)
    if not tariff:
        raise HTTPException(status_code=404, detail="Тариф не найден")
    await session.commit()
    status = "активирован" if tariff.is_active else "отключён"
    return _flash_redirect("/web/admin/tariffs", "ok", f"Тариф «{tariff.name}» {status}")


@router.post("/admin/tariffs/{tariff_id}/toggle-public")
async def tariff_toggle_public(
    tariff_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    service = TariffService(session)
    tariff = await service.toggle_public(tariff_id)
    if not tariff:
        raise HTTPException(status_code=404, detail="Тариф не найден")
    await session.commit()
    vis = "опубликован" if tariff.is_public else "скрыт с витрины"
    return _flash_redirect("/web/admin/tariffs", "ok", f"Тариф «{tariff.name}» {vis}")


@router.post("/admin/tariffs/{tariff_id}/duplicate")
async def tariff_duplicate(
    tariff_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    service = TariffService(session)
    try:
        copy = await service.duplicate_tariff(tariff_id)
        await session.commit()
        logger.info("admin_tariff_duplicated", extra={"admin_id": user.id, "copy_id": copy.id})
        return _flash_redirect(f"/web/admin/tariffs/{copy.id}/edit", "ok", f"Тариф скопирован: {copy.name}")
    except ValueError as e:
        return _flash_redirect("/web/admin/tariffs", "err", str(e))


@router.post("/admin/tariffs/{tariff_id}/move")
async def tariff_move(
    tariff_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    direction: str = Form("up"),
) -> RedirectResponse:
    _require_admin(user)
    if direction not in ("up", "down"):
        raise HTTPException(status_code=400, detail="Направление должно быть 'up' или 'down'")
    service = TariffService(session)
    moved = await service.move_tariff(tariff_id, direction)
    if moved:
        await session.commit()
    return RedirectResponse(url="/web/admin/tariffs", status_code=303)


@router.post("/admin/tariffs/{tariff_id}/delete")
async def tariff_delete(
    tariff_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    service = TariffService(session)
    tariff = await service.get_tariff_by_id(tariff_id)
    if not tariff:
        raise HTTPException(status_code=404, detail="Тариф не найден")
    name = tariff.name
    try:
        await service.delete_tariff(tariff_id)
        await session.commit()
        logger.info("admin_tariff_deleted", extra={"admin_id": user.id, "tariff_id": tariff_id})
        return _flash_redirect("/web/admin/tariffs", "ok", f"Тариф «{name}» удалён")
    except ValueError as e:
        return _flash_redirect("/web/admin/tariffs", "err", str(e))


# ── Валидация и парсинг формы ─────────────────────────────────────────────────


def _validate_form(*, code: str, name: str, price_monthly: str) -> list[str]:
    errors: list[str] = []
    code = code.strip()
    if not code:
        errors.append("Код тарифа обязателен")
    elif not all(c.isalnum() or c in "_-" for c in code):
        errors.append("Код тарифа: только латиница, цифры, дефис и подчёркивание")
    if not name.strip():
        errors.append("Название тарифа обязательно")
    try:
        p = Decimal(price_monthly or "0")
        if p < 0:
            errors.append("Цена за месяц не может быть отрицательной")
    except (InvalidOperation, ValueError):
        errors.append("Некорректная цена за месяц")
    return errors


def _parse_dec(v: str) -> Decimal | None:
    v = v.strip()
    if not v:
        return None
    try:
        d = Decimal(v)
        return d if d >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def _parse_int(v: str, default: int | None = None) -> int | None:
    v = v.strip()
    if not v:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _parse_form(**kw: str) -> dict[str, Any]:
    return {
        "code": kw["code"].strip(),
        "name": kw["name"].strip(),
        "description": kw.get("description", "").strip() or None,
        "price_monthly": _parse_dec(kw.get("price_monthly", "0")) or Decimal("0"),
        "price_3_months": _parse_dec(kw.get("price_3_months", "")),
        "price_6_months": _parse_dec(kw.get("price_6_months", "")),
        "price_yearly": _parse_dec(kw.get("price_yearly", "")),
        "currency": kw.get("currency", "RUB").strip().upper() or "RUB",
        "max_marketplace_accounts": _parse_int(kw.get("max_marketplace_accounts", "1"), 1) or 1,
        "max_orders_per_month": _parse_int(kw.get("max_orders_per_month", "")),
        "max_products": _parse_int(kw.get("max_products", "")),
        "max_users": _parse_int(kw.get("max_users", "")),
        "sync_interval_minutes": _parse_int(kw.get("sync_interval_minutes", "180"), 180) or 180,
        "analytics_depth_days": _parse_int(kw.get("analytics_depth_days", "30"), 30) or 30,
        "sort_order": _parse_int(kw.get("sort_order", "0"), 0) or 0,
        "trial_days": _parse_int(kw.get("trial_days", "")),
        "badge_text": kw.get("badge_text", "").strip() or None,
        "internal_note": kw.get("internal_note", "").strip() or None,
        "is_active": kw.get("is_active", "") == "on",
        "is_public": kw.get("is_public", "") == "on",
        "is_featured": kw.get("is_featured", "") == "on",
        "is_custom_price": kw.get("is_custom_price", "") == "on",
        "feature_web_cabinet": kw.get("feature_web_cabinet", "") == "on",
        "feature_analytics": kw.get("feature_analytics", "") == "on",
        "feature_plan_fact": kw.get("feature_plan_fact", "") == "on",
        "feature_break_even": kw.get("feature_break_even", "") == "on",
        "feature_stock_forecast": kw.get("feature_stock_forecast", "") == "on",
        "feature_alerts": kw.get("feature_alerts", "") == "on",
        "feature_api_access": kw.get("feature_api_access", "") == "on",
        "feature_priority_support": kw.get("feature_priority_support", "") == "on",
        "feature_mrc_pricing": kw.get("feature_mrc_pricing", "") == "on",
        "feature_auto_promotions": kw.get("feature_auto_promotions", "") == "on",
        "feature_telegram_notifications": kw.get("feature_telegram_notifications", "") == "on",
    }


def _error_html(errors: list[str], back_url: str) -> str:
    items = "".join(f"<li style='margin-bottom:4px;'>{_h(e)}</li>" for e in errors)
    return f"""
<div class="error-state">
  <h2>Ошибки валидации</h2>
  <ul style="text-align:left;max-width:480px;margin:0 auto 16px;color:var(--text-secondary);font-size:13px;">
    {items}
  </ul>
  <a class="btn" href="{back_url}">← Вернуться и исправить</a>
</div>"""
