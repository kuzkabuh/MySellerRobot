"""version: 1.0.0
description: Admin web routes for subscription tariff management.
updated: 2026-05-31
"""

# ruff: noqa: E501

import logging
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User
from app.services.tariff_service import TARIFF_FEATURE_FIELDS, TariffService
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY, is_admin_user
from app.web.rendering import page

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_admin_user(user: User) -> bool:
    return is_admin_user(user)


def _require_admin(user: User) -> None:
    if not _is_admin_user(user):
        raise HTTPException(status_code=403, detail="Доступно только администраторам")


def _admin_page(
    title: str, user: User, content: str, active_path: str = "/web/admin/tariffs"
) -> str:
    return page(
        title,
        f"{user.first_name or user.username or 'admin'} (admin)",
        content,
        active_path=active_path,
    )


def _h(value: object) -> str:
    return escape(str(value), quote=True)


def _rub(amount: Decimal | None) -> str:
    if amount is None:
        return "—"
    int_part = int(amount)
    formatted = f"{int_part:,}".replace(",", " ")
    return f"{formatted} ₽"


@router.get("/admin/tariffs", response_class=HTMLResponse)
async def tariffs_list_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    service = TariffService(session)
    tariffs_with_counts = await service.get_all_tariffs_with_user_counts()

    rows = ""
    for tariff, user_count in tariffs_with_counts:
        status_badge = (
            '<span class="badge good">Активен</span>'
            if tariff.is_active
            else '<span class="badge bad">Отключён</span>'
        )
        public_badge = (
            '<span class="badge action">Публичный</span>'
            if tariff.is_public
            else '<span class="badge warn">Скрыт</span>'
        )
        toggle_label = "Отключить" if tariff.is_active else "Включить"
        toggle_btn_class = "btn-danger" if tariff.is_active else "btn-primary"

        rows += f"""
        <tr>
            <td><strong>{_h(tariff.sort_order)}</strong></td>
            <td>
                <a href="/web/admin/tariffs/{tariff.id}/edit"><strong>{_h(tariff.name)}</strong></a>
                <div class="muted">{_h(tariff.code)}</div>
            </td>
            <td class="num">{_rub(tariff.price_monthly)}</td>
            <td class="num">{_rub(tariff.price_yearly)}</td>
            <td>{status_badge} {public_badge}</td>
            <td class="num"><strong>{user_count}</strong></td>
            <td>
                <div style="display:flex;gap:6px;flex-wrap:wrap;">
                    <a class="btn btn-sm" href="/web/admin/tariffs/{tariff.id}/edit">Редактировать</a>
                    <form method="post" action="/web/admin/tariffs/{tariff.id}/toggle" style="display:inline;">
                        <button class="btn btn-sm {toggle_btn_class}" type="submit">{toggle_label}</button>
                    </form>
                </div>
            </td>
        </tr>"""

    content = f"""
    <div class="page-header">
        <div>
            <h2>Управление тарифами</h2>
            <div class="summary-strip">
                <span>Всего тарифов: <strong>{len(tariffs_with_counts)}</strong></span>
            </div>
        </div>
        <div class="page-actions">
            <a class="btn btn-primary" href="/web/admin/tariffs/new">+ Создать тариф</a>
        </div>
    </div>
    <div class="table-wrap">
        <table class="table">
            <thead>
                <tr>
                    <th>Порядок</th>
                    <th>Тариф</th>
                    <th class="num">Цена/мес</th>
                    <th class="num">Цена/год</th>
                    <th>Статус</th>
                    <th class="num">Пользователей</th>
                    <th>Действия</th>
                </tr>
            </thead>
            <tbody>
                {rows if rows else '<tr><td colspan="7"><div class="empty-state">Тарифы не найдены</div></td></tr>'}
            </tbody>
        </table>
    </div>
    """
    return _admin_page("Тарифы", user, content)


@router.get("/admin/tariffs/new", response_class=HTMLResponse)
async def tariff_new_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    content = _tariff_form_html(action_url="/web/admin/tariffs/new", title="Создание тарифа")
    return _admin_page("Новый тариф", user, content, active_path="/web/admin/tariffs")


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
    is_active: str = Form(""),
    is_public: str = Form(""),
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

    errors = _validate_tariff_form(
        code=code,
        name=name,
        price_monthly=price_monthly,
        max_marketplace_accounts=max_marketplace_accounts,
    )

    service = TariffService(session)
    if code.strip() and await service.code_exists(code.strip()):
        errors.append(f"Тариф с кодом «{code.strip()}» уже существует")

    if errors:
        error_html = "".join(f"<li>{_h(e)}</li>" for e in errors)
        content = f"""
        <div class="error-state">
            <h2>Ошибки валидации</h2>
            <ul style="text-align:left;max-width:480px;margin:0 auto 16px;">{error_html}</ul>
            <a class="btn" href="/web/admin/tariffs/new">Вернуться</a>
        </div>"""
        return _admin_page("Ошибка", user, content, active_path="/web/admin/tariffs")

    data = _parse_tariff_form(
        code=code,
        name=name,
        description=description,
        price_monthly=price_monthly,
        price_3_months=price_3_months,
        price_6_months=price_6_months,
        price_yearly=price_yearly,
        currency=currency,
        max_marketplace_accounts=max_marketplace_accounts,
        max_orders_per_month=max_orders_per_month,
        max_products=max_products,
        max_users=max_users,
        sync_interval_minutes=sync_interval_minutes,
        analytics_depth_days=analytics_depth_days,
        sort_order=sort_order,
        is_active=is_active,
        is_public=is_public,
        feature_web_cabinet=feature_web_cabinet,
        feature_analytics=feature_analytics,
        feature_plan_fact=feature_plan_fact,
        feature_break_even=feature_break_even,
        feature_stock_forecast=feature_stock_forecast,
        feature_alerts=feature_alerts,
        feature_api_access=feature_api_access,
        feature_priority_support=feature_priority_support,
        feature_mrc_pricing=feature_mrc_pricing,
        feature_auto_promotions=feature_auto_promotions,
        feature_telegram_notifications=feature_telegram_notifications,
    )

    tariff = await service.create_tariff(**data)
    await session.commit()

    logger.info(
        "admin_tariff_created",
        extra={
            "admin_user_id": user.id,
            "admin_telegram_id": user.telegram_id,
            "tariff_id": tariff.id,
            "tariff_code": tariff.code,
        },
    )
    return RedirectResponse(url="/web/admin/tariffs", status_code=303)


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
    return _admin_page(f"Тариф: {tariff.name}", user, content, active_path="/web/admin/tariffs")


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
    is_active: str = Form(""),
    is_public: str = Form(""),
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

    errors = _validate_tariff_form(
        code=code,
        name=name,
        price_monthly=price_monthly,
        max_marketplace_accounts=max_marketplace_accounts,
    )

    new_code = code.strip()
    if new_code != tariff.code:
        if await service.code_exists(new_code, exclude_id=tariff_id):
            errors.append(f"Тариф с кодом «{new_code}» уже существует")
        if await service.has_active_subscribers(tariff_id):
            errors.append("Нельзя менять код тарифа, пока на нём есть активные пользователи")

    if errors:
        error_html = "".join(f"<li>{_h(e)}</li>" for e in errors)
        content = f"""
        <div class="error-state">
            <h2>Ошибки валидации</h2>
            <ul style="text-align:left;max-width:480px;margin:0 auto 16px;">{error_html}</ul>
            <a class="btn" href="/web/admin/tariffs/{tariff_id}/edit">Вернуться</a>
        </div>"""
        return _admin_page("Ошибка", user, content, active_path="/web/admin/tariffs")

    data = _parse_tariff_form(
        code=code,
        name=name,
        description=description,
        price_monthly=price_monthly,
        price_3_months=price_3_months,
        price_6_months=price_6_months,
        price_yearly=price_yearly,
        currency=currency,
        max_marketplace_accounts=max_marketplace_accounts,
        max_orders_per_month=max_orders_per_month,
        max_products=max_products,
        max_users=max_users,
        sync_interval_minutes=sync_interval_minutes,
        analytics_depth_days=analytics_depth_days,
        sort_order=sort_order,
        is_active=is_active,
        is_public=is_public,
        feature_web_cabinet=feature_web_cabinet,
        feature_analytics=feature_analytics,
        feature_plan_fact=feature_plan_fact,
        feature_break_even=feature_break_even,
        feature_stock_forecast=feature_stock_forecast,
        feature_alerts=feature_alerts,
        feature_api_access=feature_api_access,
        feature_priority_support=feature_priority_support,
        feature_mrc_pricing=feature_mrc_pricing,
        feature_auto_promotions=feature_auto_promotions,
        feature_telegram_notifications=feature_telegram_notifications,
    )

    await service.update_tariff(tariff_id, **data)
    await session.commit()

    logger.info(
        "admin_tariff_updated",
        extra={
            "admin_user_id": user.id,
            "admin_telegram_id": user.telegram_id,
            "tariff_id": tariff_id,
            "tariff_code": tariff.code,
            "changed_fields": list(data.keys()),
        },
    )
    return RedirectResponse(url="/web/admin/tariffs", status_code=303)


@router.post("/admin/tariffs/{tariff_id}/toggle", response_class=HTMLResponse)
async def tariff_toggle(
    tariff_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    service = TariffService(session)
    tariff = await service.get_tariff_by_id(tariff_id)
    if not tariff:
        raise HTTPException(status_code=404, detail="Тариф не найден")

    await service.toggle_tariff(tariff_id)
    await session.commit()

    logger.info(
        "admin_tariff_toggled",
        extra={
            "admin_user_id": user.id,
            "admin_telegram_id": user.telegram_id,
            "tariff_id": tariff_id,
            "tariff_code": tariff.code,
            "is_active": tariff.is_active,
        },
    )
    return RedirectResponse(url="/web/admin/tariffs", status_code=303)


def _validate_tariff_form(
    *,
    code: str,
    name: str,
    price_monthly: str,
    max_marketplace_accounts: str,
) -> list[str]:
    errors: list[str] = []
    if not code.strip():
        errors.append("Код тарифа обязателен")
    if not name.strip():
        errors.append("Название тарифа обязательно")
    try:
        p = Decimal(price_monthly or "0")
        if p < 0:
            errors.append("Цена за месяц не может быть отрицательной")
    except (InvalidOperation, ValueError):
        errors.append("Некорректная цена за месяц")
    try:
        int(max_marketplace_accounts or "1")
    except (ValueError, TypeError):
        errors.append("Некорректный лимит аккаунтов")
    return errors


def _parse_decimal(value: str) -> Decimal | None:
    value = value.strip()
    if not value:
        return None
    try:
        d = Decimal(value)
        return d if d >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def _parse_int(value: str, default: int | None = None) -> int | None:
    value = value.strip()
    if not value:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _parse_tariff_form(**kwargs: str) -> dict[str, Any]:
    return {
        "code": kwargs["code"].strip(),
        "name": kwargs["name"].strip(),
        "description": kwargs.get("description", "").strip() or None,
        "price_monthly": _parse_decimal(kwargs.get("price_monthly", "0")) or Decimal("0"),
        "price_3_months": _parse_decimal(kwargs.get("price_3_months", "")),
        "price_6_months": _parse_decimal(kwargs.get("price_6_months", "")),
        "price_yearly": _parse_decimal(kwargs.get("price_yearly", "")),
        "currency": kwargs.get("currency", "RUB").strip() or "RUB",
        "max_marketplace_accounts": _parse_int(kwargs.get("max_marketplace_accounts", "1"), 1) or 1,
        "max_orders_per_month": _parse_int(kwargs.get("max_orders_per_month", "")),
        "max_products": _parse_int(kwargs.get("max_products", "")),
        "max_users": _parse_int(kwargs.get("max_users", "")),
        "sync_interval_minutes": _parse_int(kwargs.get("sync_interval_minutes", "180"), 180) or 180,
        "analytics_depth_days": _parse_int(kwargs.get("analytics_depth_days", "30"), 30) or 30,
        "sort_order": _parse_int(kwargs.get("sort_order", "0"), 0) or 0,
        "is_active": kwargs.get("is_active", "") == "on",
        "is_public": kwargs.get("is_public", "") == "on",
        "feature_web_cabinet": kwargs.get("feature_web_cabinet", "") == "on",
        "feature_analytics": kwargs.get("feature_analytics", "") == "on",
        "feature_plan_fact": kwargs.get("feature_plan_fact", "") == "on",
        "feature_break_even": kwargs.get("feature_break_even", "") == "on",
        "feature_stock_forecast": kwargs.get("feature_stock_forecast", "") == "on",
        "feature_alerts": kwargs.get("feature_alerts", "") == "on",
        "feature_api_access": kwargs.get("feature_api_access", "") == "on",
        "feature_priority_support": kwargs.get("feature_priority_support", "") == "on",
        "feature_mrc_pricing": kwargs.get("feature_mrc_pricing", "") == "on",
        "feature_auto_promotions": kwargs.get("feature_auto_promotions", "") == "on",
        "feature_telegram_notifications": kwargs.get("feature_telegram_notifications", "") == "on",
    }


def _tariff_form_html(
    *,
    action_url: str,
    title: str,
    tariff: Any = None,
    user_count: int = 0,
) -> str:
    def _val(field: str, default: str = "") -> str:
        if tariff is None:
            return default
        v = getattr(tariff, field, None)
        if v is None:
            return ""
        return _h(str(v))

    def _checked(field: str, default: bool = False) -> str:
        if tariff is None:
            return " checked" if default else ""
        return " checked" if getattr(tariff, field, default) else ""

    def _num_val(field: str, default: str = "") -> str:
        if tariff is None:
            return default
        v = getattr(tariff, field, None)
        if v is None:
            return ""
        return _h(str(v))

    code_readonly = ""
    code_warning = ""
    if tariff and user_count > 0:
        code_readonly = " readonly style='background:var(--bg-muted);'"
        code_warning = f'<div class="muted" style="margin-top:4px;">Код нельзя менять: {user_count} активных пользователей</div>'

    feature_checkboxes = ""
    for field, label in TARIFF_FEATURE_FIELDS:
        checked = _checked(field)
        feature_checkboxes += f"""
        <label style="display:flex;align-items:center;gap:8px;padding:6px 0;cursor:pointer;text-transform:none;font-size:13px;font-weight:500;color:var(--text);letter-spacing:0;">
            <input type="checkbox" name="{field}"{checked} style="width:auto;height:auto;">
            {_h(label)}
        </label>"""

    return f"""
    <div class="page-header">
        <div>
            <h2>{_h(title)}</h2>
        </div>
        <div class="page-actions">
            <a class="btn" href="/web/admin/tariffs">К списку тарифов</a>
        </div>
    </div>

    <form method="post" action="{action_url}">
        <div class="band">
            <h3>Основные параметры</h3>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:12px;">
                <div>
                    <label>Код тарифа *</label>
                    <input type="text" name="code" value="{_val("code")}" required{code_readonly}>
                    {code_warning}
                </div>
                <div>
                    <label>Название *</label>
                    <input type="text" name="name" value="{_val("name")}" required>
                </div>
                <div>
                    <label>Порядок отображения</label>
                    <input type="number" name="sort_order" value="{_num_val("sort_order", "0")}">
                </div>
                <div>
                    <label>Валюта</label>
                    <input type="text" name="currency" value="{_val("currency", "RUB")}">
                </div>
            </div>
            <div style="margin-top:12px;">
                <label>Описание</label>
                <textarea name="description" rows="3">{_val("description")}</textarea>
            </div>
            <div style="display:flex;gap:16px;margin-top:12px;">
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;text-transform:none;font-size:13px;font-weight:500;color:var(--text);letter-spacing:0;">
                    <input type="checkbox" name="is_active"{_checked("is_active", True)} style="width:auto;height:auto;">
                    Активен
                </label>
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;text-transform:none;font-size:13px;font-weight:500;color:var(--text);letter-spacing:0;">
                    <input type="checkbox" name="is_public"{_checked("is_public", True)} style="width:auto;height:auto;">
                    Публичный
                </label>
            </div>
        </div>

        <div class="band">
            <h3>Цены</h3>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:12px;">
                <div>
                    <label>Цена за месяц *</label>
                    <input type="number" name="price_monthly" value="{_num_val("price_monthly", "0")}" step="0.01" min="0">
                </div>
                <div>
                    <label>Цена за 3 месяца</label>
                    <input type="number" name="price_3_months" value="{_num_val("price_3_months")}" step="0.01" min="0">
                </div>
                <div>
                    <label>Цена за 6 месяцев</label>
                    <input type="number" name="price_6_months" value="{_num_val("price_6_months")}" step="0.01" min="0">
                </div>
                <div>
                    <label>Цена за год</label>
                    <input type="number" name="price_yearly" value="{_num_val("price_yearly")}" step="0.01" min="0">
                </div>
            </div>
        </div>

        <div class="band">
            <h3>Лимиты</h3>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:12px;">
                <div>
                    <label>Макс. кабинетов МП</label>
                    <input type="number" name="max_marketplace_accounts" value="{_num_val("max_marketplace_accounts", "1")}" min="1">
                </div>
                <div>
                    <label>Макс. заказов/мес</label>
                    <input type="number" name="max_orders_per_month" value="{_num_val("max_orders_per_month")}" min="0" placeholder="Без лимита">
                </div>
                <div>
                    <label>Макс. товаров</label>
                    <input type="number" name="max_products" value="{_num_val("max_products")}" min="0" placeholder="Без лимита">
                </div>
                <div>
                    <label>Макс. пользователей</label>
                    <input type="number" name="max_users" value="{_num_val("max_users")}" min="0" placeholder="Без лимита">
                </div>
                <div>
                    <label>Интервал синхронизации (мин)</label>
                    <input type="number" name="sync_interval_minutes" value="{_num_val("sync_interval_minutes", "180")}" min="1">
                </div>
                <div>
                    <label>Глубина аналитики (дней)</label>
                    <input type="number" name="analytics_depth_days" value="{_num_val("analytics_depth_days", "30")}" min="1">
                </div>
            </div>
        </div>

        <div class="band">
            <h3>Доступные функции</h3>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:4px 24px;margin-top:12px;">
                {feature_checkboxes}
            </div>
        </div>

        <div style="display:flex;gap:8px;margin-top:16px;">
            <button type="submit" class="btn btn-primary">Сохранить</button>
            <a class="btn" href="/web/admin/tariffs">Отмена</a>
        </div>
    </form>
    """
