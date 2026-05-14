"""version: 1.0.0
description: ARQ background task functions.
updated: 2026-05-14
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount
from app.models.enums import Marketplace
from app.repositories.orders import OrderRepository
from app.schemas.profit import CostInput, ProfitInput
from app.services.message_formatter import MessageFormatter
from app.services.notification_service import NotificationService
from app.services.profit_calculator import ProfitCalculator

logger = logging.getLogger(__name__)


async def poll_new_orders(ctx: dict[str, Any]) -> None:
    """Poll active marketplace accounts and store unseen orders."""

    settings = get_settings()
    cipher = TokenCipher()
    formatter = MessageFormatter()
    calculator = ProfitCalculator()
    bot = Bot(settings.bot_token.get_secret_value())
    notifier = NotificationService(bot)
    async with AsyncSessionFactory() as session:
        accounts = (
            await session.execute(
                select(MarketplaceAccount)
                .options(selectinload(MarketplaceAccount.user))
                .where(MarketplaceAccount.is_active.is_(True))
            )
        ).scalars()
        for account in accounts:
            try:
                if account.marketplace == Marketplace.WB:
                    api_key = cipher.decrypt(account.encrypted_api_key)
                    wb_client = WildberriesClient(api_key)
                    raw_orders = await wb_client.get_new_fbs_orders()
                    normalized_orders = [wb_client.normalize_fbs_order(item) for item in raw_orders]
                else:
                    api_key = cipher.decrypt(account.encrypted_api_key)
                    client_id = cipher.decrypt(account.encrypted_client_id or "")
                    ozon_client = OzonClient(client_id=client_id, api_key=api_key)
                    now = datetime.now(tz=UTC)
                    data = await ozon_client.get_fbs_postings(now - timedelta(minutes=30), now)
                    normalized_orders = [
                        ozon_client.normalize_fbs_posting(item)
                        for item in data.get("result", {}).get("postings", [])
                    ]
                repo = OrderRepository(session)
                for normalized in normalized_orders:
                    if await repo.exists(account.id, normalized):
                        continue
                    order = await repo.create(account.user_id, account.id, normalized)
                    item = normalized.items[0]
                    profit = calculator.calculate(
                        ProfitInput(
                            gross_revenue=item.discounted_price,
                            expected_payout=item.payout_amount_estimated,
                            marketplace_commission=item.commission_estimated or Decimal("0"),
                            logistics_cost=item.logistics_estimated or Decimal("0"),
                            other_marketplace_costs=(
                                item.other_marketplace_expenses_estimated or Decimal("0")
                            ),
                            cost=CostInput(),
                        )
                    )
                    text = formatter.new_order_card(normalized, item, profit, detailed=False)
                    await notifier.send_new_order(account.user.telegram_id, text, order.id)
                await session.commit()
            except Exception:
                logger.exception("marketplace_poll_failed", extra={"account_id": account.id})
                await session.rollback()
    await bot.session.close()


async def send_daily_reports(ctx: dict[str, Any]) -> None:
    logger.info("daily_reports_task_placeholder")


async def check_fbs_deadlines(ctx: dict[str, Any]) -> None:
    logger.info("fbs_deadline_task_placeholder")


async def check_low_stocks(ctx: dict[str, Any]) -> None:
    logger.info("low_stock_task_placeholder")
