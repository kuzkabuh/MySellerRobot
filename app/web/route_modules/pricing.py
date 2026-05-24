"""Production WB pricing and promotions web section."""

# ruff: noqa: E501

import json
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    MarketplaceAccount,
    Product,
    User,
    WbAutoPromoPriceRecommendation,
    WbAutoPromotionCondition,
    WbPriceChangeHistory,
    WbProductPrice,
    WbPromotion,
    WbPromotionNomenclature,
)
from app.models.enums import Marketplace
from app.services.pricing.wb_auto_promo_condition_resolver import WbAutoPromoConditionResolver
from app.services.pricing.wb_auto_promo_import_service import WbAutoPromoImportService
from app.services.pricing.wb_auto_promo_participation_service import (
    WbAutoPromoParticipationService,
)
from app.services.pricing.wb_price_apply_service import WbPriceApplyService
from app.services.pricing.wb_price_sync_service import WbPriceSyncService
from app.services.pricing.wb_promotion_sync_service import WbPromotionSyncService
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, SESSION_DEPENDENCY
from app.web.rendering import page

router = APIRouter()
RECOMMENDATION_IDS_FORM = Form(default=[])
AUTO_PROMO_UPLOAD_FILE = File(...)


@dataclass(slots=True)
class PricingViewData:
    accounts: list[MarketplaceAccount]
    prices: list[WbProductPrice]
    products: list[Product]
    promotions: list[WbPromotion]
    conditions: list[WbAutoPromotionCondition]
    recommendations: list[WbAutoPromoPriceRecommendation]
    history: list[WbPriceChangeHistory]
    diagnostics: dict[str, Any]
    products_by_id: dict[int, Product]
    products_by_nm: dict[int, Product]
    promo_counts: dict[int, dict[str, int]]
    last_sync: str


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
    return RedirectResponse(url="/web/pricing?prices_synced=1#prices", status_code=303)


@router.post("/pricing/sync-promotions")
async def pricing_sync_promotions(session: AsyncSession = SESSION_DEPENDENCY) -> RedirectResponse:
    service = WbPromotionSyncService(session)
    acquired, _message = await service.try_acquire_sync_lock()
    if not acquired:
        return RedirectResponse(url="/web/pricing?sync_busy=1#promotions", status_code=303)
    try:
        await service.sync_all_accounts(all_promo=True)
        await session.commit()
    finally:
        await service.release_sync_lock()
    return RedirectResponse(url="/web/pricing?promotions_synced=1#promotions", status_code=303)


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
    return RedirectResponse(url=f"/web/pricing?conditions={total}#conditions", status_code=303)


@router.post("/pricing/upload-auto-promo-file")
async def pricing_upload_auto_promo_file(
    marketplace_account_id: int = Form(...),
    file: UploadFile = AUTO_PROMO_UPLOAD_FILE,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    account = await session.get(MarketplaceAccount, marketplace_account_id)
    if account is None or account.user_id != user.id or account.marketplace != Marketplace.WB:
        return RedirectResponse(url="/web/pricing?upload_error=account#recommendations", status_code=303)

    content = await file.read()
    original_filename = file.filename or "auto_promo.xlsx"
    suffix = Path(original_filename).suffix.lower()
    if suffix not in (".xlsx", ".xlsm", ".csv"):
        suffix = ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        import_service = WbAutoPromoImportService(session)
        _preview, rows = await import_service.create_preview(
            tmp_path,
            user.id,
            marketplace_account_id,
            original_file_name=original_filename,
        )
        saved = await import_service.apply_import(
            rows,
            user.id,
            marketplace_account_id,
        )
        recommendations = await WbAutoPromoParticipationService(
            session
        ).calculate_participation_recommendations(marketplace_account_id, commit=False)
        await session.commit()
        return RedirectResponse(
            url=(
                "/web/pricing?"
                f"uploaded={saved}&recommendations={len(recommendations)}#recommendations"
            ),
            status_code=303,
        )
    except ValueError as exc:
        await session.rollback()
        return RedirectResponse(
            url=f"/web/pricing?upload_error={quote(str(exc))}#recommendations",
            status_code=303,
        )
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass


@router.post("/pricing/build-recommendations")
async def pricing_build_recommendations(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    total = 0
    for account in await _wb_accounts(session, user.id):
        total += len(
            await WbAutoPromoParticipationService(
                session
            ).calculate_participation_recommendations(
                account.id,
            )
        )
    return RedirectResponse(url=f"/web/pricing?recommendations={total}#recommendations", status_code=303)


@router.post("/pricing/prepare-apply")
async def pricing_prepare_apply() -> RedirectResponse:
    return RedirectResponse(url="/web/pricing?prepared=1#recommendations", status_code=303)


@router.post("/pricing/apply")
async def pricing_apply_selected(
    recommendation_ids: list[int] = RECOMMENDATION_IDS_FORM,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> RedirectResponse:
    if not recommendation_ids:
        return RedirectResponse(url="/web/pricing?apply_empty=1#recommendations", status_code=303)

    recs = await session.execute(
        select(WbAutoPromoPriceRecommendation).where(
            WbAutoPromoPriceRecommendation.user_id == user.id,
            WbAutoPromoPriceRecommendation.id.in_(recommendation_ids),
            WbAutoPromoPriceRecommendation.status == "CAN_APPLY",
        )
    )
    by_account: dict[int, list[int]] = {}
    for rec in recs.scalars().all():
        by_account.setdefault(rec.marketplace_account_id, []).append(rec.id)

    applied = 0
    for account_id, rec_ids in by_account.items():
        account = await session.get(MarketplaceAccount, account_id)
        if account is None or account.user_id != user.id:
            continue
        result = await WbAutoPromoParticipationService(session).apply_recommendations(
            account_id,
            rec_ids,
            dry_run=False,
        )
        applied += len([row for row in result if row.get("payload")])
    return RedirectResponse(url=f"/web/pricing?applied={applied}#recommendations", status_code=303)


async def _load_pricing_data(session: AsyncSession, user_id: int) -> PricingViewData:
    accounts = await _wb_accounts(session, user_id)
    account_ids = [account.id for account in accounts]
    if not account_ids:
        return PricingViewData([], [], [], [], [], [], [], {}, {}, {}, {}, "нет данных")

    prices = list(
        (
            await session.execute(
                select(WbProductPrice)
                .where(WbProductPrice.marketplace_account_id.in_(account_ids))
                .order_by(WbProductPrice.synced_at.desc())
                .limit(250)
            )
        )
        .scalars()
        .all()
    )
    products = list(
        (
            await session.execute(
                select(Product)
                .where(
                    Product.user_id == user_id,
                    Product.marketplace == Marketplace.WB,
                    Product.marketplace_account_id.in_(account_ids),
                )
                .limit(500)
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
                .order_by(WbPromotion.is_active_today.desc(), WbPromotion.synced_at.desc())
                .limit(200)
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
                .limit(250)
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
                .limit(250)
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
                .limit(100)
            )
        )
        .scalars()
        .all()
    )

    products_by_id = {product.id: product for product in products}
    products_by_nm: dict[int, Product] = {}
    for product in products:
        nm_id = _extract_nm_id(product)
        if nm_id is not None:
            products_by_nm[nm_id] = product

    promo_counts = await _promotion_counts(session, account_ids)
    diagnostics = await _diagnostics(session, account_ids)
    last_sync_values = [
        value
        for value in [*(price.synced_at for price in prices), *(promo.synced_at for promo in promotions)]
        if value is not None
    ]
    last_sync = max(last_sync_values).strftime("%d.%m.%Y %H:%M") if last_sync_values else "нет данных"

    return PricingViewData(
        accounts=accounts,
        prices=prices,
        products=products,
        promotions=promotions,
        conditions=conditions,
        recommendations=recommendations,
        history=history,
        diagnostics=diagnostics,
        products_by_id=products_by_id,
        products_by_nm=products_by_nm,
        promo_counts=promo_counts,
        last_sync=last_sync,
    )


async def _wb_accounts(session: AsyncSession, user_id: int) -> list[MarketplaceAccount]:
    result = await session.execute(
        select(MarketplaceAccount).where(
            MarketplaceAccount.user_id == user_id,
            MarketplaceAccount.marketplace == Marketplace.WB,
            MarketplaceAccount.is_active.is_(True),
        )
    )
    return list(result.scalars().all())


async def _promotion_counts(session: AsyncSession, account_ids: list[int]) -> dict[int, dict[str, int]]:
    counts: dict[int, dict[str, int]] = defaultdict(lambda: {"products": 0, "conditions": 0, "recommendations": 0})
    nomenclatures = await session.execute(
        select(WbPromotionNomenclature.wb_promotion_id, func.count(WbPromotionNomenclature.id))
        .where(WbPromotionNomenclature.marketplace_account_id.in_(account_ids))
        .group_by(WbPromotionNomenclature.wb_promotion_id)
    )
    for promo_id, count in nomenclatures.all():
        counts[int(promo_id)]["products"] = int(count)

    conditions = await session.execute(
        select(WbAutoPromotionCondition.wb_promotion_id, func.count(WbAutoPromotionCondition.id))
        .where(WbAutoPromotionCondition.marketplace_account_id.in_(account_ids))
        .where(WbAutoPromotionCondition.wb_promotion_id.isnot(None))
        .group_by(WbAutoPromotionCondition.wb_promotion_id)
    )
    for promo_id, count in conditions.all():
        counts[int(promo_id)]["conditions"] = int(count)

    recommendations = await session.execute(
        select(WbAutoPromoPriceRecommendation.wb_promotion_id, func.count(WbAutoPromoPriceRecommendation.id))
        .where(WbAutoPromoPriceRecommendation.marketplace_account_id.in_(account_ids))
        .where(WbAutoPromoPriceRecommendation.wb_promotion_id.isnot(None))
        .group_by(WbAutoPromoPriceRecommendation.wb_promotion_id)
    )
    for promo_id, count in recommendations.all():
        counts[int(promo_id)]["recommendations"] = int(count)
    return counts


async def _diagnostics(session: AsyncSession, account_ids: list[int]) -> dict[str, Any]:
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
    active_promos = await session.scalar(
        select(func.count()).select_from(WbPromotion).where(
            WbPromotion.marketplace_account_id.in_(account_ids),
            WbPromotion.is_active_today.is_(True),
        )
    )
    errors = await session.execute(
        select(MarketplaceAccount.name, MarketplaceAccount.last_error_message)
        .where(MarketplaceAccount.id.in_(account_ids), MarketplaceAccount.last_error_message.isnot(None))
        .limit(5)
    )
    return {
        "auto_promos": auto_promos or 0,
        "details": details or 0,
        "conditions": conditions or 0,
        "required_found": found or 0,
        "required_missing": missing or 0,
        "active_promos": active_promos or 0,
        "errors": list(errors.all()),
    }


def _pricing_content(data: PricingViewData) -> str:
    return f"""
    <style>{_pricing_css()}</style>
    <div class="pricing-page">
      <section class="pricing-hero">
        <div>
          <p class="pricing-eyebrow">Wildberries pricing control</p>
          <h1>Цены и акции</h1>
          <p>Управление МРЦ, текущими ценами WB, акциями и рекомендациями для участия в автоакциях</p>
        </div>
        <div class="pricing-hero-actions">
          {_quick_action("/web/pricing/sync-prices", "Обновить цены WB", primary=True)}
          {_quick_action("/web/pricing/sync-promotions", "Синхронизировать акции")}
          {_quick_action("/web/pricing/resolve-conditions", "Найти условия автоакций")}
          {_quick_action("/web/pricing/build-recommendations", "Рассчитать участие в автоакциях")}
          <button class="pricing-button pricing-button-dark" type="submit" form="pricing-recommendations-form">Применить выбранные</button>
        </div>
      </section>
      {_kpi_grid(data)}
      {_tabs()}
      {_overview_section(data)}
      {_prices_section(data)}
      {_mrc_section(data)}
      {_promotions_section(data)}
      {_conditions_section(data)}
      {_recommendations_section(data)}
      {_history_section(data)}
      {_diagnostics_section(data)}
    </div>
    <script>{_pricing_js()}</script>
    """


def _quick_action(action: str, label: str, *, primary: bool = False) -> str:
    button_class = "pricing-button pricing-button-primary" if primary else "pricing-button"
    return (
        f'<form method="post" action="{escape(action)}">'
        f'<button class="{button_class}" type="submit">{escape(label)}</button>'
        "</form>"
    )


def _kpi_grid(data: PricingViewData) -> str:
    recommendations_to_apply = sum(1 for rec in data.recommendations if rec.status == "CAN_APPLY")
    blocked = sum(1 for rec in data.recommendations if rec.status in {"BLOCKED_BY_MRC", "BLOCKED_BY_MIN_PRICE"})
    active_promos = sum(1 for promo in data.promotions if promo.is_active_today)
    auto_promos = sum(1 for promo in data.promotions if promo.promotion_type == "auto")
    products_with_mrc = sum(1 for product in data.products if product.mrc_price is not None)
    required_found = sum(1 for condition in data.conditions if condition.required_price is not None)
    cards = [
        ("МР", products_with_mrc, "Товаров с МРЦ", "Готовы к проверке", "green"),
        ("WB", len(data.prices), "Текущих цен WB", "Из goods/filter", "blue"),
        ("АК", active_promos, "Активных акций", "Сейчас в календаре", "violet"),
        ("АВ", auto_promos, "Автоакций", "Вход через цену", "amber"),
        ("УС", required_found, "Найдено условий входа", "Из WB API", "green"),
        ("GO", recommendations_to_apply, "Рекомендаций к применению", "Можно отправить", "blue"),
        ("!", blocked, "Заблокировано по МРЦ/minPrice", "Требует внимания", "red"),
        ("↻", data.last_sync, "Последняя синхронизация", "Цены или акции", "slate"),
    ]
    return '<section class="pricing-kpi-grid">' + "".join(
        f"""
        <article class="pricing-card pricing-kpi pricing-accent-{accent}">
          <div class="pricing-kpi-icon">{escape(str(icon))}</div>
          <div>
            <strong>{escape(str(value))}</strong>
            <span>{escape(label)}</span>
            <small>{escape(status)}</small>
          </div>
        </article>
        """
        for icon, value, label, status, accent in cards
    ) + "</section>"


def _tabs() -> str:
    tabs = [
        ("overview", "Обзор"),
        ("prices", "Текущие цены"),
        ("mrc", "МРЦ"),
        ("promotions", "Акции WB"),
        ("conditions", "Условия автоакций"),
        ("recommendations", "Автоакции WB"),
        ("history", "История"),
        ("diagnostics", "Диагностика"),
    ]
    return '<nav class="pricing-tabs" aria-label="Навигация раздела">' + "".join(
        f'<a class="{"is-active" if idx == 0 else ""}" href="#{tab_id}" data-pricing-tab="{tab_id}">{escape(label)}</a>'
        for idx, (tab_id, label) in enumerate(tabs)
    ) + "</nav>"


def _overview_section(data: PricingViewData) -> str:
    steps = [
        ("Цены WB загружены", bool(data.prices), "/web/pricing/sync-prices"),
        ("Акции синхронизированы", bool(data.promotions), "/web/pricing/sync-promotions"),
        ("Условия автоакций найдены", any(c.required_price is not None for c in data.conditions), "/web/pricing/resolve-conditions"),
        ("Участие в автоакциях рассчитано", bool(data.recommendations), "/web/pricing/build-recommendations"),
        ("Цены готовы к применению", any(r.status == "CAN_APPLY" for r in data.recommendations), "/web/pricing/prepare-apply"),
    ]
    attention = _attention_items(data)
    return f"""
    <section id="overview" class="pricing-panel is-active">
      <div class="pricing-section-heading">
        <div><h2>Рабочий контур</h2><p>От синхронизации WB до безопасной отправки цены и скидки.</p></div>
      </div>
      <div class="pricing-overview-grid">
        <div class="pricing-card pricing-pipeline">
          {"".join(_pipeline_step(index + 1, title, done, action) for index, (title, done, action) in enumerate(steps))}
        </div>
        <div class="pricing-card">
          <h3>Что требует внимания</h3>
          {attention if attention else '<div class="pricing-empty-state compact"><strong>Критичных проблем не видно</strong><span>Сформируйте рекомендации после свежей синхронизации WB.</span></div>'}
        </div>
      </div>
    </section>
    """


def _pipeline_step(index: int, title: str, done: bool, action: str) -> str:
    status = "Готово" if done else "Ожидает"
    return f"""
    <form method="post" action="{escape(action)}" class="pricing-pipeline-step {'is-done' if done else ''}">
      <span>{index}</span>
      <div><strong>{escape(title)}</strong><small>{status}</small></div>
      <button type="submit">Запустить</button>
    </form>
    """


def _attention_items(data: PricingViewData) -> str:
    product_nm_ids = {_extract_nm_id(product) for product in data.products}
    price_nm_ids = {price.wb_nm_id for price in data.prices}
    no_current_price = len([nm_id for nm_id in product_nm_ids if nm_id and nm_id not in price_nm_ids])
    no_mrc = sum(1 for product in data.products if product.mrc_price is None)
    no_required = sum(1 for rec in data.recommendations if rec.status == "NO_AUTO_PROMO_PRICE")
    blocked_mrc = sum(1 for rec in data.recommendations if rec.status == "BLOCKED_BY_MRC")
    blocked_min = sum(1 for rec in data.recommendations if rec.status == "BLOCKED_BY_MIN_PRICE")
    quarantine = sum(
        1
        for rec in data.recommendations
        if rec.current_discounted_price
        and rec.recommended_discounted_price
        and rec.recommended_discounted_price <= rec.current_discounted_price / 3
    )
    items = [
        ("Нет текущей цены", no_current_price, "neutral"),
        ("Нет МРЦ", no_mrc, "warning"),
        ("WB не отдал цену входа", no_required, "warning"),
        ("Цена ниже допустимой МРЦ", blocked_mrc, "danger"),
        ("Цена ниже minPrice", blocked_min, "danger"),
        ("Возможен риск карантина WB", quarantine, "warning"),
    ]
    visible = [item for item in items if item[1] > 0]
    return '<div class="pricing-attention-list">' + "".join(
        f'<div class="pricing-attention {tone}"><strong>{count}</strong><span>{escape(label)}</span></div>'
        for label, count, tone in visible
    ) + "</div>"


def _prices_section(data: PricingViewData) -> str:
    if not data.prices:
        return _panel("prices", "Текущие цены WB", _empty_state("Цены WB ещё не загружены", "Обновить цены WB", "/web/pricing/sync-prices"))
    rows = "".join(
        f"<tr><td>{price.wb_nm_id}</td><td>{_money(price.price)}</td><td>{price.discount or 0}%</td><td>{_money(price.discounted_price)}</td><td>{_money(price.club_discounted_price)}</td><td>{_dt(price.synced_at)}</td></tr>"
        for price in data.prices
    )
    return _panel(
        "prices",
        "Текущие цены WB",
        f'<div class="pricing-table-wrap"><table class="pricing-table"><thead><tr><th>nmID</th><th>Полная цена</th><th>Скидка</th><th>Цена WB</th><th>Клубная цена</th><th>Обновлено</th></tr></thead><tbody>{rows}</tbody></table></div>',
    )


def _mrc_section(data: PricingViewData) -> str:
    products = [product for product in data.products if product.mrc_price is not None]
    if not products:
        return _panel("mrc", "МРЦ и ограничения", _empty_state("МРЦ пока не задана", "Открыть старый импорт МРЦ", "/web/mrc-pricing", method="get"))
    rows = "".join(
        f"<tr><td>{_product_title(product)}</td><td>{escape(str(_extract_nm_id(product) or ''))}</td><td>{_money(product.mrc_price)}</td><td>{escape(product.seller_article or '')}</td></tr>"
        for product in products
    )
    return _panel(
        "mrc",
        "МРЦ и ограничения",
        f'<div class="pricing-table-wrap"><table class="pricing-table"><thead><tr><th>Товар</th><th>nmID</th><th>МРЦ</th><th>Артикул</th></tr></thead><tbody>{rows}</tbody></table></div>',
    )


def _promotions_section(data: PricingViewData) -> str:
    if not data.promotions:
        return _panel("promotions", "Акции WB", _empty_state("Акции ещё не синхронизированы", "Синхронизировать акции", "/web/pricing/sync-promotions"))
    cards = "".join(_promotion_card(promo, data.promo_counts.get(promo.wb_promotion_id, {})) for promo in data.promotions)
    return _panel("promotions", "Акции WB", f'<div class="pricing-promo-grid">{cards}</div>')


def _promotion_card(promo: WbPromotion, counts: dict[str, int]) -> str:
    is_auto = promo.promotion_type == "auto"
    dates = f"{_dt(promo.start_datetime)} - {_dt(promo.end_datetime)}"
    return f"""
    <article class="pricing-card pricing-promo-card">
      <div class="pricing-promo-top">
        <div><h3>{escape(promo.name or 'Акция WB')}</h3><small>{escape(dates)}</small></div>
        {_badge("Автоакция" if is_auto else "Обычная", "violet" if is_auto else "blue")}
      </div>
      {'<p class="pricing-auto-note">Автоакция — товар попадает после изменения цены</p>' if is_auto else ''}
      <div class="pricing-mini-grid">
        <span><strong>{counts.get("products", 0)}</strong> товаров</span>
        <span><strong>{counts.get("conditions", 0)}</strong> условий</span>
        <span><strong>{counts.get("recommendations", 0)}</strong> рекомендаций</span>
      </div>
      <div class="pricing-card-footer">
        {_badge("Активна" if promo.is_active_today else "Не активна", "green" if promo.is_active_today else "gray")}
        <a class="pricing-link-button" href="#conditions" data-pricing-tab-link="conditions">Посмотреть условия</a>
      </div>
    </article>
    """


def _conditions_section(data: PricingViewData) -> str:
    if not data.conditions:
        return _panel("conditions", "Условия автоакций", _empty_state("Условия автоакций пока не найдены", "Найти условия автоакций", "/web/pricing/resolve-conditions"))
    rows = "".join(_condition_row(condition, data.products_by_nm.get(condition.wb_nm_id)) for condition in data.conditions)
    return _panel(
        "conditions",
        "Условия автоакций",
        f'<div class="pricing-table-wrap"><table class="pricing-table"><thead><tr><th>Акция</th><th>nmID</th><th>Товар</th><th>Цена входа</th><th>Текущая цена</th><th>Источник</th><th>Уверенность</th><th>Обновлено</th><th>raw payload</th></tr></thead><tbody>{rows}</tbody></table></div>',
    )


def _condition_row(condition: WbAutoPromotionCondition, product: Product | None) -> str:
    warning = ""
    if condition.required_price is None:
        warning = '<div class="pricing-warning">WB API не отдал цену входа. Откройте диагностику raw_payload.<br><button type="button">Задать вручную, если цена известна из кабинета WB</button></div>'
    return f"""
    <tr>
      <td>{escape(condition.promotion_name or '')}</td>
      <td>{condition.wb_nm_id}</td>
      <td>{_product_title(product)}</td>
      <td>{_money(condition.required_price)}{warning}</td>
      <td>{_money(condition.current_wb_price)}</td>
      <td>{escape(condition.source)}</td>
      <td>{_badge(condition.confidence, _confidence_tone(condition.confidence))}</td>
      <td>{_dt(condition.synced_at)}</td>
      <td><details><summary>Открыть</summary><pre class="pricing-code">{escape(_safe_json(condition.raw_payload))}</pre></details></td>
    </tr>
    """


def _recommendations_section(data: PricingViewData) -> str:
    upload_form = _auto_promo_upload_form(data.accounts)
    if not data.recommendations:
        return _panel(
            "recommendations",
            "Автоакции WB",
            upload_form
            + _empty_state(
                "Рекомендаций пока нет",
                "Рассчитать участие",
                "/web/pricing/build-recommendations",
            ),
        )

    promotion_options = sorted({rec.promotion_name for rec in data.recommendations if rec.promotion_name})
    filters = f"""
    <div class="pricing-action-bar">
      <input type="search" id="pricing-search" placeholder="Поиск по товару / артикулу / nmID">
      <select id="pricing-status-filter"><option value="">Все статусы</option>{''.join(f'<option value="{escape(status)}">{escape(_status_label(status))}</option>' for status in sorted({rec.status for rec in data.recommendations}))}</select>
      <select id="pricing-promo-filter"><option value="">Все акции</option>{''.join(f'<option value="{escape(name)}">{escape(name)}</option>' for name in promotion_options)}</select>
      <select id="pricing-sort"><option value="status">Сортировка: статус</option><option value="mrc">МРЦ</option><option value="recommended">Рекомендуемая цена</option><option value="updated">Дата обновления</option></select>
      <label><input type="checkbox" id="pricing-only-apply"> только можно применить</label>
      <label><input type="checkbox" id="pricing-only-problems"> только проблемы</label>
    </div>
    <div class="pricing-bulk-bar">
      <button type="button" data-bulk="select-available">Выбрать все доступные</button>
      <button type="button" data-bulk="prepare">Подготовить изменение цен</button>
      <button type="submit" class="primary">Применить выбранные</button>
      <button type="button" data-bulk="clear">Снять выделение</button>
      <span id="pricing-selected-count">Выбрано: 0</span>
    </div>
    """
    rows = "".join(_recommendation_pair(row, data.products_by_id.get(row.product_id)) for row in data.recommendations)
    table = f"""
    {upload_form}
    <form id="pricing-recommendations-form" method="post" action="/web/pricing/apply" data-apply-confirm="1">
      {filters}
      <div class="pricing-table-wrap">
        <table class="pricing-table pricing-recommendations-table">
          <thead><tr><th></th><th>Товар</th><th>Артикул</th><th>nmID</th><th>Акция</th><th>Плановая цена</th><th>Текущая полная</th><th>Текущая скидка</th><th>Текущая со скидкой</th><th>Загружаемая скидка WB</th><th>МРЦ</th><th>Мин. МРЦ</th><th>Рекомендуемая</th><th>Новая полная</th><th>Скидка отправки</th><th>Статус</th><th>Причина</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </form>
    """
    return _panel("recommendations", "Автоакции WB", table)


def _auto_promo_upload_form(accounts: list[MarketplaceAccount]) -> str:
    if not accounts:
        return ""
    options = "".join(
        f'<option value="{account.id}">{escape(account.name or f"WB #{account.id}")}</option>'
        for account in accounts
    )
    return f"""
    <form class="pricing-upload-form" method="post" action="/web/pricing/upload-auto-promo-file" enctype="multipart/form-data">
      <div>
        <strong>Файл WB по автоакции</strong>
        <small>Лист «Отчёт по скидкам»: плановая цена — цена входа, загружаемая скидка WB — диагностика.</small>
      </div>
      <select name="marketplace_account_id">{options}</select>
      <input type="file" name="file" accept=".xlsx,.xlsm,.csv" required>
      <button class="pricing-button pricing-button-primary" type="submit">Загрузить файл WB по автоакции</button>
    </form>
    """


def _recommendation_pair(row: WbAutoPromoPriceRecommendation, product: Product | None) -> str:
    payload_text = ""
    full_price = ""
    discount = ""
    checkbox = ""
    action = "Недоступно"
    if row.status == "CAN_APPLY" and row.recommended_discounted_price is not None:
        payload = WbPriceApplyService.build_payload(
            nm_id=row.wb_nm_id,
            recommended_price=row.recommended_discounted_price,
            discount=Decimal(str(row.recommended_discount or 75)),
            max_discounted_price=row.candidate_discounted_price or row.max_auto_promo_price,
        )
        payload_dict = payload.as_wb_item()
        payload_text = json.dumps(payload_dict, ensure_ascii=False, indent=2)
        full_price = str(payload.price)
        discount = f"{payload.discount}%"
        checkbox = f'<input class="pricing-rec-checkbox" type="checkbox" name="recommendation_ids" value="{row.id}">'
        action = "Готово к WB"
    searchable = " ".join(
        [
            str(row.wb_nm_id),
            product.title if product and product.title else "",
            product.seller_article if product and product.seller_article else "",
            row.promotion_name or "",
        ]
    )
    details = _recommendation_details(row, payload_text, full_price)
    problem = "1" if row.status in {"BLOCKED_BY_MRC", "BLOCKED_BY_MIN_PRICE", "NO_AUTO_PROMO_PRICE"} else "0"
    return f"""
    <tr class="pricing-rec-row" data-search="{escape(searchable.lower())}" data-status="{escape(row.status)}" data-promo="{escape(row.promotion_name or '')}" data-can-apply="{'1' if row.status == 'CAN_APPLY' else '0'}" data-problem="{problem}" data-mrc="{row.mrc_price}" data-recommended="{row.recommended_discounted_price or 0}" data-updated="{row.id}">
      <td>{checkbox}</td>
      <td>{_product_title(product)}</td>
      <td>{escape(product.seller_article or '') if product else ''}</td>
      <td>{row.wb_nm_id}</td>
      <td>{escape(row.promotion_name or '')}</td>
      <td>{_money(row.candidate_discounted_price or row.max_auto_promo_price or row.required_price)}</td>
      <td>{_money(row.current_full_price)}</td>
      <td>{row.current_discount or ''}%</td>
      <td>{_money(row.current_discounted_price or row.current_wb_price)}</td>
      <td>{row.wb_condition_discount_percent or ''}%</td>
      <td>{_money(row.mrc_price)}</td>
      <td>{_money(row.mrc_lower_bound)}</td>
      <td>{_money(row.recommended_discounted_price or row.recommended_price)}</td>
      <td>{_money(row.recommended_full_price) or escape(full_price)}</td>
      <td>{escape(discount)}</td>
      <td>{_status_badge(row.status)}</td>
      <td>{escape(row.reason or action)}</td>
    </tr>
    <tr class="pricing-rec-details"><td colspan="17"><details><summary>Подробнее</summary>{details}</details></td></tr>
    """


def _recommendation_details(row: WbAutoPromoPriceRecommendation, payload_text: str, full_price: str) -> str:
    discount_factor = "0.25"
    formula = ""
    if row.recommended_discounted_price is not None and full_price:
        formula = (
            f"Цена без скидки: {row.recommended_discounted_price} / "
            f"{discount_factor} = {full_price} ₽"
        )
    payload = payload_text or "Payload не формируется для заблокированной рекомендации."
    return f"""
    <div class="pricing-details-grid">
      <div>
        <h4>Формула расчёта</h4>
        <p>МРЦ: {_money(row.mrc_price)}<br>Допустимое снижение: по настройкам МРЦ<br>Минимальная цена: {_money(row.mrc_lower_bound)}<br>Тип условия: {escape(row.condition_type)}<br>Скидка в условии WB: {row.wb_condition_discount_percent or '-'}%<br>Цена условия WB: {_money(row.candidate_discounted_price or row.max_auto_promo_price or row.required_price)}<br>Рекомендуемая цена со скидкой: {_money(row.recommended_discounted_price or row.recommended_price)}<br>Скидка WB: {row.recommended_discount or 75}%<br>{escape(formula)}</p>
      </div>
      <div>
        <h4>Решение</h4>
        <p>{escape(row.reason or '')}</p>
        <p>Источник: {escape(row.source)}. Статус: {escape(row.status)}.</p>
      </div>
      <div>
        <h4>Payload WB</h4>
        <pre class="pricing-code">{escape(payload)}</pre>
      </div>
    </div>
    """


def _history_section(data: PricingViewData) -> str:
    if not data.history:
        return _panel("history", "История изменений цен", _empty_state("История изменений цен пока пустая", "Открыть рекомендации", "#recommendations", method="get"))
    rows = "".join(
        f"<tr><td>{row.wb_nm_id}</td><td>{_money(row.old_price)}</td><td>{_money(row.new_price)}</td><td>{row.wb_price or ''}</td><td>{row.wb_discount or ''}%</td><td>{_badge(row.status, _status_tone(row.status))}</td><td>{_dt(row.created_at)}</td></tr>"
        for row in data.history
    )
    return _panel(
        "history",
        "История изменений цен",
        f'<div class="pricing-table-wrap"><table class="pricing-table"><thead><tr><th>nmID</th><th>Было</th><th>Стало</th><th>WB price</th><th>Скидка</th><th>Статус</th><th>Дата</th></tr></thead><tbody>{rows}</tbody></table></div>',
    )


def _diagnostics_section(data: PricingViewData) -> str:
    diag = data.diagnostics
    errors = "".join(
        f"<li><strong>{escape(name or 'WB кабинет')}</strong>: {escape(message or '')}</li>"
        for name, message in diag.get("errors", [])
    )
    raw_blocks = "".join(_raw_payload_block(promo) for promo in data.promotions[:20] if promo.promotion_type == "auto")
    stats = [
        ("Найдено акций", len(data.promotions)),
        ("Автоакций", diag.get("auto_promos", 0)),
        ("details-ответов", diag.get("details", 0)),
        ("Найдено товаров/условий", diag.get("conditions", 0)),
        ("Найдено цен входа", diag.get("required_found", 0)),
        ("Без цены входа", diag.get("required_missing", 0)),
    ]
    return _panel(
        "diagnostics",
        "Диагностика WB API",
        f"""
        <div class="pricing-diagnostics">
          <div class="pricing-mini-grid">{''.join(f'<span><strong>{value}</strong>{escape(label)}</span>' for label, value in stats)}</div>
          <div class="pricing-card">{'<h3>Ошибки WB API</h3><ul>' + errors + '</ul>' if errors else '<h3>Ошибки WB API</h3><p>Последних ошибок по подключённым WB кабинетам нет.</p>'}</div>
          <div class="pricing-raw-list">{raw_blocks or _empty_state("Raw payload по автоакциям пока отсутствует", "Синхронизировать акции", "/web/pricing/sync-promotions")}</div>
        </div>
        """,
    )


def _raw_payload_block(promo: WbPromotion) -> str:
    code_id = f"raw-promo-{promo.wb_promotion_id}"
    return f"""
    <details class="pricing-raw-block">
      <summary>{escape(promo.name or 'Автоакция WB')} <span>#{promo.wb_promotion_id}</span></summary>
      <button type="button" class="pricing-copy-button" data-copy-target="{code_id}">Скопировать</button>
      <pre id="{code_id}" class="pricing-code">{escape(_safe_json(promo.raw_payload))}</pre>
    </details>
    """


def _panel(panel_id: str, title: str, body: str, *, active: bool = False) -> str:
    return f"""
    <section id="{panel_id}" class="pricing-panel {'is-active' if active else ''}">
      <div class="pricing-section-heading"><div><h2>{escape(title)}</h2></div></div>
      {body}
    </section>
    """


def _empty_state(title: str, button: str, action: str, *, method: str = "post") -> str:
    if method == "get":
        action_html = f'<a class="pricing-button pricing-button-primary" href="{escape(action)}">{escape(button)}</a>'
    else:
        action_html = f'<form method="post" action="{escape(action)}"><button class="pricing-button pricing-button-primary" type="submit">{escape(button)}</button></form>'
    return f'<div class="pricing-empty-state"><strong>{escape(title)}</strong><span>Запустите следующий шаг, чтобы наполнить раздел рабочими данными.</span>{action_html}</div>'


def _status_badge(status: str) -> str:
    return _badge(_status_label(status), _status_tone(status))


def _status_label(status: str) -> str:
    return {
        "CAN_APPLY": "Можно применить",
        "AUTO_PROMOTION_SET_PRICE": "Можно применить",
        "ALREADY_ELIGIBLE": "Уже подходит",
        "ALREADY_OK": "Уже подходит",
        "AUTO_PROMOTION_PRICE_OK": "Уже подходит",
        "BLOCKED_BY_MRC": "Ниже МРЦ",
        "AUTO_PROMOTION_PRICE_VIOLATION": "Ниже МРЦ",
        "BLOCKED_BY_MIN_PRICE": "Ниже minPrice",
        "AUTO_PROMOTION_MIN_PRICE_VIOLATION": "Ниже minPrice",
        "NO_AUTO_PROMO_PRICE": "Нет цены входа",
        "NO_CURRENT_PRICE": "Нет текущей цены",
        "NO_MRC_PRICE": "Нет МРЦ",
        "WAITING_WB_SYNC": "Ожидает WB",
        "AUTO_PROMOTION_REQUIRED_PRICE_UNKNOWN": "Нет цены входа",
        "AUTO_PROMOTION_WAITING_WB_SYNC": "Ожидает WB",
        "applied": "Применено",
        "failed": "Ошибка",
    }.get(status, status)


def _status_tone(status: str) -> str:
    if status in {"CAN_APPLY", "AUTO_PROMOTION_SET_PRICE", "applied"}:
        return "green"
    if status in {"ALREADY_ELIGIBLE", "ALREADY_OK", "AUTO_PROMOTION_PRICE_OK"}:
        return "blue"
    if status in {"BLOCKED_BY_MRC", "BLOCKED_BY_MIN_PRICE", "AUTO_PROMOTION_PRICE_VIOLATION", "AUTO_PROMOTION_MIN_PRICE_VIOLATION", "failed"}:
        return "red"
    if status in {"NO_AUTO_PROMO_PRICE", "NO_REQUIRED_PRICE", "AUTO_PROMOTION_REQUIRED_PRICE_UNKNOWN"}:
        return "amber"
    if status in {"WAITING_WB_SYNC", "AUTO_PROMOTION_WAITING_WB_SYNC"}:
        return "violet"
    return "gray"


def _confidence_tone(confidence: str | None) -> str:
    return {"high": "green", "medium": "amber", "low": "gray"}.get(confidence or "", "gray")


def _badge(label: str, tone: str) -> str:
    return f'<span class="pricing-badge pricing-badge-{escape(tone)}">{escape(label)}</span>'


def _product_title(product: Product | None) -> str:
    if product is None:
        return '<span class="pricing-muted">Товар не найден</span>'
    return escape(product.title or product.seller_article or product.marketplace_article or "Товар WB")


def _extract_nm_id(product: Product) -> int | None:
    for value in (product.external_product_id, product.marketplace_article):
        if value is None:
            continue
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            continue
    return None


def _money(value: object) -> str:
    if value is None:
        return ""
    return f"{escape(str(value))} ₽"


def _dt(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return escape(value.strftime("%d.%m.%Y %H:%M"))
    return escape(str(value))


def _safe_json(payload: object) -> str:
    sanitized = _sanitize_payload(payload)
    text = json.dumps(sanitized or {}, ensure_ascii=False, default=str, indent=2)
    return text[:6000]


def _sanitize_payload(value: object) -> object:
    if isinstance(value, dict):
        safe: dict[str, object] = {}
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(secret in lowered for secret in ("token", "key", "authorization", "cookie")):
                safe[str(key)] = "[hidden]"
            else:
                safe[str(key)] = _sanitize_payload(nested)
        return safe
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    return value


def _pricing_css() -> str:
    return """
    .pricing-page{display:flex;flex-direction:column;gap:24px;color:#0f172a}
    .pricing-hero{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;padding:30px;border-radius:24px;background:linear-gradient(135deg,#ffffff 0%,#f7fbff 58%,#eef7f2 100%);box-shadow:0 22px 70px rgba(15,23,42,.08);border:1px solid rgba(148,163,184,.18)}
    .pricing-hero h1{margin:0;font-size:34px;line-height:1.1;letter-spacing:0}
    .pricing-hero p{margin:10px 0 0;color:#475569;max-width:760px}
    .pricing-eyebrow{margin:0!important;text-transform:uppercase;font-size:12px;font-weight:800;letter-spacing:.08em;color:#0f766e}
    .pricing-hero-actions,.pricing-action-bar,.pricing-bulk-bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
    .pricing-button,.pricing-link-button,.pricing-bulk-bar button{border:1px solid #dbe3ef;background:#fff;color:#0f172a;border-radius:14px;padding:10px 14px;font-weight:700;text-decoration:none;cursor:pointer;box-shadow:0 8px 24px rgba(15,23,42,.06)}
    .pricing-button-primary,.pricing-bulk-bar button.primary{background:#0f766e;color:#fff;border-color:#0f766e}
    .pricing-button-dark{background:#0f172a;color:#fff;border-color:#0f172a}
    .pricing-kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}
    .pricing-card{background:#fff;border:1px solid #e2e8f0;border-radius:22px;box-shadow:0 18px 50px rgba(15,23,42,.07);padding:20px}
    .pricing-kpi{display:flex;gap:14px;align-items:center;min-height:112px;position:relative;overflow:hidden}
    .pricing-kpi:before{content:"";position:absolute;inset:0 auto 0 0;width:5px;background:#94a3b8}
    .pricing-kpi strong{display:block;font-size:28px;line-height:1;color:#0f172a}
    .pricing-kpi span{display:block;margin-top:6px;color:#334155;font-weight:700}
    .pricing-kpi small{display:block;margin-top:4px;color:#64748b}
    .pricing-kpi-icon{display:grid;place-items:center;width:42px;height:42px;border-radius:15px;background:#f1f5f9;font-weight:900}
    .pricing-accent-green:before{background:#10b981}.pricing-accent-blue:before{background:#2563eb}.pricing-accent-violet:before{background:#7c3aed}.pricing-accent-amber:before{background:#d97706}.pricing-accent-red:before{background:#dc2626}
    .pricing-tabs{display:flex;gap:8px;overflow:auto;padding:8px;background:#fff;border:1px solid #e2e8f0;border-radius:18px;box-shadow:0 10px 30px rgba(15,23,42,.05)}
    .pricing-tabs a{white-space:nowrap;text-decoration:none;color:#475569;padding:10px 14px;border-radius:13px;font-weight:800}
    .pricing-tabs a.is-active{background:#0f172a;color:#fff}
    .pricing-panel{display:none;scroll-margin-top:24px}
    .pricing-panel.is-active{display:block}
    .pricing-section-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
    .pricing-section-heading h2{margin:0;font-size:22px}
    .pricing-section-heading p{margin:4px 0 0;color:#64748b}
    .pricing-overview-grid{display:grid;grid-template-columns:1.1fr .9fr;gap:16px}
    .pricing-pipeline{display:flex;flex-direction:column;gap:12px}
    .pricing-pipeline-step{display:grid;grid-template-columns:38px 1fr auto;gap:12px;align-items:center;padding:12px;border-radius:16px;background:#f8fafc;border:1px solid #e2e8f0}
    .pricing-pipeline-step span{display:grid;place-items:center;width:34px;height:34px;border-radius:12px;background:#e2e8f0;font-weight:900}
    .pricing-pipeline-step.is-done span{background:#dcfce7;color:#047857}
    .pricing-pipeline-step strong,.pricing-pipeline-step small{display:block}.pricing-pipeline-step small{color:#64748b}
    .pricing-pipeline-step button{border:0;background:#fff;border-radius:12px;padding:8px 10px;font-weight:800;color:#0f766e}
    .pricing-attention-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
    .pricing-attention{padding:14px;border-radius:16px;background:#f8fafc;border:1px solid #e2e8f0}.pricing-attention strong{display:block;font-size:22px}.pricing-attention.danger{background:#fff1f2}.pricing-attention.warning{background:#fffbeb}
    .pricing-table-wrap{overflow:auto;background:#fff;border:1px solid #e2e8f0;border-radius:22px;box-shadow:0 18px 50px rgba(15,23,42,.06)}
    .pricing-table{width:100%;border-collapse:separate;border-spacing:0;min-width:980px}
    .pricing-table th{position:sticky;top:0;background:#f8fafc;color:#475569;text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.04em;padding:14px;border-bottom:1px solid #e2e8f0}
    .pricing-table td{padding:14px;border-bottom:1px solid #edf2f7;vertical-align:top}
    .pricing-table td small{display:block;color:#64748b;margin-top:4px}
    .pricing-badge{display:inline-flex;align-items:center;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:900}
    .pricing-badge-green{background:#dcfce7;color:#047857}.pricing-badge-blue{background:#dbeafe;color:#1d4ed8}.pricing-badge-red{background:#fee2e2;color:#b91c1c}.pricing-badge-amber{background:#fef3c7;color:#92400e}.pricing-badge-gray{background:#f1f5f9;color:#475569}.pricing-badge-violet{background:#ede9fe;color:#6d28d9}
    .pricing-action-bar{padding:14px;margin-bottom:12px;background:#fff;border:1px solid #e2e8f0;border-radius:20px}
    .pricing-action-bar input,.pricing-action-bar select{border:1px solid #dbe3ef;border-radius:12px;padding:10px 12px;background:#fff}
    .pricing-upload-form{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;padding:16px;margin-bottom:14px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:20px}
    .pricing-upload-form strong{display:block;color:#0f172a}
    .pricing-upload-form small{display:block;color:#64748b;margin-top:3px}
    .pricing-upload-form select,.pricing-upload-form input[type=file]{border:1px solid #dbe3ef;border-radius:12px;padding:10px 12px;background:#fff}
    .pricing-bulk-bar{padding:12px;margin-bottom:12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:18px}
    .pricing-empty-state{display:grid;gap:10px;justify-items:start;padding:28px;border-radius:22px;background:#fff;border:1px dashed #cbd5e1;color:#475569}.pricing-empty-state strong{font-size:18px;color:#0f172a}.pricing-empty-state.compact{padding:16px}
    .pricing-promo-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.pricing-promo-top,.pricing-card-footer{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.pricing-promo-card h3{margin:0}.pricing-auto-note{color:#6d28d9;background:#f5f3ff;padding:10px;border-radius:14px}
    .pricing-mini-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:16px 0}.pricing-mini-grid span{background:#f8fafc;border-radius:14px;padding:12px;color:#64748b}.pricing-mini-grid strong{display:block;color:#0f172a;font-size:20px}
    .pricing-rec-details td{background:#f8fafc}.pricing-details-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.pricing-details-grid h4{margin:0 0 8px}
    .pricing-rec-details summary{cursor:pointer;font-weight:900;color:#0f766e;margin-bottom:12px}
    .pricing-code{max-height:320px;overflow:auto;background:#0f172a;color:#e2e8f0;border-radius:16px;padding:14px;font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}
    .pricing-warning{margin-top:8px;padding:10px;border-radius:14px;background:#fffbeb;color:#92400e}.pricing-warning button{margin-top:8px;border:0;border-radius:10px;padding:7px 9px;background:#f59e0b;color:#fff;font-weight:800}
    .pricing-raw-block{position:relative;background:#fff;border:1px solid #e2e8f0;border-radius:18px;padding:14px;margin-top:12px}.pricing-copy-button{position:absolute;right:14px;top:12px;border:0;border-radius:10px;background:#e2e8f0;padding:7px 10px;font-weight:800}
    .pricing-muted{color:#94a3b8}
    @media (max-width:1100px){.pricing-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.pricing-overview-grid,.pricing-details-grid,.pricing-promo-grid{grid-template-columns:1fr}.pricing-hero{flex-direction:column}}
    @media (max-width:640px){.pricing-kpi-grid{grid-template-columns:1fr}.pricing-hero{padding:20px;border-radius:20px}.pricing-hero h1{font-size:28px}.pricing-hero-actions,.pricing-action-bar,.pricing-bulk-bar,.pricing-upload-form{flex-direction:column;align-items:stretch}.pricing-button,.pricing-action-bar input,.pricing-action-bar select,.pricing-upload-form select,.pricing-upload-form input{width:100%}.pricing-mini-grid,.pricing-attention-list{grid-template-columns:1fr}}
    """


def _pricing_js() -> str:
    return """
    (function(){
      const tabs=[...document.querySelectorAll('[data-pricing-tab]')];
      const panels=[...document.querySelectorAll('.pricing-panel')];
      function show(id){tabs.forEach(t=>t.classList.toggle('is-active',t.dataset.pricingTab===id));panels.forEach(p=>p.classList.toggle('is-active',p.id===id));}
      tabs.forEach(tab=>tab.addEventListener('click',function(e){e.preventDefault();show(tab.dataset.pricingTab);history.replaceState(null,'','#'+tab.dataset.pricingTab);}));
      document.querySelectorAll('[data-pricing-tab-link]').forEach(link=>link.addEventListener('click',function(e){e.preventDefault();show(link.dataset.pricingTabLink);}));
      if(location.hash){const id=location.hash.slice(1);if(document.getElementById(id))show(id);}
      const search=document.getElementById('pricing-search'), status=document.getElementById('pricing-status-filter'), promo=document.getElementById('pricing-promo-filter'), onlyApply=document.getElementById('pricing-only-apply'), onlyProblems=document.getElementById('pricing-only-problems'), sort=document.getElementById('pricing-sort');
      const rows=[...document.querySelectorAll('.pricing-rec-row')];
      function detailRow(row){return row.nextElementSibling && row.nextElementSibling.classList.contains('pricing-rec-details') ? row.nextElementSibling : null;}
      function applyFilters(){const q=(search?.value||'').toLowerCase();rows.forEach(row=>{let ok=true;if(q&&!row.dataset.search.includes(q))ok=false;if(status?.value&&row.dataset.status!==status.value)ok=false;if(promo?.value&&row.dataset.promo!==promo.value)ok=false;if(onlyApply?.checked&&row.dataset.canApply!=='1')ok=false;if(onlyProblems?.checked&&row.dataset.problem!=='1')ok=false;row.style.display=ok?'':'none';const d=detailRow(row);if(d)d.style.display=ok?'':'none';});}
      [search,status,promo,onlyApply,onlyProblems].forEach(el=>el&&el.addEventListener('input',applyFilters));
      sort&&sort.addEventListener('change',function(){const tbody=document.querySelector('.pricing-recommendations-table tbody');if(!tbody)return;const pairs=rows.map(r=>[r,detailRow(r)]);pairs.sort((a,b)=>String(a[0].dataset[sort.value]||'').localeCompare(String(b[0].dataset[sort.value]||''),undefined,{numeric:true}));pairs.forEach(([r,d])=>{tbody.appendChild(r);if(d)tbody.appendChild(d);});});
      function selected(){return [...document.querySelectorAll('.pricing-rec-checkbox:checked')];}
      function updateCount(){const node=document.getElementById('pricing-selected-count');if(node)node.textContent='Выбрано: '+selected().length;}
      document.addEventListener('change',e=>{if(e.target.classList&&e.target.classList.contains('pricing-rec-checkbox'))updateCount();});
      document.querySelector('[data-bulk="select-available"]')?.addEventListener('click',()=>{document.querySelectorAll('.pricing-rec-row[data-can-apply="1"] .pricing-rec-checkbox').forEach(c=>c.checked=true);updateCount();});
      document.querySelector('[data-bulk="clear"]')?.addEventListener('click',()=>{document.querySelectorAll('.pricing-rec-checkbox').forEach(c=>c.checked=false);updateCount();});
      document.querySelector('[data-bulk="prepare"]')?.addEventListener('click',()=>alert('Будет подготовлено '+selected().length+' товаров. Проверьте полную цену и скидку перед отправкой в WB.'));
      document.querySelector('[data-apply-confirm]')?.addEventListener('submit',function(e){const count=selected().length;if(!count){e.preventDefault();alert('Выберите рекомендации для применения.');return;}if(!confirm('Будет отправлено '+count+' товаров в WB. Проверьте полную цену и скидку.'))e.preventDefault();});
      document.querySelectorAll('[data-copy-target]').forEach(btn=>btn.addEventListener('click',()=>{const node=document.getElementById(btn.dataset.copyTarget);if(node)navigator.clipboard?.writeText(node.textContent||'');}));
      applyFilters();updateCount();
    })();
    """
