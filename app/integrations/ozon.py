"""version: 1.4.0
description: Ozon Seller API client, catalog, stock, price, and order normalization helpers.
updated: 2026-05-20
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.integrations.base import AsyncApiClient
from app.models.enums import Marketplace, SaleEventType, SaleModel, SourceEventType, UrgencyType
from app.schemas.orders import NormalizedOrder, NormalizedOrderItem
from app.schemas.products import ProductUpsert
from app.schemas.sales import NormalizedSaleEvent

logger = logging.getLogger(__name__)


class OzonClient:
    """Client for Ozon Seller API endpoints used by the bot."""

    def __init__(self, client_id: str, api_key: str) -> None:
        self.client_id = client_id
        self.api_key = api_key
        self.client = AsyncApiClient(get_settings().ozon_base_url, marketplace="Ozon")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    async def get_fbs_postings(
        self,
        since: datetime,
        to: datetime,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        payload = {
            "dir": "ASC",
            "filter": {
                "since": since.isoformat(),
                "to": to.isoformat(),
            },
            "limit": limit,
            "offset": offset,
            "with": {
                "analytics_data": True,
                "barcodes": True,
                "financial_data": True,
                "translit": False,
            },
        }
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v3/posting/fbs/list",
                headers=self.headers,
                json=payload,
            ),
        )

    async def get_fbs_posting(self, posting_number: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v3/posting/fbs/get",
                headers=self.headers,
                json={
                    "posting_number": posting_number,
                    "with": {
                        "analytics_data": True,
                        "barcodes": True,
                        "financial_data": True,
                        "product_exemplars": True,
                        "related_postings": True,
                    },
                },
            ),
        )

    async def get_fbs_unfulfilled(
        self,
        cutoff_from: datetime,
        cutoff_to: datetime,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v3/posting/fbs/unfulfilled/list",
                headers=self.headers,
                json={
                    "dir": "ASC",
                    "filter": {
                        "cutoff_from": cutoff_from.isoformat(),
                        "cutoff_to": cutoff_to.isoformat(),
                    },
                    "limit": limit,
                    "offset": offset,
                },
            ),
        )

    async def get_fbo_postings(
        self,
        since: datetime,
        to: datetime,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v2/posting/fbo/list",
                headers=self.headers,
                json={
                    "dir": "ASC",
                    "filter": {"since": since.isoformat(), "to": to.isoformat()},
                    "limit": limit,
                    "offset": offset,
                    "with": {"analytics_data": True, "financial_data": True},
                },
            ),
        )

    async def get_product_list(self, last_id: str = "", limit: int = 100) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v3/product/list",
                headers=self.headers,
                json={"filter": {"visibility": "ALL"}, "last_id": last_id, "limit": limit},
            ),
        )

    async def check_connection(self) -> bool:
        await self.get_product_list(limit=1)
        return True

    async def get_seller_info(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v1/seller/info",
                headers=self.headers,
                json={},
            ),
        )

    async def get_product_info_stocks(self, offer_ids: list[str] | None = None) -> dict[str, Any]:
        return await self.get_product_info_stocks_page(offer_ids=offer_ids)

    async def get_product_info_stocks_page(
        self,
        offer_ids: list[str] | None = None,
        *,
        cursor: str = "",
        limit: int = 1000,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "filter": {"offer_id": offer_ids or [], "visibility": "ALL"},
            "limit": limit,
        }
        if cursor:
            payload["cursor"] = cursor
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v4/product/info/stocks",
                headers=self.headers,
                json=payload,
            ),
        )

    async def get_product_info_warehouse_stocks(
        self,
        *,
        sku: list[str] | None = None,
        warehouse_ids: list[str] | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"limit": limit, "offset": offset}
        if sku:
            payload["sku"] = sku[:1000]
        if warehouse_ids:
            payload["warehouse_ids"] = warehouse_ids[:1000]
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v1/product/info/stocks-by-warehouse/fbs",
                headers=self.headers,
                json=payload,
            ),
        )

    async def get_product_info_prices(
        self,
        *,
        offer_ids: list[str] | None = None,
        product_ids: list[str] | None = None,
        limit: int = 1000,
        cursor: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "filter": {"offer_id": offer_ids or [], "product_id": product_ids or []},
            "limit": limit,
        }
        if cursor:
            payload["cursor"] = cursor
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v5/product/info/prices",
                headers=self.headers,
                json=payload,
            ),
        )

    async def get_warehouses(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v2/warehouse/list",
                headers=self.headers,
                json={"limit": limit, "offset": offset},
            ),
        )

    async def get_promos_products(
        self,
        action_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v1/actions/products",
                headers=self.headers,
                json={"action_id": action_id, "limit": limit, "offset": offset},
            ),
        )

    async def get_actions(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v1/actions",
                headers=self.headers,
                json={"limit": limit, "offset": offset},
            ),
        )

    async def get_product_info_list(
        self,
        *,
        product_ids: list[str] | None = None,
        offer_ids: list[str] | None = None,
        sku: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch detailed product info for up to 1000 identifiers."""

        payload: dict[str, list[str]] = {}
        if product_ids:
            payload["product_id"] = product_ids[:1000]
        if offer_ids:
            payload["offer_id"] = offer_ids[:1000]
        if sku:
            payload["sku"] = sku[:1000]
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v3/product/info/list",
                headers=self.headers,
                json=payload,
            ),
        )

    async def get_returns(
        self,
        last_id: int = 0,
        limit: int = 100,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict[str, Any]:
        filter_payload: dict[str, Any] = {}
        if date_from and date_to:
            filter_payload["date"] = {
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
            }
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v1/returns/list",
                headers=self.headers,
                json={"filter": filter_payload, "last_id": last_id, "limit": limit},
            ),
        )

    async def create_report(self, report_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = {"language": "DEFAULT", "report_type": report_type, "params": payload}
        return cast(
            dict[str, Any],
            await self.client.request("POST", "/v1/report", headers=self.headers, json=body),
        )

    async def get_report_info(self, code: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v1/report/info",
                headers=self.headers,
                json={"code": code},
            ),
        )

    def normalize_fbs_posting(self, payload: dict[str, Any]) -> NormalizedOrder:
        """Normalize Ozon FBS posting to internal format."""
        if not payload.get("posting_number"):
            raise ValidationError("Missing required field: posting_number", field="posting_number")

        sale_model = self._detect_fbs_sale_model(payload)
        created = payload.get("in_process_at") or payload.get("shipment_date")
        order_date = (
            datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created
            else datetime.now(tz=UTC)
        )
        items = self._normalize_products(payload)
        return NormalizedOrder(
            marketplace=Marketplace.OZON,
            order_external_id=str(payload["posting_number"]),
            posting_number=payload.get("posting_number"),
            order_date=order_date,
            sale_model=sale_model,
            fulfillment_type=sale_model.value,
            urgency_type=UrgencyType.ACTION_REQUIRED,
            source_event_type=SourceEventType.POSTING_EVENT,
            status=payload.get("status", "unknown"),
            raw_status=payload.get("status", "unknown"),
            normalized_status=self._normalize_status(payload.get("status")),
            warehouse=_safe_get(payload.get("delivery_method"), "warehouse"),
            warehouse_type="seller",
            delivery_schema=sale_model.value,
            deadline_at=self._parse_dt(payload.get("shipment_date")),
            processing_deadline_at=self._parse_dt(payload.get("shipment_date")),
            requires_seller_action=True,
            items=items,
            raw_payload=payload,
        )

    def normalize_fbo_posting(self, payload: dict[str, Any]) -> NormalizedOrder:
        created = (
            payload.get("in_process_at")
            or payload.get("created_at")
            or payload.get("shipment_date")
        )
        order_date = (
            datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created
            else datetime.now(tz=UTC)
        )
        items = self._normalize_products(payload)
        return NormalizedOrder(
            marketplace=Marketplace.OZON,
            order_external_id=str(payload["posting_number"]),
            posting_number=payload.get("posting_number"),
            order_date=order_date,
            sale_model=SaleModel.FBO,
            fulfillment_type="FBO",
            urgency_type=UrgencyType.INFORMATIONAL,
            source_event_type=SourceEventType.POSTING_EVENT,
            status=payload.get("status", "unknown"),
            raw_status=payload.get("status", "unknown"),
            normalized_status=self._normalize_status(payload.get("status")),
            warehouse=_safe_get(payload.get("analytics_data"), "warehouse_name"),
            warehouse_type="marketplace",
            delivery_schema="FBO",
            requires_seller_action=False,
            items=items,
            raw_payload=payload,
        )

    def normalize_completed_sale_events(
        self,
        payload: dict[str, Any],
        *,
        sale_model: SaleModel,
    ) -> list[NormalizedSaleEvent]:
        status = str(payload.get("status") or "").lower()
        event_date = self._parse_dt(
            payload.get("delivering_date")
            or payload.get("delivered_at")
            or payload.get("shipment_date")
            or payload.get("in_process_at")
            or payload.get("created_at")
        ) or datetime.now(tz=UTC)
        posting_number = str(payload.get("posting_number") or "")
        events: list[NormalizedSaleEvent] = []
        for product in payload.get("products", []):
            if not isinstance(product, dict):
                continue
            product_key = str(
                product.get("sku") or product.get("offer_id") or product.get("product_id") or ""
            )
            amount = Decimal(str(product.get("price") or 0)) * Decimal(
                str(product.get("quantity") or 1)
            )
            events.append(
                NormalizedSaleEvent(
                    marketplace=Marketplace.OZON,
                    external_event_id=f"ozon-sale-{posting_number}-{product_key}",
                    order_external_id=posting_number or None,
                    event_type=SaleEventType.DELIVERED_TO_CUSTOMER,
                    event_date=event_date,
                    external_product_id=product_key or None,
                    seller_article=product.get("offer_id"),
                    marketplace_article=str(product.get("sku") or "") or None,
                    title=product.get("name"),
                    quantity=int(product.get("quantity") or 1),
                    amount=amount,
                    expected_payout=amount,
                    sale_model=sale_model.value,
                    status=status,
                    raw_payload=payload,
                )
            )
        return events

    def _normalize_products(self, payload: dict[str, Any]) -> list[NormalizedOrderItem]:
        items: list[NormalizedOrderItem] = []
        financial_products: dict[str, dict[str, Any]] = {}
        financial_data = payload.get("financial_data")
        if financial_data is None:
            logger.debug(
                "ozon_posting_financial_data_missing",
                extra={"posting_number": payload.get("posting_number")},
            )
        else:
            for item in financial_data.get("products", []):
                for field in ["product_id", "offer_id", "sku"]:
                    if item.get(field):
                        financial_products[str(item[field])] = item
        for product in payload.get("products", []):
            key = str(product.get("sku") or product.get("offer_id") or product.get("product_id"))
            finance = financial_products.get(key, {})
            price = Decimal(str(product.get("price") or finance.get("price") or 0))
            commission = self._extract_commission(finance)
            logistics = self._extract_service_amount(finance, ("delivery", "logistic"))
            other_services = self._extract_service_amount(
                finance,
                ("service", "processing", "return", "storage", "last_mile"),
                exclude=("delivery", "logistic"),
            )
            payout = Decimal(str(finance.get("payout") or 0))

            # Выручка продавца = цена покупателя - расходы МП
            seller_payout = payout if payout > 0 else price
            if payout == 0:
                # Рассчитываем вручную
                if commission:
                    seller_payout -= commission
                seller_payout -= logistics
                seller_payout -= other_services

            items.append(
                NormalizedOrderItem(
                    external_product_id=str(product.get("sku") or product.get("product_id") or ""),
                    seller_article=product.get("offer_id"),
                    marketplace_article=str(product.get("sku") or ""),
                    title=product.get("name"),
                    quantity=int(product.get("quantity") or 1),
                    buyer_price=price,
                    seller_price=price,
                    discounted_price=price,
                    payout_amount_estimated=payout if payout > 0 else price,
                    seller_payout_estimated=seller_payout,
                    commission_estimated=commission,
                    logistics_estimated=logistics,
                    other_marketplace_expenses_estimated=other_services,
                    raw_payload=product,
                )
            )
        return items

    @staticmethod
    def _extract_commission(finance: dict[str, Any]) -> Decimal | None:
        if finance.get("commission_amount") is None:
            return None
        return abs(Decimal(str(finance.get("commission_amount") or 0)))

    @staticmethod
    def _extract_service_amount(
        finance: dict[str, Any],
        keywords: tuple[str, ...],
        *,
        exclude: tuple[str, ...] = (),
    ) -> Decimal:
        total = Decimal("0")
        services = finance.get("services") or []
        if not isinstance(services, list):
            return total
        for service in services:
            if not isinstance(service, dict):
                continue
            name = str(service.get("name") or service.get("type") or "").lower()
            if exclude and any(item in name for item in exclude):
                continue
            if any(item in name for item in keywords):
                total += abs(Decimal(str(service.get("price") or service.get("amount") or 0)))
        return total

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _normalize_status(value: str | None) -> str:
        return (value or "unknown").lower()

    @staticmethod
    def _detect_fbs_sale_model(payload: dict[str, Any]) -> SaleModel:
        delivery_method = payload.get("delivery_method") or {}
        schema = str(
            payload.get("delivery_schema")
            or payload.get("schema")
            or delivery_method.get("tpl_provider")
            or delivery_method.get("provider_type")
            or ""
        ).lower()
        if "rfbs" in schema or "real" in schema:
            return SaleModel.RFBS
        return SaleModel.FBS

    def normalize_product(
        self,
        *,
        payload: dict[str, Any],
        user_id: int,
        account_id: int,
    ) -> ProductUpsert:
        product_id = str(payload.get("product_id") or payload.get("id") or payload.get("sku") or "")
        offer_id = str(payload.get("offer_id") or "")
        return ProductUpsert(
            user_id=user_id,
            marketplace_account_id=account_id,
            marketplace=Marketplace.OZON,
            external_product_id=product_id or offer_id,
            seller_article=offer_id or None,
            marketplace_article=str(payload.get("sku") or product_id or ""),
            title=payload.get("name"),
            brand=payload.get("brand"),
            image_url=_first_ozon_image(payload),
            category=payload.get("category_name") or payload.get("description_category_name"),
            is_active=payload.get("visibility") != "HIDDEN",
        )


def _first_ozon_image(payload: dict[str, Any]) -> str | None:
    images = payload.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("file_name") or first.get("url")
    return payload.get("primary_image") or payload.get("image")


def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    """Safely get a key from a dict-like object that may be None."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default
