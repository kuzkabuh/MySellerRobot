"""Public payment return routes (no auth required).

These routes are reachable at /payment/success and /payment/cancel
so that YooKassa can redirect users here after payment without
requiring a WEB cabinet session.
"""
# ruff: noqa: E501

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.models.enums import PaymentStatus
from app.models.subscriptions import Payment
from app.services.payment_service import PaymentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payment", tags=["payment-public"])
PUBLIC_SESSION_DEPENDENCY = Depends(get_session)

_PERIOD_LABELS = {"monthly": "1 месяц", "yearly": "1 год"}


def _html(value: str) -> str:
    from html import escape as html_escape

    return html_escape(value, quote=False)


async def _fetch_payment_status_from_yookassa(
    payment: Payment,
    session: AsyncSession,
) -> dict[str, Any] | None:
    """Query YooKassa API for the current payment status."""
    try:
        settings = get_settings()
        from app.integrations.yookassa import YooKassaClient

        yk = YooKassaClient(
            shop_id=settings.yookassa_shop_id,
            secret_key=settings.yookassa_secret_key.get_secret_value(),
        )
        return await yk.get_payment(payment.provider_payment_id)
    except Exception:
        logger.exception(
            "payment_status_check_failed",
            extra={
                "payment_id": payment.id,
                "provider_payment_id": payment.provider_payment_id,
            },
        )
        return None


async def _reconcile_on_return(
    payment: Payment,
    session: AsyncSession,
) -> tuple[str, str | None]:
    """Check payment status via YooKassa and reconcile if needed.

    Returns (status_label, expires_at_formatted).
    """
    if payment.status == PaymentStatus.SUCCEEDED:
        tier_code = (payment.payment_metadata or {}).get("tier_code", "")
        period = (payment.payment_metadata or {}).get("period", "monthly")
        period_label = _PERIOD_LABELS.get(period, period)

        if payment.subscription:
            await session.refresh(payment.subscription, ["tier"])
            sub = payment.subscription
            tier_name = sub.tier.name if sub.tier else tier_code
            expires_at = sub.expires_at
            if expires_at:
                from datetime import datetime as _dt

                if expires_at > _dt.now(tz=__import__("datetime", fromlist=["UTC"]).UTC):
                    return (
                        "active",
                        f"{tier_name} / {period_label} — до {expires_at.strftime('%d.%m.%Y')}",
                    )
                return (
                    "expired",
                    f"{tier_name} / {period_label} — истёк {expires_at.strftime('%d.%m.%Y')}",
                )
        return "pending_activation", f"{tier_code} / {period_label}"

    yk_data = await _fetch_payment_status_from_yookassa(payment, session)
    if yk_data:
        yk_status = yk_data.get("status")
        logger.info(
            "payment_return_status_checked",
            extra={
                "payment_id": payment.id,
                "provider_payment_id": payment.provider_payment_id,
                "yookassa_status": yk_status,
                "local_status": payment.status.value,
            },
        )

        if yk_status == "succeeded" and payment.status == PaymentStatus.PENDING:
            payment_service = PaymentService(session)
            await payment_service.confirm_payment(
                payment.provider_payment_id,
                yookassa_data=yk_data,
                source="return_page",
            )
            await session.flush()

            tier_code = (payment.payment_metadata or {}).get("tier_code", "")
            period = (payment.payment_metadata or {}).get("period", "monthly")
            period_label = _PERIOD_LABELS.get(period, period)

            if payment.subscription:
                await session.refresh(payment.subscription, ["tier"])
                sub = payment.subscription
                tier_name = sub.tier.name if sub.tier else tier_code
                expires_at = sub.expires_at
                if expires_at:
                    return (
                        "active",
                        f"{tier_name} / {period_label} — до {expires_at.strftime('%d.%m.%Y')}",
                    )
            return "just_activated", f"{tier_code} / {period_label}"

        if yk_status in {"canceled", "cancelled"}:
            return "canceled", None

        if yk_status == "pending":
            return "pending", None

    if payment.status == PaymentStatus.PENDING:
        return "pending", None

    if payment.status == PaymentStatus.CANCELLED:
        return "canceled", None

    return "unknown", None


@router.get("/success", response_class=HTMLResponse)
async def payment_success(
    request: Request,
    session: AsyncSession = PUBLIC_SESSION_DEPENDENCY,
    payment_id: str | None = Query(default=None),
) -> HTMLResponse:
    """Public payment success page.

    If payment_id is provided, checks actual status via YooKassa API
    and reconciles if needed.
    """
    logger.info(
        "payment_return_success_opened",
        extra={
            "payment_id": payment_id,
            "remote_addr": request.client.host if request.client else None,
        },
    )

    status_label = "checking"
    status_detail: str | None = ""

    if payment_id:
        try:
            result = await session.execute(
                select(Payment).where(Payment.provider_payment_id == payment_id)
            )
            payment = result.scalar_one_or_none()

            if payment:
                status_label, status_detail = await _reconcile_on_return(payment, session)
                await session.commit()
            else:
                status_label = "unknown_payment"
                status_detail = "Платёж не найден в системе."
        except Exception:
            logger.exception("payment_return_reconciliation_error")
            status_label = "error"
            status_detail = "Не удалось проверить статус платежа."
    else:
        status_label = "no_payment_id"
        status_detail = "Платёж обрабатывается. Подписка будет активирована автоматически."

    safe_status_detail = _html(status_detail or "")

    status_blocks = {
        "active": (
            '<div class="icon">✅</div>'
            "<h1>Оплата подтверждена</h1>"
            f"<p>Подписка активирована: <strong>{safe_status_detail}</strong></p>"
            "<p>Вы можете вернуться в Telegram-бот для продолжения работы.</p>"
        ),
        "just_activated": (
            '<div class="icon">✅</div>'
            "<h1>Оплата подтверждена</h1>"
            f"<p>Подписка активирована: <strong>{safe_status_detail}</strong></p>"
            "<p>Вы можете вернуться в Telegram-бот для продолжения работы.</p>"
        ),
        "pending_activation": (
            '<div class="icon">⏳</div>'
            "<h1>Платёж подтверждён</h1>"
            f"<p>Подписка: <strong>{safe_status_detail}</strong></p>"
            "<p>Активация завершена. Вернитесь в Telegram-бот.</p>"
        ),
        "pending": (
            '<div class="icon">⏳</div>'
            "<h1>Платёж обрабатывается</h1>"
            "<p>Ожидание подтверждения от платёжной системы.</p>"
            "<p>Подписка будет активирована автоматически. "
            "Вернитесь в Telegram-бот через несколько минут.</p>"
        ),
        "canceled": (
            '<div class="icon">❌</div>'
            "<h1>Платёж отменён</h1>"
            "<p>Платёж был отменён. Подписка не активирована.</p>"
            "<p>Вы можете попробовать оплатить снова через Telegram-бот.</p>"
        ),
        "unknown_payment": (
            '<div class="icon">⚠️</div>'
            "<h1>Платёж не найден</h1>"
            f"<p>{safe_status_detail}</p>"
            "<p>Откройте Telegram-бот и проверьте статус подписки.</p>"
        ),
        "no_payment_id": (
            '<div class="icon">✅</div>'
            "<h1>Платёж принят</h1>"
            f"<p>{safe_status_detail}</p>"
            "<p>Подписка активируется автоматически после подтверждения платёжной системой.</p>"
            "<p><strong>Вернитесь в Telegram-бот</strong>, чтобы продолжить работу.</p>"
        ),
        "error": (
            '<div class="icon">⚠️</div>'
            "<h1>Ошибка проверки</h1>"
            f"<p>{safe_status_detail}</p>"
            "<p>Откройте Telegram-бот и проверьте статус подписки.</p>"
        ),
    }

    body_content = status_blocks.get(status_label, status_blocks["no_payment_id"])

    settings = get_settings()
    bot_url = (
        f"https://t.me/{settings.bot_username}"
        if hasattr(settings, "bot_username") and settings.bot_username
        else "https://t.me/mpcontrolrobot"
    )

    return HTMLResponse(
        f"""
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Оплата · MP Control</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    max-width: 560px; margin: 60px auto; padding: 20px; text-align: center;
                    color: #1f2937; background: #f9fafb;
                }}
                .card {{
                    background: #fff; border-radius: 16px; padding: 32px 24px;
                    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
                }}
                .icon {{ font-size: 56px; margin-bottom: 16px; }}
                h1 {{ color: #111827; margin: 0 0 12px; font-size: 24px; }}
                p {{ color: #4b5563; line-height: 1.6; margin: 0 0 8px; }}
                .btn {{
                    display: inline-block; margin-top: 20px; padding: 12px 24px;
                    background: #2563eb; color: #fff; text-decoration: none;
                    border-radius: 10px; font-weight: 600; font-size: 15px;
                }}
                .btn:hover {{ background: #1d4ed8; }}
            </style>
        </head>
        <body>
            <div class="card">
                {body_content}
                <a class="btn" href="{bot_url}" target="_blank" rel="noopener">Открыть Telegram-бот</a>
            </div>
        </body>
        </html>
        """,
        status_code=200,
    )


@router.get("/cancel", response_class=HTMLResponse)
async def payment_cancel(
    request: Request,
    session: AsyncSession = PUBLIC_SESSION_DEPENDENCY,
    payment_id: str | None = Query(default=None),
) -> HTMLResponse:
    """Public payment cancel page."""
    logger.info(
        "payment_return_cancel_opened",
        extra={
            "payment_id": payment_id,
            "remote_addr": request.client.host if request.client else None,
        },
    )

    if payment_id:
        try:
            result = await session.execute(
                select(Payment).where(Payment.provider_payment_id == payment_id)
            )
            payment = result.scalar_one_or_none()

            if payment and payment.status == PaymentStatus.PENDING:
                yk_data = await _fetch_payment_status_from_yookassa(payment, session)
                if yk_data:
                    yk_status = yk_data.get("status")
                    if yk_status in {"canceled", "cancelled"}:
                        payment.status = PaymentStatus.CANCELLED
                        await session.flush()
                        await session.commit()
                        logger.info(
                            "payment_return_marked_cancelled",
                            extra={
                                "payment_id": payment.id,
                                "provider_payment_id": payment.provider_payment_id,
                            },
                        )
                    elif yk_status == "succeeded":
                        payment_service = PaymentService(session)
                        await payment_service.confirm_payment(
                            payment.provider_payment_id,
                            yookassa_data=yk_data,
                            source="return_page",
                        )
                        await session.flush()
                        await session.commit()
                        settings = get_settings()
                        bot_url = (
                            f"https://t.me/{settings.bot_username}"
                            if hasattr(settings, "bot_username") and settings.bot_username
                            else "https://t.me/mpcontrolrobot"
                        )
                        return HTMLResponse(
                            f"""
                            <!DOCTYPE html>
                            <html lang="ru">
                            <head>
                                <meta charset="utf-8">
                                <meta name="viewport" content="width=device-width, initial-scale=1">
                                <title>Оплата подтверждена · MP Control</title>
                                <style>
                                    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 560px; margin: 60px auto; padding: 20px; text-align: center; color: #1f2937; background: #f9fafb; }}
                                    .card {{ background: #fff; border-radius: 16px; padding: 32px 24px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }}
                                    .icon {{ font-size: 56px; margin-bottom: 16px; }}
                                    h1 {{ color: #111827; margin: 0 0 12px; font-size: 24px; }}
                                    p {{ color: #4b5563; line-height: 1.6; margin: 0 0 8px; }}
                                    .btn {{ display: inline-block; margin-top: 20px; padding: 12px 24px; background: #2563eb; color: #fff; text-decoration: none; border-radius: 10px; font-weight: 600; font-size: 15px; }}
                                </style>
                            </head>
                            <body>
                                <div class="card">
                                    <div class="icon">✅</div>
                                    <h1>Оплата подтверждена</h1>
                                    <p>Платёж успешно обработан. Подписка активирована.</p>
                                    <a class="btn" href="{bot_url}" target="_blank" rel="noopener">Открыть Telegram-бот</a>
                                </div>
                            </body>
                            </html>
                            """,
                            status_code=200,
                        )
        except Exception:
            logger.exception("payment_return_cancel_reconciliation_error")

    settings = get_settings()
    bot_url = (
        f"https://t.me/{settings.bot_username}"
        if hasattr(settings, "bot_username") and settings.bot_username
        else "https://t.me/mpcontrolrobot"
    )

    return HTMLResponse(
        f"""
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Платёж отменён · MP Control</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 560px; margin: 60px auto; padding: 20px; text-align: center; color: #1f2937; background: #f9fafb; }}
                .card {{ background: #fff; border-radius: 16px; padding: 32px 24px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }}
                .icon {{ font-size: 56px; margin-bottom: 16px; }}
                h1 {{ color: #111827; margin: 0 0 12px; font-size: 24px; }}
                p {{ color: #4b5563; line-height: 1.6; margin: 0 0 8px; }}
                .btn {{ display: inline-block; margin-top: 20px; padding: 12px 24px; background: #2563eb; color: #fff; text-decoration: none; border-radius: 10px; font-weight: 600; font-size: 15px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="icon">❌</div>
                <h1>Платёж отменён</h1>
                <p>Вы отменили платёж на странице ЮKassa. Подписка не активирована.</p>
                <p>Вы можете попробовать оплатить снова через Telegram-бот.</p>
                <a class="btn" href="{bot_url}" target="_blank" rel="noopener">Открыть Telegram-бот</a>
            </div>
        </body>
        </html>
        """,
        status_code=200,
    )
