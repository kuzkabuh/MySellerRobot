"""version: 1.0.0
description: Wildberries auto promotions sync service.
    Handles auto promotion participation data that cannot be fetched via nomenclatures API.
updated: 2026-05-22
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import TokenCipher
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount, WbPromotion, WbPromotionNomenclature
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AutoPromoSyncStats:
    accounts_processed: int = 0
    accounts_failed: int = 0
    auto_promotions_found: int = 0
    auto_promotions_details_fetched: int = 0
    auto_promo_products_saved: int = 0
    errors: list[str] = field(default_factory=list)


class WbAutoPromotionsSyncService:
    """Sync auto promotion participation data.

    Auto promotions cannot use the /nomenclatures endpoint.
    Instead, we use /promotion/details to get participation data.
    """

    def __init__(self, session: AsyncSession, cipher: TokenCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()
        self.settings = get_settings()

    async def sync_auto_promotions(
        self,
        marketplace_account_id: int | None = None,
    ) -> AutoPromoSyncStats:
        """Sync auto promotion data for all or specific WB accounts."""
        stats = AutoPromoSyncStats()

        query = select(MarketplaceAccount).where(
            MarketplaceAccount.marketplace == Marketplace.WB,
            MarketplaceAccount.is_active.is_(True),
        )
        if marketplace_account_id is not None:
            query = query.where(MarketplaceAccount.id == marketplace_account_id)

        result = await self.session.execute(query)
        accounts = list(result.scalars().all())

        if not accounts:
            logger.info("wb_auto_promotions_sync_no_active_accounts")
            return stats

        for account in accounts:
            try:
                account_stats = await self._sync_account_auto_promotions(account)
                stats.accounts_processed += 1
                stats.auto_promotions_found += account_stats.auto_promotions_found
                stats.auto_promotions_details_fetched += (
                    account_stats.auto_promotions_details_fetched
                )
                stats.auto_promo_products_saved += account_stats.auto_promo_products_saved
                stats.errors.extend(account_stats.errors)
            except Exception:
                stats.accounts_failed += 1
                error_msg = f"Account {account.id} auto promo sync failed"
                stats.errors.append(error_msg)
                logger.exception(
                    "wb_auto_promotions_account_sync_failed",
                    extra={"account_id": account.id},
                )

        logger.info(
            "wb_auto_promotions_sync_completed",
            extra={
                "accounts_processed": stats.accounts_processed,
                "accounts_failed": stats.accounts_failed,
                "auto_promotions_found": stats.auto_promotions_found,
                "auto_promotions_details_fetched": stats.auto_promotions_details_fetched,
                "auto_promo_products_saved": stats.auto_promo_products_saved,
            },
        )

        return stats

    async def _sync_account_auto_promotions(
        self,
        account: MarketplaceAccount,
    ) -> AutoPromoSyncStats:
        """Sync auto promotions for a single account."""
        stats = AutoPromoSyncStats()

        # Find auto promotions for this account
        result = await self.session.execute(
            select(WbPromotion).where(
                WbPromotion.marketplace_account_id == account.id,
                WbPromotion.promotion_type == "auto",
            )
        )
        auto_promotions = list(result.scalars().all())

        if not auto_promotions:
            return stats

        stats.auto_promotions_found = len(auto_promotions)

        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client = WildberriesClient(api_key)
        now_utc = datetime.now(tz=UTC)

        # Fetch details in batches (API may have limits on promotionIDs count)
        batch_size = 50
        for i in range(0, len(auto_promotions), batch_size):
            batch = auto_promotions[i : i + batch_size]
            promo_ids = [p.wb_promotion_id for p in batch]

            try:
                await asyncio.sleep(0.6)  # Rate limiting
                details_response = await client.get_promotion_details(promotion_ids=promo_ids)
                stats.auto_promotions_details_fetched += len(batch)
            except Exception:
                error_msg = f"Failed to fetch details for promotions {promo_ids}"
                stats.errors.append(error_msg)
                logger.exception(
                    "wb_auto_promotions_details_fetch_failed",
                    extra={"account_id": account.id, "promotion_ids": promo_ids},
                )
                continue

            # Parse details response
            promo_details = _extract_promotion_details(details_response)

            for promo in batch:
                detail = promo_details.get(promo.wb_promotion_id)
                if detail:
                    # Update promotion with details data
                    await self._update_promotion_with_details(promo, detail, now_utc)

                    # Extract and save nomenclature data from details
                    products_saved = await self._save_auto_promo_nomenclatures(
                        account=account,
                        promotion=promo,
                        detail=detail,
                        now_utc=now_utc,
                    )
                    stats.auto_promo_products_saved += products_saved

        return stats

    async def _update_promotion_with_details(
        self,
        promotion: WbPromotion,
        detail: dict[str, Any],
        now_utc: datetime,
    ) -> None:
        """Update promotion record with details data."""
        # Update participation stats from details
        for key, _attr in [
            ("participationPercentage", None),
            ("inPromoActionLeftovers", None),
            ("inPromoActionTotal", None),
            ("notInPromoActionLeftovers", None),
            ("notInPromoActionTotal", None),
            ("exceptionProductsCount", None),
        ]:
            if key in detail:
                # Store in raw_payload for now
                pass

        # Merge detail into raw_payload
        if promotion.raw_payload is None:
            promotion.raw_payload = {}
        promotion.raw_payload["_details"] = detail
        promotion.synced_at = now_utc

        await self.session.flush()

    async def _save_auto_promo_nomenclatures(
        self,
        account: MarketplaceAccount,
        promotion: WbPromotion,
        detail: dict[str, Any],
        now_utc: datetime,
    ) -> int:
        """Save nomenclature data from auto promotion details.

        Auto promotion details may contain product participation data
        in various formats depending on WB API response structure.
        """
        saved = 0

        # Try to find nomenclatures/products in the detail response
        nomenclatures = _extract_nomenclatures_from_details(detail)

        for nom_data in nomenclatures:
            wb_nm_id = int(nom_data.get("id") or nom_data.get("nmId") or nom_data.get("nmID") or 0)
            if not wb_nm_id:
                continue

            # Check if nomenclature already exists
            result = await self.session.execute(
                select(WbPromotionNomenclature).where(
                    WbPromotionNomenclature.marketplace_account_id == account.id,
                    WbPromotionNomenclature.wb_promotion_id == promotion.wb_promotion_id,
                    WbPromotionNomenclature.wb_nm_id == wb_nm_id,
                    WbPromotionNomenclature.in_action.is_(True),
                )
            )
            nomenclature = result.scalar_one_or_none()

            if nomenclature is None:
                nomenclature = WbPromotionNomenclature(
                    user_id=account.user_id,
                    marketplace_account_id=account.id,
                    wb_promotion_id=promotion.wb_promotion_id,
                    wb_nm_id=wb_nm_id,
                    in_action=True,
                )
                self.session.add(nomenclature)

            nomenclature.current_price = _money(nom_data.get("price"))
            nomenclature.plan_price = _money(
                nom_data.get("planPrice")
                or nom_data.get("requiredPrice")
                or nom_data.get("maxPrice")
            )
            nomenclature.current_discount = _decimal_optional(nom_data.get("discount"))
            nomenclature.plan_discount = _decimal_optional(nom_data.get("planDiscount"))
            nomenclature.raw_payload = nom_data
            nomenclature.synced_at = now_utc
            saved += 1

        await self.session.flush()
        return saved


def _extract_promotion_details(response: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Extract promotion details from WB API response.

    Response format may vary. Try multiple formats:
    - {"data": {"promotions": [...]}}
    - {"data": [...]}
    - {"promotions": [...]}
    """
    result: dict[int, dict[str, Any]] = {}

    if not isinstance(response, dict):
        return result

    # Try data.promotions
    data = response.get("data")
    promotions = None
    if isinstance(data, dict):
        promotions = data.get("promotions")
    elif isinstance(data, list):
        promotions = data

    if promotions is None:
        promotions = response.get("promotions")

    if not isinstance(promotions, list):
        return result

    for promo in promotions:
        if not isinstance(promo, dict):
            continue
        promo_id = int(promo.get("id") or promo.get("promotionId") or 0)
        if promo_id:
            result[promo_id] = promo

    return result


def _extract_nomenclatures_from_details(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract nomenclature/product list from auto promotion details.

    Try multiple field names since WB API structure may vary:
    - nomenclatures
    - products
    - items
    - nmIds
    """
    for key in ("nomenclatures", "products", "items"):
        items = detail.get(key)
        if isinstance(items, list):
            return items

    # Try nested structures
    data = detail.get("data")
    if isinstance(data, dict):
        for key in ("nomenclatures", "products", "items"):
            items = data.get(key)
            if isinstance(items, list):
                return items

    return []


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
