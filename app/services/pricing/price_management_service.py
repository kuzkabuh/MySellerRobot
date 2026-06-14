"""version: 1.0.0
description: Unified price management service for manual edits on WB and Ozon.
    Handles single product edits, bulk operations, validation, and audit logging.
    Bulk operations: set, +/-%, +/-fixed, round, min-margin, min-profit.
updated: 2026-06-13
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.models.domain import (
    MarketplaceAccount,
    OzonCurrentPrice,
    PriceChangeLog,
    Product,
    ProductCostHistory,
    WbProductPrice,
)
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)

STATUS_APPLIED = "applied"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_DRY_RUN = "dry_run"
SOURCE_MANUAL = "manual"
SOURCE_BULK = "bulk"


class BulkOperation(StrEnum):
    SET = "set"
    INCREASE_PERCENT = "increase_percent"
    DECREASE_PERCENT = "decrease_percent"
    INCREASE_FIXED = "increase_fixed"
    DECREASE_FIXED = "decrease_fixed"
    ROUND = "round"
    MIN_MARGIN = "min_margin"
    MIN_PROFIT = "min_profit"


@dataclass(slots=True)
class PriceEditItem:
    product_id: int
    marketplace: str
    new_price: Decimal
    new_discount: int | None = None
    reason: str | None = None
    comment: str | None = None


@dataclass(slots=True)
class BulkPriceParams:
    operation: BulkOperation
    value: Decimal
    round_to: int = 0
    marketplace_filter: str | None = None


@dataclass(slots=True)
class PriceEditResult:
    product_id: int
    status: str
    old_price: Decimal | None
    new_price: Decimal | None
    error: str | None = None


@dataclass(slots=True)
class BulkPricePreviewRow:
    product_id: int
    seller_article: str | None
    title: str | None
    marketplace: str
    current_price: Decimal | None
    new_price: Decimal | None
    can_apply: bool
    error: str | None = None


class PriceManagementService:
    """Unified service for manual price management across WB and Ozon."""

    def __init__(self, session: AsyncSession, cipher: TokenCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()

    async def edit_single_price(
        self,
        user_id: int,
        marketplace_account_id: int,
        item: PriceEditItem,
        *,
        dry_run: bool = False,
        source: str = SOURCE_MANUAL,
        changed_by_ip: str | None = None,
    ) -> PriceEditResult:
        """Edit price for a single product. Applies via marketplace API."""
        product = await self.session.get(Product, item.product_id)
        if product is None or product.user_id != user_id:
            return PriceEditResult(
                product_id=item.product_id,
                status=STATUS_SKIPPED,
                old_price=None,
                new_price=item.new_price,
                error="Товар не найден",
            )
        if product.marketplace_account_id != marketplace_account_id:
            return PriceEditResult(
                product_id=item.product_id,
                status=STATUS_SKIPPED,
                old_price=None,
                new_price=item.new_price,
                error="Товар относится к другому кабинету",
            )
        if product.marketplace.value != item.marketplace:
            return PriceEditResult(
                product_id=item.product_id,
                status=STATUS_SKIPPED,
                old_price=None,
                new_price=item.new_price,
                error="Маркетплейс товара не совпадает с операцией",
            )

        old_price = await self._get_current_price(product)
        validation_error = await self._validate_price(item.new_price, product)
        if validation_error:
            return PriceEditResult(
                product_id=item.product_id,
                status=STATUS_SKIPPED,
                old_price=old_price,
                new_price=item.new_price,
                error=validation_error,
            )

        if dry_run:
            await self._write_log(
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
            return PriceEditResult(
                product_id=item.product_id,
                status=STATUS_DRY_RUN,
                old_price=old_price,
                new_price=item.new_price,
            )

        account = await self.session.get(MarketplaceAccount, marketplace_account_id)
        if account is None or account.user_id != user_id:
            return PriceEditResult(
                product_id=item.product_id,
                status=STATUS_FAILED,
                old_price=old_price,
                new_price=item.new_price,
                error="Аккаунт не найден",
            )
        if (
            account.id != product.marketplace_account_id
            or account.marketplace != product.marketplace
        ):
            return PriceEditResult(
                product_id=item.product_id,
                status=STATUS_FAILED,
                old_price=old_price,
                new_price=item.new_price,
                error="Кабинет не соответствует товару",
            )

        try:
            if item.marketplace == "WB":
                api_error = await self._apply_wb_price(account, product, item)
            else:
                api_error = await self._apply_ozon_price(
                    account,
                    product,
                    item,
                    source=source,
                    changed_by_ip=changed_by_ip,
                )
        except Exception as exc:
            api_error = str(exc)

        status = STATUS_FAILED if api_error else STATUS_APPLIED
        if item.marketplace != Marketplace.OZON.value:
            await self._write_log(
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
            )
        return PriceEditResult(
            product_id=item.product_id,
            status=status,
            old_price=old_price,
            new_price=item.new_price,
            error=api_error,
        )

    async def build_bulk_preview(
        self,
        user_id: int,
        product_ids: list[int],
        params: BulkPriceParams,
    ) -> list[BulkPricePreviewRow]:
        """Calculate what new prices would be without applying them."""
        rows: list[BulkPricePreviewRow] = []
        for pid in product_ids:
            product = await self.session.get(Product, pid)
            if product is None or product.user_id != user_id:
                continue
            current_price = await self._get_current_price(product)
            cost_price = await self._get_cost_price(product)
            new_price = self._apply_operation(current_price, params, cost_price)
            error = None
            can_apply = True
            if new_price is not None:
                error = await self._validate_price(new_price, product)
                can_apply = error is None
            else:
                can_apply = False
                error = "Невозможно рассчитать цену"
            rows.append(
                BulkPricePreviewRow(
                    product_id=product.id,
                    seller_article=product.seller_article,
                    title=product.title,
                    marketplace=product.marketplace.value if product.marketplace else "",
                    current_price=current_price,
                    new_price=new_price,
                    can_apply=can_apply,
                    error=error,
                )
            )
        return rows

    async def apply_bulk_prices(
        self,
        user_id: int,
        product_ids: list[int],
        params: BulkPriceParams,
        *,
        marketplace_account_id: int | None = None,
        reason: str | None = None,
        comment: str | None = None,
        changed_by_ip: str | None = None,
    ) -> list[PriceEditResult]:
        """Apply bulk price operation to selected products."""
        results: list[PriceEditResult] = []
        for pid in product_ids:
            product = await self.session.get(Product, pid)
            if product is None or product.user_id != user_id:
                continue
            account_id = marketplace_account_id or product.marketplace_account_id
            if account_id != product.marketplace_account_id:
                results.append(
                    PriceEditResult(
                        product_id=pid,
                        status=STATUS_SKIPPED,
                        old_price=None,
                        new_price=None,
                        error="Товар относится к другому кабинету",
                    )
                )
                continue
            current_price = await self._get_current_price(product)
            cost_price = await self._get_cost_price(product)
            new_price = self._apply_operation(current_price, params, cost_price)
            if new_price is None:
                results.append(
                    PriceEditResult(
                        product_id=pid,
                        status=STATUS_SKIPPED,
                        old_price=current_price,
                        new_price=None,
                        error="Невозможно рассчитать новую цену",
                    )
                )
                continue
            item = PriceEditItem(
                product_id=pid,
                marketplace=product.marketplace.value if product.marketplace else "",
                new_price=new_price,
                reason=reason or params.operation.value,
                comment=comment,
            )
            result = await self.edit_single_price(
                user_id=user_id,
                marketplace_account_id=account_id,
                item=item,
                source=SOURCE_BULK,
                changed_by_ip=changed_by_ip,
            )
            results.append(result)
        return results

    def _apply_operation(
        self,
        current_price: Decimal | None,
        params: BulkPriceParams,
        cost_price: Decimal | None,
    ) -> Decimal | None:
        op = params.operation
        val = params.value

        if op == BulkOperation.SET:
            new_price = val

        elif op == BulkOperation.INCREASE_PERCENT:
            if current_price is None:
                return None
            new_price = current_price * (1 + val / 100)

        elif op == BulkOperation.DECREASE_PERCENT:
            if current_price is None:
                return None
            new_price = current_price * (1 - val / 100)

        elif op == BulkOperation.INCREASE_FIXED:
            if current_price is None:
                return None
            new_price = current_price + val

        elif op == BulkOperation.DECREASE_FIXED:
            if current_price is None:
                return None
            new_price = current_price - val

        elif op == BulkOperation.ROUND:
            if current_price is None:
                return None
            step = params.round_to or int(val) or 1
            new_price = (current_price / step).to_integral_value(ROUND_HALF_UP) * step

        elif op == BulkOperation.MIN_MARGIN:
            # new_price = cost / (1 - margin%) — minimum price to achieve target margin
            if cost_price is None:
                return None
            margin_factor = 1 - val / 100
            if margin_factor <= 0:
                return None
            new_price = cost_price / margin_factor

        elif op == BulkOperation.MIN_PROFIT:
            # new_price = cost + target_profit
            if cost_price is None:
                return None
            new_price = cost_price + val

        else:
            return None

        return max(Decimal("1"), new_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    async def _validate_price(self, price: Decimal, product: Product) -> str | None:
        if price <= 0:
            return "Цена должна быть больше 0"
        min_price = await self._get_effective_min_price(product)
        if min_price and price < min_price:
            return f"Цена {price} ниже минимальной {min_price}"
        if product.max_price and price > product.max_price:
            return f"Цена {price} выше максимальной {product.max_price}"
        return None

    async def _get_effective_min_price(self, product: Product) -> Decimal | None:
        if product.min_price:
            return product.min_price
        if product.marketplace == Marketplace.OZON:
            offer_id = product.seller_article or product.external_product_id
            if not offer_id:
                return None
            result = await self.session.execute(
                select(OzonCurrentPrice.min_price).where(
                    OzonCurrentPrice.marketplace_account_id == product.marketplace_account_id,
                    OzonCurrentPrice.offer_id == offer_id,
                    OzonCurrentPrice.min_price.isnot(None),
                )
            )
            return result.scalar_one_or_none()
        return None

    async def _get_current_price(self, product: Product) -> Decimal | None:
        if product.marketplace == Marketplace.WB:
            nm_id_str = product.external_product_id or product.marketplace_article
            if not nm_id_str:
                return None
            try:
                nm_id = int(nm_id_str)
            except (ValueError, TypeError):
                return None
            result = await self.session.execute(
                select(WbProductPrice.discounted_price, WbProductPrice.price).where(
                    WbProductPrice.marketplace_account_id == product.marketplace_account_id,
                    WbProductPrice.wb_nm_id == nm_id,
                )
            )
            row = result.one_or_none()
            if row is None:
                return None
            discounted_price, price = row
            return discounted_price or price
        elif product.marketplace == Marketplace.OZON:
            offer_id = product.seller_article or product.external_product_id
            if not offer_id:
                return None
            result = await self.session.execute(
                select(OzonCurrentPrice.price).where(
                    OzonCurrentPrice.marketplace_account_id == product.marketplace_account_id,
                    OzonCurrentPrice.offer_id == offer_id,
                )
            )
            return result.scalar_one_or_none()
        return None

    async def _get_cost_price(self, product: Product) -> Decimal | None:
        result = await self.session.execute(
            select(ProductCostHistory.cost_price)
            .where(
                ProductCostHistory.product_id == product.id,
                ProductCostHistory.valid_to.is_(None),
            )
            .order_by(ProductCostHistory.valid_from.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _apply_wb_price(
        self, account: MarketplaceAccount, product: Product, item: PriceEditItem
    ) -> str | None:
        from app.integrations.wb import WildberriesClient
        from app.services.wb.pricing.wb_price_update_service import (
            calculate_wb_price_payload_for_target,
        )

        nm_id_str = product.external_product_id or product.marketplace_article
        if not nm_id_str:
            return "Не найден nmID"
        try:
            nm_id = int(nm_id_str)
        except (ValueError, TypeError):
            return f"Некорректный nmID: {nm_id_str}"

        discount = (
            Decimal(str(item.new_discount)) if item.new_discount is not None else Decimal("75")
        )
        payload = calculate_wb_price_payload_for_target(
            target_discounted_price=item.new_price,
            discount_percent=discount,
            nm_id=nm_id,
        )
        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client = WildberriesClient(api_key=api_key)
        try:
            response = await client.upload_task_prices_discounts(
                items=[{"nmID": nm_id, "price": payload.price, "discount": payload.discount}]
            )
            if response.get("error"):
                return response.get("errorText", "WB API error")
            return None
        except Exception as exc:
            return str(exc)

    async def _apply_ozon_price(
        self,
        account: MarketplaceAccount,
        product: Product,
        item: PriceEditItem,
        *,
        source: str,
        changed_by_ip: str | None,
    ) -> str | None:
        from app.services.ozon.pricing.ozon_price_update_service import (
            OzonPriceUpdateItem,
            OzonPriceUpdateService,
        )

        offer_id = product.seller_article or product.external_product_id
        if not offer_id:
            return "Не найден offer_id"

        update_item = OzonPriceUpdateItem(
            product_id=product.id,
            offer_id=offer_id,
            new_price=item.new_price,
            reason=item.reason,
            comment=item.comment,
        )
        results = await OzonPriceUpdateService(self.session, self.cipher).update_prices(
            user_id=product.user_id,
            marketplace_account_id=account.id,
            items=[update_item],
            source=source,
            changed_by_ip=changed_by_ip,
        )
        if results and results[0].error:
            return results[0].error
        return None

    async def _write_log(
        self,
        *,
        user_id: int,
        marketplace_account_id: int,
        product: Product,
        item: PriceEditItem,
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
            marketplace=item.marketplace,
            external_product_id=product.external_product_id or "",
            seller_article=product.seller_article,
            old_price=old_price,
            new_price=item.new_price,
            new_discount=item.new_discount,
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
