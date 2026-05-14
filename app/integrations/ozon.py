"""version: 1.0.0
description: Ozon Seller API client and normalization helpers.
updated: 2026-05-14
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from app.core.config import get_settings
from app.integrations.base import AsyncApiClient
from app.models.enums import Marketplace, SaleModel
from app.schemas.orders import NormalizedOrder, NormalizedOrderItem
from app.schemas.products import ProductUpsert


class OzonClient:
    """Client for Ozon Seller API endpoints used by the bot."""

    def __init__(self, client_id: str, api_key: str) -> None:
        self.client_id = client_id
        self.api_key = api_key
        self.client = AsyncApiClient(get_settings().ozon_base_url)

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

    async def get_product_info_stocks(self, offer_ids: list[str] | None = None) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v4/product/info/stocks",
                headers=self.headers,
                json={"filter": {"offer_id": offer_ids or [], "visibility": "ALL"}, "limit": 1000},
            ),
        )

    async def get_returns(self, last_id: int = 0, limit: int = 100) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.client.request(
                "POST",
                "/v1/returns/list",
                headers=self.headers,
                json={"filter": {}, "last_id": last_id, "limit": limit},
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
        created = payload.get("in_process_at") or payload.get("shipment_date")
        order_date = (
            datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created
            else datetime.now(tz=UTC)
        )
        items: list[NormalizedOrderItem] = []
        financial_products = {
            str(item.get("product_id") or item.get("offer_id")): item
            for item in payload.get("financial_data", {}).get("products", [])
        }
        for product in payload.get("products", []):
            key = str(product.get("sku") or product.get("offer_id") or product.get("product_id"))
            finance = financial_products.get(key, {})
            price = Decimal(str(product.get("price") or finance.get("price") or 0))
            commission = abs(Decimal(str(finance.get("commission_amount") or 0)))
            payout = Decimal(str(finance.get("payout") or price))
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
                    payout_amount_estimated=payout,
                    commission_estimated=commission,
                    raw_payload=product,
                )
            )
        return NormalizedOrder(
            marketplace=Marketplace.OZON,
            order_external_id=str(payload["posting_number"]),
            posting_number=payload.get("posting_number"),
            order_date=order_date,
            sale_model=SaleModel.FBS,
            status=payload.get("status", "unknown"),
            warehouse=payload.get("delivery_method", {}).get("warehouse"),
            deadline_at=self._parse_dt(payload.get("shipment_date")),
            items=items,
            raw_payload=payload,
        )

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

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
            image_url=payload.get("primary_image") or payload.get("image"),
            category=payload.get("category_name"),
            is_active=payload.get("visibility") != "HIDDEN",
        )
