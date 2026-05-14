"""version: 1.0.0
description: Wildberries official API client and normalization helpers.
updated: 2026-05-14
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from app.core.config import get_settings
from app.integrations.base import AsyncApiClient
from app.models.enums import Marketplace, SaleEventType, SaleModel, SourceEventType, UrgencyType
from app.schemas.orders import NormalizedOrder, NormalizedOrderItem
from app.schemas.products import ProductUpsert
from app.schemas.sales import NormalizedSaleEvent


class WildberriesClient:
    """Client for current Wildberries public APIs used by the bot."""

    def __init__(self, api_key: str) -> None:
        settings = get_settings()
        self.api_key = api_key
        self.common = AsyncApiClient(settings.wb_base_common_url)
        self.marketplace = AsyncApiClient(settings.wb_base_marketplace_url)
        self.content = AsyncApiClient(settings.wb_base_content_url)
        self.analytics = AsyncApiClient(settings.wb_base_analytics_url)
        self.finance = AsyncApiClient(settings.wb_base_finance_url)
        self.statistics = AsyncApiClient(settings.wb_base_statistics_url)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": self.api_key}

    async def check_connection(self) -> bool:
        await self.common.request("GET", "/ping", headers=self.headers)
        return True

    async def get_new_fbs_orders(self) -> list[dict[str, Any]]:
        data = await self.marketplace.request("GET", "/api/v3/orders/new", headers=self.headers)
        return list(data.get("orders", []))

    async def get_fbs_orders(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
    ) -> list[dict[str, Any]]:
        data = await self.marketplace.request(
            "GET",
            "/api/v3/orders",
            headers=self.headers,
            params={"dateFrom": date_from.isoformat(), "dateTo": date_to.isoformat()},
        )
        return list(data.get("orders", []))

    async def get_fbs_orders_status(self, order_ids: list[int]) -> list[dict[str, Any]]:
        if not order_ids:
            return []
        data = await self.marketplace.request(
            "POST",
            "/api/v3/orders/status",
            headers=self.headers,
            json={"orders": order_ids},
        )
        return list(data.get("orders", []))

    async def get_cards_list(self, cursor: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"settings": {"cursor": cursor or {"limit": 100}, "filter": {"withPhoto": -1}}}
        return cast(
            dict[str, Any],
            await self.content.request(
                "POST",
                "/content/v2/get/cards/list",
                headers=self.headers,
                json=payload,
            ),
        )

    async def get_wb_warehouses_stocks(
        self,
        *,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.analytics.request(
                "POST",
                "/api/analytics/v1/stocks-report/wb-warehouses",
                headers=self.headers,
                json={"limit": limit, "offset": offset},
            ),
        )

    async def get_sales_report_details(
        self,
        date_from: str,
        date_to: str,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"dateFrom": date_from, "dateTo": date_to}
        if fields:
            payload["fields"] = fields
        return cast(
            dict[str, Any],
            await self.finance.request(
                "POST",
                "/api/finance/v1/sales-reports/detailed",
                headers=self.headers,
                json=payload,
            ),
        )

    async def get_supplier_orders(self, date_from: datetime) -> list[dict[str, Any]]:
        data = await self.statistics.request(
            "GET",
            "/api/v1/supplier/orders",
            headers=self.headers,
            params={"dateFrom": date_from.isoformat(), "flag": 0},
        )
        return list(data) if isinstance(data, list) else []

    async def get_supplier_sales(self, date_from: datetime) -> list[dict[str, Any]]:
        data = await self.statistics.request(
            "GET",
            "/api/v1/supplier/sales",
            headers=self.headers,
            params={"dateFrom": date_from.isoformat(), "flag": 0},
        )
        return list(data) if isinstance(data, list) else []

    def normalize_fbs_order(self, payload: dict[str, Any]) -> NormalizedOrder:
        created = payload.get("createdAt")
        order_date = (
            datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created
            else datetime.now(tz=UTC)
        )
        price = Decimal(str(payload.get("convertedFinalPrice") or payload.get("finalPrice") or 0))
        item = NormalizedOrderItem(
            external_product_id=str(
                payload.get("nmId") or payload.get("chrtId") or payload.get("id")
            ),
            seller_article=payload.get("article"),
            marketplace_article=str(payload.get("nmId") or ""),
            title=payload.get("subject"),
            quantity=1,
            buyer_price=price,
            seller_price=price,
            discounted_price=price,
            payout_amount_estimated=price,
            raw_payload=payload,
        )
        return NormalizedOrder(
            marketplace=Marketplace.WB,
            order_external_id=str(payload["id"]),
            assembly_id=str(payload.get("id")),
            srid=payload.get("rid"),
            order_date=order_date,
            sale_model=SaleModel.FBS,
            fulfillment_type="FBS",
            urgency_type=UrgencyType.ACTION_REQUIRED,
            source_event_type=SourceEventType.LIVE_ORDER,
            status="new",
            raw_status="new",
            normalized_status="new",
            warehouse=str(payload.get("warehouseId") or payload.get("officeId") or ""),
            warehouse_type="seller",
            delivery_schema=str(payload.get("deliveryType") or "fbs").upper(),
            deadline_at=self._parse_optional_date(payload.get("sellerDate")),
            processing_deadline_at=self._parse_optional_date(payload.get("sellerDate")),
            requires_seller_action=True,
            items=[item],
            raw_payload=payload,
        )

    def normalize_historical_fbs_order(self, payload: dict[str, Any]) -> NormalizedOrder:
        order = self.normalize_fbs_order(payload)
        raw_status = str(payload.get("status") or payload.get("wbStatus") or "history_order")
        order.status = raw_status
        order.raw_status = raw_status
        order.normalized_status = raw_status.lower()
        order.source_event_type = SourceEventType.STATISTICS_ORDER
        order.urgency_type = UrgencyType.INFORMATIONAL
        order.requires_seller_action = False
        return order

    def normalize_report_order(self, payload: dict[str, Any]) -> NormalizedOrder:
        order_date = self._parse_optional_date(
            payload.get("orderDate") or payload.get("date") or payload.get("saleDt")
        ) or datetime.now(tz=UTC)
        nm_id = str(payload.get("nmID") or payload.get("nmId") or payload.get("nmId") or "")
        article = payload.get("supplierArticle") or payload.get("saName")
        title = payload.get("title") or payload.get("subjectName")
        revenue = Decimal(
            str(
                payload.get("retailPriceWithDiscRub")
                or payload.get("retailPrice")
                or payload.get("ppvzForPay")
                or 0
            )
        )
        item = NormalizedOrderItem(
            external_product_id=nm_id,
            seller_article=article,
            marketplace_article=nm_id,
            title=title,
            quantity=int(payload.get("quantity") or 1),
            buyer_price=revenue,
            seller_price=revenue,
            discounted_price=revenue,
            payout_amount_estimated=Decimal(str(payload.get("ppvzForPay") or revenue)),
            raw_payload=payload,
        )
        external_id = str(
            payload.get("srid")
            or payload.get("rrdId")
            or payload.get("realizationreportId")
            or f"wb-report-{nm_id}-{order_date.isoformat()}"
        )
        return NormalizedOrder(
            marketplace=Marketplace.WB,
            order_external_id=external_id,
            srid=str(payload.get("srid") or "") or None,
            order_date=order_date,
            sale_model=SaleModel.FBO,
            fulfillment_type="FBO",
            urgency_type=UrgencyType.INFORMATIONAL,
            source_event_type=SourceEventType.REPORT_ORDER,
            status=str(payload.get("orderStatus") or payload.get("status") or "report_order"),
            raw_status=str(payload.get("orderStatus") or payload.get("status") or "report_order"),
            normalized_status="ordered",
            warehouse=str(payload.get("officeName") or payload.get("warehouseName") or ""),
            warehouse_type="marketplace",
            delivery_schema="FBO",
            requires_seller_action=False,
            items=[item],
            raw_payload=payload,
        )

    def normalize_statistics_order(self, payload: dict[str, Any]) -> NormalizedOrder:
        order_date = self._parse_optional_date(payload.get("date")) or datetime.now(tz=UTC)
        nm_id = str(payload.get("nmId") or payload.get("nmID") or "")
        revenue = Decimal(str(payload.get("finishedPrice") or payload.get("totalPrice") or 0))
        item = NormalizedOrderItem(
            external_product_id=nm_id,
            seller_article=payload.get("supplierArticle"),
            marketplace_article=nm_id,
            title=payload.get("subject"),
            quantity=1,
            buyer_price=revenue,
            seller_price=revenue,
            discounted_price=revenue,
            payout_amount_estimated=revenue,
            raw_payload=payload,
        )
        external_id = str(
            payload.get("srid")
            or payload.get("odid")
            or f"wb-stat-order-{nm_id}-{order_date.isoformat()}"
        )
        is_cancel = bool(payload.get("isCancel"))
        return NormalizedOrder(
            marketplace=Marketplace.WB,
            order_external_id=external_id,
            srid=str(payload.get("srid") or "") or None,
            order_date=order_date,
            sale_model=SaleModel.FBO,
            fulfillment_type="FBO",
            urgency_type=UrgencyType.INFORMATIONAL,
            source_event_type=SourceEventType.STATISTICS_ORDER,
            status="cancelled" if is_cancel else "statistics_order",
            raw_status="cancelled" if is_cancel else "statistics_order",
            normalized_status="cancelled" if is_cancel else "ordered",
            warehouse=str(payload.get("warehouseName") or ""),
            warehouse_type="marketplace",
            delivery_schema="FBO",
            requires_seller_action=False,
            items=[item],
            raw_payload=payload,
        )

    def normalize_supplier_sale(self, payload: dict[str, Any]) -> NormalizedSaleEvent:
        event_date = self._parse_optional_date(payload.get("date")) or datetime.now(tz=UTC)
        nm_id = str(payload.get("nmId") or payload.get("nmID") or "")
        sale_id = str(
            payload.get("saleID")
            or payload.get("srid")
            or f"wb-sale-{nm_id}-{event_date.isoformat()}"
        )
        amount = Decimal(str(payload.get("finishedPrice") or payload.get("totalPrice") or 0))
        payout = Decimal(str(payload.get("forPay") or amount))
        return NormalizedSaleEvent(
            marketplace=Marketplace.WB,
            external_event_id=f"wb-sale-{sale_id}",
            order_external_id=str(payload.get("srid") or "") or None,
            event_type=SaleEventType.BUYOUT,
            event_date=event_date,
            external_product_id=nm_id,
            seller_article=payload.get("supplierArticle"),
            marketplace_article=nm_id,
            title=payload.get("subject"),
            quantity=1,
            amount=amount,
            expected_payout=payout,
            raw_payload=payload,
        )

    @staticmethod
    def _parse_optional_date(value: object) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            try:
                return datetime.strptime(text, "%d.%m.%Y").replace(tzinfo=UTC)
            except ValueError:
                return None

    def normalize_card_product(
        self,
        *,
        payload: dict[str, Any],
        user_id: int,
        account_id: int,
    ) -> ProductUpsert:
        nm_id = str(payload.get("nmID") or payload.get("nmId") or "")
        photos = payload.get("photos") or []
        image_url = None
        if photos and isinstance(photos[0], dict):
            image_url = photos[0].get("big") or photos[0].get("c516x688")
        return ProductUpsert(
            user_id=user_id,
            marketplace_account_id=account_id,
            marketplace=Marketplace.WB,
            external_product_id=nm_id,
            seller_article=payload.get("vendorCode"),
            marketplace_article=nm_id,
            title=payload.get("title"),
            brand=payload.get("brand"),
            image_url=image_url,
            category=payload.get("subjectName") or payload.get("object"),
            is_active=not bool(payload.get("isDeleted")),
        )
