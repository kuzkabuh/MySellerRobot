"""version: 1.0.0
description: Online order ingestion, idempotency, product matching, and estimated profit snapshots.
updated: 2026-05-14
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount, Order
from app.models.enums import FboNotificationMode, Marketplace
from app.repositories.orders import FboDigestQueueRepository, OrderRepository
from app.schemas.orders import NormalizedOrder
from app.services.message_formatter import MessageFormatter
from app.services.order_notification_policy import OrderNotificationPolicyService
from app.services.order_profit_service import OrderProfitService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NewOrderNotification:
    telegram_id: int
    order_id: int
    text: str


class OrderProcessingService:
    """Process marketplace orders and prepare Telegram notifications."""

    def __init__(
        self,
        session: AsyncSession,
        cipher: TokenCipher | None = None,
    ) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()
        self.orders = OrderRepository(session)
        self.fbo_queue = FboDigestQueueRepository(session)
        self.notification_policy = OrderNotificationPolicyService(session)
        self.profits = OrderProfitService(session)
        self.formatter = MessageFormatter()

    async def poll_account(self, account: MarketplaceAccount) -> list[NewOrderNotification]:
        normalized_orders = await self._fetch_orders(account)
        policy = await self.notification_policy.resolve(account)
        notifications: list[NewOrderNotification] = []
        for normalized in normalized_orders:
            if await self.orders.exists(account.id, normalized):
                continue
            order = await self.orders.create(account.user_id, account.id, normalized)
            await self.profits.calculate_estimated_profit(account, order, normalized)
            if policy.should_queue_fbo_digest(normalized.sale_model):
                await self._queue_fbo_digest(account, order, policy.fbo_mode)
                continue
            if not policy.is_instant_enabled_for(normalized.sale_model):
                continue
            first_item = normalized.items[0] if normalized.items else None
            if not first_item or not account.user:
                continue
            order_with_items = await self.orders.get_with_items(order.id)
            item = (
                order_with_items.items[0] if order_with_items and order_with_items.items else None
            )
            profit = self.profits.latest_estimated_result(item) if item else None
            if profit:
                await self.orders.mark_notified(order.id)
                notifications.append(
                    NewOrderNotification(
                        telegram_id=account.user.telegram_id,
                        order_id=order.id,
                        text=self.formatter.new_order_card(
                            normalized,
                            first_item,
                            profit,
                            detailed=False,
                        ),
                    )
                )
        await self.session.commit()
        return notifications

    async def _fetch_orders(self, account: MarketplaceAccount) -> list[NormalizedOrder]:
        if account.marketplace == Marketplace.WB:
            api_key = self.cipher.decrypt(account.encrypted_api_key)
            wb_client = WildberriesClient(api_key)
            return [
                wb_client.normalize_fbs_order(item) for item in await wb_client.get_new_fbs_orders()
            ]

        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client_id = self.cipher.decrypt(account.encrypted_client_id or "")
        ozon_client = OzonClient(client_id=client_id, api_key=api_key)
        now = datetime.now(tz=UTC)
        fbs_data = await ozon_client.get_fbs_postings(now - timedelta(minutes=30), now)
        fbs_postings = self._extract_postings(fbs_data)
        fbo_postings: list[object] = []
        try:
            fbo_data = await ozon_client.get_fbo_postings(now - timedelta(minutes=30), now)
            fbo_postings = self._extract_postings(fbo_data)
        except Exception:
            logger.exception(
                "ozon_fbo_poll_failed",
                extra={"account_id": account.id},
            )
        return [
            ozon_client.normalize_fbs_posting(item)
            for item in fbs_postings
            if isinstance(item, dict)
        ] + [
            ozon_client.normalize_fbo_posting(item)
            for item in fbo_postings
            if isinstance(item, dict)
        ]

    async def _queue_fbo_digest(
        self,
        account: MarketplaceAccount,
        order: Order,
        mode: FboNotificationMode,
    ) -> None:
        revenue, estimated_profit = await self.orders.order_totals(order.id)
        await self.fbo_queue.add_once(
            user_id=account.user_id,
            order_id=order.id,
            marketplace=account.marketplace,
            revenue=revenue,
            estimated_profit=estimated_profit,
            mode=mode,
        )

    @staticmethod
    def _extract_postings(data: dict[str, object]) -> list[object]:
        result = data.get("result")
        if isinstance(result, dict):
            postings = result.get("postings")
            return postings if isinstance(postings, list) else []
        return result if isinstance(result, list) else []
