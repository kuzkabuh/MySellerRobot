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
from app.models.domain import MarketplaceAccount, OrderItem, ProfitSnapshot, SalesEvent
from app.models.enums import CalculationType, Marketplace, NotificationType, SaleModel
from app.repositories.events import ReturnsEventRepository, SalesEventRepository
from app.repositories.orders import OrderRepository
from app.repositories.products import ProductRepository
from app.schemas.orders import NormalizedOrder
from app.schemas.sales import NormalizedSaleEvent
from app.services.message_formatter import rub
from app.services.order_card_service import OrderCardService
from app.services.order_profit_service import OrderProfitService

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
    telegram_id: int
    text: str
    marketplace: Marketplace
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
        rows = await self.sales.pending_notifications(limit=limit)
        notifications: list[SaleNotification] = []
        for row in rows:
            account = await self.session.get(MarketplaceAccount, row.marketplace_account_id)
            if account is None or account.user is None:
                continue
            if not account.user.notifications_enabled:
                continue
            if not self._buyout_notifications_enabled(account):
                continue
            card = await self.cards.buyout_card(
                event=row,
                timezone_name=account.user.timezone,
            )
            notifications.append(
                SaleNotification(
                    event_id=row.id,
                    telegram_id=account.user.telegram_id,
                    text=card.text,
                    marketplace=account.marketplace,
                    image_url=card.image_url,
                    product_url=card.product_url,
                    parse_mode=card.parse_mode,
                )
            )
        return notifications

    async def mark_notified(self, event_id: int) -> None:
        await self.sales.mark_notified(event_id)

    async def _sync_wb(
        self,
        account: MarketplaceAccount,
        date_from: datetime,
    ) -> SalesSyncResult:
        result = SalesSyncResult(account_id=account.id, marketplace=account.marketplace)
        client = WildberriesClient(self.cipher.decrypt(account.encrypted_api_key))
        try:
            orders = await client.get_supplier_orders(date_from)
            result.orders_fetched = len(orders)
            for payload in orders:
                normalized = client.normalize_statistics_order(payload)
                created = await self._upsert_order_with_profit(account, normalized)
                result.orders_created += int(created)
                result.orders_updated += int(not created)
        except Exception:
            result.failed += 1
            logger.exception("wb_statistics_orders_sync_failed", extra={"account_id": account.id})
            await self.session.rollback()
        try:
            sales = await client.get_supplier_sales(date_from)
            result.sales_fetched = len(sales)
            for payload in sales:
                row, created = await self._upsert_sale_event(
                    account,
                    client.normalize_supplier_sale(payload),
                )
                result.sales_created += int(created)
                result.sales_updated += int(not created)
                logger.debug("wb_sale_event_synced", extra={"event_id": row.id})
        except Exception:
            result.failed += 1
            logger.exception("wb_supplier_sales_sync_failed", extra={"account_id": account.id})
            await self.session.rollback()
        await self.session.commit()
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
                "created": result.sales_created,
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
        result = SalesSyncResult(account_id=account.id, marketplace=account.marketplace)
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
            except Exception:
                result.failed += 1
                logger.exception(
                    "ozon_completed_sales_sync_failed", extra={"account_id": account.id}
                )
                await self.session.rollback()
        await self.session.commit()
        return result

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
    ) -> tuple[object, bool]:
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

    @staticmethod
    def _extract_postings(data: dict[str, object]) -> list[object]:
        result = data.get("result")
        if isinstance(result, dict):
            postings = result.get("postings")
            return postings if isinstance(postings, list) else []
        return result if isinstance(result, list) else []

    @staticmethod
    def _buyout_notifications_enabled(account: MarketplaceAccount) -> bool:
        settings = account.notification_settings or {}
        value = settings.get(NotificationType.SALE_COMPLETED.value, True)
        return bool(value)

    @staticmethod
    def format_sale_notification(row: SalesEvent) -> str:
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
            f"🕒 Событие зафиксировано: {row.event_date:%d.%m.%Y %H:%M}",
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
