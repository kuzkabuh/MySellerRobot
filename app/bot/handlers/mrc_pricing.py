"""version: 1.3.0
description: Telegram bot handlers for MRC pricing and WB promotions management.
    Includes safe_edit_text helper to handle "message is not modified" errors gracefully.
    All handlers have try/except and always call callback.answer().
    Includes MRC bulk import/export via Excel files.
updated: 2026-05-21
"""

import logging
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy import or_, select

from app.bot.bot_provider import bot_session
from app.bot.keyboards.main import (
    mrc_back_menu,
    mrc_import_confirm_keyboard,
    mrc_menu,
    mrc_product_card_keyboard,
)
from app.bot.states import MrcStates
from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.core.security import TokenCipher
from app.models.domain import MarketplaceAccount, Product, WbPromotion
from app.models.enums import Marketplace
from app.repositories.users import UserRepository
from app.services.feature_access_service import FeatureAccessService, FeatureCode
from app.services.pricing.mrc_import_service import MrcImportService
from app.services.pricing.mrc_pricing_settings_service import MrcPricingSettingsService
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
    """Edit message text, ignoring 'message is not modified' and 'MESSAGE_TOO_LONG' errors."""
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        error_str = str(e).lower()
        if "message is not modified" in error_str:
            logger.debug("message_not_modified: %s", e)
        elif "message_too_long" in error_str or "too long" in error_str:
            logger.warning("message_too_long_truncated", extra={"text_len": len(text)})
            truncated = text[:4000] + "\n...(сообщение обрезано)"
            try:
                await message.edit_text(truncated, reply_markup=reply_markup, parse_mode=parse_mode)
            except TelegramBadRequest as e2:
                if "message is not modified" not in str(e2).lower():
                    raise
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
            await safe_edit_text(
                callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML"
            )
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
        await safe_edit_text(
            callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML"
        )
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
                .where((Product.mrc_price.is_(None)) | (Product.mrc_price <= 0))
                .order_by(Product.seller_article)
                .limit(20)
            )
            products = result.scalars().all()

        if not products:
            text = "✅ <b>Отлично!</b>\n\nУ вас все товары WB имеют заполненную МРЦ."
            await safe_edit_text(
                callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML"
            )
            return

        lines = ["⚠️ <b>Товары без МРЦ</b> (первые 20):\n"]
        for p in products:
            nm_id = p.marketplace_article or p.external_product_id or "—"
            article = p.seller_article or "—"
            title = (p.title or "Без названия")[:40]
            lines.append(
                f"• <b>{escape(title)}</b>\n" f"  Артикул: {escape(article)} | nmID: {nm_id}"
            )

        text = "\n\n".join(lines)
        await safe_edit_text(
            callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML"
        )
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
                .join(
                    MarketplaceAccount, MarketplaceAccount.id == WbPromotion.marketplace_account_id
                )
                .where(MarketplaceAccount.user_id == user_id)
                .where(WbPromotion.start_datetime <= now_utc)
                .where(WbPromotion.end_datetime >= now_utc)
                .order_by(WbPromotion.start_datetime)
            )
            promotions = result.scalars().all()

            sync_result = await session.execute(
                select(WbPromotion.synced_at)
                .join(
                    MarketplaceAccount, MarketplaceAccount.id == WbPromotion.marketplace_account_id
                )
                .where(MarketplaceAccount.user_id == user_id)
                .where(WbPromotion.synced_at.isnot(None))
                .order_by(WbPromotion.synced_at.desc())
                .limit(1)
            )
            last_sync = sync_result.scalar_one_or_none()

        if not promotions:
            last_sync_text = ""
            if last_sync:
                last_sync_text = (
                    "\nПоследняя синхронизация: "
                    f"{format_datetime_for_user(last_sync, 'Europe/Moscow')}"
                )

            text = (
                "🎯 <b>Акции Wildberries на сегодня</b>\n\n"
                "Активных акций не найдено."
                f"{last_sync_text}\n\n"
                "Нажмите «Синхронизировать акции», чтобы обновить данные."
            )
            await safe_edit_text(
                callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML"
            )
            return

        lines = ["🎯 <b>Акции Wildberries на сегодня</b>\n"]
        if last_sync:
            lines.append(
                f"Последняя синхронизация: {format_datetime_for_user(last_sync, 'Europe/Moscow')}\n"
            )

        for i, promo in enumerate(promotions, 1):
            start_str = (
                format_datetime_for_user(promo.start_datetime, "Europe/Moscow", "%d.%m.%Y")
                if promo.start_datetime
                else "—"
            )
            end_str = (
                format_datetime_for_user(promo.end_datetime, "Europe/Moscow", "%d.%m.%Y")
                if promo.end_datetime
                else "—"
            )
            promo_type = (
                "Авто"
                if promo.promotion_type and promo.promotion_type.lower() == "auto"
                else "Обычная"
            )

            lines.append(
                f"<b>{i}. {escape(promo.name or 'Без названия')}</b>\n"
                f"ID: {promo.wb_promotion_id} | Тип: {promo_type}\n"
                f"Период: {start_str} — {end_str}"
            )

        text = "\n\n".join(lines)

        # Telegram message limit is 4096 chars. Split if too long.
        if len(text) > 4000:
            header = lines[0]
            if last_sync:
                header += "\n" + lines[1]
            promo_lines = lines[2:] if last_sync else lines[1:]

            chunks: list[str] = []
            current_chunk = header + "\n\n"
            for promo_line in promo_lines:
                if len(current_chunk) + len(promo_line) + 20 > 4000:
                    chunks.append(current_chunk)
                    current_chunk = f"🎯 <b>Акции WB (продолжение)</b>\n\n{promo_line}"
                else:
                    current_chunk += "\n\n" + promo_line
            if current_chunk.strip():
                chunks.append(current_chunk)

            for idx, chunk in enumerate(chunks):
                if idx == 0:
                    await safe_edit_text(
                        callback.message,
                        chunk,
                        reply_markup=mrc_back_menu() if len(chunks) == 1 else None,
                        parse_mode="HTML",
                    )
                else:
                    async with bot_session() as bot:
                        await bot.send_message(
                            chat_id=callback.message.chat.id,
                            text=chunk,
                            reply_markup=mrc_back_menu() if idx == len(chunks) - 1 else None,
                            parse_mode="HTML",
                        )
        else:
            await safe_edit_text(
                callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML"
            )
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
    """Ручная синхронизация акций WB (обычный режим allPromo=false)."""
    await _run_promotions_sync(callback, all_promo=False)


@router.callback_query(F.data == "mrc:sync_promos_all")
async def mrc_sync_promos_all_handler(callback: CallbackQuery) -> None:
    """Расширенная синхронизация акций WB (allPromo=true)."""
    await _run_promotions_sync(callback, all_promo=True)


async def _run_promotions_sync(callback: CallbackQuery, all_promo: bool) -> None:
    """Run WB promotions sync with detailed reporting."""
    user_id = await _get_user_id_from_callback(callback)
    if user_id is None:
        return

    mode_text = "Расширенная проверка (allPromo=true)" if all_promo else "Синхронизация акций WB"
    await safe_edit_text(
        callback.message,
        f"🔄 <b>{mode_text}...</b>\n\nЭто может занять несколько минут.",
        reply_markup=mrc_back_menu(),
        parse_mode="HTML",
    )
    await callback.answer()

    try:
        async with AsyncSessionFactory() as session:
            service = WbPromotionsSyncService(session, cipher=TokenCipher())
            stats = await service.sync_all_accounts(all_promo=all_promo)
            await session.commit()

        all_promo_str = "true" if all_promo else "false"
        text = (
            f"✅ <b>Синхронизация акций WB завершена</b>\n\n"
            f"Режим: allPromo={all_promo_str}\n"
            f"Период запроса (UTC): {stats.sync_period_start} — {stats.sync_period_end}\n\n"
            f"Кабинетов обработано: {stats.accounts_processed}\n"
            f"Ошибок: {stats.accounts_failed}\n"
            f"WB вернул акций: {stats.promotions_fetched}\n"
            f"Акции сохранены: {stats.promotions_upserted}\n"
            f"Автоакций (пропущено): {stats.promotions_skipped_auto}\n"
            f"Товаров в акциях: {stats.nomenclatures_fetched}\n"
            f"Товаров сопоставлено: {stats.products_matched}"
        )

        if stats.promotions_fetched == 0 and not all_promo:
            text += (
                "\n\n💡 WB вернул 0 доступных для участия акций. "
                "Попробуйте расширенную проверку allPromo=true, чтобы получить все акции."
            )

        if stats.errors:
            text += f"\n\n⚠️ Ошибки: {len(stats.errors)}"

        await safe_edit_text(
            callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML"
        )
    except Exception:
        logger.exception("mrc_sync_promos_failed")
        await safe_edit_text(
            callback.message,
            "❌ <b>Ошибка синхronизации</b>\n\nПопробуйте позже.",
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
            "🔍 <b>Поиск товара</b>\n\n" "Введите артикул продавца или nmID товара WB:",
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


@router.callback_query(F.data == "mrc:set")
async def mrc_set_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Изменить МРЦ — запуск FSM-сценария (алиас для mrc:search)."""
    try:
        await state.set_state(MrcStates.waiting_for_article)
        await safe_edit_text(
            callback.message,
            "✏️ <b>Изменение МРЦ</b>\n\n"
            "Введите артикул продавца или WB nmID товара, "
            "для которого нужно изменить МРЦ:",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("mrc_set_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось начать изменение МРЦ. Попробуйте позже.",
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
    mrc_val = (
        f"{product.mrc_price:.0f} ₽" if product.mrc_price and product.mrc_price > 0 else "не задана"
    )

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
            "❌ Некорректное число. Введите МРЦ в виде числа, "
            "например: <b>699</b> или <b>699.50</b>",
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
        await message.answer(
            "❌ Ошибка: товар не найден. Начните заново.", reply_markup=mrc_back_menu()
        )
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

        promo_required_price = (
            promo_nomenclature.plan_price
            if promo_nomenclature and promo_nomenclature.plan_price
            else None
        )
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
        mrc_val = (
            f"{product.mrc_price:.0f} ₽"
            if product.mrc_price and product.mrc_price > 0
            else "не задана"
        )

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

        datetime.now(tz=UTC)
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

                promo_required_price = (
                    promo_nomenclature.plan_price
                    if promo_nomenclature and promo_nomenclature.plan_price
                    else None
                )
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
        await safe_edit_text(
            callback.message, text, reply_markup=mrc_back_menu(), parse_mode="HTML"
        )
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

            promo_required_price = (
                promo_nomenclature.plan_price
                if promo_nomenclature and promo_nomenclature.plan_price
                else None
            )
            result = mrc_service.calculate(
                mrc_price=product.mrc_price,
                promo_required_price=promo_required_price,
            )

        promo_text = "Нет"
        if promo_nomenclature:
            promo_text = f"Да — {promo_nomenclature.plan_price:.0f} ₽"

        limit_label = (
            "Да"
            if result.is_limited_by_mrc_rule or result.is_limited_by_min_price
            else "Нет"
        )
        text = (
            f"🔄 <b>Пересчёт цены</b>\n\n"
            f"МРЦ: <b>{result.mrc_price:.0f} ₽</b>\n"
            f"Итоговая цена со скидкой: <b>{result.final_discounted_price:.0f} ₽</b>\n"
            f"Цена до скидки WB: <b>{result.price_before_discount:.0f} ₽</b>\n"
            f"Акция WB: {promo_text}\n"
            f"Ограничение: {limit_label}\n\n"
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


@router.callback_query(F.data == "mrc:template_download")
async def mrc_template_download_handler(callback: CallbackQuery) -> None:
    """Скачать шаблон МРЦ в Excel."""
    try:
        user_id = await _get_user_id_from_callback(callback)
        if user_id is None:
            return

        await callback.answer()
        await safe_edit_text(
            callback.message,
            "⏳ <b>Формирую шаблон МРЦ...</b>\n\nПодождите немного.",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )

        async with AsyncSessionFactory() as session:
            service = MrcImportService(session)
            file_path = await service.generate_mrc_template(user_id)

        if not file_path.exists():
            await safe_edit_text(
                callback.message,
                "❌ Не удалось создать файл шаблона. Попробуйте позже.",
                reply_markup=mrc_back_menu(),
                parse_mode="HTML",
            )
            return

        input_file = FSInputFile(path=file_path, filename=file_path.name)
        await callback.message.answer_document(
            document=input_file,
            caption=(
                "📥 <b>Файл-шаблон МРЦ готов</b>\n\n"
                "Заполните колонку <b>new_mrc_price</b> и загрузите файл обратно "
                "через кнопку «Загрузить МРЦ из файла»."
            ),
            parse_mode="HTML",
        )

        await safe_edit_text(
            callback.message,
            "💰 <b>МРЦ и акции Wildberries</b>\n\nВыберите действие:",
            reply_markup=mrc_menu(),
            parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        logger.warning(
            "mrc_template_download_telegram_error",
            extra={"user_id": callback.from_user.id, "error": str(exc)},
        )
        await safe_edit_text(
            callback.message,
            "❌ Не удалось отправить файл шаблона в Telegram. "
            "Скачайте шаблон через WEB-кабинет: /web/mrc-pricing",
            reply_markup=mrc_back_menu(),
        )
    except Exception:
        logger.exception("mrc_template_download_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось сформировать шаблон МРЦ. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.callback_query(F.data == "mrc:import_upload")
async def mrc_import_upload_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Начать загрузку файла МРЦ."""
    try:
        await state.set_state(MrcStates.waiting_for_import_file)
        await safe_edit_text(
            callback.message,
            "📤 <b>Загрузка МРЦ из файла</b>\n\n"
            "Загрузите заполненный Excel-файл .xlsx. "
            "Используйте шаблон, который был сформирован ботом. "
            "Заполняйте только колонку <b>new_mrc_price</b>.",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("mrc_import_upload_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось начать загрузку. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.message(MrcStates.waiting_for_import_file, F.document)
async def mrc_import_file_handler(message: Message, state: FSMContext) -> None:
    """Обработка загруженного файла МРЦ."""
    user_id = None
    try:
        doc = message.document
        if not doc.file_name or not doc.file_name.endswith(".xlsx"):
            await message.answer(
                "❌ Неверный формат файла. Загрузите файл <b>.xlsx</b>.",
                reply_markup=mrc_back_menu(),
                parse_mode="HTML",
            )
            return

        max_size = get_settings().mrc_import_max_file_size_mb * 1024 * 1024
        if doc.file_size and doc.file_size > max_size:
            max_size_mb = get_settings().mrc_import_max_file_size_mb
            await message.answer(
                f"❌ Файл слишком большой. Максимум: {max_size_mb} МБ.",
                reply_markup=mrc_back_menu(),
                parse_mode="HTML",
            )
            return

        user_id = await _get_user_id_from_message(message)
        if user_id is None:
            return

        await message.answer("⏳ <b>Проверяю файл...</b>", parse_mode="HTML")

        file_info = await message.bot.get_file(doc.file_id)
        tmp_path = Path(f"/tmp/mrc_import_{message.from_user.id}_{doc.file_name}")
        await message.bot.download_file(file_info.file_path, tmp_path)

        async with AsyncSessionFactory() as session:
            service = MrcImportService(session)
            preview = await service.create_preview(
                tmp_path, user_id, source="bot", original_file_name=doc.file_name
            )
            rows = await service.get_import_rows(preview.import_id, user_id)

        await state.update_data(import_id=preview.import_id)
        await state.set_state(MrcStates.waiting_for_import_confirm)

        updated_count = sum(1 for r in rows if r.status in ("valid", "warning"))
        cleared_count = sum(1 for r in rows if r.status == "valid_clear")
        skipped_count = sum(1 for r in rows if r.status.startswith("skipped"))
        warning_count = sum(1 for r in rows if r.status == "warning")
        error_count = sum(1 for r in rows if r.status == "error")

        error_rows = [r for r in rows if r.status == "error"]
        error_lines = []
        for row in error_rows[:5]:
            error_lines.append(f"• Строка {row.row_number}: {row.message}")

        errors_text = "\n\n".join(error_lines) if error_lines else ""
        errors_footer = f"\n\nПоказаны первые 5 ошибок из {error_count}." if error_count > 5 else ""

        text = (
            f"📤 <b>Проверка файла МРЦ завершена</b>\n\n"
            f"Всего строк: <b>{preview.total_rows}</b>\n"
            f"Будет обновлено: <b>{updated_count}</b>\n"
            f"Будет очищено: <b>{cleared_count}</b>\n"
            f"Без изменений: <b>{skipped_count}</b>\n"
            f"Ошибок: <b>{error_count}</b>\n"
            f"Предупреждений: <b>{warning_count}</b>"
        )

        if errors_text:
            text += f"\n\n⚠️ Ошибки:\n{errors_text}{errors_footer}"

        await message.answer(text, reply_markup=mrc_import_confirm_keyboard(), parse_mode="HTML")
    except ValueError as exc:
        logger.warning(
            "mrc_import_file_validation_error",
            extra={"user_id": user_id or message.from_user.id, "error": str(exc)},
        )
        await message.answer(
            f"❌ {str(exc)}",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception(
            "mrc_import_file_handler_failed", extra={"user_id": user_id or message.from_user.id}
        )
        await message.answer(
            "❌ Не удалось прочитать Excel-файл. Скачайте новый шаблон "
            "и заполните колонку new_mrc_price.",
            reply_markup=mrc_back_menu(),
        )


@router.callback_query(F.data == "mrc:import_confirm", MrcStates.waiting_for_import_confirm)
async def mrc_import_confirm_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Подтвердить и сохранить импорт МРЦ."""
    user_id = None
    import_id = None
    try:
        user_id = await _get_user_id_from_callback(callback)
        if user_id is None:
            return

        data = await state.get_data()
        import_id = data.get("import_id")
        if not import_id:
            await callback.answer("Ошибка: данные импорта не найдены.", show_alert=True)
            return

        await callback.answer()
        await safe_edit_text(
            callback.message,
            "⏳ <b>Сохраняю МРЦ...</b>",
            reply_markup=mrc_back_menu(),
        )

        async with AsyncSessionFactory() as session:
            service = MrcImportService(session)
            result = await service.apply_mrc_import(int(import_id), user_id, source="bot")

        text = (
            f"✅ <b>МРЦ успешно импортированы</b>\n\n"
            f"Обновлено товаров: <b>{result.updated_count}</b>\n"
            f"Очищено МРЦ: <b>{result.cleared_count}</b>\n"
            f"Пропущено: <b>{result.skipped_count}</b>\n"
            f"Ошибок: <b>{result.error_count}</b>\n\n"
            "Теперь можно перейти в раздел «МРЦ и акции WB» и проверить расчёт цен."
        )

        await safe_edit_text(callback.message, text, reply_markup=mrc_menu(), parse_mode="HTML")
        await state.clear()
    except ValueError as exc:
        error_msg = str(exc)
        logger.warning(
            "mrc_import_confirm_validation_error",
            extra={
                "user_id": user_id or callback.from_user.id,
                "import_id": import_id,
                "error": error_msg,
            },
        )
        await safe_edit_text(
            callback.message,
            f"❌ {error_msg}",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
        await state.clear()
    except Exception:
        logger.exception(
            "mrc_import_confirm_failed",
            extra={"user_id": user_id or callback.from_user.id, "import_id": import_id},
        )
        await safe_edit_text(
            callback.message,
            "❌ Не удалось сохранить МРЦ из-за ошибки базы данных. Ошибка записана в лог.",
            reply_markup=mrc_back_menu(),
        )
        await state.clear()
    finally:
        await callback.answer()


@router.callback_query(F.data == "mrc:import_cancel", MrcStates.waiting_for_import_confirm)
async def mrc_import_cancel_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Отменить импорт МРЦ."""
    try:
        user_id = await _get_user_id_from_callback(callback)
        if user_id is None:
            return

        data = await state.get_data()
        import_id = data.get("import_id")

        if import_id:
            async with AsyncSessionFactory() as session:
                service = MrcImportService(session)
                await service.cancel_import(int(import_id), user_id)

        await state.clear()
        await safe_edit_text(
            callback.message,
            "❌ <b>Импорт отменён</b>",
            reply_markup=mrc_menu(),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("mrc_import_cancel_failed")
        await safe_edit_text(
            callback.message,
            "Импорт отменён.",
            reply_markup=mrc_menu(),
        )
    finally:
        await callback.answer()


@router.callback_query(F.data == "mrc:settings")
async def mrc_settings_handler(callback: CallbackQuery) -> None:
    """Show MRC settings."""
    try:
        user_id = await _get_user_id_from_callback(callback)
        if user_id is None:
            return

        async with AsyncSessionFactory() as session:
            settings_service = MrcPricingSettingsService(session)
            settings = await settings_service.get_settings(user_id=user_id)

        discount_str = f"{settings.default_discount_percent:.0f}%"
        multiplier_val = settings.full_price_multiplier
        multiplier_str = (
            f"{multiplier_val:.0f}"
            if multiplier_val == multiplier_val.to_integral_value()
            else str(multiplier_val)
        )
        deviation_str = f"{settings.allowed_action_price_deviation_percent:.0f}%"
        auto_check = "вкл" if settings.auto_promo_check_enabled else "выкл"
        auto_add = "вкл" if settings.auto_add_to_promotions else "выкл"
        auto_price = "вкл" if settings.auto_price_for_auto_promotions else "выкл"

        text = (
            "⚙️ <b>Настройки МРЦ и акций WB</b>\n\n"
            f"Процент скидки WB: <b>{discount_str}</b>\n"
            f"Коэффициент полной цены: <b>{multiplier_str}</b>\n"
            f"Допуск цены акции: <b>{deviation_str}</b>\n"
            f"Автопроверка акций: <b>{auto_check}</b>\n"
            f"Автодобавление в акции: <b>{auto_add}</b>\n"
            f"Автоцена для автоакций WB: <b>{auto_price}</b>\n\n"
            "Выберите параметр для изменения:"
        )

        from app.bot.keyboards.main import mrc_settings_keyboard

        await safe_edit_text(
            callback.message, text, reply_markup=mrc_settings_keyboard(), parse_mode="HTML"
        )
    except Exception:
        logger.exception("mrc_settings_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось открыть настройки МРЦ. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.callback_query(F.data == "mrc:settings:discount")
async def mrc_settings_discount_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Change discount percent."""
    try:
        await state.set_state(MrcStates.waiting_for_discount_percent)
        await safe_edit_text(
            callback.message,
            "✏️ <b>Процент скидки WB</b>\n\n"
            "Введите новый процент скидки (0–99), например: <b>75</b>",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("mrc_settings_discount_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось начать изменение. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.callback_query(F.data == "mrc:settings:multiplier")
async def mrc_settings_multiplier_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Change price multiplier."""
    try:
        await state.set_state(MrcStates.waiting_for_price_multiplier)
        await safe_edit_text(
            callback.message,
            "✏️ <b>Коэффициент полной цены</b>\n\n"
            "Введите новый коэффициент (1–20), например: <b>4</b>",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("mrc_settings_multiplier_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось начать изменение. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.callback_query(F.data == "mrc:settings:deviation")
async def mrc_settings_deviation_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Change deviation percent."""
    try:
        await state.set_state(MrcStates.waiting_for_deviation_percent)
        await safe_edit_text(
            callback.message,
            "✏️ <b>Допустимое отклонение цены в акции от МРЦ</b>\n\n"
            "Введите новый процент (0–100), например: <b>10</b>",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("mrc_settings_deviation_failed")
        await safe_edit_text(
            callback.message,
            "Не удалось начать изменение. Попробуйте позже.",
            reply_markup=mrc_back_menu(),
        )
    finally:
        await callback.answer()


@router.message(MrcStates.waiting_for_discount_percent)
async def mrc_settings_discount_input_handler(message: Message, state: FSMContext) -> None:
    """Handle discount percent input."""
    raw_value = message.text.strip().replace(",", ".")
    try:
        value = Decimal(raw_value)
    except (InvalidOperation, ValueError):
        await message.answer(
            "❌ Некорректное число. Введите процент от 0 до 99:",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
        return

    if value < 0 or value > 99:
        await message.answer(
            "❌ Процент должен быть от 0 до 99. Введите корректное значение:",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
        return

    value = value.quantize(Decimal("0.01"))
    user_id = await _get_user_id_from_message(message)
    if user_id is None:
        return

    async with AsyncSessionFactory() as session:
        settings_service = MrcPricingSettingsService(session)
        await settings_service.update_settings(user_id=user_id, default_discount_percent=value)
        await session.commit()

    await message.answer(
        f"✅ <b>Процент скидки WB обновлён</b>\n\nНовое значение: <b>{value:.0f}%</b>",
        reply_markup=mrc_back_menu(),
        parse_mode="HTML",
    )
    await state.clear()


@router.message(MrcStates.waiting_for_price_multiplier)
async def mrc_settings_multiplier_input_handler(message: Message, state: FSMContext) -> None:
    """Handle price multiplier input."""
    raw_value = message.text.strip().replace(",", ".")
    try:
        value = Decimal(raw_value)
    except (InvalidOperation, ValueError):
        await message.answer(
            "❌ Некорректное число. Введите коэффициент от 1 до 20:",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
        return

    if value < 1 or value > 20:
        await message.answer(
            "❌ Коэффициент должен быть от 1 до 20. Введите корректное значение:",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
        return

    value = value.quantize(Decimal("0.01"))
    user_id = await _get_user_id_from_message(message)
    if user_id is None:
        return

    async with AsyncSessionFactory() as session:
        settings_service = MrcPricingSettingsService(session)
        await settings_service.update_settings(user_id=user_id, full_price_multiplier=value)
        await session.commit()

    await message.answer(
        f"✅ <b>Коэффициент полной цены обновлён</b>\n\nНовое значение: <b>{value:.0f}</b>",
        reply_markup=mrc_back_menu(),
        parse_mode="HTML",
    )
    await state.clear()


@router.message(MrcStates.waiting_for_deviation_percent)
async def mrc_settings_deviation_input_handler(message: Message, state: FSMContext) -> None:
    """Handle deviation percent input."""
    raw_value = message.text.strip().replace(",", ".")
    try:
        value = Decimal(raw_value)
    except (InvalidOperation, ValueError):
        await message.answer(
            "❌ Некорректное число. Введите процент от 0 до 100:",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
        return

    if value < 0 or value > 100:
        await message.answer(
            "❌ Процент должен быть от 0 до 100. Введите корректное значение:",
            reply_markup=mrc_back_menu(),
            parse_mode="HTML",
        )
        return

    value = value.quantize(Decimal("0.01"))
    user_id = await _get_user_id_from_message(message)
    if user_id is None:
        return

    async with AsyncSessionFactory() as session:
        settings_service = MrcPricingSettingsService(session)
        await settings_service.update_settings(
            user_id=user_id, allowed_action_price_deviation_percent=value
        )
        await session.commit()

    await message.answer(
        f"✅ <b>Допустимое отклонение обновлено</b>\n\nНовое значение: <b>{value:.0f}%</b>",
        reply_markup=mrc_back_menu(),
        parse_mode="HTML",
    )
    await state.clear()
