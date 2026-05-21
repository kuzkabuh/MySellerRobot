"""version: 1.2.0
description: Telegram bot handlers for MRC pricing and WB promotions management.
    Includes safe_edit_text helper to handle "message is not modified" errors gracefully.
    All handlers have try/except and always call callback.answer().
updated: 2026-05-21
"""

import logging
from decimal import Decimal, InvalidOperation
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message
from sqlalchemy import or_, select

from app.bot.keyboards.main import (
    mrc_back_menu,
    mrc_menu,
    mrc_product_card_keyboard,
    web_cabinet_link,
)
from app.bot.states import MrcStates
from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.core.security import TokenCipher
from app.models.domain import MarketplaceAccount, Product, WbPromotion, WbPromotionNomenclature
from app.models.enums import Marketplace
from app.repositories.users import UserRepository
from app.services.feature_access_service import FeatureAccessService, FeatureCode
from app.services.pricing.wb_mrc_price_service import WbMrcPriceService
from app.services.wb.wb_promotions_sync_service import WbPromotionsSyncService
from app.utils.datetime import format_datetime_for_user

logger = logging.getLogger(__name__)
router = Router(name="mrc_pricing")

settings = get_settings()


async def safe_edit_text(
    message,
    text: str,
    reply_markup=None,
    parse_mode: str | None = "HTML",
) -> None:
    """Edit message text, ignoring 'message is not modified' errors."""
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.debug("message_not_modified: %s", e)
        else:
            raise


async def _get_user_id_from_message(message: Message) -> int | None:
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        await session.commit()
        return user.id


async def _get_user_id_from_callback(callback: CallbackQuery) -> int | None:
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        await session.commit()
        return user.id


async def _check_mrc_access(user_id: int) -> tuple[bool, str | None]:
    """Check if user has access to MRC feature. Returns (allowed, error_message)."""
    async with AsyncSessionFactory() as session:
        access = await FeatureAccessService(session).can_use_feature(
            user_id, FeatureCode.MRC_PRICING
        )
        if not access.allowed:
            msg = (
                f"🔒 {access.reason}\n\n"
                f"Для управления МРЦ и акциями WB нужен тариф: <b>{access.required_plan}</b>"
            )
            return False, msg
        return True, None


@router.callback_query(F.data == "mrc_menu")
async def mrc_menu_handler(callback: CallbackQuery) -> None:
    """Главное меню МРЦ и акций WB."""
    try:
        user_id = await _get_user_id_from_callback(callback)
        if user_id is None:
            await callback.answer()
            return

        allowed, error_msg = await _check_mrc_access(user_id)
        if not allowed:
            await safe_edit_text(callback.message, error_msg, reply_markup=mrc_back_menu())
            await callback.answer()
            return

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Product.id, Product.mrc_price)
                .join(MarketplaceAccount, MarketplaceAccount.id == Product.marketplace_account_id)
                .where(Product.user_id == user_id)
                .where(Product.marketplace == Marketplace.WB)
                .where(Product.is_active.is_(True))
            )
            rows = result.all()
            total = len(rows)
            with_mrc = sum(1 for _, mrc in rows if mrc and mrc > 0)
            without_mrc = total - with_mrc

        logger.info(
            "mrc_pricing_menu_opened",
            extra={
                "user_id": user_id,
                "tier_code": "pro",
                "products_with_mrc_count": with_mrc,
                "active_promotions_count": 0,
                "source": "bot",
            },
        )

        text = (
            "💰 <b>МРЦ и акции Wildberries</b>\n\n"
            "МРЦ — это целевая цена товара со скидкой на Wildberries.\n"
            "Цена продавца до скидки рассчитывается автоматически: <b>МРЦ × 4</b>.\n\n"
            f"📦 Всего товаров WB: <b>{total}</b>\n"
            f"✅ С заполненной МРЦ: <b>{with_mrc}</b>\n"
            f"⚠️ Без МРЦ: <b>{without_mrc}</b>\n\n"
            "Выберите действие:"
        )
        await safe_edit_text(callback.message, text, reply_markup=mrc_menu(), parse_mode="HTML")
    except Exception:
        logger.exception("mrc_pricing_bot_menu_failed", extra={"user_id": callback.from_user.id})
        await safe_edit_text(
            callback.message,
            "Не удалось открыть раздел МРЦ и акций WB. Ошибка уже записана в лог.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.callback_query(F.data == "mrc:with_mrc")
async def mrc_with_mrc_handler(callback: CallbackQuery) -> None:
    """Показать товары с МРЦ."""
    try:
        user_id = await _get_user_id_from_callback(callback)
        if user_id is None:
            return

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Product)
                .join(MarketplaceAccount, MarketplaceAccount.id == Product.marketplace_account_id)
                .where(Product.user_id == user_id)
                .where(Product.marketplace == Marketplace.WB)
                .where(Product.is_active.is_(True))
                .where(Product.mrc_price.isnot(None))
                .where(Product.mrc_price > 0)
                .order_by(Product.seller_article)
                .limit(20)
            )
            products = result.scalars().all()

        if not products:
            text = "📦 <b>Товары с МРЦ</b>\n\nУ вас пока нет товаров с заполненной МРЦ."
            await safe_edit_text(callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML")
            return

        lines = ["📦 <b>Товары с МРЦ</b> (первые 20):\n"]
        for p in products:
            nm_id = p.marketplace_article or p.external_product_id or "—"
            article = p.seller_article or "—"
            title = (p.title or "Без названия")[:40]
            mrc_val = f"{p.mrc_price:.0f}" if p.mrc_price else "—"
            lines.append(
                f"• <b>{escape(title)}</b>\n"
                f"  Артикул: {escape(article)} | nmID: {nm_id}\n"
                f"  МРЦ: <b>{mrc_val} ₽</b>"
            )

        text = "\n\n".join(lines)
        await safe_edit_text(callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML")
    except Exception:
        logger.exception("mrc_with_mrc_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось загрузить товары с МРЦ. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.callback_query(F.data == "mrc:without_mrc")
async def mrc_without_mrc_handler(callback: CallbackQuery) -> None:
    """Показать товары без МРЦ."""
    try:
        user_id = await _get_user_id_from_callback(callback)
        if user_id is None:
            return

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Product)
                .join(MarketplaceAccount, MarketplaceAccount.id == Product.marketplace_account_id)
                .where(Product.user_id == user_id)
                .where(Product.marketplace == Marketplace.WB)
                .where(Product.is_active.is_(True))
                .where(
                    (Product.mrc_price.is_(None))
                    | (Product.mrc_price <= 0)
                )
                .order_by(Product.seller_article)
                .limit(20)
            )
            products = result.scalars().all()

        if not products:
            text = "✅ <b>Отлично!</b>\n\nУ вас все товары WB имеют заполненную МРЦ."
            await safe_edit_text(callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML")
            return

        lines = ["⚠️ <b>Товары без МРЦ</b> (первые 20):\n"]
        for p in products:
            nm_id = p.marketplace_article or p.external_product_id or "—"
            article = p.seller_article or "—"
            title = (p.title or "Без названия")[:40]
            lines.append(
                f"• <b>{escape(title)}</b>\n"
                f"  Артикул: {escape(article)} | nmID: {nm_id}"
            )

        text = "\n\n".join(lines)
        await safe_edit_text(callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML")
    except Exception:
        logger.exception("mrc_without_mrc_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось загрузить товары без МРЦ. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.callback_query(F.data == "mrc:promos_today")
async def mrc_promos_today_handler(callback: CallbackQuery) -> None:
    """Показать акции WB на сегодня."""
    try:
        user_id = await _get_user_id_from_callback(callback)
        if user_id is None:
            return

        from datetime import UTC, datetime

        now_utc = datetime.now(tz=UTC)

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(WbPromotion)
                .join(MarketplaceAccount, MarketplaceAccount.id == WbPromotion.marketplace_account_id)
                .where(MarketplaceAccount.user_id == user_id)
                .where(WbPromotion.is_active_today.is_(True))
                .where(WbPromotion.start_datetime <= now_utc)
                .where(WbPromotion.end_datetime >= now_utc)
                .order_by(WbPromotion.start_datetime)
            )
            promotions = result.scalars().all()

            sync_result = await session.execute(
                select(WbPromotion.synced_at)
                .join(MarketplaceAccount, MarketplaceAccount.id == WbPromotion.marketplace_account_id)
                .where(MarketplaceAccount.user_id == user_id)
                .where(WbPromotion.synced_at.isnot(None))
                .order_by(WbPromotion.synced_at.desc())
                .limit(1)
            )
            last_sync = sync_result.scalar_one_or_none()

        if not promotions:
            last_sync_text = ""
            if last_sync:
                last_sync_text = f"\nПоследняя синхронизация: {format_datetime_for_user(last_sync, 'Europe/Moscow')}"

            text = (
                "🎯 <b>Акции Wildberries на сегодня</b>\n\n"
                "Активных акций не найдено."
                f"{last_sync_text}\n\n"
                "Нажмите «Синхронизировать акции», чтобы обновить данные."
            )
            await safe_edit_text(callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML")
            return

        lines = ["🎯 <b>Акции Wildberries на сегодня</b>\n"]
        if last_sync:
            lines.append(f"Последняя синхронизация: {format_datetime_for_user(last_sync, 'Europe/Moscow')}\n")

        for i, promo in enumerate(promotions, 1):
            start_str = format_datetime_for_user(promo.start_datetime, "Europe/Moscow", "%d.%m.%Y") if promo.start_datetime else "—"
            end_str = format_datetime_for_user(promo.end_datetime, "Europe/Moscow", "%d.%m.%Y") if promo.end_datetime else "—"
            promo_type = "Авто" if promo.promotion_type and promo.promotion_type.lower() == "auto" else "Обычная"

            lines.append(
                f"<b>{i}. {escape(promo.name or 'Без названия')}</b>\n"
                f"ID: {promo.wb_promotion_id} | Тип: {promo_type}\n"
                f"Период: {start_str} — {end_str}"
            )

        text = "\n\n".join(lines)
        await safe_edit_text(callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML")
    except Exception:
        logger.exception("mrc_promos_today_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось загрузить акции WB. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.callback_query(F.data == "mrc:sync_promos")
async def mrc_sync_promos_handler(callback: CallbackQuery) -> None:
    """Ручная синхронизация акций WB."""
    user_id = await _get_user_id_from_callback(callback)
    if user_id is None:
        return

    await safe_edit_text(
        callback.message,
        "🔄 <b>Синхронизация акций WB...</b>\n\nЭто может занять несколько минут.",
        reply_markup=mrc_back_menu(),
        parse_mode="HTML",
    )
    await callback.answer()

    try:
        async with AsyncSessionFactory() as session:
            service = WbPromotionsSyncService(session, cipher=TokenCipher())
            stats = await service.sync_all_accounts()
            await session.commit()

        text = (
            "✅ <b>Синхронизация акций WB завершена</b>\n\n"
            f"Кабинетов обработано: {stats.accounts_processed}\n"
            f"Ошибок: {stats.accounts_failed}\n"
            f"Акции найдены: {stats.promotions_fetched}\n"
            f"Акции сохранены: {stats.promotions_upserted}\n"
            f"Товаров в акциях: {stats.nomenclatures_fetched}\n"
            f"Товаров сопоставлено: {stats.products_matched}"
        )
        if stats.errors:
            text += f"\n\n⚠️ Ошибки: {len(stats.errors)}"

        await safe_edit_text(callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML")
    except Exception:
        logger.exception("mrc_sync_promos_failed")
        await safe_edit_text(
            callback.message,
            "❌ <b>Ошибка синхронизации</b>\n\nПопробуйте позже.",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "mrc:search")
async def mrc_search_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Начать поиск товара для изменения МРЦ."""
    try:
        await state.set_state(MrcStates.waiting_for_article)
        await safe_edit_text(
            callback.message,
            "🔍 <b>Поиск товара</b>\n\n"
            "Введите артикул продавца или nmID товара WB:",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("mrc_search_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось начать поиск. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.message(MrcStates.waiting_for_article)
async def mrc_article_handler(message: Message, state: FSMContext) -> None:
    """Обработка ввода артикула/nmID."""
    query = message.text.strip()
    if not query:
        await message.answer("Введите артикул или nmID:", reply_markup=mrc_back_menu())
        return

    user_id = await _get_user_id_from_message(message)
    if user_id is None:
        return

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Product)
            .join(MarketplaceAccount, MarketplaceAccount.id == Product.marketplace_account_id)
            .where(Product.user_id == user_id)
            .where(Product.marketplace == Marketplace.WB)
            .where(Product.is_active.is_(True))
            .where(
                or_(
                    Product.seller_article == query,
                    Product.marketplace_article == query,
                    Product.external_product_id == query,
                )
            )
            .limit(1)
        )
        product = result.scalar_one_or_none()

    if product is None:
        await message.answer(
            f"❌ Товар с артикулом/nmID <b>{escape(query)}</b> не найден.\n\n"
            "Попробуйте ещё раз или нажмите Отмена.",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
        return

    await state.update_data(product_id=product.id)
    await state.set_state(MrcStates.waiting_for_mrc_price)

    nm_id = product.marketplace_article or product.external_product_id or "—"
    article = product.seller_article or "—"
    title = product.title or "Без названия"
    mrc_val = f"{product.mrc_price:.0f} ₽" if product.mrc_price and product.mrc_price > 0 else "не задана"

    await message.answer(
        f"📦 <b>{escape(title)}</b>\n\n"
        f"Артикул: <b>{escape(article)}</b>\n"
        f"WB nmID: <b>{nm_id}</b>\n"
        f"Текущая МРЦ: <b>{mrc_val}</b>\n\n"
        "Введите новую МРЦ (число больше 0) или нажмите Отмена:",
        reply_markup=mrc_back_menu(),
        parse_mode="HTML",
    )


@router.message(MrcStates.waiting_for_mrc_price)
async def mrc_price_handler(message: Message, state: FSMContext) -> None:
    """Обработка ввода новой МРЦ."""
    raw_value = message.text.strip().replace(",", ".")

    try:
        mrc_decimal = Decimal(raw_value)
    except (InvalidOperation, ValueError):
        await message.answer(
            "❌ Некорректное число. Введите МРЦ в виде числа, например: <b>699</b> или <b>699.50</b>",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
        return

    if mrc_decimal <= 0:
        await message.answer(
            "❌ МРЦ должна быть больше нуля. Введите корректное значение:",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
        return

    mrc_decimal = mrc_decimal.quantize(Decimal("0.01"))

    data = await state.get_data()
    product_id = data.get("product_id")
    if not product_id:
        await message.answer("❌ Ошибка: товар не найден. Начните заново.", reply_markup=mrc_back_menu())
        await state.clear()
        return

    user_id = await _get_user_id_from_message(message)
    if user_id is None:
        return

    async with AsyncSessionFactory() as session:
        product = await session.get(Product, product_id)
        if product is None or product.user_id != user_id:
            await message.answer("❌ Товар не найден.", reply_markup=mrc_back_menu())
            await state.clear()
            return

        old_mrc = product.mrc_price
        product.mrc_price = mrc_decimal
        await session.commit()

        # Calculate new price
        mrc_service = WbMrcPriceService()
        promo_service = WbPromotionsSyncService(session)
        wb_nm_id = _extract_nm_id(product)
        promo_nomenclature = None
        if wb_nm_id:
            promo_nomenclature = await promo_service.get_actual_promo_for_product(
                marketplace_account_id=product.marketplace_account_id,
                wb_nm_id=wb_nm_id,
            )

        promo_required_price = promo_nomenclature.plan_price if promo_nomenclature and promo_nomenclature.plan_price else None
        result = mrc_service.calculate(
            mrc_price=mrc_decimal,
            promo_required_price=promo_required_price,
        )

    # Build response
    promo_text = "Нет"
    if promo_nomenclature:
        promo_text = f"Да — {promo_nomenclature.plan_price:.0f} ₽"

    limit_text = "Нет"
    if result.is_limited_by_mrc_rule:
        limit_text = "Да — цена ограничена 10% от МРЦ"
    elif result.is_limited_by_min_price:
        limit_text = "Да — цена ограничена minPrice"

    old_mrc_str = f"{old_mrc:.0f} ₽" if old_mrc else "не была задана"

    text = (
        f"✅ <b>МРЦ обновлена</b>\n\n"
        f"Старая МРЦ: {old_mrc_str}\n"
        f"Новая МРЦ: <b>{result.mrc_price:.0f} ₽</b>\n\n"
        f"📊 Расчёт цены:\n"
        f"Итоговая цена со скидкой: <b>{result.final_discounted_price:.0f} ₽</b>\n"
        f"Цена до скидки WB: <b>{result.price_before_discount:.0f} ₽</b>\n"
        f"Скидка WB: {result.discount_percent:.0f}%\n\n"
        f"🎯 Акция WB: {promo_text}\n"
        f"⚠️ Ограничение: {limit_text}\n\n"
        f"📝 {result.reason}"
    )

    web_url = f"{settings.get_web_base_url()}/web/mrc-pricing"
    await message.answer(
        text,
        reply_markup=mrc_product_card_keyboard(product.id, wb_nm_id, web_url),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data.startswith("mrc:edit:"))
async def mrc_edit_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Изменить МРЦ конкретного товара по ID."""
    try:
        product_id = int(callback.data.split(":")[2])
        user_id = await _get_user_id_from_callback(callback)
        if user_id is None:
            return

        async with AsyncSessionFactory() as session:
            product = await session.get(Product, product_id)
            if product is None or product.user_id != user_id:
                await callback.answer("Товар не найден", show_alert=True)
                return

        await state.update_data(product_id=product_id)
        await state.set_state(MrcStates.waiting_for_mrc_price)

        nm_id = product.marketplace_article or product.external_product_id or "—"
        article = product.seller_article or "—"
        title = product.title or "Без названия"
        mrc_val = f"{product.mrc_price:.0f} ₽" if product.mrc_price and product.mrc_price > 0 else "не задана"

        await safe_edit_text(
            callback.message,
            f"✏️ <b>{escape(title)}</b>\n\n"
            f"Артикул: {escape(article)} | nmID: {nm_id}\n"
            f"Текущая МРЦ: <b>{mrc_val}</b>\n\n"
            "Введите новую МРЦ:",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("mrc_edit_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось открыть редактирование МРЦ. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.callback_query(F.data == "mrc:limits_report")
async def mrc_limits_report_handler(callback: CallbackQuery) -> None:
    """Отчёт по ограничениям МРЦ."""
    try:
        user_id = await _get_user_id_from_callback(callback)
        if user_id is None:
            return

        from datetime import UTC, datetime

        now_utc = datetime.now(tz=UTC)
        mrc_service = WbMrcPriceService()

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Product)
                .join(MarketplaceAccount, MarketplaceAccount.id == Product.marketplace_account_id)
                .where(Product.user_id == user_id)
                .where(Product.marketplace == Marketplace.WB)
                .where(Product.is_active.is_(True))
                .where(Product.mrc_price.isnot(None))
                .where(Product.mrc_price > 0)
            )
            products = result.scalars().all()

            promo_service = WbPromotionsSyncService(session)
            limited_by_mrc = []
            limited_by_min = []
            within_promo = []
            no_promo = []

            for p in products:
                wb_nm_id = _extract_nm_id(p)
                promo_nomenclature = None
                if wb_nm_id:
                    promo_nomenclature = await promo_service.get_actual_promo_for_product(
                        marketplace_account_id=p.marketplace_account_id,
                        wb_nm_id=wb_nm_id,
                    )

                promo_required_price = promo_nomenclature.plan_price if promo_nomenclature and promo_nomenclature.plan_price else None
                calc_result = mrc_service.calculate(
                    mrc_price=p.mrc_price,
                    promo_required_price=promo_required_price,
                )

                if calc_result.is_limited_by_mrc_rule:
                    limited_by_mrc.append((p, calc_result, promo_nomenclature))
                elif calc_result.is_limited_by_min_price:
                    limited_by_min.append((p, calc_result, promo_nomenclature))
                elif calc_result.is_promo_applied:
                    within_promo.append((p, calc_result, promo_nomenclature))
                else:
                    no_promo.append((p, calc_result, promo_nomenclature))

        total_with_mrc = len(products)
        total_with_promo = len(within_promo) + len(limited_by_mrc) + len(limited_by_min)

        lines = [
            "📊 <b>Контроль МРЦ и акций WB</b>\n\n",
            f"Товаров с МРЦ: <b>{total_with_mrc}</b>",
            f"С акцией WB: <b>{total_with_promo}</b>",
            f"В пределах 10%: <b>{len(within_promo)}</b>",
            f"Ограничены правилом МРЦ: <b>{len(limited_by_mrc)}</b>",
            f"Ограничены minPrice: <b>{len(limited_by_min)}</b>",
            f"Без акции: <b>{len(no_promo)}</b>\n",
        ]

        problematic = limited_by_mrc + limited_by_min
        if problematic:
            lines.append("⚠️ <b>Товары, требующие внимания:</b>\n")
            for p, calc_result, promo in problematic[:5]:
                article = p.seller_article or "—"
                nm_id = p.marketplace_article or p.external_product_id or "—"
                promo_price = f"{promo.plan_price:.0f}" if promo and promo.plan_price else "—"
                min_allowed = calc_result.mrc_price * Decimal("0.9")

                lines.append(
                    f"• <b>{escape(article)}</b> / {nm_id}\n"
                    f"  МРЦ: {calc_result.mrc_price:.0f} ₽\n"
                    f"  Цена акции: {promo_price} ₽\n"
                    f"  Минимум 10%: {min_allowed:.0f} ₽\n"
                    f"  Итоговая цена: {calc_result.final_discounted_price:.0f} ₽\n"
                    f"  Причина: {calc_result.reason}\n"
                )

        text = "\n".join(lines)
        await safe_edit_text(callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML")
    except Exception:
        logger.exception("mrc_limits_report_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось сформировать отчёт по МРЦ. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.callback_query(F.data.startswith("mrc:recalc:"))
async def mrc_recalc_handler(callback: CallbackQuery) -> None:
    """Пересчитать цену для товара."""
    try:
        product_id = int(callback.data.split(":")[2])
        user_id = await _get_user_id_from_callback(callback)
        if user_id is None:
            return

        async with AsyncSessionFactory() as session:
            product = await session.get(Product, product_id)
            if product is None or product.user_id != user_id or not product.mrc_price:
                await callback.answer("Товар не найден или МРЦ не задана", show_alert=True)
                return

            mrc_service = WbMrcPriceService()
            promo_service = WbPromotionsSyncService(session)
            wb_nm_id = _extract_nm_id(product)
            promo_nomenclature = None
            if wb_nm_id:
                promo_nomenclature = await promo_service.get_actual_promo_for_product(
                    marketplace_account_id=product.marketplace_account_id,
                    wb_nm_id=wb_nm_id,
                )

            promo_required_price = promo_nomenclature.plan_price if promo_nomenclature and promo_nomenclature.plan_price else None
            result = mrc_service.calculate(
                mrc_price=product.mrc_price,
                promo_required_price=promo_required_price,
            )

        promo_text = "Нет"
        if promo_nomenclature:
            promo_text = f"Да — {promo_nomenclature.plan_price:.0f} ₽"

        text = (
            f"🔄 <b>Пересчёт цены</b>\n\n"
            f"МРЦ: <b>{result.mrc_price:.0f} ₽</b>\n"
            f"Итоговая цена со скидкой: <b>{result.final_discounted_price:.0f} ₽</b>\n"
            f"Цена до скидки WB: <b>{result.price_before_discount:.0f} ₽</b>\n"
            f"Акция WB: {promo_text}\n"
            f"Ограничение: {'Да' if result.is_limited_by_mrc_rule or result.is_limited_by_min_price else 'Нет'}\n\n"
            f"📝 {result.reason}"
        )

        web_url = f"{settings.get_web_base_url()}/web/mrc-pricing"
        await safe_edit_text(
            callback.message,
            text,
            reply_markup=mrc_product_card_keyboard(product.id, wb_nm_id, web_url),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("mrc_recalc_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось пересчитать цену. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


def _extract_nm_id(product: Product) -> int | None:
    """Extract WB nmID from product."""
    if product.marketplace_article and product.marketplace_article.isdigit():
        return int(product.marketplace_article)
    if product.external_product_id and product.external_product_id.isdigit():
        return int(product.external_product_id)
    return None
