"""version: 2.0.0
description: Wildberries official API client, seller stocks, daily sales, tariffs, and normalizers.
updated: 2026-05-20
"""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.exceptions import MarketplaceApiError, ValidationError
from app.integrations.base import AsyncApiClient
from app.models.enums import Marketplace, SaleEventType, SaleModel, SourceEventType, UrgencyType
from app.schemas.orders import NormalizedOrder, NormalizedOrderItem
from app.schemas.products import ProductUpsert
from app.schemas.sales import NormalizedSaleEvent
from app.services.common.product_dimensions import calculate_volume_liters, decimal_or_none
from app.utils.datetime import get_moscow_today

logger = logging.getLogger(__name__)

WB_STATISTICS_TZ = ZoneInfo("Europe/Moscow")
WB_FBS_ORDERS_LIMIT_MAX = 1000


def _wb_unix_timestamp_utc(value: datetime) -> int:
    return int(value.astimezone(UTC).replace(microsecond=0).timestamp())


def _wb_fbs_orders_limit(value: int) -> int:
    return max(1, min(int(value), WB_FBS_ORDERS_LIMIT_MAX))


def _compact_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value is not None and value != ""}


class WildberriesClient:
    """Client for current Wildberries public APIs used by the bot."""

    def __init__(self, api_key: str) -> None:
        settings = get_settings()
        self.api_key = api_key
        self.common = AsyncApiClient(settings.wb_base_common_url, marketplace="Wildberries")
        self.marketplace = AsyncApiClient(
            settings.wb_base_marketplace_url, marketplace="Wildberries"
        )
        self.content = AsyncApiClient(settings.wb_base_content_url, marketplace="Wildberries")
        self.analytics = AsyncApiClient(settings.wb_base_analytics_url, marketplace="Wildberries")
        self.finance = AsyncApiClient(settings.wb_base_finance_url, marketplace="Wildberries")
        self.statistics = AsyncApiClient(settings.wb_base_statistics_url, marketplace="Wildberries")
        self.calendar = AsyncApiClient(settings.wb_base_calendar_url, marketplace="Wildberries")
        self.discounts_prices = AsyncApiClient(
            settings.wb_base_discounts_prices_url, marketplace="Wildberries"
        )

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": self.api_key}

    async def check_connection(self) -> bool:
        await self.common.request("GET", "/ping", headers=self.headers)
        return True

    async def get_seller_info(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.common.request("GET", "/api/v1/seller-info", headers=self.headers),
        )

    async def get_account_balance(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.finance.request(
                "GET",
                "/api/v1/account/balance",
                headers=self.headers,
                retries=1,
            ),
        )

    async def get_news(
        self,
        *,
        from_date: str | None = None,
        from_id: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if from_id is not None:
            params["fromID"] = from_id
        elif from_date:
            params["from"] = from_date
        else:
            raise ValidationError("Нужно указать from_date или from_id", field="from")
        data = await self.common.request(
            "GET",
            "/api/communications/v2/news",
            headers=self.headers,
            params=params,
        )
        return list(data) if isinstance(data, list) else list(data.get("news", []))

    async def get_product_search_texts(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.analytics.request(
                "POST",
                "/api/v2/search-report/product/search-texts",
                headers=self.headers,
                json=payload,
            ),
        )

    async def get_new_fbs_orders(self) -> list[dict[str, Any]]:
        data = await self.marketplace.request("GET", "/api/v3/orders/new", headers=self.headers)
        return list(data.get("orders", []))

    async def get_fbs_orders(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        limit: int = 1000,
        account_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch FBS orders for a period with pagination.

        Wildberries GET /api/v3/orders supports:
        - dateFrom / dateTo in Unix timestamp format
        - limit (max 1000)
        - next cursor for pagination, starting from 0
        """
        all_orders: list[dict[str, Any]] = []
        next_cursor: int | str | None = 0
        page_count = 0
        safe_limit = _wb_fbs_orders_limit(limit)
        date_from_ts = _wb_unix_timestamp_utc(date_from)
        date_to_ts = _wb_unix_timestamp_utc(date_to)

        while True:
            params = _compact_params(
                {
                    "dateFrom": date_from_ts,
                    "dateTo": date_to_ts,
                    "limit": safe_limit,
                    "next": next_cursor,
                }
            )

            logger.debug(
                "wb_fbs_period_request_params",
                extra={
                    "date_from": date_from_ts,
                    "date_to": date_to_ts,
                    "limit": safe_limit,
                    "next_cursor_present": next_cursor is not None,
                    "page": page_count + 1,
                },
            )

            logger.info(
                "wb_fbs_period_poll_started",
                extra={
                    "page": page_count + 1,
                    "date_from": date_from_ts,
                    "date_to": date_to_ts,
                    "limit": safe_limit,
                },
            )

            try:
                data = await self.marketplace.request(
                    "GET",
                    "/api/v3/orders",
                    headers=self.headers,
                    params=params,
                )
            except MarketplaceApiError as exc:
                payload = exc.details.get("payload") if isinstance(exc.details, dict) else None
                if isinstance(payload, dict) and payload.get("code") == "IncorrectParameter":
                    logger.error(
                        "wb_fbs_period_incorrect_parameter",
                        extra={
                            "endpoint": "/api/v3/orders",
                            "account_id": account_id,
                            "marketplace": Marketplace.WB.value,
                            "params": params,
                            "date_from": date_from_ts,
                            "date_to": date_to_ts,
                            "limit": safe_limit,
                            "next_cursor_present": next_cursor is not None,
                            "status_code": exc.status_code,
                            "response_body": payload,
                        },
                    )
                raise
            page_count += 1
            orders = list(data.get("orders", []))
            all_orders.extend(orders)

            logger.debug(
                "wb_fbs_period_page_fetched",
                extra={"page": page_count, "orders_on_page": len(orders)},
            )

            logger.info(
                "wb_fbs_period_poll_finished",
                extra={
                    "page": page_count,
                    "orders_on_page": len(orders),
                    "total_orders": len(all_orders),
                },
            )

            next_cursor = data.get("next")
            if not next_cursor or not orders:
                break

        return all_orders

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

    async def get_seller_warehouses(self) -> list[dict[str, Any]]:
        """Return seller warehouses used by FBS inventory endpoints."""

        data = await self.marketplace.request("GET", "/api/v3/warehouses", headers=self.headers)
        return list(data) if isinstance(data, list) else list(data.get("warehouses", []))

    async def get_seller_warehouse_stocks(
        self,
        *,
        warehouse_id: int | str,
        chrt_ids: list[int],
    ) -> list[dict[str, Any]]:
        """Return FBS inventory for seller warehouse by WB size IDs."""

        if not chrt_ids:
            return []
        data = await self.marketplace.request(
            "POST",
            f"/api/v3/stocks/{warehouse_id}",
            headers=self.headers,
            json={"chrtIds": chrt_ids[:1000]},
        )
        stocks = data.get("stocks", []) if isinstance(data, dict) else []
        return [item for item in stocks if isinstance(item, dict)]

    async def get_commission_tariffs(self, *, locale: str = "ru") -> list[dict[str, Any]]:
        """Return official WB category commission tariffs.

        Official endpoint:
        GET https://common-api.wildberries.ru/api/v1/tariffs/commission
        """

        data = await self.common.request(
            "GET",
            "/api/v1/tariffs/commission",
            headers=self.headers,
            params={"locale": locale},
        )
        report = data.get("report", []) if isinstance(data, dict) else []
        return list(report) if isinstance(report, list) else []

    async def get_box_tariffs(self, *, date: str | None = None) -> list[dict[str, Any]]:
        """Return WB box delivery logistics tariffs.

        Official endpoint:
        GET https://common-api.wildberries.ru/api/v1/tariffs/box

        Response contains per-warehouse tariff data with fields:
        - warehouseName, geoName
        - boxDeliveryBase, boxDeliveryLiter, boxDeliveryCoefExpr (FBO)
        - boxDeliveryMarketplaceBase, boxDeliveryMarketplaceLiter,
          boxDeliveryMarketplaceCoefExpr (FBS)
        """

        params = {"date": date or get_moscow_today()}
        data = await self.common.request(
            "GET",
            "/api/v1/tariffs/box",
            headers=self.headers,
            params=params,
            retries=4,
        )
        if not isinstance(data, dict):
            raise MarketplaceApiError(
                "Wildberries вернул ответ в неизвестном формате",
                marketplace="Wildberries",
                details={
                    "endpoint": "/api/v1/tariffs/box",
                    "params": params,
                    "attempts": 4,
                    "reason": "invalid_payload_type",
                },
            )
        if "text" in data:
            raise MarketplaceApiError(
                "Wildberries вернул не JSON-ответ",
                marketplace="Wildberries",
                details={
                    "endpoint": "/api/v1/tariffs/box",
                    "params": params,
                    "attempts": 4,
                    "reason": "invalid_json",
                    "body_preview": str(data.get("text") or "")[:500],
                },
            )
        tariffs = data.get("tariffs", [])
        if not isinstance(tariffs, list):
            raise MarketplaceApiError(
                "Wildberries вернул тарифы в неизвестном формате",
                marketplace="Wildberries",
                details={
                    "endpoint": "/api/v1/tariffs/box",
                    "params": params,
                    "attempts": 4,
                    "reason": "invalid_tariffs_type",
                },
            )
        if not tariffs:
            raise MarketplaceApiError(
                "Wildberries вернул пустой ответ",
                marketplace="Wildberries",
                details={
                    "endpoint": "/api/v1/tariffs/box",
                    "params": params,
                    "attempts": 4,
                    "reason": "empty_response",
                },
            )
        return list(tariffs) if isinstance(tariffs, list) else []

    async def get_pallet_tariffs(self, *, date: str | None = None) -> dict[str, Any]:
        """Return WB pallet logistics tariffs with required Moscow date."""

        return cast(
            dict[str, Any],
            await self.common.request(
                "GET",
                "/api/v1/tariffs/pallet",
                headers=self.headers,
                params={"date": date or get_moscow_today()},
            ),
        )

    async def get_return_tariffs(self, *, date: str | None = None) -> dict[str, Any]:
        """Return WB return logistics tariffs with required Moscow date."""

        return cast(
            dict[str, Any],
            await self.common.request(
                "GET",
                "/api/v1/tariffs/return",
                headers=self.headers,
                params={"date": date or get_moscow_today()},
            ),
        )

    async def get_sales_report_details(
        self,
        date_from: str,
        date_to: str,
        period: str = "daily",
        limit: int = 1000,
        rrd_id: int = 0,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "period": period,
            "limit": limit,
            "rrdId": rrd_id,
        }
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

    async def get_sales_reports_list(
        self,
        *,
        period: str,
        date_from: date,
        date_to: date,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        payload = {
            "period": period,
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
            "limit": limit,
            "offset": offset,
        }
        return cast(
            dict[str, Any],
            await self.finance.request(
                "POST",
                "/api/finance/v1/sales-reports/list",
                headers=self.headers,
                json=payload,
                retries=1,
            ),
        )

    async def get_sales_report_detail_by_id(self, report_id: str | int) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self.finance.request(
                "POST",
                f"/api/finance/v1/sales-reports/detailed/{report_id}",
                headers=self.headers,
                retries=1,
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

    async def get_supplier_sales_for_day(self, report_date: date) -> list[dict[str, Any]]:
        """Return preliminary WB sales/returns rows for one Moscow calendar day."""

        data = await self.statistics.request(
            "GET",
            "/api/v1/supplier/sales",
            headers=self.headers,
            params={"dateFrom": report_date.isoformat(), "flag": 1},
        )
        return list(data) if isinstance(data, list) else []

    async def get_calendar_promotions(
        self,
        *,
        start_datetime: str,
        end_datetime: str,
        all_promo: bool = False,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get list of WB calendar promotions for a date range.

        GET https://dp-calendar-api.wildberries.ru/api/v1/calendar/promotions
        """
        params: dict[str, Any] = {
            "startDateTime": start_datetime,
            "endDateTime": end_datetime,
            "allPromo": str(all_promo).lower(),
            "limit": limit,
            "offset": offset,
        }
        return cast(
            dict[str, Any],
            await self.calendar.request(
                "GET",
                "/api/v1/calendar/promotions",
                headers=self.headers,
                params=params,
            ),
        )

    async def get_promotion_details(
        self,
        *,
        promotion_ids: list[int],
    ) -> dict[str, Any]:
        """Get details of WB calendar promotions.

        GET https://dp-calendar-api.wildberries.ru/api/v1/calendar/promotions/details
        Parameter: promotionIDs as repeated query params.

        WB API requires repeated params: promotionIDs=2450&promotionIDs=2448
        httpx encodes list values as repeated params automatically.
        """
        params: dict[str, Any] = {
            "promotionIDs": [str(pid) for pid in promotion_ids],
        }
        return cast(
            dict[str, Any],
            await self.calendar.request(
                "GET",
                "/api/v1/calendar/promotions/details",
                headers=self.headers,
                params=params,
            ),
        )

    async def get_promotion_nomenclatures(
        self,
        *,
        promotion_id: int,
        in_action: bool,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get list of products for a WB promotion.

        GET https://dp-calendar-api.wildberries.ru/api/v1/calendar/promotions/nomenclatures
        """
        params: dict[str, Any] = {
            "promotionID": promotion_id,
            "inAction": str(in_action).lower(),
            "limit": limit,
            "offset": offset,
        }
        return cast(
            dict[str, Any],
            await self.calendar.request(
                "GET",
                "/api/v1/calendar/promotions/nomenclatures",
                headers=self.headers,
                params=params,
            ),
        )

    async def upload_prices_discounts(
        self,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Upload prices and discounts for products.

        POST https://discounts-prices-api.wildberries.ru/api/v2/upload

        Items format: [{"id": nmId, "price": price_before_discount, "discount": discount_percent}]
        """
        payload = {"data": {"items": items}}
        return cast(
            dict[str, Any],
            await self.discounts_prices.request(
                "POST",
                "/api/v2/upload",
                headers=self.headers,
                json=payload,
            ),
        )

    async def upload_task_prices_discounts(
        self,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Upload prices and discounts via task endpoint.

        POST https://discounts-prices-api.wildberries.ru/api/v2/upload/task

        Items format: [{"nmID": int, "price": int, "discount": int}]
        Max 1000 items per request.

        Returns:
            {"data": {"id": upload_id, "alreadyExists": bool}, "error": bool, "errorText": str}
        """
        payload = {"data": items}
        return cast(
            dict[str, Any],
            await self.discounts_prices.request(
                "POST",
                "/api/v2/upload/task",
                headers=self.headers,
                json=payload,
            ),
        )

    async def get_price_upload_status(
        self,
        upload_id: int,
    ) -> dict[str, Any]:
        """Check status of a price/discount upload.

        GET https://discounts-prices-api.wildberries.ru/api/v2/history/tasks
        """
        params = {"uploadID": upload_id}
        return cast(
            dict[str, Any],
            await self.discounts_prices.request(
                "GET",
                "/api/v2/history/tasks",
                headers=self.headers,
                params=params,
            ),
        )

    async def get_price_upload_details(
        self,
        upload_id: int,
    ) -> dict[str, Any]:
        """Get details of a processed price/discount upload.

        GET https://discounts-prices-api.wildberries.ru/api/v2/history/tasks/{upload_id}/details
        """
        return cast(
            dict[str, Any],
            await self.discounts_prices.request(
                "GET",
                f"/api/v2/history/tasks/{upload_id}/details",
                headers=self.headers,
            ),
        )

    async def get_current_prices(
        self,
        *,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get current product prices from WB.

        GET https://discounts-prices-api.wildberries.ru/api/v2/prices

        Returns list of products with their current prices and discounts.
        """
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }
        return cast(
            dict[str, Any],
            await self.discounts_prices.request(
                "GET",
                "/api/v2/prices",
                headers=self.headers,
                params=params,
            ),
        )

    async def get_goods_prices_by_nm_ids(
        self,
        nm_ids: list[int],
    ) -> dict[str, Any]:
        """Get current product prices by nmID list.

        POST https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter

        Body: {"nmList": [nmID1, nmID2, ...]}
        Max 1000 nmIDs per request.

        Returns data.listGoods with price info for each product.
        """
        if not nm_ids:
            return {"data": {"listGoods": []}, "error": False, "errorText": ""}

        logger.info(
            "wb_prices_filter_started",
            extra={"nm_ids_count": len(nm_ids)},
        )

        payload = {"nmList": nm_ids}

        logger.info(
            "wb_prices_filter_request",
            extra={
                "method": "POST",
                "endpoint": "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter",
                "nm_ids_count": len(nm_ids),
            },
        )

        try:
            response = await self.discounts_prices.request(
                "POST",
                "/api/v2/list/goods/filter",
                headers=self.headers,
                json=payload,
            )

            error = response.get("error", False)
            error_text = response.get("errorText", "")

            if error:
                logger.warning(
                    "wb_prices_filter_failed",
                    extra={"error_text": error_text, "nm_ids_count": len(nm_ids)},
                )
                return cast(dict[str, Any], response)

            list_goods = response.get("data", {}).get("listGoods", [])
            if not isinstance(list_goods, list):
                list_goods = []

            logger.info(
                "wb_prices_filter_response",
                extra={
                    "nm_ids_count": len(nm_ids),
                    "goods_found": len(list_goods),
                },
            )

            logger.info(
                "wb_prices_filter_completed",
                extra={"nm_ids_count": len(nm_ids), "goods_found": len(list_goods)},
            )

            return cast(dict[str, Any], response)
        except Exception as exc:
            logger.exception(
                "wb_prices_filter_failed",
                extra={
                    "nm_ids_count": len(nm_ids),
                    "error": str(exc),
                    "method": "POST",
                    "endpoint": "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter",
                },
            )
            raise

    async def add_products_to_promotion(
        self,
        *,
        promotion_id: int,
        nm_ids: list[int],
        upload_now: bool = True,
    ) -> dict[str, Any]:
        """Add products to a WB promotion.

        POST https://dp-calendar-api.wildberries.ru/api/v1/calendar/promotions/upload

        Not applicable for auto-promotions.
        """
        payload = {
            "data": {
                "promotionID": promotion_id,
                "uploadNow": upload_now,
                "nomenclatures": nm_ids,
            }
        }
        return cast(
            dict[str, Any],
            await self.calendar.request(
                "POST",
                "/api/v1/calendar/promotions/upload",
                headers=self.headers,
                json=payload,
            ),
        )

    def normalize_fbs_order(self, payload: dict[str, Any]) -> NormalizedOrder:
        """Normalize WB FBS order to internal format."""
        if not payload.get("id"):
            raise ValidationError("Missing required field: id", field="id")

        created = payload.get("createdAt")
        order_date = (
            datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created
            else datetime.now(tz=UTC)
        )
        price = self.extract_fbs_order_price(payload)
        logger.debug(
            "wb_fbs_price_normalized",
            extra={
                "order_id": payload.get("id"),
                "nm_id": payload.get("nmId"),
                "raw_converted_final_price": payload.get("convertedFinalPrice"),
                "raw_final_price": payload.get("finalPrice"),
                "raw_converted_price": payload.get("convertedPrice"),
                "raw_price": payload.get("price"),
                "normalized_price": str(price),
            },
        )
        commission = self._extract_commission(payload, price)
        logistics = self._extract_logistics(payload)
        other = self._extract_other_expenses(payload)

        # Выручка продавца = цена покупателя - расходы МП
        seller_payout = price
        if commission:
            seller_payout -= commission
        seller_payout -= logistics
        seller_payout -= other

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
            seller_payout_estimated=seller_payout,
            commission_estimated=commission,
            logistics_estimated=logistics,
            other_marketplace_expenses_estimated=other,
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
        # ppvzForPay - это выплата продавцу от WB (уже за вычетом всех расходов МП)
        payout = Decimal(str(payload.get("ppvzForPay") or 0))
        commission = self._extract_commission(payload, revenue)
        logistics = self._extract_logistics(payload)
        other = self._extract_other_expenses(payload)

        # Если есть ppvzForPay, используем его как seller_payout
        seller_payout = payout if payout > 0 else revenue
        if payout == 0:
            # Рассчитываем вручную
            if commission:
                seller_payout -= commission
            seller_payout -= logistics
            seller_payout -= other

        item = NormalizedOrderItem(
            external_product_id=nm_id,
            seller_article=article,
            marketplace_article=nm_id,
            title=title,
            quantity=int(payload.get("quantity") or 1),
            buyer_price=revenue,
            seller_price=revenue,
            discounted_price=revenue,
            payout_amount_estimated=payout if payout > 0 else revenue,
            seller_payout_estimated=seller_payout,
            commission_estimated=commission,
            logistics_estimated=logistics,
            other_marketplace_expenses_estimated=other,
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
        order_date = self._parse_wb_statistics_datetime(payload.get("date")) or datetime.now(tz=UTC)
        nm_id = str(payload.get("nmId") or payload.get("nmID") or "")
        revenue = Decimal(str(payload.get("finishedPrice") or payload.get("totalPrice") or 0))
        commission = self._extract_commission(payload, revenue)
        logistics = self._extract_logistics(payload)
        other = self._extract_other_expenses(payload)

        # Выручка продавца = цена покупателя - расходы МП
        seller_payout = revenue
        if commission:
            seller_payout -= commission
        seller_payout -= logistics
        seller_payout -= other

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
            seller_payout_estimated=seller_payout,
            commission_estimated=commission,
            logistics_estimated=logistics,
            other_marketplace_expenses_estimated=other,
            raw_payload=payload,
        )
        external_id = str(
            payload.get("srid")
            or payload.get("odid")
            or f"wb-stat-order-{nm_id}-{order_date.isoformat()}"
        )
        is_cancel = bool(payload.get("isCancel"))
        is_seller_warehouse = self._is_seller_warehouse(payload.get("warehouseType"))
        sale_model = SaleModel.FBS if is_seller_warehouse else SaleModel.FBO
        warehouse_type = "seller" if is_seller_warehouse else "marketplace"
        delivery_schema = "FBS" if is_seller_warehouse else "FBO"
        return NormalizedOrder(
            marketplace=Marketplace.WB,
            order_external_id=external_id,
            srid=str(payload.get("srid") or "") or None,
            order_date=order_date,
            sale_model=sale_model,
            fulfillment_type=delivery_schema,
            urgency_type=UrgencyType.INFORMATIONAL,
            source_event_type=SourceEventType.STATISTICS_ORDER,
            status="cancelled" if is_cancel else "statistics_order",
            raw_status="cancelled" if is_cancel else "statistics_order",
            normalized_status="cancelled" if is_cancel else "ordered",
            warehouse=str(payload.get("warehouseName") or ""),
            warehouse_type=warehouse_type,
            delivery_schema=delivery_schema,
            requires_seller_action=False,
            items=[item],
            raw_payload=payload,
        )

    def normalize_supplier_sale(self, payload: dict[str, Any]) -> NormalizedSaleEvent:
        event_date = self._parse_wb_statistics_datetime(payload.get("date")) or datetime.now(tz=UTC)
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

    def normalize_supplier_return(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_date = self._parse_wb_statistics_datetime(
            payload.get("date") or payload.get("lastChangeDate")
        ) or datetime.now(tz=UTC)
        nm_id = str(payload.get("nmId") or payload.get("nmID") or "")
        sale_id = str(
            payload.get("saleID")
            or payload.get("srid")
            or f"wb-return-{nm_id}-{event_date.isoformat()}"
        )
        amount = abs(Decimal(str(payload.get("forPay") or payload.get("finishedPrice") or 0)))
        return {
            "external_event_id": f"wb-return-{sale_id}",
            "order_external_id": str(payload.get("srid") or "") or None,
            "event_date": event_date,
            "quantity": abs(int(payload.get("quantity") or 1)),
            "amount": amount,
            "reason": str(payload.get("returnReason") or "Возврат Wildberries"),
            "raw_payload": payload,
        }

    @staticmethod
    def is_supplier_sales_return(payload: dict[str, Any]) -> bool:
        sale_id = str(payload.get("saleID") or "").upper()
        doc_type = str(payload.get("docTypeName") or payload.get("docType") or "").lower()
        if sale_id.startswith("R") or "возврат" in doc_type or "return" in doc_type:
            return True
        try:
            return int(payload.get("quantity") or 1) < 0
        except (TypeError, ValueError):
            return False

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

    @staticmethod
    def _parse_wb_statistics_datetime(value: object) -> datetime | None:
        """Parse WB Statistics API datetime strings.

        WB Statistics API returns naive datetime strings like
        "2026-05-20T10:19:17" which represent Moscow time, not UTC.
        This method treats naive strings as Europe/Moscow timezone.
        """
        if not value:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=WB_STATISTICS_TZ)
        text = str(value)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo:
                return parsed
            logger.info(
                "wb_statistics_datetime_normalized",
                extra={"raw_value": text, "timezone": "Europe/Moscow"},
            )
            return parsed.replace(tzinfo=WB_STATISTICS_TZ)
        except ValueError:
            try:
                return datetime.strptime(text, "%d.%m.%Y").replace(tzinfo=WB_STATISTICS_TZ)
            except ValueError:
                return None

    @staticmethod
    def _is_seller_warehouse(value: object) -> bool:
        normalized = str(value or "").casefold()
        return "склад продавца" in normalized or normalized in {"seller", "fbs"}

    @classmethod
    def extract_fbs_order_price(cls, payload: dict[str, Any]) -> Decimal:
        """Return WB FBS order customer price in rubles.

        Wildberries FBS/DBS order price fields such as convertedFinalPrice,
        finalPrice, convertedPrice and price are returned in kopecks according
        to the official Orders API examples and field notes. Statistics/report
        fields with Rub suffix are normalized separately and already represent
        rubles.
        """

        for key in ("convertedFinalPrice", "finalPrice", "convertedPrice", "price"):
            if payload.get(key) is not None:
                return cls._kopecks_to_rubles(payload[key])
        return Decimal("0.00")

    @staticmethod
    def _kopecks_to_rubles(value: Any) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return Decimal("0.00")
        return (amount / Decimal("100")).quantize(Decimal("0.01"))

    @staticmethod
    def _extract_commission(payload: dict[str, Any], revenue: Decimal) -> Decimal | None:
        for key in (
            "commission",
            "commissionRub",
            "commissionAmount",
            "ppvzReward",
            "supplierReward",
            "retailAmountCommission",
        ):
            if payload.get(key) is not None:
                return abs(Decimal(str(payload[key])))
        for key in ("commissionPercent", "commissionPercentRub", "ppvzKvw", "ppvzKvwPrc"):
            if payload.get(key) is not None:
                percent = Decimal(str(payload[key]))
                return (revenue * percent / Decimal("100")).quantize(Decimal("0.01"))
        return None

    @staticmethod
    def _extract_logistics(payload: dict[str, Any]) -> Decimal:
        total = Decimal("0")
        for key in ("deliveryRub", "deliveryAmount", "logisticsCost", "logistics"):
            if payload.get(key) is not None:
                total += abs(Decimal(str(payload[key])))
        return total

    @staticmethod
    def _extract_other_expenses(payload: dict[str, Any]) -> Decimal:
        total = Decimal("0")
        for key in ("penalty", "penaltyRub", "storageFee", "acceptance", "deduction"):
            if payload.get(key) is not None:
                total += abs(Decimal(str(payload[key])))
        return total

    def normalize_card_product(
        self,
        *,
        payload: dict[str, Any],
        user_id: int,
        account_id: int,
    ) -> ProductUpsert:
        nm_id = str(payload.get("nmID") or payload.get("nmId") or "")
        dimensions = payload.get("dimensions")
        dimensions = dimensions if isinstance(dimensions, dict) else {}
        length = decimal_or_none(dimensions.get("length"))
        width = decimal_or_none(dimensions.get("width"))
        height = decimal_or_none(dimensions.get("height"))
        volume = calculate_volume_liters(length, width, height)
        chrt_id = _first_chrt_id(payload)
        barcode = _first_barcode(payload)
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
            barcode=barcode,
            chrt_id=chrt_id,
            title=payload.get("title"),
            brand=payload.get("brand"),
            image_url=image_url,
            category=payload.get("subjectName") or payload.get("object"),
            marketplace_category_id=(
                str(payload.get("subjectID") or payload.get("subjectId") or "") or None
            ),
            length_cm=length,
            width_cm=width,
            height_cm=height,
            volume_liters=volume,
            dimensions_source="WB_CONTENT_API" if volume is not None else None,
            is_active=not bool(payload.get("isDeleted")),
        )


def _first_chrt_id(payload: dict[str, Any]) -> str | None:
    sizes = payload.get("sizes")
    if not isinstance(sizes, list):
        return None
    for size in sizes:
        if isinstance(size, dict) and size.get("chrtID"):
            return str(size["chrtID"])
        if isinstance(size, dict) and size.get("chrtId"):
            return str(size["chrtId"])
    return None


def _first_barcode(payload: dict[str, Any]) -> str | None:
    sizes = payload.get("sizes")
    if not isinstance(sizes, list):
        return None
    for size in sizes:
        if not isinstance(size, dict):
            continue
        for key in ("skus", "barcodes", "barcode"):
            value = size.get(key)
            if isinstance(value, list) and value:
                return str(value[0]).strip() or None
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None
