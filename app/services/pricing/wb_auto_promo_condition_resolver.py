"""Resolve WB auto promotion entry-price conditions from raw API details."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import WbAutoPromotionCondition, WbPromotion

logger = logging.getLogger(__name__)

PRICE_FIELDS = (
    "requiredPrice",
    "planPrice",
    "maxPrice",
    "actionPrice",
    "participationPrice",
    "targetPrice",
    "thresholdPrice",
    "autoActionPrice",
    "discountPrice",
    "priceForParticipation",
    "maxDiscountedPrice",
    "promotionPrice",
    "actionDiscountedPrice",
)
NESTED_PRICE_PATHS = (
    ("priceInfo", "requiredPrice"),
    ("priceInfo", "maxPrice"),
    ("pricing", "requiredPrice"),
    ("pricing", "maxPrice"),
    ("conditions", "requiredPrice"),
    ("conditions", "maxPrice"),
)
PRODUCT_LIST_KEYS = {"nomenclatures", "products", "items", "goods"}
NM_ID_FIELDS = ("nmID", "nmId", "id")
FULL_PRICE_FIELDS = ("fullPrice", "price", "basePrice", "wbPrice", "priceBeforeDiscount")
DISCOUNT_FIELDS = ("requiredDiscount", "discount", "planDiscount", "targetDiscount")


@dataclass(slots=True)
class WbAutoPromoConditionDTO:
    wb_nm_id: int
    required_price: Decimal | None
    max_auto_promo_price: Decimal | None
    current_wb_price: Decimal | None
    current_full_price: Decimal | None
    current_discount: int | None
    is_participating: bool | None
    promotion_id: int | None
    promotion_name: str | None
    raw_payload: dict[str, Any]
    source: str = "wb_api"
    confidence: str = "low"


class WbAutoPromoConditionResolver:
    """Find product-level entry prices in changing WB auto-promotion payloads."""

    def resolve(
        self,
        detail: dict[str, Any],
        *,
        promotion_id: int | None = None,
        promotion_name: str | None = None,
    ) -> list[WbAutoPromoConditionDTO]:
        conditions: list[WbAutoPromoConditionDTO] = []
        for item in self._iter_product_items(detail):
            wb_nm_id = self._extract_nm_id(item)
            if wb_nm_id is None:
                continue

            required_price, confidence = self._extract_required_price(item)
            conditions.append(
                WbAutoPromoConditionDTO(
                    wb_nm_id=wb_nm_id,
                    required_price=required_price,
                    max_auto_promo_price=required_price,
                    current_wb_price=self._money(item.get("price") or item.get("currentPrice")),
                    current_full_price=self._first_money(item, FULL_PRICE_FIELDS),
                    current_discount=self._int_optional(
                        item.get("discount") or item.get("currentDiscount")
                    ),
                    is_participating=self._parse_bool(
                        item.get("inAction")
                        or item.get("isParticipating")
                        or item.get("participating")
                    ),
                    promotion_id=promotion_id,
                    promotion_name=promotion_name,
                    raw_payload=item,
                    confidence=confidence,
                )
            )

        if not conditions:
            logger.info(
                "wb_auto_promo_condition_resolver_no_products",
                extra={"promotion_id": promotion_id, "detail_keys": list(detail.keys())},
            )
        return conditions

    async def resolve_for_account(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        marketplace_account_id: int,
    ) -> list[WbAutoPromoConditionDTO]:
        result = await session.execute(
            select(WbPromotion).where(
                WbPromotion.user_id == user_id,
                WbPromotion.marketplace_account_id == marketplace_account_id,
                WbPromotion.promotion_type == "auto",
            )
        )
        resolved: list[WbAutoPromoConditionDTO] = []
        for promotion in result.scalars().all():
            raw_payload = promotion.raw_payload or {}
            detail = raw_payload.get("_details") if isinstance(raw_payload, dict) else None
            if not isinstance(detail, dict):
                detail = raw_payload if isinstance(raw_payload, dict) else {}
            conditions = self.resolve(
                detail,
                promotion_id=promotion.wb_promotion_id,
                promotion_name=promotion.name,
            )
            for condition in conditions:
                await self._upsert_condition(
                    session,
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    condition=condition,
                )
            resolved.extend(conditions)
        await session.commit()
        return resolved

    async def _upsert_condition(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        marketplace_account_id: int,
        condition: WbAutoPromoConditionDTO,
    ) -> None:
        result = await session.execute(
            select(WbAutoPromotionCondition).where(
                WbAutoPromotionCondition.marketplace_account_id == marketplace_account_id,
                WbAutoPromotionCondition.wb_promotion_id == condition.promotion_id,
                WbAutoPromotionCondition.wb_nm_id == condition.wb_nm_id,
                WbAutoPromotionCondition.source == condition.source,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = WbAutoPromotionCondition(
                user_id=user_id,
                marketplace_account_id=marketplace_account_id,
                wb_promotion_id=condition.promotion_id,
                wb_nm_id=condition.wb_nm_id,
                promotion_name=condition.promotion_name,
                source=condition.source,
            )
            session.add(record)
        record.required_price = condition.required_price
        record.current_wb_price = condition.current_wb_price
        record.is_participating = condition.is_participating
        record.confidence = condition.confidence
        record.raw_payload = condition.raw_payload
        record.synced_at = datetime.now(tz=UTC)

    def _iter_product_items(self, payload: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []

        def walk(value: Any, parent_key: str | None = None) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    walk(nested, key)
                return
            if not isinstance(value, list):
                return

            if parent_key in PRODUCT_LIST_KEYS:
                for entry in value:
                    if isinstance(entry, dict):
                        found.append(entry)
            for entry in value:
                if isinstance(entry, (dict, list)):
                    walk(entry, parent_key)

        walk(payload)
        return self._dedupe_items(found)

    def _extract_required_price(self, item: dict[str, Any]) -> tuple[Decimal | None, str]:
        for key in PRICE_FIELDS:
            parsed = self._money(item.get(key))
            if parsed is not None and parsed > 0:
                return parsed, "high"

        for first, second in NESTED_PRICE_PATHS:
            nested = item.get(first)
            if not isinstance(nested, dict):
                continue
            parsed = self._money(nested.get(second))
            if parsed is not None and parsed > 0:
                return parsed, "high" if second == "requiredPrice" else "medium"

        price_from_discount = self._price_from_discount(item)
        if price_from_discount is not None:
            return price_from_discount, "medium"

        return None, "low"

    def _price_from_discount(self, item: dict[str, Any]) -> Decimal | None:
        full_price = self._first_money(item, FULL_PRICE_FIELDS)
        required_discount = self._first_money(item, DISCOUNT_FIELDS)
        if full_price is None or required_discount is None:
            return None
        if full_price <= 0 or required_discount < 0 or required_discount >= 100:
            return None
        result = full_price * (Decimal("1") - required_discount / Decimal("100"))
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _first_money(self, item: dict[str, Any], keys: tuple[str, ...]) -> Decimal | None:
        for key in keys:
            parsed = self._money(item.get(key))
            if parsed is not None:
                return parsed
        for nested_key in ("priceInfo", "pricing", "conditions"):
            nested = item.get(nested_key)
            if isinstance(nested, dict):
                parsed = self._first_money(nested, keys)
                if parsed is not None:
                    return parsed
        return None

    @staticmethod
    def _extract_nm_id(item: dict[str, Any]) -> int | None:
        for key in NM_ID_FIELDS:
            raw_value = item.get(key)
            if raw_value is None:
                continue
            try:
                return int(str(raw_value).strip())
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _money(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _parse_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1", "да", "участвует"}:
                return True
            if lowered in {"false", "no", "0", "нет", "не участвует"}:
                return False
        return None

    @staticmethod
    def _int_optional(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[int | None, int]] = set()
        for item in items:
            nm_id = WbAutoPromoConditionResolver._extract_nm_id(item)
            identity = (nm_id, id(item))
            if identity in seen:
                continue
            seen.add(identity)
            result.append(item)
        return result
