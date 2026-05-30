"""version: 1.0.0
description: Wildberries promotion participation workflow service.
    Handles: get nomenclatures, check eligibility, upload prices, add to promotion.
    Supports dry-run mode by default.
updated: 2026-05-21
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import TokenCipher
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount, Product, WbPromotion, WbPromotionNomenclature
from app.models.enums import Marketplace
from app.services.pricing.wb_mrc_price_service import WbMrcPriceService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProductEligibilityResult:
    """Eligibility check result for a single product in a promotion."""

    wb_nm_id: int
    product: Product | None
    nomenclature: WbPromotionNomenclature
    eligibility_status: str
    eligibility_reason: str
    calculated_discounted_price: Decimal | None = None
    calculated_price_before_discount: Decimal | None = None
    calculated_discount: Decimal | None = None
    in_action: bool = False


@dataclass(slots=True)
class PriceUploadResult:
    """Result of a price upload to WB."""

    upload_id: int | None
    status: str
    error_text: str | None = None


@dataclass(slots=True)
class PromotionUploadResult:
    """Result of adding products to a promotion."""

    upload_id: int | None
    already_exists: bool
    status: str
    error_text: str | None = None


@dataclass(slots=True)
class PromotionParticipationReport:
    """Full report for a promotion participation run."""

    promotion_id: int
    promotion_name: str | None
    dry_run: bool
    total_nomenclatures: int
    matched_products: int
    eligible_products: int
    blocked_products: int
    already_in_action: int
    not_found_in_db: int
    price_upload_id: int | None = None
    price_upload_status: str | None = None
    promotion_upload_id: int | None = None
    promotion_upload_status: str | None = None
    errors: list[str] = field(default_factory=list)
    product_results: list[ProductEligibilityResult] = field(default_factory=list)


class WbPromotionParticipationService:
    """Workflow for checking and adding products to WB promotions.

    Steps:
    1. Get nomenclatures from WB (/calendar/promotions/nomenclatures)
    2. Match with our Product DB
    3. Check eligibility (MRC, minPrice, margin)
    4. Calculate final price
    5. If dry_run: return report only
    6. If apply: upload prices, check status, add to promotion
    """

    def __init__(
        self,
        session: AsyncSession,
        cipher: TokenCipher | None = None,
    ) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()
        self.settings = get_settings()
        self.mrc_service = WbMrcPriceService()
        self._last_request_time = 0.0

    async def _rate_limit(self) -> None:
        """Enforce 600ms between requests for calendar API."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < 0.6:
            await asyncio.sleep(0.6 - elapsed)
        self._last_request_time = time.monotonic()

    async def prepare_and_upload_products_to_promotion(
        self,
        account_id: int,
        promotion_id: int,
        upload_now: bool = True,
        dry_run: bool = True,
    ) -> PromotionParticipationReport:
        """Main workflow: check eligibility and optionally apply.

        Args:
            account_id: MarketplaceAccount ID
            promotion_id: WB promotion ID
            upload_now: If True, set discount now; if False, at promotion start
            dry_run: If True, only check and report; if False, actually apply
        """
        event_name = (
            "promotion_participation_dry_run_started"
            if dry_run
            else "promotion_participation_apply_started"
        )
        logger.info(
            event_name,
            extra={"account_id": account_id, "promotion_id": promotion_id, "dry_run": dry_run},
        )

        # Load account and promotion
        account = await self.session.get(MarketplaceAccount, account_id)
        if account is None or account.marketplace != Marketplace.WB:
            return PromotionParticipationReport(
                promotion_id=promotion_id,
                promotion_name=None,
                dry_run=dry_run,
                total_nomenclatures=0,
                matched_products=0,
                eligible_products=0,
                blocked_products=0,
                already_in_action=0,
                not_found_in_db=0,
                errors=["Account not found or not WB"],
            )

        promo_result = await self.session.execute(
            select(WbPromotion).where(
                WbPromotion.marketplace_account_id == account_id,
                WbPromotion.wb_promotion_id == promotion_id,
            )
        )
        promotion = promo_result.scalar_one_or_none()
        if promotion is None:
            return PromotionParticipationReport(
                promotion_id=promotion_id,
                promotion_name=None,
                dry_run=dry_run,
                total_nomenclatures=0,
                matched_products=0,
                eligible_products=0,
                blocked_products=0,
                already_in_action=0,
                not_found_in_db=0,
                errors=["Promotion not found in DB"],
            )

        # Check auto-promotion
        if promotion.promotion_type and promotion.promotion_type.lower() == "auto":
            return PromotionParticipationReport(
                promotion_id=promotion_id,
                promotion_name=promotion.name,
                dry_run=dry_run,
                total_nomenclatures=0,
                matched_products=0,
                eligible_products=0,
                blocked_products=0,
                already_in_action=0,
                not_found_in_db=0,
                errors=["Автоакция. Метод /nomenclatures и /upload неприменимы."],
            )

        # Step 1: Get nomenclatures
        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client = WildberriesClient(api_key)

        all_nomenclatures = await self._fetch_all_nomenclatures(
            client=client,
            promotion_id=promotion_id,
        )

        report = PromotionParticipationReport(
            promotion_id=promotion_id,
            promotion_name=promotion.name,
            dry_run=dry_run,
            total_nomenclatures=len(all_nomenclatures),
            matched_products=0,
            eligible_products=0,
            blocked_products=0,
            already_in_action=0,
            not_found_in_db=0,
        )

        # Step 2: Match with our products and check eligibility
        product_results: list[ProductEligibilityResult] = []
        eligible_nm_ids: list[int] = []

        for nom in all_nomenclatures:
            result = await self._check_product_eligibility(account_id, nom)
            product_results.append(result)

            if result.eligibility_status == "eligible":
                report.eligible_products += 1
                eligible_nm_ids.append(nom.wb_nm_id)
            elif result.eligibility_status == "already_in_action":
                report.already_in_action += 1
            elif result.eligibility_status == "product_not_found":
                report.not_found_in_db += 1
            else:
                report.blocked_products += 1

        report.product_results = product_results
        report.matched_products = (
            report.eligible_products + report.blocked_products + report.already_in_action
        )

        if dry_run:
            logger.info(
                "promotion_participation_dry_run_completed",
                extra={
                    "account_id": account_id,
                    "promotion_id": promotion_id,
                    "total_nomenclatures": report.total_nomenclatures,
                    "eligible_products": report.eligible_products,
                    "blocked_products": report.blocked_products,
                    "already_in_action": report.already_in_action,
                },
            )
            return report

        # Step 3-7: Apply (upload prices, check status, add to promotion)
        if not eligible_nm_ids:
            report.errors.append("Нет товаров для добавления в акцию.")
            return report

        # Upload prices
        price_upload = await self._upload_prices(
            client, account_id, eligible_nm_ids, product_results
        )
        report.price_upload_id = price_upload.upload_id
        report.price_upload_status = price_upload.status

        if price_upload.status != "success":
            report.errors.append(
                f"Загрузка цен не успешна: {price_upload.error_text or price_upload.status}"
            )
            return report

        # Check price upload status
        price_status = await self._check_price_upload_status(client, price_upload.upload_id)
        report.price_upload_status = price_status

        if price_status not in ("processed_success", "processed_partial"):
            report.errors.append(f"Цены не обновлены: status={price_status}")
            return report

        # Add to promotion
        promo_upload = await self._add_to_promotion(
            client, promotion_id, eligible_nm_ids, upload_now
        )
        report.promotion_upload_id = promo_upload.upload_id
        report.promotion_upload_status = (
            "already_exists" if promo_upload.already_exists else promo_upload.status
        )

        if promo_upload.error_text:
            report.errors.append(promo_upload.error_text)

        logger.info(
            "promotion_participation_apply_completed",
            extra={
                "account_id": account_id,
                "promotion_id": promotion_id,
                "eligible_products": report.eligible_products,
                "price_upload_id": report.price_upload_id,
                "promotion_upload_id": report.promotion_upload_id,
                "errors_count": len(report.errors),
            },
        )

        return report

    async def _fetch_all_nomenclatures(
        self,
        client: WildberriesClient,
        promotion_id: int,
    ) -> list[WbPromotionNomenclature]:
        """Fetch all nomenclatures for a promotion (both inAction=false and true)."""
        all_items: list[WbPromotionNomenclature] = []
        limit = self.settings.wb_promotions_page_limit

        for in_action in (False, True):
            offset = 0
            while True:
                await self._rate_limit()
                try:
                    response = await client.get_promotion_nomenclatures(
                        promotion_id=promotion_id,
                        in_action=in_action,
                        limit=limit,
                        offset=offset,
                    )
                except Exception:
                    logger.exception(
                        "wb_promotions_nomenclatures_fetch_failed",
                        extra={
                            "promotion_id": promotion_id,
                            "in_action": in_action,
                            "offset": offset,
                        },
                    )
                    break

                # Parse official format: {"data": {"nomenclatures": [...]}}
                data = response.get("data")
                items_data = []
                if isinstance(data, dict):
                    items_data = data.get("nomenclatures", [])
                elif isinstance(data, list):
                    items_data = data
                elif isinstance(response.get("nomenclatures"), list):
                    items_data = response["nomenclatures"]

                if not isinstance(items_data, list):
                    items_data = []

                for item in items_data:
                    nom = WbPromotionNomenclature(
                        wb_nm_id=int(item.get("id") or item.get("nmId") or 0),
                        in_action=bool(item.get("inAction", False)),
                        current_price=_money(item.get("price")),
                        currency_code=str(item.get("currencyCode") or "RUB")[:16],
                        plan_price=_money(item.get("planPrice")),
                        current_discount=_decimal_optional(item.get("discount")),
                        plan_discount=_decimal_optional(item.get("planDiscount")),
                        raw_payload=item,
                    )
                    all_items.append(nom)

                if len(items_data) < limit:
                    break
                offset += limit

        return all_items

    async def _check_product_eligibility(
        self,
        account_id: int,
        nom: WbPromotionNomenclature,
    ) -> ProductEligibilityResult:
        """Check if a product is eligible for the promotion."""
        # Find product in our DB
        product = await self._find_product(account_id, nom.wb_nm_id)

        # Already in action
        if nom.in_action:
            return ProductEligibilityResult(
                wb_nm_id=nom.wb_nm_id,
                product=product,
                nomenclature=nom,
                eligibility_status="already_in_action",
                eligibility_reason="Товар уже участвует в акции.",
                in_action=True,
            )

        # Not found in our DB
        if product is None:
            return ProductEligibilityResult(
                wb_nm_id=nom.wb_nm_id,
                product=None,
                nomenclature=nom,
                eligibility_status="product_not_found",
                eligibility_reason="Товар не найден в базе MP Control.",
            )

        # No MRC
        if not product.mrc_price or product.mrc_price <= 0:
            return ProductEligibilityResult(
                wb_nm_id=nom.wb_nm_id,
                product=product,
                nomenclature=nom,
                eligibility_status="no_mrc",
                eligibility_reason="МРЦ не задана.",
            )

        # Invalid plan price
        if not nom.plan_price or nom.plan_price <= 0:
            return ProductEligibilityResult(
                wb_nm_id=nom.wb_nm_id,
                product=product,
                nomenclature=nom,
                eligibility_status="invalid_plan_price",
                eligibility_reason="planPrice отсутствует или <= 0.",
            )

        # Calculate MRC price
        try:
            mrc_result = self.mrc_service.calculate(
                mrc_price=product.mrc_price,
                promo_required_price=nom.plan_price,
            )
        except Exception:
            return ProductEligibilityResult(
                wb_nm_id=nom.wb_nm_id,
                product=product,
                nomenclature=nom,
                eligibility_status="calculation_error",
                eligibility_reason="Ошибка расчёта МРЦ.",
            )

        # Check minPrice
        if mrc_result.is_limited_by_min_price:
            return ProductEligibilityResult(
                wb_nm_id=nom.wb_nm_id,
                product=product,
                nomenclature=nom,
                eligibility_status="limited_by_min_price",
                eligibility_reason=(
                    "Цена ниже minPrice. Минимум: "
                    f"{mrc_result.final_discounted_price:.0f} ₽"
                ),
                calculated_discounted_price=mrc_result.final_discounted_price,
                calculated_price_before_discount=mrc_result.price_before_discount,
                calculated_discount=mrc_result.discount_percent,
            )

        # Check MRC rule limit
        if mrc_result.is_limited_by_mrc_rule:
            return ProductEligibilityResult(
                wb_nm_id=nom.wb_nm_id,
                product=product,
                nomenclature=nom,
                eligibility_status="limited_by_mrc_rule",
                eligibility_reason=(
                    "Цена акции ниже 90% от МРЦ. Минимум: "
                    f"{mrc_result.final_discounted_price:.0f} ₽"
                ),
                calculated_discounted_price=mrc_result.final_discounted_price,
                calculated_price_before_discount=mrc_result.price_before_discount,
                calculated_discount=mrc_result.discount_percent,
            )

        # Eligible
        return ProductEligibilityResult(
            wb_nm_id=nom.wb_nm_id,
            product=product,
            nomenclature=nom,
            eligibility_status="eligible",
            eligibility_reason="Товар подходит для участия.",
            calculated_discounted_price=mrc_result.final_discounted_price,
            calculated_price_before_discount=mrc_result.price_before_discount,
            calculated_discount=mrc_result.discount_percent,
        )

    async def _find_product(self, account_id: int, wb_nm_id: int) -> Product | None:
        """Find product by wb_nm_id matching marketplace_article or external_product_id."""
        nm_id_str = str(wb_nm_id)
        result = await self.session.execute(
            select(Product).where(
                Product.marketplace_account_id == account_id,
                Product.marketplace == Marketplace.WB,
                Product.is_active.is_(True),
                (Product.marketplace_article == nm_id_str)
                | (Product.external_product_id == nm_id_str),
            )
        )
        return result.scalar_one_or_none()

    async def _upload_prices(
        self,
        client: WildberriesClient,
        account_id: int,
        eligible_nm_ids: list[int],
        product_results: list[ProductEligibilityResult],
    ) -> PriceUploadResult:
        """Upload prices for eligible products to WB prices/discounts API."""
        # Build payload: only eligible products
        payload_items: list[dict[str, Any]] = []
        for result in product_results:
            if result.eligibility_status != "eligible":
                continue
            if (
                result.calculated_price_before_discount is None
                or result.calculated_discount is None
            ):
                continue

            payload_items.append(
                {
                    "id": result.wb_nm_id,
                    "price": int(result.calculated_price_before_discount.to_integral_value()),
                    "discount": int(result.calculated_discount.to_integral_value()),
                }
            )

        if not payload_items:
            return PriceUploadResult(
                upload_id=None, status="no_items", error_text="Нет товаров для загрузки цен."
            )

        try:
            await self._rate_limit()
            response = await client.upload_prices_discounts(payload_items)
            upload_id = response.get("data", {}).get("uploadID")
            return PriceUploadResult(upload_id=upload_id, status="created")
        except Exception:
            logger.exception("wb_promotion_price_upload_failed", extra={"account_id": account_id})
            return PriceUploadResult(
                upload_id=None, status="failed", error_text="Ошибка загрузки цен."
            )

    async def _check_price_upload_status(
        self,
        client: WildberriesClient,
        upload_id: int | None,
        max_attempts: int = 10,
        interval_seconds: int = 15,
    ) -> str:
        """Check price upload status with polling."""
        if upload_id is None:
            return "no_upload_id"

        for _attempt in range(max_attempts):
            await self._rate_limit()
            try:
                response = await client.get_price_upload_status(upload_id)
                data = response.get("data")
                if data is None:
                    # Task not processed yet
                    await asyncio.sleep(interval_seconds)
                    continue

                status = data.get("status")
                if status == 3:
                    return "processed_success"
                if status == 4:
                    return "cancelled"
                if status == 5:
                    return "processed_partial"
                if status == 6:
                    return "processed_all_errors"

                # Other status, keep polling
                await asyncio.sleep(interval_seconds)
            except Exception:
                logger.exception(
                    "wb_promotion_price_status_check_failed", extra={"upload_id": upload_id}
                )
                return "check_failed"

        return "pending_timeout"

    async def _add_to_promotion(
        self,
        client: WildberriesClient,
        promotion_id: int,
        nm_ids: list[int],
        upload_now: bool,
    ) -> PromotionUploadResult:
        """Add products to promotion via /calendar/promotions/upload."""
        # Chunk by 1000
        chunks = [nm_ids[i : i + 1000] for i in range(0, len(nm_ids), 1000)]

        last_result = PromotionUploadResult(upload_id=None, already_exists=False, status="failed")

        for chunk in chunks:
            await self._rate_limit()
            try:
                response = await client.add_products_to_promotion(
                    promotion_id=promotion_id,
                    nm_ids=chunk,
                    upload_now=upload_now,
                )
                data = response.get("data", {})
                last_result = PromotionUploadResult(
                    upload_id=data.get("uploadID"),
                    already_exists=bool(data.get("alreadyExists", False)),
                    status="created",
                )
            except Exception:
                logger.exception(
                    "wb_promotion_upload_failed",
                    extra={"promotion_id": promotion_id, "chunk_size": len(chunk)},
                )
                last_result = PromotionUploadResult(
                    upload_id=None,
                    already_exists=False,
                    status="failed",
                    error_text="Ошибка добавления товаров в акцию.",
                )

        return last_result


def _money(value: Any) -> Decimal | None:
    """Parse monetary value."""
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value).replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _decimal_optional(value: Any) -> Decimal | None:
    """Parse optional decimal."""
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        return None
