"""version: 1.7.0
description: Order ingestion with resilient poll windows and retryable FBS notifications.
updated: 2026-05-17
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
from app.models.enums import FboNotificationMode, Marketplace, SaleModel
from app.repositories.orders import FboDigestQueueRepository, OrderRepository
from app.schemas.orders import NormalizedOrder
from app.services.order_card_service import OrderCardService
from app.services.order_notification_policy import (
    OrderNotificationPolicy,
    OrderNotificationPolicyService,
)
from app.services.order_profit_service import OrderProfitService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NewOrderNotification:
    telegram_id: int
    user_id: int
    account_id: int
    order_id: int
    text: str
    marketplace: Marketplace
    sale_model: str | None = None
    fulfillment_type: str | None = None
    event_type: str = "new_order"
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
    skipped_without_items: int = 0
    retried_unnotified: int = 0
    recovered_unnotified: int = 0
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

    async def collect_saved_unnotified_notifications(
        self,
        account: MarketplaceAccount,
    ) -> list[NewOrderNotification]:
        """Prepare saved FBS-like order notifications without polling marketplace APIs."""
        result = OrderPollResult(
            account_id=account.id,
            marketplace=account.marketplace,
            notifications=[],
        )
        policy = await self.notification_policy.resolve(account)
        await self._append_saved_unnotified(account, policy, result)
        return result.notifications or []

    async def poll_account_with_stats(self, account: MarketplaceAccount) -> OrderPollResult:
        """Poll marketplace account for new orders with comprehensive error handling."""
        account_id = account.id
        marketplace_value = account.marketplace.value
        user_id = account.user_id

        with LogContext(
            account_id=account_id,
            marketplace=marketplace_value,
            user_id=user_id,
        ):
            result = OrderPollResult(
                account_id=account_id,
                marketplace=account.marketplace,
                notifications=[],
            )

            recovery_failed = False

            try:
                logger.info("order_poll_started")
                normalized_orders, recovery_failed = await self._fetch_orders(account)
                result.fetched = len(normalized_orders)

                policy = await self.notification_policy.resolve(account)

                for normalized in normalized_orders:
                    try:
                        existing_order = await self.orders.get_by_external(
                            account_id=account_id,
                            marketplace=normalized.marketplace,
                            order_external_id=normalized.order_external_id,
                        )
                        if existing_order is not None:
                            result.duplicated += 1
                            if await self._prepare_retry_notification(
                                account=account,
                                order=existing_order,
                                normalized=normalized,
                                policy=policy,
                                result=result,
                            ):
                                result.retried_unnotified += 1
                            elif _is_fbs_like(normalized.sale_model):
                                logger.info(
                                    "fbs_order_duplicate_skipped",
                                    extra={
                                        "account_id": account_id,
                                        "user_id": user_id,
                                        "marketplace": marketplace_value,
                                        "fulfillment_type": normalized.fulfillment_type,
                                        "sale_model": normalized.sale_model.value
                                        if normalized.sale_model
                                        else None,
                                        "order_id": existing_order.id,
                                        "order_external_id": normalized.order_external_id,
                                        "notified": existing_order.first_notified_at is not None,
                                    },
                                )
                            continue

                        order = await self.orders.create(account.user_id, account_id, normalized)
                        result.created += 1
                        logger.info(
                            "order_persisted",
                            extra={
                                "account_id": account_id,
                                "user_id": user_id,
                                "marketplace": marketplace_value,
                                "fulfillment_type": normalized.fulfillment_type,
                                "sale_model": normalized.sale_model.value
                                if normalized.sale_model
                                else None,
                                "order_external_id": normalized.order_external_id,
                            },
                        )
                        if _is_fbs_like(normalized.sale_model):
                            logger.info(
                                "fbs_order_detected_as_new",
                                extra={
                                    "account_id": account_id,
                                    "user_id": user_id,
                                    "marketplace": marketplace_value,
                                    "fulfillment_type": normalized.fulfillment_type,
                                    "sale_model": normalized.sale_model.value
                                    if normalized.sale_model
                                    else None,
                                    "order_id": order.id,
                                    "order_external_id": normalized.order_external_id,
                                },
                            )
                            logger.info(
                                "fbs_order_persisted",
                                extra={
                                    "account_id": account_id,
                                    "user_id": user_id,
                                    "marketplace": marketplace_value,
                                    "fulfillment_type": normalized.fulfillment_type,
                                    "sale_model": normalized.sale_model.value
                                    if normalized.sale_model
                                    else None,
                                    "order_id": order.id,
                                    "order_external_id": normalized.order_external_id,
                                },
                            )

                        await self.profits.calculate_estimated_profit(account, order, normalized)

                        if policy.should_queue_fbo_digest(normalized.sale_model):
                            await self._queue_fbo_digest(account, order, policy.fbo_mode)
                            result.queued_digest += 1
                            continue

                        if not policy.is_instant_enabled_for(normalized.sale_model):
                            result.skipped_by_policy += 1
                            continue

                        first_item = normalized.items[0] if normalized.items else None
                        if not first_item:
                            result.skipped_without_items += 1
                            continue
                        if not account.user:
                            result.skipped_without_user += 1
                            continue

                        if not account.user.notifications_enabled:
                            result.skipped_by_policy += 1
                            continue

                        await self._append_notification(account, order, result)

                    except Exception as exc:
                        log_exception(
                            logger,
                            exc,
                            "order_processing_failed",
                            order_external_id=normalized.order_external_id,
                        )
                        continue

                await self._append_saved_unnotified(account, policy, result)

                now = datetime.now(tz=UTC)
                account.last_order_poll_at = now
                account.last_orders_sync_at = now

                if recovery_failed:
                    logger.warning(
                        "order_poll_completed_with_recovery_warning",
                        extra={
                            "account_id": account_id,
                            "user_id": user_id,
                            "marketplace": marketplace_value,
                            "reason": "recovery_poll_failed",
                            "last_order_poll_at": now.isoformat(),
                        },
                    )
                else:
                    account.last_success_sync_at = now
                    logger.info(
                        "order_poll_timestamp_updated",
                        extra={
                            "account_id": account_id,
                            "marketplace": marketplace_value,
                            "last_order_poll_at": now.isoformat(),
                        },
                    )
                await self.session.commit()

                logger.info(
                    "order_poll_finished",
                    extra={
                        "orders_fetched": result.fetched,
                        "orders_created": result.created,
                        "orders_duplicated": result.duplicated,
                        "queued_digest": result.queued_digest,
                        "skipped_by_policy": result.skipped_by_policy,
                        "retried_unnotified": result.retried_unnotified,
                        "recovered_unnotified": result.recovered_unnotified,
                        "notifications_prepared": result.notification_count,
                        "recovery_failed": recovery_failed,
                    },
                )

                return result

            except Exception as exc:
                await self.session.rollback()
                log_exception(
                    logger,
                    exc,
                    "order_poll_failed",
                    account_id=account_id,
                    user_id=user_id,
                    marketplace=marketplace_value,
                )
                raise IntegrationError(
                    f"Failed to poll orders for {marketplace_value}",
                    details={"account_id": account_id},
                ) from exc

    async def _fetch_orders(self, account: MarketplaceAccount) -> tuple[list[NormalizedOrder], bool]:
        """Fetch orders from marketplace. Returns (orders, recovery_failed)."""
        if account.marketplace == Marketplace.WB:
            api_key = self.cipher.decrypt(account.encrypted_api_key)
            wb_client = WildberriesClient(api_key)
            now = datetime.now(tz=UTC)
            raw_orders = await wb_client.get_new_fbs_orders()
            logger.info(
                "wb_fbs_new_orders_polled",
                extra={
                    "account_id": account.id,
                    "user_id": account.user_id,
                    "marketplace": account.marketplace.value,
                    "source": "wb_orders_new",
                    "count": len(raw_orders),
                },
            )
            normalized_orders = [
                _log_normalized_order(wb_client.normalize_fbs_order(item), account)
                for item in raw_orders
            ]
            seen_order_ids = {order.order_external_id for order in normalized_orders}
            logger.info(
                "wb_live_orders_poll_completed",
                extra={
                    "account_id": account.id,
                    "marketplace": account.marketplace.value,
                    "live_orders_count": len(normalized_orders),
                },
            )
            recovery_failed = False
            try:
                window_start = self._poll_window_start(account, now)
                logger.info(
                    "wb_fbs_period_poll_started",
                    extra={
                        "account_id": account.id,
                        "marketplace": account.marketplace.value,
                        "window_start": window_start.isoformat(),
                        "window_end": now.isoformat(),
                        "last_poll_at": account.last_order_poll_at.isoformat()
                        if account.last_order_poll_at
                        else None,
                    },
                )
                recovered_orders = await wb_client.get_fbs_orders(
                    date_from=window_start,
                    date_to=now,
                )
                logger.info(
                    "wb_fbs_period_poll_finished",
                    extra={
                        "account_id": account.id,
                        "user_id": account.user_id,
                        "marketplace": account.marketplace.value,
                        "orders_count": len(recovered_orders),
                    },
                )
                dedup_count = 0
                for item in recovered_orders:
                    normalized = wb_client.normalize_historical_fbs_order(item)
                    if normalized.order_external_id in seen_order_ids:
                        dedup_count += 1
                        continue
                    seen_order_ids.add(normalized.order_external_id)
                    normalized_orders.append(_log_normalized_order(normalized, account))
                if dedup_count > 0:
                    logger.info(
                        "wb_period_poll_dedup",
                        extra={
                            "account_id": account.id,
                            "marketplace": account.marketplace.value,
                            "recovered_count": len(recovered_orders),
                            "deduplicated": dedup_count,
                            "unique_added": len(recovered_orders) - dedup_count,
                        },
                    )
            except Exception:
                recovery_failed = True
                logger.exception(
                    "wb_fbs_period_poll_failed",
                    extra={
                        "account_id": account.id,
                        "user_id": account.user_id,
                        "marketplace": account.marketplace.value,
                    },
                )
            return normalized_orders, recovery_failed

        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client_id = self.cipher.decrypt(account.encrypted_client_id or "")
        ozon_client = OzonClient(client_id=client_id, api_key=api_key)
        now = datetime.now(tz=UTC)
        date_from = self._poll_window_start(account, now)
        fbs_data = await ozon_client.get_fbs_postings(date_from, now)
        fbs_postings = self._extract_postings(fbs_data)
        logger.info(
            "fbs_order_polled",
            extra={
                "account_id": account.id,
                "user_id": account.user_id,
                "marketplace": account.marketplace.value,
                "source": "ozon_fbs_list",
                "count": len(fbs_postings),
            },
        )
        try:
            unfulfilled_data = await ozon_client.get_fbs_unfulfilled(
                now - timedelta(days=1),
                now + timedelta(days=14),
            )
            unfulfilled_postings = self._extract_postings(unfulfilled_data)
            logger.info(
                "fbs_order_polled",
                extra={
                    "account_id": account.id,
                    "user_id": account.user_id,
                    "marketplace": account.marketplace.value,
                    "source": "ozon_fbs_unfulfilled",
                    "count": len(unfulfilled_postings),
                },
            )
            fbs_postings = self._merge_postings(fbs_postings, unfulfilled_postings)
        except Exception:
            logger.exception(
                "ozon_fbs_unfulfilled_poll_failed",
                extra={"account_id": account.id, "user_id": account.user_id},
            )
        fbo_postings: list[object] = []
        try:
            fbo_data = await ozon_client.get_fbo_postings(date_from, now)
            fbo_postings = self._extract_postings(fbo_data)
            logger.info(
                "fbo_order_polled",
                extra={
                    "account_id": account.id,
                    "user_id": account.user_id,
                    "marketplace": account.marketplace.value,
                    "source": "ozon_fbo_list",
                    "count": len(fbo_postings),
                },
            )
        except Exception:
            logger.exception(
                "ozon_fbo_poll_failed",
                extra={"account_id": account.id},
            )
        normalized_fbs = [
            _log_normalized_order(ozon_client.normalize_fbs_posting(item), account)
            for item in fbs_postings
            if isinstance(item, dict)
        ]
        normalized_fbo = [
            ozon_client.normalize_fbo_posting(item)
            for item in fbo_postings
            if isinstance(item, dict)
        ]
        logger.info(
            "ozon_poll_summary",
            extra={
                "account_id": account.id,
                "marketplace": account.marketplace.value,
                "fbs_normalized": len(normalized_fbs),
                "fbo_normalized": len(normalized_fbo),
                "total": len(normalized_fbs) + len(normalized_fbo),
            },
        )
        logger.info(
            "ozon_order_poll_completed",
            extra={
                "account_id": account.id,
                "marketplace": account.marketplace.value,
                "total_orders": len(normalized_fbs) + len(normalized_fbo),
            },
        )
        return normalized_fbs + normalized_fbo, False

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

    async def _prepare_retry_notification(
        self,
        *,
        account: MarketplaceAccount,
        order: Order,
        normalized: NormalizedOrder,
        policy: OrderNotificationPolicy,
        result: OrderPollResult,
    ) -> bool:
        if order.first_notified_at is not None:
            return False
        if policy.should_queue_fbo_digest(normalized.sale_model):
            return False
        if not policy.is_instant_enabled_for(normalized.sale_model):
            result.skipped_by_policy += 1
            return False
        if not account.user or not account.user.notifications_enabled:
            result.skipped_without_user += 1
            return False
        await self._append_notification(account, order, result)
        logger.info(
            "unnotified_order_notification_retried",
            extra={
                "account_id": account.id,
                "user_id": account.user_id,
                "marketplace": account.marketplace.value,
                "fulfillment_type": normalized.fulfillment_type,
                "sale_model": normalized.sale_model.value if normalized.sale_model else None,
                "order_id": order.id,
                "order_external_id": normalized.order_external_id,
            },
        )
        if _is_fbs_like(normalized.sale_model):
            logger.info(
                "fbs_order_duplicate_with_unsent_notification_requeued",
                extra={
                    "account_id": account.id,
                    "user_id": account.user_id,
                    "marketplace": account.marketplace.value,
                    "fulfillment_type": normalized.fulfillment_type,
                    "sale_model": normalized.sale_model.value if normalized.sale_model else None,
                    "order_id": order.id,
                    "order_external_id": normalized.order_external_id,
                },
            )
        return True

    async def _append_saved_unnotified(
        self,
        account: MarketplaceAccount,
        policy: OrderNotificationPolicy,
        result: OrderPollResult,
    ) -> None:
        prepared_ids = {notification.order_id for notification in result.notifications or []}
        pending = await self.orders.pending_unnotified_for_account(
            account_id=account.id,
            sale_models={
                SaleModel.FBS, SaleModel.RFBS,
                SaleModel.DBS, SaleModel.DBW,
                SaleModel.FBO,
            },
            limit=100,
        )
        for order in pending:
            if order.id in prepared_ids:
                continue
            if order.sale_model == SaleModel.FBO and not policy.fbo_enabled:
                result.skipped_by_policy += 1
                continue
            is_fbo = order.sale_model == SaleModel.FBO
            if not is_fbo and not policy.is_instant_enabled_for(order.sale_model):
                result.skipped_by_policy += 1
                continue
            if not account.user or not account.user.notifications_enabled:
                result.skipped_without_user += 1
                continue
            try:
                await self._append_notification(account, order, result)
                result.recovered_unnotified += 1
                prepared_ids.add(order.id)
                logger.info(
                    "saved_unnotified_order_notification_requeued",
                    extra={
                        "account_id": account.id,
                        "user_id": account.user_id,
                        "marketplace": account.marketplace.value,
                        "fulfillment_type": order.fulfillment_type,
                        "sale_model": order.sale_model.value if order.sale_model else None,
                        "order_id": order.id,
                        "order_external_id": order.order_external_id,
                    },
                )
            except Exception:
                logger.exception(
                    "saved_unnotified_order_card_failed",
                    extra={
                        "account_id": account.id,
                        "user_id": account.user_id,
                        "marketplace": account.marketplace.value,
                        "order_id": order.id,
                        "order_external_id": order.order_external_id,
                    },
                )

    async def _append_notification(
        self,
        account: MarketplaceAccount,
        order: Order,
        result: OrderPollResult,
    ) -> None:
        if not account.user:
            result.skipped_without_user += 1
            return
        order_with_items = await self.orders.get_with_items(order.id)
        item = order_with_items.items[0] if order_with_items and order_with_items.items else None
        if item is None or order_with_items is None:
            result.skipped_without_items += 1
            logger.warning(
                "order_notification_skipped_without_items",
                extra={
                    "account_id": account.id,
                    "user_id": account.user_id,
                    "marketplace": account.marketplace.value,
                    "order_id": order.id,
                },
            )
            return
        card = await self.cards.new_order_card(
            order=order_with_items,
            item=item,
            timezone_name=account.user.timezone,
        )
        result.notifications = result.notifications or []
        result.notifications.append(
            NewOrderNotification(
                telegram_id=account.user.telegram_id,
                user_id=account.user_id,
                account_id=account.id,
                order_id=order.id,
                text=card.text,
                marketplace=account.marketplace,
                sale_model=order.sale_model.value if order.sale_model else None,
                fulfillment_type=order.fulfillment_type,
                image_url=card.image_url,
                product_url=card.product_url,
                parse_mode=card.parse_mode,
            )
        )
        logger.info(
            "order_notification_prepared",
            extra={
                "account_id": account.id,
                "user_id": account.user_id,
                "telegram_id": account.user.telegram_id,
                "marketplace": account.marketplace.value,
                "sale_model": order.sale_model.value if order.sale_model else None,
                "fulfillment_type": order.fulfillment_type,
                "order_id": order.id,
                "order_external_id": order.order_external_id,
            },
        )
        if _is_fbs_like(order.sale_model):
            logger.info(
                "fbs_order_notification_prepared",
                extra={
                    "account_id": account.id,
                    "user_id": account.user_id,
                    "telegram_id": account.user.telegram_id,
                    "marketplace": account.marketplace.value,
                    "sale_model": order.sale_model.value if order.sale_model else None,
                    "fulfillment_type": order.fulfillment_type,
                    "order_id": order.id,
                    "order_external_id": order.order_external_id,
                },
            )

    @staticmethod
    def _extract_postings(data: dict[str, object]) -> list[object]:
        result = data.get("result")
        if isinstance(result, dict):
            postings = result.get("postings")
            return postings if isinstance(postings, list) else []
        return result if isinstance(result, list) else []

    @staticmethod
    def _merge_postings(*groups: list[object]) -> list[object]:
        merged: list[object] = []
        seen: set[str] = set()
        for group in groups:
            for item in group:
                key = None
                if isinstance(item, dict):
                    key = str(item.get("posting_number") or item.get("id") or "")
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                merged.append(item)
        return merged

    @staticmethod
    def _poll_window_start(account: MarketplaceAccount, now: datetime) -> datetime:
        if account.last_order_poll_at is None:
            return now - timedelta(hours=24)
        return max(account.last_order_poll_at - timedelta(minutes=10), now - timedelta(days=7))


def _is_fbs_like(sale_model: SaleModel | None) -> bool:
    return sale_model in {SaleModel.FBS, SaleModel.RFBS, SaleModel.DBS, SaleModel.DBW}


def _log_normalized_order(order: NormalizedOrder, account: MarketplaceAccount) -> NormalizedOrder:
    if _is_fbs_like(order.sale_model):
        logger.info(
            "fbs_order_normalized",
            extra={
                "account_id": account.id,
                "user_id": account.user_id,
                "marketplace": account.marketplace.value,
                "fulfillment_type": order.fulfillment_type,
                "sale_model": order.sale_model.value if order.sale_model else None,
                "order_external_id": order.order_external_id,
                "requires_seller_action": order.requires_seller_action,
                "normalized_status": order.normalized_status,
                "source_event_type": order.source_event_type.value
                if order.source_event_type
                else None,
            },
        )
    return order
