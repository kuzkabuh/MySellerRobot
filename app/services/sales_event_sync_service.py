"""version: 1.3.0
description: Synchronize marketplace buyout, WB daily sales reports, and completed sale events.
updated: 2026-05-17
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import (
    MarketplaceAccount,
    Order,
    OrderItem,
    ProfitSnapshot,
    ReturnsEvent,
    SalesEvent,
    User,
)
from app.models.enums import CalculationType, Marketplace, NotificationType, SaleModel
from app.repositories.events import ReturnsEventRepository, SalesEventRepository
from app.repositories.orders import OrderRepository
from app.repositories.products import ProductRepository
from app.schemas.orders import NormalizedOrder
from app.schemas.sales import NormalizedSaleEvent
from app.services.message_formatter import rub
from app.services.order_card_service import OrderCardService
from app.services.order_profit_service import OrderProfitService
from app.utils.datetime import format_datetime_for_user

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SalesSyncResult:
    account_id: int
    marketplace: Marketplace
    orders_fetched: int = 0
    orders_created: int = 0
    orders_updated: int = 0
    sales_fetched: int = 0
    sales_created: int = 0
    sales_updated: int = 0
    returns_fetched: int = 0
    returns_created: int = 0
    returns_updated: int = 0
    failed: int = 0


@dataclass(slots=True)
class SaleNotification:
    event_id: int
    user_id: int
    account_id: int
    telegram_id: int
    text: str
    marketplace: Marketplace
    event_type: str
    external_event_id: str
    image_url: str | None = None
    product_url: str | None = None
    parse_mode: str | None = "HTML"


@dataclass(slots=True)
class OrderLifecycleNotification:
    event_id: int
    user_id: int
    account_id: int
    telegram_id: int
    text: str
    marketplace: Marketplace
    event_type: str
    external_event_id: str
    order_id: int | None = None
    image_url: str | None = None
    product_url: str | None = None
    parse_mode: str | None = "HTML"


class SalesEventSyncService:
    """Import completed sales and prepare buyout notifications."""

    completed_ozon_statuses = {"delivered", "completed", "received"}

    def __init__(self, session: AsyncSession, cipher: TokenCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()
        self.orders = OrderRepository(session)
        self.sales = SalesEventRepository(session)
        self.returns = ReturnsEventRepository(session)
        self.profits = OrderProfitService(session)
        self.products = ProductRepository(session)
        self.cards = OrderCardService(session)

    async def sync_account(
        self,
        account: MarketplaceAccount,
        *,
        lookback_hours: int = 72,
    ) -> SalesSyncResult:
        date_from = datetime.now(tz=UTC) - timedelta(hours=lookback_hours)
        if account.marketplace == Marketplace.WB:
            return await self._sync_wb(account, date_from)
        return await self._sync_ozon(account, date_from, datetime.now(tz=UTC))

    async def pending_notifications(self, limit: int = 100) -> list[SaleNotification]:
        result = await self.session.execute(
            select(SalesEvent, MarketplaceAccount, User)
            .outerjoin(
                MarketplaceAccount,
                MarketplaceAccount.id == SalesEvent.marketplace_account_id,
            )
            .outerjoin(User, User.id == SalesEvent.user_id)
            .where(SalesEvent.notification_sent_at.is_(None))
            .order_by(SalesEvent.event_date.asc())
            .limit(limit)
        )
        notifications: list[SaleNotification] = []
        for row, account, user in result.all():
            if account is None or user is None:
                logger.warning(
                    "sale_notification_skipped_without_user",
                    extra={
                        "event_id": row.id,
                        "event_type": row.event_type.value,
                        "marketplace": row.marketplace.value,
                        "account_id": row.marketplace_account_id,
                        "user_id": row.user_id,
                        "external_event_id": row.external_event_id,
                    },
                )
                continue
            if not user.notifications_enabled:
                logger.info(
                    "sale_notification_skipped_by_user_settings",
                    extra={
                        "event_id": row.id,
                        "event_type": row.event_type.value,
                        "marketplace": row.marketplace.value,
                        "account_id": account.id,
                        "user_id": user.id,
                        "external_event_id": row.external_event_id,
                    },
                )
                continue
            if not self._buyout_notifications_enabled(account):
                logger.info(
                    "sale_notification_skipped_by_account_settings",
                    extra={
                        "event_id": row.id,
                        "event_type": row.event_type.value,
                        "marketplace": row.marketplace.value,
                        "account_id": account.id,
                        "user_id": user.id,
                        "external_event_id": row.external_event_id,
                    },
                )
                continue
            try:
                card = await self.cards.buyout_card(event=row, timezone_name=user.timezone)
            except Exception as exc:
                logger.exception(
                    "sale_notification_card_failed",
                    extra={
                        "event_id": row.id,
                        "event_type": row.event_type.value,
                        "marketplace": row.marketplace.value,
                        "account_id": account.id,
                        "user_id": user.id,
                        "external_event_id": row.external_event_id,
                        "exception_class": type(exc).__name__,
                        "error": str(exc)[:300],
                    },
                )
                continue
            notifications.append(
                SaleNotification(
                    event_id=row.id,
                    user_id=user.id,
                    account_id=account.id,
                    telegram_id=user.telegram_id,
                    text=card.text,
                    marketplace=account.marketplace,
                    event_type=row.event_type.value,
                    external_event_id=row.external_event_id,
                    image_url=card.image_url,
                    product_url=card.product_url,
                    parse_mode=card.parse_mode,
                )
            )
        return notifications

    async def mark_notified(self, event_id: int) -> None:
        await self.sales.mark_notified(event_id)

    async def pending_order_lifecycle_notifications(
        self,
        limit: int = 100,
    ) -> list[OrderLifecycleNotification]:
        notifications: list[OrderLifecycleNotification] = []
        notifications.extend(await self._pending_cancel_notifications(limit=limit))
        remaining = max(limit - len(notifications), 0)
        if remaining:
            notifications.extend(await self._pending_return_notifications(limit=remaining))
        return notifications

    async def mark_lifecycle_notified(
        self,
        *,
        event_type: str,
        event_id: int,
    ) -> None:
        if event_type == NotificationType.RETURN_CREATED.value:
            await self.returns.mark_notified(event_id)
            return
        await self.orders.mark_cancellation_notified(event_id)

    async def _sync_wb(
        self,
        account: MarketplaceAccount,
        date_from: datetime,
    ) -> SalesSyncResult:
        account_id = account.id
        user_id = account.user_id
        marketplace = account.marketplace.value
        result = SalesSyncResult(account_id=account_id, marketplace=account.marketplace)
        client = WildberriesClient(self.cipher.decrypt(account.encrypted_api_key))
        try:
            orders = await client.get_supplier_orders(date_from)
            result.orders_fetched = len(orders)
            logger.info(
                "wb_statistics_orders_fetched",
                extra={
                    "account_id": account_id,
                    "user_id": user_id,
                    "marketplace": marketplace,
                    "orders_fetched": result.orders_fetched,
                    "date_from": date_from.isoformat(),
                },
            )
            for payload in orders:
                normalized = client.normalize_statistics_order(payload)
                created = await self._upsert_order_with_profit(account, normalized)
                result.orders_created += int(created)
                result.orders_updated += int(not created)
        except Exception as exc:
            result.failed += 1
            logger.exception(
                "wb_statistics_orders_sync_failed",
                extra={
                    "account_id": account_id,
                    "user_id": user_id,
                    "marketplace": marketplace,
                    "exception_class": type(exc).__name__,
                    "error": str(exc)[:500],
                },
            )
            await self.session.rollback()
        try:
            sales = await client.get_supplier_sales(date_from)
            result.sales_fetched = len(sales)
            logger.info(
                "wb_supplier_sales_fetched",
                extra={
                    "account_id": account_id,
                    "user_id": user_id,
                    "marketplace": marketplace,
                    "sales_fetched": result.sales_fetched,
                    "date_from": date_from.isoformat(),
                },
            )
            sales_as_buyouts = 0
            sales_as_returns = 0
            for payload in sales:
                if client.is_supplier_sales_return(payload):
                    sales_as_returns += 1
                    return_event, created = await self._upsert_return_event(
                        account,
                        client.normalize_supplier_return(payload),
                    )
                    result.returns_fetched += 1
                    result.returns_created += int(created)
                    result.returns_updated += int(not created)
                    logger.debug(
                        "wb_return_event_synced",
                        extra={"event_id": return_event.id},
                    )
                    continue
                sales_as_buyouts += 1
                row, created = await self._upsert_sale_event(
                    account,
                    client.normalize_supplier_sale(payload),
                )
                result.sales_created += int(created)
                result.sales_updated += int(not created)
                logger.debug("wb_sale_event_synced", extra={"event_id": row.id})
            logger.info(
                "wb_supplier_sales_categorized",
                extra={
                    "account_id": account_id,
                    "marketplace": marketplace,
                    "total_fetched": result.sales_fetched,
                    "categorized_as_buyouts": sales_as_buyouts,
                    "categorized_as_returns": sales_as_returns,
                    "sales_created": result.sales_created,
                    "sales_updated": result.sales_updated,
                    "returns_created": result.returns_created,
                    "returns_updated": result.returns_updated,
                },
            )
        except Exception as exc:
            result.failed += 1
            logger.exception(
                "wb_supplier_sales_sync_failed",
                extra={
                    "account_id": account_id,
                    "user_id": user_id,
                    "marketplace": marketplace,
                    "exception_class": type(exc).__name__,
                    "error": str(exc)[:500],
                },
            )
            await self.session.rollback()
        await self.session.commit()
        now = datetime.now(tz=UTC)
        account.last_sales_sync_at = now
        account.last_success_sync_at = now
        logger.info(
            "wb_sale_sync_completed",
            extra={
                "account_id": account_id,
                "marketplace": marketplace,
                "orders_fetched": result.orders_fetched,
                "orders_created": result.orders_created,
                "sales_fetched": result.sales_fetched,
                "sales_created": result.sales_created,
                "returns_created": result.returns_created,
                "failed": result.failed,
            },
        )
        return result

    async def sync_wb_sales_report_day(
        self,
        account: MarketplaceAccount,
        report_date: date,
    ) -> SalesSyncResult:
        result = SalesSyncResult(account_id=account.id, marketplace=account.marketplace)
        if account.marketplace != Marketplace.WB:
            return result
        client = WildberriesClient(self.cipher.decrypt(account.encrypted_api_key))
        logger.info(
            "daily_wb_sales_sync_started",
            extra={
                "account_id": account.id,
                "user_id": account.user_id,
                "report_date": report_date.isoformat(),
            },
        )
        try:
            rows = await client.get_supplier_sales_for_day(report_date)
            result.sales_fetched = len(rows)
            for payload in rows:
                if client.is_supplier_sales_return(payload):
                    result.returns_fetched += 1
                    _, created = await self._upsert_return_event(
                        account,
                        client.normalize_supplier_return(payload),
                    )
                    result.returns_created += int(created)
                    result.returns_updated += int(not created)
                    continue
                row, created = await self._upsert_sale_event(
                    account,
                    client.normalize_supplier_sale(payload),
                )
                result.sales_created += int(created)
                result.sales_updated += int(not created)
                logger.debug("wb_daily_sale_event_synced", extra={"event_id": row.id})
            await self.session.commit()
        except Exception:
            result.failed += 1
            logger.exception(
                "daily_wb_sales_sync_failed",
                extra={"account_id": account.id, "report_date": report_date.isoformat()},
            )
            await self.session.rollback()
            raise
        logger.info(
            "daily_wb_sales_sync_completed",
            extra={
                "account_id": account.id,
                "user_id": account.user_id,
                "report_date": report_date.isoformat(),
                "fetched": result.sales_fetched,
                "sales_created": result.sales_created,
                "updated": result.sales_updated,
                "returns_created": result.returns_created,
                "returns_updated": result.returns_updated,
                "failed": result.failed,
            },
        )
        return result

    async def _sync_ozon(
        self,
        account: MarketplaceAccount,
        date_from: datetime,
        date_to: datetime,
    ) -> SalesSyncResult:
        account_id = account.id
        user_id = account.user_id
        marketplace = account.marketplace.value
        result = SalesSyncResult(account_id=account_id, marketplace=account.marketplace)
        client = OzonClient(
            client_id=self.cipher.decrypt(account.encrypted_client_id or ""),
            api_key=self.cipher.decrypt(account.encrypted_api_key),
        )
        for fetcher, normalizer, sale_model in [
            (client.get_fbs_postings, client.normalize_fbs_posting, None),
            (client.get_fbo_postings, client.normalize_fbo_posting, SaleModel.FBO),
        ]:
            try:
                offset = 0
                while True:
                    data = await fetcher(date_from, date_to, limit=100, offset=offset)
                    postings = self._extract_postings(data)
                    if not postings:
                        break
                    result.orders_fetched += len(postings)
                    logger.info(
                        "ozon_sale_orders_fetched",
                        extra={
                            "account_id": account_id,
                            "user_id": user_id,
                            "marketplace": marketplace,
                            "postings_fetched": len(postings),
                            "offset": offset,
                        },
                    )
                    for payload in postings:
                        if not isinstance(payload, dict):
                            continue
                        normalized = normalizer(payload)
                        created = await self._upsert_order_with_profit(account, normalized)
                        result.orders_created += int(created)
                        result.orders_updated += int(not created)
                        status = str(payload.get("status") or "").lower()
                        if status not in self.completed_ozon_statuses:
                            continue
                        model = sale_model or normalized.sale_model or SaleModel.FBS
                        for event in client.normalize_completed_sale_events(
                            payload,
                            sale_model=model,
                        ):
                            _, event_created = await self._upsert_sale_event(account, event)
                            result.sales_fetched += 1
                            result.sales_created += int(event_created)
                            result.sales_updated += int(not event_created)
                    if len(postings) < 100:
                        break
                    offset += 100
            except Exception as exc:
                result.failed += 1
                logger.exception(
                    "ozon_completed_sales_sync_failed",
                    extra={
                        "account_id": account_id,
                        "user_id": user_id,
                        "marketplace": marketplace,
                        "exception_class": type(exc).__name__,
                        "error": str(exc)[:500],
                    },
                )
                await self.session.rollback()
        try:
            returns_data = await client.get_returns(date_from=date_from, date_to=date_to)
            for row in self._extract_returns(returns_data):
                return_event, created = await self._upsert_ozon_return_event(account, row)
                result.returns_fetched += 1
                result.returns_created += int(created)
                result.returns_updated += int(not created)
                logger.debug(
                    "ozon_return_event_synced",
                    extra={"event_id": return_event.id},
                )
        except Exception as exc:
            result.failed += 1
            logger.exception(
                "ozon_returns_sync_failed",
                extra={
                    "account_id": account_id,
                    "user_id": user_id,
                    "marketplace": marketplace,
                    "exception_class": type(exc).__name__,
                    "error": str(exc)[:500],
                },
            )
            await self.session.rollback()
        await self.session.commit()
        now = datetime.now(tz=UTC)
        account.last_sales_sync_at = now
        account.last_success_sync_at = now
        logger.info(
            "ozon_sale_sync_completed",
            extra={
                "account_id": account_id,
                "marketplace": marketplace,
                "orders_fetched": result.orders_fetched,
                "orders_created": result.orders_created,
                "sales_fetched": result.sales_fetched,
                "sales_created": result.sales_created,
                "returns_created": result.returns_created,
                "failed": result.failed,
            },
        )
        return result

    async def _pending_cancel_notifications(
        self,
        *,
        limit: int,
    ) -> list[OrderLifecycleNotification]:
        orders = await self.orders.pending_cancelled_unnotified(limit=limit)
        notifications: list[OrderLifecycleNotification] = []
        account_ids = {order.marketplace_account_id for order in orders}
        accounts = await self._accounts_by_id(account_ids)
        users = await self._users_by_id({order.user_id for order in orders})
        for order in orders:
            account = accounts.get(order.marketplace_account_id)
            user = users.get(order.user_id)
            if account is None or user is None:
                logger.warning(
                    "cancel_notification_skipped_without_user",
                    extra=_lifecycle_log_extra(order, NotificationType.ORDER_CANCELLED.value),
                )
                continue
            if not user.notifications_enabled:
                continue
            if not self._lifecycle_notifications_enabled(
                account,
                NotificationType.ORDER_CANCELLED,
            ):
                continue
            item = order.items[0] if order.items else None
            try:
                card = await self.cards.cancellation_card(
                    order=order,
                    item=item,
                    timezone_name=user.timezone,
                )
            except Exception as exc:
                logger.exception(
                    "cancel_notification_card_failed",
                    extra={
                        **_lifecycle_log_extra(order, NotificationType.ORDER_CANCELLED.value),
                        "exception_class": type(exc).__name__,
                        "error": str(exc)[:300],
                    },
                )
                continue
            notifications.append(
                OrderLifecycleNotification(
                    event_id=order.id,
                    user_id=user.id,
                    account_id=order.marketplace_account_id,
                    telegram_id=user.telegram_id,
                    text=card.text,
                    marketplace=order.marketplace,
                    event_type=NotificationType.ORDER_CANCELLED.value,
                    external_event_id=order.order_external_id,
                    order_id=order.id,
                    image_url=card.image_url,
                    product_url=card.product_url,
                    parse_mode=card.parse_mode,
                )
            )
        return notifications

    async def _pending_return_notifications(
        self,
        *,
        limit: int,
    ) -> list[OrderLifecycleNotification]:
        events = await self.returns.pending_notifications(limit=limit)
        notifications: list[OrderLifecycleNotification] = []
        account_ids = {event.marketplace_account_id for event in events}
        accounts = await self._accounts_by_id(account_ids)
        users = await self._users_by_id({event.user_id for event in events})
        for event in events:
            account = accounts.get(event.marketplace_account_id)
            user = users.get(event.user_id)
            if account is None or user is None:
                logger.warning(
                    "return_notification_skipped_without_user",
                    extra=_return_log_extra(event),
                )
                continue
            if not user.notifications_enabled:
                continue
            if not self._lifecycle_notifications_enabled(account, NotificationType.RETURN_CREATED):
                continue
            try:
                card = await self.cards.return_card(event=event, timezone_name=user.timezone)
            except Exception as exc:
                logger.exception(
                    "return_notification_card_failed",
                    extra={
                        **_return_log_extra(event),
                        "exception_class": type(exc).__name__,
                        "error": str(exc)[:300],
                    },
                )
                continue
            notifications.append(
                OrderLifecycleNotification(
                    event_id=event.id,
                    user_id=user.id,
                    account_id=event.marketplace_account_id,
                    telegram_id=user.telegram_id,
                    text=card.text,
                    marketplace=event.marketplace,
                    event_type=NotificationType.RETURN_CREATED.value,
                    external_event_id=event.external_event_id,
                    order_id=None,
                    image_url=card.image_url,
                    product_url=card.product_url,
                    parse_mode=card.parse_mode,
                )
            )
        return notifications

    async def _accounts_by_id(self, ids: set[int]) -> dict[int, MarketplaceAccount]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(MarketplaceAccount).where(MarketplaceAccount.id.in_(ids))
        )
        return {account.id: account for account in result.scalars().all()}

    async def _users_by_id(self, ids: set[int]) -> dict[int, User]:
        if not ids:
            return {}
        result = await self.session.execute(select(User).where(User.id.in_(ids)))
        return {user.id: user for user in result.scalars().all()}

    async def _upsert_order_with_profit(
        self,
        account: MarketplaceAccount,
        normalized: NormalizedOrder,
    ) -> bool:
        order, created = await self.orders.upsert(account.user_id, account.id, normalized)
        await self.session.execute(
            delete(ProfitSnapshot).where(
                ProfitSnapshot.order_item_id.in_(
                    select(OrderItem.id).where(OrderItem.order_id == order.id)
                ),
                ProfitSnapshot.calculation_type == CalculationType.ESTIMATED,
            )
        )
        await self.profits.calculate_estimated_profit(
            account,
            order,
            normalized,
            calculation_source="statistics_estimated",
        )
        return created

    async def _upsert_sale_event(
        self,
        account: MarketplaceAccount,
        event: NormalizedSaleEvent,
    ) -> tuple[SalesEvent, bool]:
        related_order = await self.orders.get_by_external(
            account_id=account.id,
            marketplace=event.marketplace,
            order_external_id=event.order_external_id,
        )
        related_item_id: int | None = None
        product_id: int | None = None
        estimated_profit: Decimal | None = None
        if related_order is not None:
            related_item_id = related_order.items[0].id if related_order.items else None
            _, estimated_profit = await self.orders.order_totals(related_order.id)
            product_id = related_order.items[0].product_id if related_order.items else None
        if product_id is None:
            product = await self.products.find_for_order_item(
                account_id=account.id,
                marketplace=account.marketplace,
                seller_article=event.seller_article,
                marketplace_article=event.marketplace_article,
                external_product_id=event.external_product_id,
            )
            product_id = product.id if product else None
        return await self.sales.upsert_normalized(
            user_id=account.user_id,
            account_id=account.id,
            event=event,
            related_order_id=related_order.id if related_order else None,
            related_order_item_id=related_item_id,
            product_id=product_id,
            estimated_profit=estimated_profit,
        )

    async def _upsert_return_event(
        self,
        account: MarketplaceAccount,
        event: dict[str, object],
    ) -> tuple[ReturnsEvent, bool]:
        order_external_id = event.get("order_external_id")
        event_date = event.get("event_date")
        amount = event.get("amount")
        reason = event.get("reason")
        raw_payload = event.get("raw_payload")
        return await self.returns.upsert(
            user_id=account.user_id,
            account_id=account.id,
            marketplace=account.marketplace,
            external_event_id=str(event["external_event_id"]),
            order_external_id=order_external_id if isinstance(order_external_id, str) else None,
            event_date=event_date if isinstance(event_date, datetime) else datetime.now(tz=UTC),
            quantity=_int_value(event.get("quantity"), default=1),
            amount=amount if isinstance(amount, Decimal) else Decimal(str(amount or 0)),
            reason=reason if isinstance(reason, str) else None,
            raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
        )

    async def _upsert_ozon_return_event(
        self,
        account: MarketplaceAccount,
        row: dict[str, object],
    ) -> tuple[ReturnsEvent, bool]:
        event_date = _parse_return_date(
            row.get("created_at") or row.get("returned_at") or row.get("updated_at")
        )
        external_id = str(
            row.get("return_id")
            or row.get("id")
            or row.get("posting_number")
            or f"ozon-return-{account.id}-{event_date.isoformat()}"
        )
        return await self.returns.upsert(
            user_id=account.user_id,
            account_id=account.id,
            marketplace=Marketplace.OZON,
            external_event_id=external_id,
            order_external_id=str(row.get("posting_number") or "") or None,
            event_date=event_date,
            quantity=_int_value(row.get("quantity"), default=1),
            amount=Decimal(str(row.get("price") or row.get("amount") or 0)),
            reason=str(row.get("return_reason_name") or row.get("reason") or "") or None,
            raw_payload=dict(row),
        )

    @staticmethod
    def _extract_postings(data: dict[str, object]) -> list[object]:
        result = data.get("result")
        if isinstance(result, dict):
            postings = result.get("postings")
            return postings if isinstance(postings, list) else []
        return result if isinstance(result, list) else []

    @staticmethod
    def _extract_returns(data: dict[str, object]) -> list[dict[str, object]]:
        rows = data.get("returns")
        if not isinstance(rows, list):
            result = data.get("result")
            if isinstance(result, dict):
                rows = result.get("returns")
            elif isinstance(result, list):
                rows = result
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def _buyout_notifications_enabled(account: MarketplaceAccount) -> bool:
        settings = account.notification_settings or {}
        value = settings.get(NotificationType.SALE_COMPLETED.value, True)
        return _settings_bool(value)

    @staticmethod
    def _lifecycle_notifications_enabled(
        account: MarketplaceAccount,
        notification_type: NotificationType,
    ) -> bool:
        settings = account.notification_settings or {}
        value = settings.get(notification_type.value, True)
        return _settings_bool(value)

    @staticmethod
    def format_sale_notification(row: SalesEvent, timezone_name: str = "Europe/Moscow") -> str:
        marketplace_title = "Wildberries" if row.marketplace == Marketplace.WB else "Ozon"
        title = (
            f"✅ Выкуп товара — {marketplace_title}"
            if row.marketplace == Marketplace.WB
            else f"✅ Продажа завершена — {marketplace_title}"
        )
        profit = row.estimated_profit
        profit_line = rub(profit) if profit is not None else "пока не рассчитана"
        lines = [
            title,
            "",
            f"📦 Товар: {row.seller_article or row.marketplace_article or 'н/д'}",
            f"🏷 Артикул продавца: {row.seller_article or 'н/д'}",
            f"🔢 Артикул маркетплейса: {row.marketplace_article or 'н/д'}",
            "",
            f"🕒 Событие зафиксировано: {format_datetime_for_user(row.event_date, timezone_name)}",
            f"💰 Сумма продажи: {rub(row.amount)}",
            "",
            "📊 Предварительный результат:",
            f"— Плановая прибыль: {profit_line}",
            "",
            "ℹ Фактические расходы будут уточнены после финансовой отчётности маркетплейса.",
        ]
        return "\n".join(lines)


def _int_value(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    try:
        return int(str(value))
    except ValueError:
        return default


def _parse_return_date(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(tz=UTC)


def _settings_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on", "да"}
    return bool(value)


def _lifecycle_log_extra(order: Order, event_type: str) -> dict[str, object]:
    return {
        "event_type": event_type,
        "account_id": order.marketplace_account_id,
        "user_id": order.user_id,
        "order_id": order.id,
        "order_external_id": order.order_external_id,
        "marketplace": order.marketplace.value,
        "status": order.normalized_status or order.status,
    }


def _return_log_extra(event: ReturnsEvent) -> dict[str, object]:
    return {
        "event_type": NotificationType.RETURN_CREATED.value,
        "event_id": event.id,
        "external_event_id": event.external_event_id,
        "account_id": event.marketplace_account_id,
        "user_id": event.user_id,
        "order_external_id": event.order_external_id,
        "marketplace": event.marketplace.value,
    }
