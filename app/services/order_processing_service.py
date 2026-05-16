"""version: 1.4.0
description: Enhanced order ingestion with marketplace-aware notifications.
updated: 2026-05-16
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import IntegrationError
from app.core.logging import LogContext, log_exception
from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount, Order
from app.models.enums import FboNotificationMode, Marketplace
from app.repositories.orders import FboDigestQueueRepository, OrderRepository
from app.schemas.orders import NormalizedOrder
from app.services.order_card_service import OrderCardService
from app.services.order_notification_policy import OrderNotificationPolicyService
from app.services.order_profit_service import OrderProfitService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NewOrderNotification:
    telegram_id: int
    order_id: int
    text: str
    marketplace: Marketplace
    image_url: str | None = None
    product_url: str | None = None
    parse_mode: str | None = "HTML"


@dataclass(slots=True)
class OrderPollResult:
    account_id: int
    marketplace: Marketplace
    fetched: int = 0
    created: int = 0
    duplicated: int = 0
    queued_digest: int = 0
    skipped_by_policy: int = 0
    skipped_without_user: int = 0
    notifications: list[NewOrderNotification] | None = None

    @property
    def notification_count(self) -> int:
        return len(self.notifications or [])


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
        self.cards = OrderCardService(session)

    async def poll_account(self, account: MarketplaceAccount) -> list[NewOrderNotification]:
        result = await self.poll_account_with_stats(account)
        return result.notifications or []

    async def poll_account_with_stats(self, account: MarketplaceAccount) -> OrderPollResult:
        """Poll marketplace account for new orders with comprehensive error handling."""
        with LogContext(
            account_id=account.id,
            marketplace=account.marketplace.value,
            user_id=account.user_id,
        ):
            result = OrderPollResult(
                account_id=account.id,
                marketplace=account.marketplace,
                notifications=[],
            )

            try:
                logger.info("order_poll_started")
                normalized_orders = await self._fetch_orders(account)
                result.fetched = len(normalized_orders)

                policy = await self.notification_policy.resolve(account)

                for normalized in normalized_orders:
                    try:
                        if await self.orders.exists(account.id, normalized):
                            result.duplicated += 1
                            continue

                        order = await self.orders.create(account.user_id, account.id, normalized)
                        result.created += 1

                        await self.profits.calculate_estimated_profit(account, order, normalized)

                        if policy.should_queue_fbo_digest(normalized.sale_model):
                            await self._queue_fbo_digest(account, order, policy.fbo_mode)
                            result.queued_digest += 1
                            continue

                        if not policy.is_instant_enabled_for(normalized.sale_model):
                            result.skipped_by_policy += 1
                            continue

                        first_item = normalized.items[0] if normalized.items else None
                        if not first_item or not account.user:
                            result.skipped_without_user += 1
                            continue

                        if not account.user.notifications_enabled:
                            result.skipped_by_policy += 1
                            continue

                        order_with_items = await self.orders.get_with_items(order.id)
                        item = (
                            order_with_items.items[0]
                            if order_with_items and order_with_items.items
                            else None
                        )

                        if item and order_with_items:
                            card = await self.cards.new_order_card(
                                order=order_with_items,
                                item=item,
                                timezone_name=account.user.timezone,
                            )
                            await self.orders.mark_notified(order.id)
                            result.notifications = result.notifications or []
                            result.notifications.append(
                                NewOrderNotification(
                                    telegram_id=account.user.telegram_id,
                                    order_id=order.id,
                                    text=card.text,
                                    marketplace=account.marketplace,
                                    image_url=card.image_url,
                                    product_url=card.product_url,
                                    parse_mode=card.parse_mode,
                                )
                            )

                    except Exception as exc:
                        log_exception(
                            logger,
                            exc,
                            "order_processing_failed",
                            order_external_id=normalized.order_external_id,
                        )
                        continue

                await self.session.commit()

                logger.info(
                    "order_poll_finished",
                    extra={
                        "fetched": result.fetched,
                        "created": result.created,
                        "duplicates": result.duplicated,
                        "queued_digest": result.queued_digest,
                        "skipped_by_policy": result.skipped_by_policy,
                        "notifications": result.notification_count,
                    },
                )

                return result

            except Exception as exc:
                await self.session.rollback()
                log_exception(logger, exc, "order_poll_failed")
                raise IntegrationError(
                    f"Failed to poll orders for {account.marketplace.value}",
                    details={"account_id": account.id},
                ) from exc

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
