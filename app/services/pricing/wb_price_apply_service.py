"""Prepare and apply WB price payloads for pricing recommendations."""

import logging
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.wb import WildberriesClient
from app.models.domain import WbAutoPromoPriceRecommendation

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WbPriceApplyPayload:
    nm_id: int
    price: int
    discount: int
    final_discounted_price: Decimal | None = None

    def as_wb_item(self) -> dict[str, int]:
        return {"nmID": self.nm_id, "price": self.price, "discount": self.discount}


class WbPriceApplyService:
    """Build WB upload payloads without changing minPrice."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    @staticmethod
    def build_payload(
        *,
        nm_id: int,
        recommended_price: Decimal,
        discount: Decimal = Decimal("75"),
        min_price: Decimal | None = None,
        max_discounted_price: Decimal | None = None,
    ) -> WbPriceApplyPayload:
        if min_price is not None and recommended_price < min_price:
            raise ValueError("recommended_price is below WB minPrice")
        discount_factor = Decimal("1") - discount / Decimal("100")
        if discount_factor <= 0:
            raise ValueError("discount must be less than 100")
        full_wb_price = (recommended_price / discount_factor).to_integral_value(
            rounding=ROUND_CEILING
        )
        final_discounted = (full_wb_price * discount_factor).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        ceiling = max_discounted_price or recommended_price
        while final_discounted > ceiling and full_wb_price > 1:
            full_wb_price -= 1
            final_discounted = (full_wb_price * discount_factor).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        return WbPriceApplyPayload(
            nm_id=nm_id,
            price=int(full_wb_price),
            discount=int(discount),
            final_discounted_price=final_discounted,
        )

    async def prepare_from_recommendations(
        self,
        *,
        user_id: int,
        marketplace_account_id: int,
        recommendation_ids: list[int] | None = None,
        discount: Decimal = Decimal("75"),
    ) -> list[dict[str, Any]]:
        if self.session is None:
            raise RuntimeError("session is required for DB-backed preparation")
        query = select(WbAutoPromoPriceRecommendation).where(
            WbAutoPromoPriceRecommendation.user_id == user_id,
            WbAutoPromoPriceRecommendation.marketplace_account_id == marketplace_account_id,
            WbAutoPromoPriceRecommendation.status == "CAN_APPLY",
            WbAutoPromoPriceRecommendation.recommended_price.isnot(None),
        )
        if recommendation_ids:
            query = query.where(WbAutoPromoPriceRecommendation.id.in_(recommendation_ids))
        result = await self.session.execute(query)

        preview: list[dict[str, Any]] = []
        for rec in result.scalars().all():
            payload = self.build_payload(
                nm_id=rec.wb_nm_id,
                recommended_price=rec.recommended_price,
                discount=discount,
                min_price=rec.min_price,
            )
            preview.append({"recommendation": rec, "payload": payload.as_wb_item()})
        return preview

    async def apply(
        self,
        *,
        wb_api_key: str,
        user_id: int,
        marketplace_account_id: int,
        recommendation_ids: list[int],
        discount: Decimal = Decimal("75"),
        dry_run: bool = True,
    ) -> dict[str, Any]:
        items = [
            row["payload"]
            for row in await self.prepare_from_recommendations(
                user_id=user_id,
                marketplace_account_id=marketplace_account_id,
                recommendation_ids=recommendation_ids,
                discount=discount,
            )
        ]
        if dry_run or not items:
            return {"dry_run": True, "items": items}
        client = WildberriesClient(api_key=wb_api_key)
        response = await client.upload_task_prices_discounts(items)
        logger.info(
            "wb_pricing_apply_uploaded",
            extra={"marketplace_account_id": marketplace_account_id, "items_count": len(items)},
        )
        return {"dry_run": False, "items": items, "response": response}
