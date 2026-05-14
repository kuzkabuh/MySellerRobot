"""version: 1.0.0
description: FastAPI routes for web cabinet login, sessions, and base dashboard.
updated: 2026-05-14
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.domain import User
from app.repositories.web_auth import WebAuthRepository
from app.services.web_auth_service import WEB_SESSION_COOKIE, WebAuthService
from app.services.web_dashboard_service import WebDashboardService
from app.web.rendering import page

router = APIRouter(prefix="/web", tags=["web"])
SESSION_DEPENDENCY = Depends(get_session)


async def current_web_user(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> User:
    raw_session = request.cookies.get(WEB_SESSION_COOKIE)
    if not raw_session:
        raise HTTPException(status_code=401, detail="Требуется вход в web-кабинет")
    user = await WebAuthRepository(session).get_active_session_user(
        WebAuthService.hash_secret(raw_session)
    )
    await session.commit()
    if user is None:
        raise HTTPException(status_code=401, detail="Сессия истекла")
    return user


CURRENT_WEB_USER_DEPENDENCY = Depends(current_web_user)


@router.get("/login")
async def login(
    request: Request,
    token: str,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> Response:
    web_session = await WebAuthService(session).consume_login_token(
        token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    if web_session is None:
        await session.rollback()
        return HTMLResponse(
            "<h1>Ссылка недействительна</h1><p>Запросите новую ссылку в Telegram-боте.</p>",
            status_code=400,
        )
    await session.commit()
    response = RedirectResponse(url="/web/", status_code=303)
    response.set_cookie(
        WEB_SESSION_COOKIE,
        web_session.token,
        expires=web_session.expires_at,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    await WebAuthService(session).revoke_session(request.cookies.get(WEB_SESSION_COOKIE))
    await session.commit()
    response = RedirectResponse(url="/web/login-required", status_code=303)
    response.delete_cookie(WEB_SESSION_COOKIE)
    return response


@router.get("/login-required", response_class=HTMLResponse)
async def login_required() -> str:
    return (
        "<h1>Вход в web-кабинет</h1>"
        "<p>Откройте Telegram-бота и нажмите «🌐 Web-кабинет», чтобы получить новую ссылку.</p>"
    )


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    service = WebDashboardService(session)
    kpi = await service.today_kpi(user.id)
    actual_profit = await service.actual_profit_total(user.id)
    content = f"""
      <section class="kpi-grid">
        {_kpi("Выручка сегодня", _rub(kpi.revenue_today))}
        {_kpi("Заказы сегодня", str(kpi.orders_today))}
        {_kpi("Продажи сегодня", str(kpi.sales_today))}
        {_kpi("Плановая прибыль", _rub(kpi.estimated_profit_today))}
        {_kpi("Фактическая прибыль", _rub(actual_profit))}
        {_kpi("Возвраты", str(kpi.returns_today))}
        {_kpi("Средняя маржа", f"{kpi.average_margin_today:.2f}%")}
        {_kpi("Убыточные заказы", str(kpi.loss_orders_today))}
      </section>
      <section class="band">
        <h2>Пульс бизнеса</h2>
        <p class="muted">
          Это базовая версия web-кабинета. Данные уже берутся из общей БД бота,
          а следующие этапы добавят фильтры, графики, таблицы заказов и аналитику по товарам.
        </p>
      </section>
    """
    return page("Главная", user.first_name or user.username or str(user.telegram_id), content)


@router.get("/{section}", response_class=HTMLResponse)
async def placeholder(
    section: str,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> str:
    titles = {
        "orders": "Заказы",
        "profit": "Прибыль",
        "products": "Товары",
        "stocks": "Остатки",
        "analytics": "Аналитика",
        "control": "Контроль",
        "costs": "Себестоимость",
        "settings": "Настройки",
    }
    title = titles.get(section)
    if title is None:
        raise HTTPException(status_code=404, detail="Раздел не найден")
    content = (
        '<section class="band">'
        f"<h2>{title}</h2>"
        '<p class="muted">Раздел подготовлен в навигации и будет наполнен в следующих этапах.</p>'
        "</section>"
    )
    return page(title, user.first_name or user.username or str(user.telegram_id), content)


def _kpi(label: str, value: str) -> str:
    return f'<article class="kpi"><span>{label}</span><strong>{value}</strong></article>'


def _rub(value: Decimal) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")
