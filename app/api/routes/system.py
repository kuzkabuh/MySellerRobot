"""version: 1.0.0
description: System endpoints: health, landing, admin errors, legacy redirects, YooKassa webhook compat.
updated: 2026-06-10
"""

import asyncio
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session

router = APIRouter()


def _read_app_version() -> str:
    path = Path("VERSION")
    if not path.exists():
        return "0.0.0"
    return path.read_text(encoding="utf-8").strip() or "0.0.0"


def _read_errors_log() -> str:
    path = Path("logs/errors.log")
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")[-20_000:]


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    path = Path("logo.png")
    if await asyncio.to_thread(path.exists):
        return FileResponse(path, media_type="image/x-icon")
    return Response(status_code=204)


@router.get("/robots.txt", response_class=HTMLResponse, include_in_schema=False)
async def robots_txt() -> str:
    return "User-agent: *\nDisallow: /web/\nDisallow: /admin/\n"


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("select 1"))
    return {"status": "ok"}


@router.get("/logo.png")
async def logo() -> FileResponse:
    path = Path("logo.png")
    return FileResponse(path)


@router.get("/", response_class=HTMLResponse)
async def landing() -> Response:
    public_index = Path("public/index.html")
    if await asyncio.to_thread(public_index.exists):
        return FileResponse(public_index)
    return HTMLResponse(_landing_page())


@router.get("/admin/errors")
async def errors(
    x_admin_secret: str = Header(default=""),
    current_settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    import asyncio
    expected = current_settings.app_secret_key.get_secret_value()
    if x_admin_secret != expected:
        raise HTTPException(status_code=403, detail="Нет доступа")
    log = await asyncio.to_thread(_read_errors_log)
    return {"log": log}


@router.get("/web/payment/success")
async def redirect_payment_success(payment_id: str | None = None) -> RedirectResponse:
    """Redirect legacy /web/payment/success to /payment/success."""
    url = "/payment/success"
    if payment_id:
        url = f"/payment/success?payment_id={payment_id}"
    return RedirectResponse(url=url, status_code=301)


@router.get("/web/payment/cancel")
async def redirect_payment_cancel(payment_id: str | None = None) -> RedirectResponse:
    """Redirect legacy /web/payment/cancel to /payment/cancel."""
    url = "/payment/cancel"
    if payment_id:
        url = f"/payment/cancel?payment_id={payment_id}"
    return RedirectResponse(url=url, status_code=301)


@router.post("/web/webhooks/yookassa", include_in_schema=False)
async def yookassa_webhook_compat(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Accept YooKassa webhooks when a reverse proxy prepends /web upstream."""
    from app.api.webhooks import yookassa_webhook

    return await yookassa_webhook(request=request, session=session)


def _landing_page() -> str:
    return """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MP Control — управление Wildberries и Ozon</title>
  <style>
    body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;color:#111827;background:#f6f7f9}
    .wrap{max-width:1180px;margin:0 auto;padding:26px 18px}
    .hero{min-height:76vh;display:flex;flex-direction:column;justify-content:center;padding:42px 0 28px}
    .logo{width:86px;height:86px;object-fit:contain;margin-bottom:22px}
    h1{font-size:58px;line-height:1.02;margin:0 0 18px;letter-spacing:0}
    p{font-size:18px;line-height:1.65;color:#4b5563;max-width:760px}
    .cta{display:inline-flex;align-items:center;gap:10px;background:#111827;color:#fff;text-decoration:none;padding:14px 18px;border-radius:8px;font-weight:700;margin-top:8px}
    .preview{margin-top:40px;border:1px solid #d7dde5;border-radius:8px;background:#fff;overflow:hidden;box-shadow:0 18px 45px rgb(17 24 39 / .12)}
    .bar{height:38px;background:#223047;color:#cbd5e1;display:flex;align-items:center;gap:8px;padding:0 14px;font-size:13px}
    .dot{width:9px;height:9px;border-radius:50%;background:#ef4444}.dot:nth-child(2){background:#f59e0b}.dot:nth-child(3){background:#10b981}
    .dash{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;padding:18px;background:#f8fafc}
    .metric,.row{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:14px}
    .metric span,.row span{display:block;color:#6b7280;font-size:13px}.metric strong{font-size:24px}
    .rows{grid-column:1/-1;display:grid;grid-template-columns:1.2fr .8fr .8fr .8fr;gap:10px}
    .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:24px}
    .item{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:18px}
    h2{margin:0 0 10px;font-size:24px} h3{margin:0 0 8px;font-size:17px}
    @media(max-width:820px){.hero{min-height:auto;padding-top:28px}h1{font-size:40px}.dash,.grid,.rows{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <img class="logo" src="/logo.png" alt="MP Control">
      <h1>MP Control</h1>
      <p>Профессиональный сервис для продавцов Wildberries и Ozon: аналитика, Telegram-уведомления, отчёты, бэкапы, возвраты, план/факт и расчёт unit-экономики.</p>
      <a class="cta" href="https://t.me/mpcontrolrobot">Открыть Telegram-бота</a>
      <div class="preview" aria-label="WEB-кабинет MP Control">
        <div class="bar"><i class="dot"></i><i class="dot"></i><i class="dot"></i><span>WEB-кабинет продавца</span></div>
        <div class="dash">
          <div class="metric"><span>Выручка</span><strong>248 900 ₽</strong></div>
          <div class="metric"><span>Заказы</span><strong>137</strong></div>
          <div class="metric"><span>Прибыль</span><strong>62 400 ₽</strong></div>
          <div class="metric"><span>Остатки</span><strong>18 SKU</strong></div>
          <div class="rows">
            <div class="row"><span>WB и FBS</span><strong>Новый заказ</strong></div>
            <div class="row"><span>Ozon</span><strong>Выкупы</strong></div>
            <div class="row"><span>План/Факт</span><strong>+7%</strong></div>
            <div class="row"><span>Подписка</span><strong>2 месяца</strong></div>
          </div>
        </div>
      </div>
    </section>
    <section class="grid">
      <div class="item"><h3>Всё под контролем</h3><p>Мониторинг заказов в реальном времени, уведомления о выкупах, возвратах, отгрузках и изменении цены.</p></div>
      <div class="item"><h3>Две площадки</h3><p>Единая платформа для Wildberries и Ozon с полным циклом учёта unit-экономики в одном интерфейсе.</p></div>
      <div class="item"><h3>WEB-кабинет</h3><p>Дашборды, графики, остатки, план/факт, контроль цен и управление себестоимостью.</p></div>
    </section>
  </main>
</body>
</html>"""
