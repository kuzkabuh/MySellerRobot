"""version: 1.0.0
description: Admin web routes for promo code management.
updated: 2026-05-31
"""

# ruff: noqa: E501

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User
from app.models.enums import PromoType, PromoUsageStatus
from app.services.subscriptions.promo_code_service import PromoCodeService, PromoValidationError
from app.services.subscriptions.tariff_service import TariffService
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY, is_admin_user
from app.web.rendering import page

logger = logging.getLogger(__name__)
router = APIRouter()

_VALID_PERIODS = ["monthly", "3_months", "6_months", "yearly"]
_PERIOD_LABELS = {
    "monthly": "1 месяц",
    "3_months": "3 месяца",
    "6_months": "6 месяцев",
    "yearly": "1 год",
}
_PROMO_TYPE_LABELS = {
    PromoType.PERCENT_DISCOUNT: "Скидка в процентах",
    PromoType.FIXED_DISCOUNT: "Фиксированная скидка",
    PromoType.FREE_DAYS: "Бесплатные дни",
}


def _is_admin_user(user: User) -> bool:
    return is_admin_user(user)


def _require_admin(user: User) -> None:
    if not _is_admin_user(user):
        raise HTTPException(status_code=403, detail="Доступно только администраторам")


def _admin_page(
    title: str, user: User, content: str, active_path: str = "/web/admin/promocodes"
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


def _parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


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


@router.get("/admin/promocodes", response_class=HTMLResponse)
async def promo_list_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    service = PromoCodeService(session)
    promos = await service.get_all()

    rows = ""
    for promo in promos:
        status_badge = (
            '<span class="badge good">Активен</span>'
            if promo.is_active
            else '<span class="badge bad">Отключён</span>'
        )
        type_label = (
            _PROMO_TYPE_LABELS.get(promo.promo_type, promo.promo_type.value)
            if isinstance(promo.promo_type, PromoType)
            else str(promo.promo_type)
        )
        discount_info = ""
        if promo.promo_type == PromoType.PERCENT_DISCOUNT:
            discount_info = f"{promo.discount_percent}%"
        elif promo.promo_type == PromoType.FIXED_DISCOUNT:
            discount_info = _rub(promo.discount_amount)
        elif promo.promo_type == PromoType.FREE_DAYS:
            discount_info = f"{promo.free_days} дн."

        toggle_label = "Отключить" if promo.is_active else "Включить"
        toggle_btn_class = "btn-danger" if promo.is_active else "btn-primary"

        rows += f"""
        <tr>
            <td><code>{_h(promo.code)}</code></td>
            <td>{_h(promo.name)}</td>
            <td>{_h(type_label)}<br><span class="muted">{_h(discount_info)}</span></td>
            <td class="num">{promo.used_count}</td>
            <td>{status_badge}</td>
            <td>
                <div style="display:flex;gap:6px;flex-wrap:wrap;">
                    <a class="btn btn-sm" href="/web/admin/promocodes/{promo.id}/edit">Редактировать</a>
                    <a class="btn btn-sm" href="/web/admin/promocodes/{promo.id}/usages">Использования</a>
                    <form method="post" action="/web/admin/promocodes/{promo.id}/toggle" style="display:inline;">
                        <button class="btn btn-sm {toggle_btn_class}" type="submit">{toggle_label}</button>
                    </form>
                </div>
            </td>
        </tr>"""

    content = f"""
    <div class="page-header">
        <div>
            <h2>Управление промокодами</h2>
            <div class="summary-strip">
                <span>Всего промокодов: <strong>{len(promos)}</strong></span>
            </div>
        </div>
        <div class="page-actions">
            <a class="btn btn-primary" href="/web/admin/promocodes/new">+ Создать промокод</a>
        </div>
    </div>
    <div class="table-wrap">
        <table class="table">
            <thead>
                <tr>
                    <th>Код</th>
                    <th>Название</th>
                    <th>Тип / Скидка</th>
                    <th class="num">Использован</th>
                    <th>Статус</th>
                    <th>Действия</th>
                </tr>
            </thead>
            <tbody>
                {rows if rows else '<tr><td colspan="6"><div class="empty-state">Промокоды не найдены</div></td></tr>'}
            </tbody>
        </table>
    </div>
    """
    return _admin_page("Промокоды", user, content)


@router.get("/admin/promocodes/new", response_class=HTMLResponse)
async def promo_new_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    tariff_service = TariffService(session)
    tariffs = await tariff_service.get_all_tariffs()
    content = _promo_form_html(
        action_url="/web/admin/promocodes/new",
        title="Создание промокода",
        tariffs=tariffs,
    )
    return _admin_page("Новый промокод", user, content)


@router.post("/admin/promocodes/new")
async def promo_create(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    code: str = Form(""),
    name: str = Form(""),
    description: str = Form(""),
    promo_type: str = Form(PromoType.PERCENT_DISCOUNT),
    discount_percent: str = Form(""),
    discount_amount: str = Form(""),
    free_days: str = Form(""),
    starts_at: str = Form(""),
    expires_at: str = Form(""),
    max_uses_total: str = Form(""),
    max_uses_per_user: str = Form("1"),
    min_order_amount: str = Form(""),
    only_for_new_users: str = Form(""),
    is_active: str = Form("on"),
    tariff_ids: list[str] = Form(default_factory=list),  # noqa: B008
    periods: list[str] = Form(default_factory=list),  # noqa: B008
) -> Any:
    _require_admin(user)
    service = PromoCodeService(session)

    try:
        parsed_tariff_ids = [int(t) for t in tariff_ids if t.strip().isdigit()]
        parsed_periods = [p for p in periods if p in _VALID_PERIODS]

        promo = await service.create(
            code=code,
            name=name,
            description=description or None,
            promo_type=promo_type,
            discount_percent=_parse_int(discount_percent),
            discount_amount=_parse_decimal(discount_amount),
            free_days=_parse_int(free_days),
            is_active=is_active == "on",
            starts_at=_parse_datetime(starts_at),
            expires_at=_parse_datetime(expires_at),
            max_uses_total=_parse_int(max_uses_total),
            max_uses_per_user=_parse_int(max_uses_per_user, 1) or 1,
            min_order_amount=_parse_decimal(min_order_amount),
            only_for_new_users=only_for_new_users == "on",
            created_by_admin_id=user.id,
            tariff_ids=parsed_tariff_ids or None,
            periods=parsed_periods or None,
        )
        await session.commit()
        logger.info(
            "admin_promo_created",
            extra={
                "admin_user_id": user.id,
                "promo_code": promo.code,
            },
        )
    except PromoValidationError as e:
        error_content = f"""
        <div class="error-state">
            <h2>Ошибка</h2>
            <p>{_h(str(e))}</p>
            <a class="btn" href="/web/admin/promocodes/new">Вернуться</a>
        </div>"""
        return _admin_page("Ошибка", user, error_content)

    return RedirectResponse(url="/web/admin/promocodes", status_code=303)


@router.get("/admin/promocodes/{promo_id}/edit", response_class=HTMLResponse)
async def promo_edit_page(
    promo_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    service = PromoCodeService(session)
    promo = await service.get_by_id(promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Промокод не найден")

    tariff_service = TariffService(session)
    tariffs = await tariff_service.get_all_tariffs()
    content = _promo_form_html(
        action_url=f"/web/admin/promocodes/{promo_id}/edit",
        title=f"Редактирование: {promo.code}",
        promo=promo,
        tariffs=tariffs,
    )
    return _admin_page(f"Промокод: {promo.code}", user, content)


@router.post("/admin/promocodes/{promo_id}/edit")
async def promo_update(
    promo_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
    code: str = Form(""),
    name: str = Form(""),
    description: str = Form(""),
    promo_type: str = Form(PromoType.PERCENT_DISCOUNT),
    discount_percent: str = Form(""),
    discount_amount: str = Form(""),
    free_days: str = Form(""),
    starts_at: str = Form(""),
    expires_at: str = Form(""),
    max_uses_total: str = Form(""),
    max_uses_per_user: str = Form("1"),
    min_order_amount: str = Form(""),
    only_for_new_users: str = Form(""),
    is_active: str = Form("on"),
    tariff_ids: list[str] = Form(default_factory=list),  # noqa: B008
    periods: list[str] = Form(default_factory=list),  # noqa: B008
) -> Any:
    _require_admin(user)
    service = PromoCodeService(session)

    try:
        parsed_tariff_ids = [int(t) for t in tariff_ids if t.strip().isdigit()]
        parsed_periods = [p for p in periods if p in _VALID_PERIODS]

        await service.update(
            promo_id,
            code=code,
            name=name,
            description=description or None,
            promo_type=promo_type,
            discount_percent=_parse_int(discount_percent),
            discount_amount=_parse_decimal(discount_amount),
            free_days=_parse_int(free_days),
            is_active=is_active == "on",
            starts_at=_parse_datetime(starts_at),
            expires_at=_parse_datetime(expires_at),
            max_uses_total=_parse_int(max_uses_total),
            max_uses_per_user=_parse_int(max_uses_per_user, 1) or 1,
            min_order_amount=_parse_decimal(min_order_amount),
            only_for_new_users=only_for_new_users == "on",
            tariff_ids=parsed_tariff_ids,
            periods=parsed_periods,
        )
        await session.commit()
    except PromoValidationError as e:
        error_content = f"""
        <div class="error-state">
            <h2>Ошибка</h2>
            <p>{_h(str(e))}</p>
            <a class="btn" href="/web/admin/promocodes/{promo_id}/edit">Вернуться</a>
        </div>"""
        return _admin_page("Ошибка", user, error_content)

    return RedirectResponse(url="/web/admin/promocodes", status_code=303)


@router.post("/admin/promocodes/{promo_id}/toggle")
async def promo_toggle(
    promo_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    _require_admin(user)
    service = PromoCodeService(session)
    promo = await service.toggle(promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Промокод не найден")
    await session.commit()
    return RedirectResponse(url="/web/admin/promocodes", status_code=303)


@router.get("/admin/promocodes/{promo_id}/usages", response_class=HTMLResponse)
async def promo_usages_page(
    promo_id: int,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    _require_admin(user)
    service = PromoCodeService(session)
    promo = await service.get_by_id(promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Промокод не найден")

    usages = await service.get_usages(promo_id, limit=200)
    stats = await service.get_usage_stats(promo_id)

    rows = ""
    for u in usages:
        if u.status == PromoUsageStatus.APPLIED:
            status_badge = '<span class="badge good">Применён</span>'
        elif u.status == PromoUsageStatus.RESERVED:
            status_badge = '<span class="badge warn">Резерв</span>'
        elif u.status == PromoUsageStatus.CANCELLED:
            status_badge = '<span class="badge bad">Отменён</span>'
        else:
            status_badge = f'<span class="badge">{_h(u.status.value if isinstance(u.status, PromoUsageStatus) else u.status)}</span>'

        rows += f"""
        <tr>
            <td>{u.used_at.strftime("%d.%m.%Y %H:%M") if u.used_at else "—"}</td>
            <td>{u.user_id}</td>
            <td>{_h(u.period)}</td>
            <td class="num">{_rub(u.original_amount)}</td>
            <td class="num">{_rub(u.discount_amount)}</td>
            <td class="num"><strong>{_rub(u.final_amount)}</strong></td>
            <td>{status_badge}</td>
        </tr>"""

    content = f"""
    <div class="page-header">
        <div>
            <h2>Использования: <code>{_h(promo.code)}</code></h2>
            <div class="summary-strip">
                <span>Применён: <strong>{stats["total_uses"]}</strong> раз</span>
                <span>Общая скидка: <strong>{_rub(stats["total_discount"])}</strong></span>
            </div>
        </div>
        <div class="page-actions">
            <a class="btn" href="/web/admin/promocodes">К списку промокодов</a>
        </div>
    </div>
    <div class="table-wrap">
        <table class="table">
            <thead>
                <tr>
                    <th>Дата</th>
                    <th>User ID</th>
                    <th>Период</th>
                    <th class="num">Сумма</th>
                    <th class="num">Скидка</th>
                    <th class="num">Итого</th>
                    <th>Статус</th>
                </tr>
            </thead>
            <tbody>
                {rows if rows else '<tr><td colspan="7"><div class="empty-state">Использований нет</div></td></tr>'}
            </tbody>
        </table>
    </div>
    """
    return _admin_page(f"Использования: {promo.code}", user, content)


def _promo_form_html(
    *,
    action_url: str,
    title: str,
    promo: Any = None,
    tariffs: Any = None,
) -> str:
    def _val(field: str, default: str = "") -> str:
        if promo is None:
            return default
        v = getattr(promo, field, None)
        if v is None:
            return ""
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%dT%H:%M")
        return _h(str(v))

    def _checked(field: str, default: bool = False) -> str:
        if promo is None:
            return " checked" if default else ""
        return " checked" if getattr(promo, field, default) else ""

    def _selected_type(value: str) -> str:
        if promo is None:
            return " selected" if value == PromoType.PERCENT_DISCOUNT else ""
        return " selected" if promo.promo_type == value else ""

    existing_tariff_ids = set()
    if promo and promo.tariffs:
        existing_tariff_ids = {pt.tariff_id for pt in promo.tariffs}

    existing_periods = set()
    if promo and promo.periods:
        existing_periods = {pp.period for pp in promo.periods}

    tariff_checkboxes = ""
    if tariffs:
        for t in tariffs:
            checked = " checked" if t.id in existing_tariff_ids else ""
            tariff_checkboxes += f"""
            <label style="display:flex;align-items:center;gap:8px;padding:4px 0;cursor:pointer;text-transform:none;font-size:13px;font-weight:500;color:var(--text);letter-spacing:0;">
                <input type="checkbox" name="tariff_ids" value="{t.id}"{checked} style="width:auto;height:auto;">
                {_h(t.name)} ({_h(t.code)})
            </label>"""

    period_checkboxes = ""
    for p_code, p_label in _PERIOD_LABELS.items():
        checked = " checked" if p_code in existing_periods else ""
        period_checkboxes += f"""
        <label style="display:flex;align-items:center;gap:8px;padding:4px 0;cursor:pointer;text-transform:none;font-size:13px;font-weight:500;color:var(--text);letter-spacing:0;">
            <input type="checkbox" name="periods" value="{p_code}"{checked} style="width:auto;height:auto;">
            {_h(p_label)}
        </label>"""

    return f"""
    <div class="page-header">
        <div><h2>{_h(title)}</h2></div>
        <div class="page-actions">
            <a class="btn" href="/web/admin/promocodes">К списку промокодов</a>
        </div>
    </div>

    <form method="post" action="{action_url}">
        <div class="band">
            <h3>Основные параметры</h3>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:12px;">
                <div>
                    <label>Код промокода *</label>
                    <input type="text" name="code" value="{_val("code")}" required placeholder="START10">
                </div>
                <div>
                    <label>Название *</label>
                    <input type="text" name="name" value="{_val("name")}" required placeholder="Стартовая скидка">
                </div>
                <div>
                    <label>Тип промокода *</label>
                    <select name="promo_type">
                        <option value="percent_discount"{_selected_type("percent_discount")}>Скидка в процентах</option>
                        <option value="fixed_discount"{_selected_type("fixed_discount")}>Фиксированная скидка</option>
                        <option value="free_days"{_selected_type("free_days")}>Бесплатные дни</option>
                    </select>
                </div>
            </div>
            <div style="margin-top:12px;">
                <label>Описание</label>
                <textarea name="description" rows="2">{_val("description")}</textarea>
            </div>
            <div style="margin-top:12px;">
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;text-transform:none;font-size:13px;font-weight:500;color:var(--text);letter-spacing:0;">
                    <input type="checkbox" name="is_active"{_checked("is_active", True)} style="width:auto;height:auto;">
                    Активен
                </label>
            </div>
        </div>

        <div class="band">
            <h3>Параметры скидки</h3>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:12px;">
                <div>
                    <label>Процент скидки (1-100)</label>
                    <input type="number" name="discount_percent" value="{_val("discount_percent")}" min="1" max="100">
                </div>
                <div>
                    <label>Фиксированная скидка (₽)</label>
                    <input type="number" name="discount_amount" value="{_val("discount_amount")}" step="0.01" min="0">
                </div>
                <div>
                    <label>Бесплатные дни</label>
                    <input type="number" name="free_days" value="{_val("free_days")}" min="1">
                </div>
            </div>
        </div>

        <div class="band">
            <h3>Ограничения</h3>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:12px;">
                <div>
                    <label>Дата начала</label>
                    <input type="datetime-local" name="starts_at" value="{_val("starts_at")}">
                </div>
                <div>
                    <label>Дата окончания</label>
                    <input type="datetime-local" name="expires_at" value="{_val("expires_at")}">
                </div>
                <div>
                    <label>Макс. использований (всего)</label>
                    <input type="number" name="max_uses_total" value="{_val("max_uses_total")}" min="1" placeholder="Без лимита">
                </div>
                <div>
                    <label>Макс. на пользователя</label>
                    <input type="number" name="max_uses_per_user" value="{_val("max_uses_per_user", "1")}" min="1">
                </div>
                <div>
                    <label>Мин. сумма заказа (₽)</label>
                    <input type="number" name="min_order_amount" value="{_val("min_order_amount")}" step="0.01" min="0">
                </div>
            </div>
            <div style="margin-top:12px;">
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;text-transform:none;font-size:13px;font-weight:500;color:var(--text);letter-spacing:0;">
                    <input type="checkbox" name="only_for_new_users"{_checked("only_for_new_users")} style="width:auto;height:auto;">
                    Только для новых пользователей
                </label>
            </div>
        </div>

        <div class="band">
            <h3>Применимые тарифы</h3>
            <p class="muted">Если не выбрано — промокод действует на все тарифы.</p>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:4px 24px;margin-top:8px;">
                {tariff_checkboxes}
            </div>
        </div>

        <div class="band">
            <h3>Применимые периоды</h3>
            <p class="muted">Если не выбрано — промокод действует на все периоды.</p>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:4px 24px;margin-top:8px;">
                {period_checkboxes}
            </div>
        </div>

        <div style="display:flex;gap:8px;margin-top:16px;">
            <button type="submit" class="btn btn-primary">Сохранить</button>
            <a class="btn" href="/web/admin/promocodes">Отмена</a>
        </div>
    </form>
    """
