"""version: 1.0.0
description: Telegram marketplace account connection and management handlers.
updated: 2026-05-14
"""

import logging
from collections.abc import Sequence
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.bot.keyboards.main import (
    account_actions,
    account_history_periods,
    accounts_list_menu,
    accounts_menu,
    back_to_settings,
    confirm_delete_account,
)
from app.bot.states import ConnectOzonStates, ConnectWildberriesStates
from app.core.db import AsyncSessionFactory
from app.models.domain import (
    AccountBalanceSnapshot,
    MarketplaceAccount,
    User,
    WbFinancialReport,
    WbReportCheckState,
)
from app.models.enums import Marketplace
from app.repositories.users import UserRepository
from app.services.account_profile_service import AccountProfileService
from app.services.account_service import (
    AccountConnectionError,
    CreateAccountCommand,
    MarketplaceAccountService,
)
from app.services.history_backfill_service import HistoryBackfillService
from app.services.marketplace_presentation import marketplace_marker
from app.services.wb_report_service import WbFinancialReportService

router = Router(name="accounts")
logger = logging.getLogger(__name__)


@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=back_to_settings())


@router.message(Command("accounts"))
async def accounts_command_handler(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить Telegram-пользователя.")
        return
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        await session.commit()
        accounts = await MarketplaceAccountService(session).list_accounts(user.id)
    await message.answer(_format_accounts_list(accounts), reply_markup=accounts_list_menu(accounts))


@router.callback_query(F.data == "connect_wb")
async def start_wb_connection(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ConnectWildberriesStates.waiting_for_name)
    await _answer_callback_message(
        callback,
        "Введите название кабинета Wildberries. Например: Основной WB",
    )
    await callback.answer()


@router.message(ConnectWildberriesStates.waiting_for_name)
async def wb_name_handler(message: Message, state: FSMContext) -> None:
    name = _clean_text(message.text)
    if not name:
        await message.answer("Название не должно быть пустым.")
        return
    await state.update_data(name=name)
    await state.set_state(ConnectWildberriesStates.waiting_for_api_key)
    await message.answer(
        "Теперь отправьте API-ключ Wildberries.\n\n"
        "Нужен ключ с доступом к FBS-заказам, товарам, остаткам и отчётам. "
        "После проверки ключ будет сохранён в зашифрованном виде."
    )


@router.message(ConnectWildberriesStates.waiting_for_api_key)
async def wb_api_key_handler(message: Message, state: FSMContext) -> None:
    api_key = _clean_text(message.text)
    await _try_delete_sensitive_message(message)
    if not api_key:
        await message.answer("Ключ не должен быть пустым.")
        return
    data = await state.get_data()
    await _connect_account(
        message=message,
        state=state,
        marketplace=Marketplace.WB,
        name=str(data["name"]),
        api_key=api_key,
    )


@router.callback_query(F.data == "connect_ozon")
async def start_ozon_connection(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ConnectOzonStates.waiting_for_name)
    await _answer_callback_message(
        callback,
        "Введите название кабинета Ozon. Например: Основной Ozon",
    )
    await callback.answer()


@router.message(ConnectOzonStates.waiting_for_name)
async def ozon_name_handler(message: Message, state: FSMContext) -> None:
    name = _clean_text(message.text)
    if not name:
        await message.answer("Название не должно быть пустым.")
        return
    await state.update_data(name=name)
    await state.set_state(ConnectOzonStates.waiting_for_client_id)
    await message.answer("Отправьте Client ID из настроек Seller API в кабинете Ozon.")


@router.message(ConnectOzonStates.waiting_for_client_id)
async def ozon_client_id_handler(message: Message, state: FSMContext) -> None:
    client_id = _clean_text(message.text)
    await _try_delete_sensitive_message(message)
    if not client_id:
        await message.answer("Client ID не должен быть пустым.")
        return
    await state.update_data(client_id=client_id)
    await state.set_state(ConnectOzonStates.waiting_for_api_key)
    await message.answer("Теперь отправьте API key Ozon. После проверки он будет зашифрован.")


@router.message(ConnectOzonStates.waiting_for_api_key)
async def ozon_api_key_handler(message: Message, state: FSMContext) -> None:
    api_key = _clean_text(message.text)
    await _try_delete_sensitive_message(message)
    if not api_key:
        await message.answer("API key не должен быть пустым.")
        return
    data = await state.get_data()
    await _connect_account(
        message=message,
        state=state,
        marketplace=Marketplace.OZON,
        name=str(data["name"]),
        api_key=api_key,
        client_id=str(data["client_id"]),
    )


@router.callback_query(F.data == "accounts")
async def accounts_list_handler(callback: CallbackQuery) -> None:
    user = await _get_or_create_user_from_callback(callback)
    if user is None:
        await callback.answer("Не удалось определить пользователя", show_alert=True)
        return
    async with AsyncSessionFactory() as session:
        service = MarketplaceAccountService(session)
        accounts = await service.list_accounts(user.id)
    text = _format_accounts_list(accounts)
    await _edit_or_answer(callback, text, accounts_list_menu(accounts))
    await callback.answer()


@router.callback_query(F.data.startswith("account:"))
async def account_action_handler(callback: CallbackQuery) -> None:
    user = await _get_or_create_user_from_callback(callback)
    if user is None:
        await callback.answer("Не удалось определить пользователя", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[1].isdigit():
        await callback.answer("Некорректная команда", show_alert=True)
        return
    account_id = int(parts[1])
    action = parts[2]
    async with AsyncSessionFactory() as session:
        service = MarketplaceAccountService(session)
        if action == "delete":
            deleted = await service.delete_account(user.id, account_id)
            await callback.answer("Кабинет удалён" if deleted else "Кабинет не найден")
            accounts = await service.list_accounts(user.id)
            await _edit_or_answer(
                callback,
                _format_accounts_list(accounts),
                accounts_list_menu(accounts),
            )
            return
        accounts = await service.list_accounts(user.id)
        account = next((item for item in accounts if item.id == account_id), None)
        if action.startswith("history_") and account is not None:
            days = int(action.removeprefix("history_"))
            job = await HistoryBackfillService(session).schedule_manual(account, days=days)
            await callback.answer("Задача загрузки истории создана")
            await _edit_or_answer(
                callback,
                "🔄 Загрузка истории запущена.\n\n"
                f"Период: последние {days} дней.\n"
                f"Задача: #{job.id}.\n\n"
                "Когда данные будут готовы, бот сообщит об этом.",
                account_actions(account.id, account.is_active),
            )
            return
        if action == "seller" and account is not None:
            profile = await AccountProfileService(session).refresh_account(
                account,
                force_balance=False,
            )
            await session.commit()
            await _edit_or_answer(
                callback,
                _format_seller_profile(profile.account, profile.balance),
                account_actions(account.id, account.is_active),
            )
            await callback.answer()
            return
        if action == "reports" and account is not None:
            report_service = WbFinancialReportService(session)
            if account.marketplace == Marketplace.WB:
                await report_service.check_recent(account)
                await session.commit()
            reports = await report_service.latest_reports(account.id, limit=6)
            states = await report_service.latest_states(account.id)
            await _edit_or_answer(
                callback,
                _format_wb_reports(account, reports, states),
                account_actions(account.id, account.is_active),
            )
            await callback.answer()
            return
    if account is None:
        await callback.answer("Кабинет не найден", show_alert=True)
        return
    if action == "delete_confirm":
        await _edit_or_answer(
            callback,
            f"Удалить кабинет «{_safe_text(account.name)}»?\n\nAPI-ключи будут отключены в боте.",
            confirm_delete_account(account.id),
        )
    elif action == "history":
        await _edit_or_answer(
            callback,
            "Выберите период исторической загрузки.",
            account_history_periods(account.id),
        )
    else:
        await _edit_or_answer(
            callback,
            _format_account_card(account),
            account_actions(account.id, account.is_active),
        )
    await callback.answer()


async def _connect_account(
    *,
    message: Message,
    state: FSMContext,
    marketplace: Marketplace,
    name: str,
    api_key: str,
    client_id: str | None = None,
) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить Telegram-пользователя.")
        return
    await message.answer("Проверяю подключение к маркетплейсу...")
    try:
        async with AsyncSessionFactory() as session:
            user_repo = UserRepository(session)
            user = await user_repo.get_or_create(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )
            service = MarketplaceAccountService(session)
            account = await service.connect(
                CreateAccountCommand(
                    user_id=user.id,
                    marketplace=marketplace,
                    name=name,
                    api_key=api_key,
                    client_id=client_id,
                )
            )
        await state.clear()
        await message.answer(
            "✅ Кабинет подключён.\n\n"
            f"{_format_account_card(account)}\n\n"
            "Начинаю первичную загрузку заказов, продаж и аналитики за последние 30 дней.\n"
            "Когда данные будут готовы, бот сообщит об этом.\n\n"
            "Теперь можно загрузить себестоимость.",
            reply_markup=accounts_menu(),
        )
    except AccountConnectionError as exc:
        logger.info("marketplace_account_connection_rejected")
        await message.answer(_safe_text(str(exc)), reply_markup=back_to_settings())
    except ValueError:
        logger.exception("token_cipher_configuration_error")
        await message.answer(
            "Не настроен ключ шифрования ENCRYPTION_KEY. Сгенерируйте Fernet-ключ и обновите .env.",
            reply_markup=back_to_settings(),
        )
    except Exception:
        logger.exception("marketplace_account_connection_failed")
        await message.answer(
            "Не удалось подключить кабинет из-за технической ошибки. Попробуйте позже.",
            reply_markup=back_to_settings(),
        )


async def _get_or_create_user_from_callback(callback: CallbackQuery) -> User | None:
    if callback.from_user is None:
        return None
    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        user = await repo.get_or_create(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        await session.commit()
        return user


def _format_accounts_list(accounts: list[MarketplaceAccount]) -> str:
    if not accounts:
        return "У вас пока нет подключённых кабинетов."
    lines = ["Мои кабинеты", ""]
    for account in accounts:
        status = "активен" if account.is_active else "отключён"
        marker = marketplace_marker(account.marketplace)
        name = _safe_text(account.name)
        lines.append(f"#{account.id} — {marker}: {name} ({status})")
    lines.append("")
    lines.append("Чтобы открыть карточку кабинета, используйте кнопки ниже.")
    return "\n".join(lines)


def _format_account_card(account: MarketplaceAccount) -> str:
    client_id = "сохранён" if account.encrypted_client_id else "не требуется"
    return (
        f"Маркетплейс: {marketplace_marker(account.marketplace)}\n"
        f"Название: {_safe_text(account.name)}\n"
        f"Статус: {account.status.value}\n"
        f"Client ID: {client_id}\n"
        "Ключ API: сохранён в зашифрованном виде"
    )


def _format_seller_profile(
    account: MarketplaceAccount,
    balance: AccountBalanceSnapshot | None,
) -> str:
    payload = account.seller_info_payload or {}
    lines = [
        "👤 Кабинет продавца",
        "",
        f"Маркетплейс: {marketplace_marker(account.marketplace)}",
        f"Название: {_safe_text(account.seller_name or account.name)}",
        f"Юр. имя: {_safe_text(account.seller_legal_name)}",
        f"ИНН: {_safe_text(payload.get('tin'))}",
        f"SID: {_safe_text(payload.get('sid') or account.seller_external_id)}",
        f"Торговая марка: {_safe_text(payload.get('tradeMark'))}",
    ]
    if balance is None:
        lines.extend(["", "💰 Баланс: пока не загружен"])
    elif getattr(balance, "status", "") == "OK":
        currency = getattr(balance, "currency", "RUB")
        current = _safe_text(getattr(balance, "current", None))
        for_withdraw = _safe_text(getattr(balance, "for_withdraw", None))
        lines.extend(
            [
                "",
                "💰 Баланс",
                f"Текущий: {current} {currency}",
                f"Доступно к выводу: {for_withdraw} {currency}",
                f"Обновлено: {balance.fetched_at.strftime('%d.%m.%Y %H:%M')}",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "💰 Баланс недоступен.",
                "Для WB нужен ключ с категорией Finance. "
                "Для Ozon показываются доступные данные профиля.",
            ]
        )
    return "\n".join(lines)


def _format_wb_reports(
    account: MarketplaceAccount,
    reports: Sequence[WbFinancialReport],
    states: Sequence[WbReportCheckState],
) -> str:
    if account.marketplace != Marketplace.WB:
        return "Финансовые отчёты сейчас поддержаны только для Wildberries."
    state_by_period = {state.period_type: state for state in states}
    lines = ["📄 Отчёты Wildberries", ""]
    for period, title in (("daily", "Ежедневные"), ("weekly", "Еженедельные")):
        state = state_by_period.get(period)
        if state is None:
            lines.append(f"{title}: ещё не проверялись")
        elif getattr(state, "status", "") == "FOUND":
            lines.append(f"{title}: найдены, записей: {state.reports_found}")
        elif getattr(state, "status", "") in {"NO_ACCESS", "RATE_LIMITED"}:
            lines.append(f"{title}: нет доступа или превышен лимит Finance API")
        else:
            lines.append(f"{title}: пока не найдены")
    lines.append("")
    if not reports:
        lines.append("Последних отчётов в базе пока нет.")
    for report in reports[:6]:
        amount = getattr(report, "for_pay_sum", None)
        lines.append(
            f"{getattr(report, 'period_type', '')}: "
            f"{getattr(report, 'date_from', None)} — {getattr(report, 'date_to', None)}, "
            f"к выплате: {_safe_text(amount)}"
        )
    return "\n".join(lines)


async def _answer_callback_message(callback: CallbackQuery, text: str) -> None:
    message = callback.message
    if isinstance(message, Message):
        await message.answer(text)


async def _edit_or_answer(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    message = callback.message
    if isinstance(message, Message):
        await message.edit_text(text, reply_markup=reply_markup)


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


def _safe_text(value: object | None, fallback: str = "н/д") -> str:
    if value is None or value == "":
        return fallback
    return escape(str(value), quote=False)


async def _try_delete_sensitive_message(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        logger.debug("failed_to_delete_sensitive_message")
