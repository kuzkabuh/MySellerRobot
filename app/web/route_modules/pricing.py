"""Production WB pricing and promotions web section."""

# ruff: noqa: E501

import json
from decimal import Decimal
from html import escape

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.models.domain import (
    MarketplaceAccount,
    Product,
    User,
    WbAutoPromoPriceRecommendation,
    WbAutoPromotionCondition,
    WbPriceChangeHistory,
    WbProductPrice,
    WbPromotion,
)
from app.models.enums import Marketplace
from app.services.pricing.wb_auto_promo_condition_resolver import WbAutoPromoConditionResolver
from app.services.pricing.wb_price_apply_service import WbPriceApplyService
from app.services.pricing.wb_price_recommendation_service import WbPriceRecommendationService
from app.services.pricing.wb_price_sync_service import WbPriceSyncService
from app.services.pricing.wb_promotion_sync_service import WbPromotionSyncService
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.rendering import page

router = APIRouter()
RECOMMENDATION_IDS_FORM = Form(default=[])


@router.get("/pricing", response_class=HTMLResponse)
async def pricing_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> str:
    data = await _load_pricing_data(session, user.id)
    return page(
        "Цены и акции",
        user.first_name or user.username or str(user.telegram_id),
        _pricing_content(data),
        active_path="/web/pricing",
    )


@router.post("/pricing/sync-prices")
async def pricing_sync_prices(session: AsyncSession = SESSION_DEPENDENCY) -> RedirectResponse:
    await WbPriceSyncService(session).sync_all_accounts()
    await session.commit()
    return RedirectResponse(url="/web/pricing?prices_synced=1", status_code=303)


@router.post("/pricing/sync-promotions")
async def pricing_sync_promotions(session: AsyncSession = SESSION_DEPENDENCY) -> RedirectResponse:
    service = WbPromotionSyncService(session)
    acquired, _message = await service.try_acquire_sync_lock()
    if not acquired:
        return RedirectResponse(url="/web/pricing?sync_busy=1", status_code=303)
    try:
        await service.sync_all_accounts(all_promo=True)
        await session.commit()
    finally:
        await service.release_sync_lock()
    return RedirectResponse(url="/web/pricing?promotions_synced=1", status_code=303)


@router.post("/pricing/resolve-conditions")
async def pricing_resolve_conditions(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    accounts = await _wb_accounts(session, user.id)
    resolver = WbAutoPromoConditionResolver()
    total = 0
    for account in accounts:
        total += len(
            await resolver.resolve_for_account(
                session,
                user_id=user.id,
                marketplace_account_id=account.id,
            )
        )
    return RedirectResponse(url=f"/web/pricing?conditions={total}", status_code=303)


@router.post("/pricing/build-recommendations")
async def pricing_build_recommendations(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    total = 0
    for account in await _wb_accounts(session, user.id):
        total += len(
            await WbPriceRecommendationService(session).save_for_account(
                user_id=user.id,
                marketplace_account_id=account.id,
            )
        )
    return RedirectResponse(url=f"/web/pricing?recommendations={total}", status_code=303)


@router.post("/pricing/prepare-apply")
async def pricing_prepare_apply() -> RedirectResponse:
    return RedirectResponse(url="/web/pricing?prepared=1", status_code=303)


@router.post("/pricing/apply")
async def pricing_apply_selected(
    recommendation_ids: list[int] = RECOMMENDATION_IDS_FORM,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    if not recommendation_ids:
        return RedirectResponse(url="/web/pricing?apply_empty=1", status_code=303)

    recs = await session.execute(
        select(WbAutoPromoPriceRecommendation).where(
            WbAutoPromoPriceRecommendation.user_id == user.id,
            WbAutoPromoPriceRecommendation.id.in_(recommendation_ids),
        )
    )
    by_account: dict[int, list[int]] = {}
    for rec in recs.scalars().all():
        by_account.setdefault(rec.marketplace_account_id, []).append(rec.id)

    cipher = TokenCipher()
    applied = 0
    for account_id, rec_ids in by_account.items():
        account = await session.get(MarketplaceAccount, account_id)
        if account is None or account.user_id != user.id:
            continue
        api_key = cipher.decrypt(account.encrypted_api_key)
        result = await WbPriceApplyService(session).apply(
            wb_api_key=api_key,
            user_id=user.id,
            marketplace_account_id=account_id,
            recommendation_ids=rec_ids,
            discount=Decimal("75"),
            dry_run=False,
        )
        applied += len(result.get("items", []))
    await session.commit()
    return RedirectResponse(url=f"/web/pricing?applied={applied}", status_code=303)


async def _load_pricing_data(session: AsyncSession, user_id: int) -> dict:
    accounts = await _wb_accounts(session, user_id)
    account_ids = [account.id for account in accounts]
    if not account_ids:
        return {
            "accounts": [],
            "prices": [],
            "mrc_products": [],
            "promotions": [],
            "conditions": [],
            "recommendations": [],
            "history": [],
            "diagnostics": {},
        }

    prices = list(
        (
            await session.execute(
                select(WbProductPrice)
                .where(WbProductPrice.marketplace_account_id.in_(account_ids))
                .order_by(WbProductPrice.synced_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    mrc_products = list(
        (
            await session.execute(
                select(Product)
                .where(
                    Product.user_id == user_id,
                    Product.marketplace == Marketplace.WB,
                    Product.mrc_price.isnot(None),
                )
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    promotions = list(
        (
            await session.execute(
                select(WbPromotion)
                .where(WbPromotion.marketplace_account_id.in_(account_ids))
                .order_by(WbPromotion.synced_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    conditions = list(
        (
            await session.execute(
                select(WbAutoPromotionCondition)
                .where(WbAutoPromotionCondition.marketplace_account_id.in_(account_ids))
                .order_by(WbAutoPromotionCondition.synced_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    recommendations = list(
        (
            await session.execute(
                select(WbAutoPromoPriceRecommendation)
                .where(WbAutoPromoPriceRecommendation.marketplace_account_id.in_(account_ids))
                .order_by(WbAutoPromoPriceRecommendation.id.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    history = list(
        (
            await session.execute(
                select(WbPriceChangeHistory)
                .where(WbPriceChangeHistory.marketplace_account_id.in_(account_ids))
                .order_by(WbPriceChangeHistory.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    diagnostics = await _diagnostics(session, account_ids)
    return {
        "accounts": accounts,
        "prices": prices,
        "mrc_products": mrc_products,
        "promotions": promotions,
        "conditions": conditions,
        "recommendations": recommendations,
        "history": history,
        "diagnostics": diagnostics,
    }


async def _wb_accounts(session: AsyncSession, user_id: int) -> list[MarketplaceAccount]:
    result = await session.execute(
        select(MarketplaceAccount).where(
            MarketplaceAccount.user_id == user_id,
            MarketplaceAccount.marketplace == Marketplace.WB,
            MarketplaceAccount.is_active.is_(True),
        )
    )
    return list(result.scalars().all())


async def _diagnostics(session: AsyncSession, account_ids: list[int]) -> dict:
    auto_promos = await session.scalar(
        select(func.count()).select_from(WbPromotion).where(
            WbPromotion.marketplace_account_id.in_(account_ids),
            WbPromotion.promotion_type == "auto",
        )
    )
    details = await session.scalar(
        select(func.count()).select_from(WbPromotion).where(
            WbPromotion.marketplace_account_id.in_(account_ids),
            WbPromotion.promotion_type == "auto",
            WbPromotion.raw_payload["_details"].isnot(None),
        )
    )
    conditions = await session.scalar(
        select(func.count()).select_from(WbAutoPromotionCondition).where(
            WbAutoPromotionCondition.marketplace_account_id.in_(account_ids)
        )
    )
    found = await session.scalar(
        select(func.count()).select_from(WbAutoPromotionCondition).where(
            WbAutoPromotionCondition.marketplace_account_id.in_(account_ids),
            WbAutoPromotionCondition.required_price.isnot(None),
        )
    )
    missing = await session.scalar(
        select(func.count()).select_from(WbAutoPromotionCondition).where(
            WbAutoPromotionCondition.marketplace_account_id.in_(account_ids),
            WbAutoPromotionCondition.required_price.is_(None),
        )
    )
    return {
        "auto_promos": auto_promos or 0,
        "details": details or 0,
        "conditions": conditions or 0,
        "required_found": found or 0,
        "required_missing": missing or 0,
    }


def _pricing_content(data: dict) -> str:
    actions = """
    <div class="toolbar">
      <form method="post" action="/web/pricing/sync-prices"><button class="button primary">Обновить текущие цены WB</button></form>
      <form method="post" action="/web/pricing/sync-promotions"><button class="button">Синхронизировать акции WB</button></form>
      <form method="post" action="/web/pricing/resolve-conditions"><button class="button">Найти условия автоакций</button></form>
      <form method="post" action="/web/pricing/build-recommendations"><button class="button">Сформировать рекомендации</button></form>
      <form method="post" action="/web/pricing/prepare-apply"><button class="button">Подготовить применение</button></form>
    </div>
    """
    tabs = """
    <nav class="tabs">
      <a href="#prices">Текущие цены WB</a>
      <a href="#mrc">МРЦ и ограничения</a>
      <a href="#promotions">Акции WB</a>
      <a href="#conditions">Условия автоакций</a>
      <a href="#recommendations">Рекомендации</a>
      <a href="#history">История изменений цен</a>
      <a href="#diagnostics">Диагностика WB API</a>
    </nav>
    """
    return f"""
    <section class="page-header">
      <h1>Цены и акции</h1>
      <p>Автоматические рекомендации для автоакций WB на базе МРЦ, текущих цен и условий входа из WB API.</p>
    </section>
    {actions}
    {tabs}
    {_prices_section(data["prices"])}
    {_mrc_section(data["mrc_products"])}
    {_promotions_section(data["promotions"])}
    {_conditions_section(data["conditions"])}
    {_recommendations_section(data["recommendations"])}
    {_history_section(data["history"])}
    {_diagnostics_section(data)}
    """


def _prices_section(rows: list[WbProductPrice]) -> str:
    body = "".join(
        f"<tr><td>{row.wb_nm_id}</td><td>{_money(row.price)}</td><td>{row.discount or 0}%</td><td>{_money(row.discounted_price)}</td><td>{_money(row.club_discounted_price)}</td></tr>"
        for row in rows
    )
    return f"<section id='prices'><h2>Текущие цены WB</h2><table><thead><tr><th>nmID</th><th>Полная цена</th><th>Скидка</th><th>Цена со скидкой</th><th>Клубная цена</th></tr></thead><tbody>{body or _empty_row(5)}</tbody></table></section>"


def _mrc_section(rows: list[Product]) -> str:
    body = "".join(
        f"<tr><td>{escape(row.title or row.seller_article or 'Товар')}</td><td>{escape(row.external_product_id or '')}</td><td>{_money(row.mrc_price)}</td></tr>"
        for row in rows
    )
    return f"<section id='mrc'><h2>МРЦ и ограничения</h2><table><thead><tr><th>Товар</th><th>nmID</th><th>МРЦ</th></tr></thead><tbody>{body or _empty_row(3)}</tbody></table></section>"


def _promotions_section(rows: list[WbPromotion]) -> str:
    body = "".join(
        f"<tr><td>{row.wb_promotion_id}</td><td>{escape(row.name or '')}</td><td>{escape(row.promotion_type or '')}</td><td>{'да' if row.is_active_today else 'нет'}</td></tr>"
        for row in rows
    )
    return f"<section id='promotions'><h2>Акции WB</h2><table><thead><tr><th>ID</th><th>Название</th><th>Тип</th><th>Активна</th></tr></thead><tbody>{body or _empty_row(4)}</tbody></table></section>"


def _conditions_section(rows: list[WbAutoPromotionCondition]) -> str:
    body = "".join(
        f"<tr><td>{row.wb_nm_id}</td><td>{escape(row.promotion_name or '')}</td><td>{_money(row.required_price)}</td><td>{_money(row.current_wb_price)}</td><td>{escape(row.confidence)}</td><td>{escape(row.source)}</td></tr>"
        for row in rows
    )
    return f"<section id='conditions'><h2>Условия автоакций</h2><table><thead><tr><th>nmID</th><th>Акция</th><th>Цена входа</th><th>Текущая цена</th><th>Confidence</th><th>Источник</th></tr></thead><tbody>{body or _empty_row(6)}</tbody></table></section>"


def _recommendations_section(rows: list[WbAutoPromoPriceRecommendation]) -> str:
    body = "".join(_recommendation_row(row) for row in rows)
    return f"<section id='recommendations'><h2>Рекомендации</h2><form method='post' action='/web/pricing/apply'><table><thead><tr><th></th><th>nmID</th><th>МРЦ</th><th>Текущая цена WB</th><th>Цена входа</th><th>Низ/верх МРЦ</th><th>Рекомендуемая</th><th>Полная цена WB</th><th>Скидка</th><th>Статус</th><th>Причина</th></tr></thead><tbody>{body or _empty_row(11)}</tbody></table><p><button class='button primary'>Применить выбранные</button></p></form></section>"


def _recommendation_row(row: WbAutoPromoPriceRecommendation) -> str:
    full_price = ""
    discount = ""
    checked = ""
    if row.status == "CAN_APPLY" and row.recommended_price is not None:
        payload = WbPriceApplyService.build_payload(nm_id=row.wb_nm_id, recommended_price=row.recommended_price)
        full_price = str(payload.price)
        discount = str(payload.discount)
        checked = f"<input type='checkbox' name='recommendation_ids' value='{row.id}'>"
    bounds = f"{_money(row.mrc_lower_bound)} / {_money(row.mrc_upper_bound)}"
    return f"<tr><td>{checked}</td><td>{row.wb_nm_id}</td><td>{_money(row.mrc_price)}</td><td>{_money(row.current_wb_price)}</td><td>{_money(row.required_price)}</td><td>{bounds}</td><td>{_money(row.recommended_price)}</td><td>{full_price}</td><td>{discount}</td><td>{escape(row.status)}</td><td>{escape(row.reason or '')}</td></tr>"


def _history_section(rows: list[WbPriceChangeHistory]) -> str:
    body = "".join(
        f"<tr><td>{row.wb_nm_id}</td><td>{_money(row.old_price)}</td><td>{_money(row.new_price)}</td><td>{row.wb_price or ''}</td><td>{row.wb_discount or ''}</td><td>{escape(row.status)}</td></tr>"
        for row in rows
    )
    return f"<section id='history'><h2>История изменений цен</h2><table><thead><tr><th>nmID</th><th>Было</th><th>Стало</th><th>WB price</th><th>Скидка</th><th>Статус</th></tr></thead><tbody>{body or _empty_row(6)}</tbody></table></section>"


def _diagnostics_section(data: dict) -> str:
    diag = data["diagnostics"]
    raw_rows = []
    for promo in data["promotions"][:10]:
        if promo.promotion_type != "auto":
            continue
        raw_rows.append(
            f"<tr><td>{promo.wb_promotion_id}</td><td>{escape(promo.name or '')}</td><td><pre>{escape(_safe_json(promo.raw_payload))}</pre></td></tr>"
        )
    stats = f"<ul><li>Автоакции найдены: {diag.get('auto_promos', 0)}</li><li>Details получены: {diag.get('details', 0)}</li><li>Товаров/условий внутри details: {diag.get('conditions', 0)}</li><li>required_price найдено: {diag.get('required_found', 0)}</li><li>Не удалось определить: {diag.get('required_missing', 0)}</li></ul>"
    return f"<section id='diagnostics'><h2>Диагностика автоакций WB</h2>{stats}<p>Если WB API не отдал цену входа, рекомендация получит статус NO_REQUIRED_PRICE. Ручной ввод остаётся fallback: задайте цену вручную только если она известна из кабинета WB.</p><table><thead><tr><th>ID</th><th>Автоакция</th><th>raw_payload без токенов</th></tr></thead><tbody>{''.join(raw_rows) or _empty_row(3)}</tbody></table></section>"


def _money(value: object) -> str:
    if value is None:
        return ""
    return f"{value} ₽"


def _empty_row(colspan: int) -> str:
    return f"<tr><td colspan='{colspan}'>Нет данных</td></tr>"


def _safe_json(payload: object) -> str:
    if isinstance(payload, dict):
        payload = {
            key: value
            for key, value in payload.items()
            if "token" not in key.lower() and "key" not in key.lower()
        }
    text = json.dumps(payload or {}, ensure_ascii=False, default=str)
    return text[:2000]
