"""version: 1.0.0
description: Wildberries official API client and normalization helpers.
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

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": self.api_key}

    async def check_connection(self) -> bool:
        await self.common.request("GET", "/ping", headers=self.headers)
        return True

    async def get_new_fbs_orders(self) -> list[dict[str, Any]]:
        data = await self.marketplace.request("GET", "/api/v3/orders/new", headers=self.headers)
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
            status="new",
            warehouse=str(payload.get("warehouseId") or payload.get("officeId") or ""),
            items=[item],
            raw_payload=payload,
        )

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
