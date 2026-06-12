"""version: 1.0.0
description: Update Ozon product prices via /v1/product/import/prices.
    Validates min_price and max_price constraints before sending.
    Writes result to price_change_log.
updated: 2026-06-13
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.models.domain import (
    MarketplaceAccount,
    OzonCurrentPrice,
    PriceChangeLog,
    Product,
)
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)

STATUS_APPLIED = "applied"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_DRY_RUN = "dry_run"
SOURCE_MANUAL = "manual"


@dataclass(slots=True)
class OzonPriceUpdateItem:
    product_id: int
    offer_id: str
    new_price: Decimal
    new_old_price: Decimal | None = None
    reason: str | None = None
    comment: str | None = None


@dataclass(slots=True)
class OzonPriceUpdateResult:
    product_id: int
    offer_id: str
    status: str
    old_price: Decimal | None
    new_price: Decimal
    error: str | None = None


class OzonPriceUpdateService:
    """Update Ozon prices with validation and audit logging."""

    def __init__(self, session: AsyncSession, cipher: TokenCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()

    async def update_prices(
        self,
        user_id: int,
        marketplace_account_id: int,
        items: list[OzonPriceUpdateItem],
        *,
        dry_run: bool = False,
        source: str = SOURCE_MANUAL,
        changed_by_ip: str | None = None,
    ) -> list[OzonPriceUpdateResult]:
        account = await self.session.get(MarketplaceAccount, marketplace_account_id)
        if account is None or account.user_id != user_id or account.marketplace != Marketplace.OZON:
            raise ValueError(f"Ozon account {marketplace_account_id} not found for user {user_id}")

        results: list[OzonPriceUpdateResult] = []
        upload_items: list[dict[str, Any]] = []
        upload_context: list[tuple[OzonPriceUpdateItem, Decimal | None]] = []

        for item in items:
            product = await self.session.get(Product, item.product_id)
            if product is None:
                results.append(
                    OzonPriceUpdateResult(
                        product_id=item.product_id,
                        offer_id=item.offer_id,
                        status=STATUS_SKIPPED,
                        old_price=None,
                        new_price=item.new_price,
                        error="Товар не найден",
                    )
                )
                continue

            old_price = await self._get_current_price(marketplace_account_id, item.offer_id)
            error = self._validate(item, product)
            if error:
                await self._log(
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    product=product,
                    item=item,
                    old_price=old_price,
                    status=STATUS_SKIPPED,
                    dry_run=dry_run,
                    source=source,
                    changed_by_ip=changed_by_ip,
                    error=error,
                )
                results.append(
                    OzonPriceUpdateResult(
                        product_id=item.product_id,
                        offer_id=item.offer_id,
                        status=STATUS_SKIPPED,
                        old_price=old_price,
                        new_price=item.new_price,
                        error=error,
                    )
                )
                continue

            if dry_run:
                await self._log(
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    product=product,
                    item=item,
                    old_price=old_price,
                    status=STATUS_DRY_RUN,
                    dry_run=True,
                    source=source,
                    changed_by_ip=changed_by_ip,
                )
                results.append(
                    OzonPriceUpdateResult(
                        product_id=item.product_id,
                        offer_id=item.offer_id,
                        status=STATUS_DRY_RUN,
                        old_price=old_price,
                        new_price=item.new_price,
                    )
                )
                continue

            upload_items.append(
                {
                    "offer_id": item.offer_id,
                    "price": str(item.new_price),
                    "old_price": str(item.new_old_price) if item.new_old_price else "0",
                    "min_price": "0",
                }
            )
            upload_context.append((item, old_price, product))

        if upload_items and not dry_run:
            if not account.encrypted_client_id:
                raise ValueError(f"Ozon account {marketplace_account_id} missing client_id")
            api_key = self.cipher.decrypt(account.encrypted_api_key)
            client_id = self.cipher.decrypt(account.encrypted_client_id)
            client = OzonClient(client_id=client_id, api_key=api_key)
            try:
                response = await client.set_product_prices(upload_items)
                errors_map = self._parse_errors(response)
            except Exception as exc:
                errors_map = {item.offer_id: str(exc) for item, _, _ in upload_context}
                response = {}

            for item, old_price, product in upload_context:
                api_error = errors_map.get(item.offer_id)
                status = STATUS_FAILED if api_error else STATUS_APPLIED
                await self._log(
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    product=product,
                    item=item,
                    old_price=old_price,
                    status=status,
                    dry_run=False,
                    source=source,
                    changed_by_ip=changed_by_ip,
                    error=api_error,
                    raw_response=response,
                )
                results.append(
                    OzonPriceUpdateResult(
                        product_id=item.product_id,
                        offer_id=item.offer_id,
                        status=status,
                        old_price=old_price,
                        new_price=item.new_price,
                        error=api_error,
                    )
                )

        return results

    def _validate(self, item: OzonPriceUpdateItem, product: Product) -> str | None:
        if item.new_price <= 0:
            return "Цена должна быть больше 0"
        if product.min_price and item.new_price < product.min_price:
            return f"Цена {item.new_price} ниже минимальной {product.min_price}"
        if product.max_price and item.new_price > product.max_price:
            return f"Цена {item.new_price} выше максимальной {product.max_price}"
        return None

    async def _get_current_price(
        self, marketplace_account_id: int, offer_id: str
    ) -> Decimal | None:
        result = await self.session.execute(
            select(OzonCurrentPrice.price).where(
                OzonCurrentPrice.marketplace_account_id == marketplace_account_id,
                OzonCurrentPrice.offer_id == offer_id,
            )
        )
        return result.scalar_one_or_none()

    async def _log(
        self,
        *,
        user_id: int,
        marketplace_account_id: int,
        product: Product,
        item: OzonPriceUpdateItem,
        old_price: Decimal | None,
        status: str,
        dry_run: bool,
        source: str,
        changed_by_ip: str | None,
        error: str | None = None,
        raw_response: dict[str, Any] | None = None,
    ) -> None:
        log = PriceChangeLog(
            user_id=user_id,
            marketplace_account_id=marketplace_account_id,
            product_id=product.id,
            marketplace="OZON",
            external_product_id=item.offer_id,
            seller_article=product.seller_article,
            old_price=old_price,
            new_price=item.new_price,
            source=source,
            reason=item.reason,
            comment=item.comment,
            changed_by_user_id=user_id,
            changed_by_ip=changed_by_ip,
            status=status,
            error=error,
            dry_run=dry_run,
            raw_response=raw_response,
        )
        self.session.add(log)
        await self.session.flush()

    @staticmethod
    def _parse_errors(response: dict[str, Any]) -> dict[str, str]:
        errors: dict[str, str] = {}
        items = response.get("result", []) or []
        for item in items:
            if item.get("errors"):
                offer_id = item.get("offer_id", "")
                errors[offer_id] = "; ".join(
                    e.get("message", str(e)) for e in item["errors"]
                )
        return errors
