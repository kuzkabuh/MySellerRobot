"""version: 1.0.0
description: Wildberries daily promotions synchronization service.
updated: 2026-05-21
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import TokenCipher
from app.integrations.wb import WildberriesClient
from app.models.domain import (
    MarketplaceAccount,
    Product,
    WbPromotion,
    WbPromotionNomenclature,
)
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WbPromotionsSyncStats:
    """Statistics for a single WB promotions sync run."""

    accounts_processed: int = 0
    accounts_failed: int = 0
    promotions_fetched: int = 0
    promotions_upserted: int = 0
    promotions_skipped_auto: int = 0
    nomenclatures_fetched: int = 0
    nomenclatures_upserted: int = 0
    products_matched: int = 0
    errors: list[str] = field(default_factory=list)


class WbPromotionsSyncService:
    """Synchronize WB calendar promotions and product nomenclatures.

    Runs daily at configured time (default 00:15 Moscow time).
    Fetches promotions active today, then fetches product lists for
    regular (non-auto) promotions.
    """

    def __init__(self, session: AsyncSession, cipher: TokenCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()
        self.settings = get_settings()

    async def sync_all_accounts(self) -> WbPromotionsSyncStats:
        """Run promotions sync for all active WB accounts."""
        stats = WbPromotionsSyncStats()

        result = await self.session.execute(
            select(MarketplaceAccount).where(
                MarketplaceAccount.marketplace == Marketplace.WB,
                MarketplaceAccount.is_active.is_(True),
            )
        )
        accounts = list(result.scalars().all())

        if not accounts:
            logger.info("wb_promotions_sync_no_active_accounts")
            return stats

        # Determine today's date range in UTC
        sync_tz_name = self.settings.wb_promotions_sync_timezone
        try:
            from zoneinfo import ZoneInfo
            sync_tz = ZoneInfo(sync_tz_name)
        except Exception:
            sync_tz = UTC

        now_in_sync_tz = datetime.now(tz=sync_tz)
        today_start = now_in_sync_tz.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1) - timedelta(seconds=1)

        # Convert to UTC ISO format for WB API
        start_datetime = today_start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_datetime = today_end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info(
            "wb_promotions_sync_period",
            extra={
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "accounts_count": len(accounts),
            },
        )

        for account in accounts:
            try:
                account_stats = await self._sync_account(
                    account=account,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                )
                stats.accounts_processed += 1
                stats.promotions_fetched += account_stats.promotions_fetched
                stats.promotions_upserted += account_stats.promotions_upserted
                stats.promotions_skipped_auto += account_stats.promotions_skipped_auto
                stats.nomenclatures_fetched += account_stats.nomenclatures_fetched
                stats.nomenclatures_upserted += account_stats.nomenclatures_upserted
                stats.products_matched += account_stats.products_matched
                stats.errors.extend(account_stats.errors)
            except Exception:
                stats.accounts_failed += 1
                error_msg = f"Account {account.id} sync failed"
                stats.errors.append(error_msg)
                logger.exception(
                    "wb_promotions_account_sync_failed",
                    extra={"account_id": account.id},
                )
                await self.session.rollback()

        logger.info(
            "wb_promotions_sync_completed",
            extra={
                "accounts_processed": stats.accounts_processed,
                "accounts_failed": stats.accounts_failed,
                "promotions_fetched": stats.promotions_fetched,
                "promotions_upserted": stats.promotions_upserted,
                "nomenclatures_fetched": stats.nomenclatures_fetched,
                "nomenclatures_upserted": stats.nomenclatures_upserted,
                "products_matched": stats.products_matched,
                "errors_count": len(stats.errors),
            },
        )

        return stats

    async def _sync_account(
        self,
        account: MarketplaceAccount,
        start_datetime: str,
        end_datetime: str,
    ) -> WbPromotionsSyncStats:
        """Sync promotions for a single WB account."""
        stats = WbPromotionsSyncStats()

        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client = WildberriesClient(api_key)

        # Step 1: Fetch promotions for today
        all_promotions = await self._fetch_all_promotions(
            client=client,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
        )
        stats.promotions_fetched = len(all_promotions)

        if not all_promotions:
            logger.info(
                "wb_promotions_no_promotions_for_account",
                extra={"account_id": account.id},
            )
            return stats

        # Step 2: Upsert promotions
        now_utc = datetime.now(tz=UTC)
        for promo_data in all_promotions:
            promo = await self._upsert_promotion(
                account=account,
                promo_data=promo_data,
                now_utc=now_utc,
            )
            stats.promotions_upserted += 1

            # Step 3: Fetch nomenclatures for regular promotions only
            promo_type = promo_data.get("type") or promo_data.get("promoType", "")
            is_auto = promo_type.lower() == "auto"

            if is_auto:
                stats.promotions_skipped_auto += 1
                logger.info(
                    "wb_promotions_skip_auto_nomenclatures",
                    extra={
                        "account_id": account.id,
                        "promotion_id": promo.wb_promotion_id,
                        "promotion_type": promo_type,
                    },
                )
                continue

            try:
                nomenclature_count = await self._sync_promotion_nomenclatures(
                    account=account,
                    promotion=promo,
                    client=client,
                    now_utc=now_utc,
                )
                stats.nomenclatures_fetched += nomenclature_count
            except Exception:
                error_msg = (
                    f"Failed to fetch nomenclatures for promotion {promo.wb_promotion_id}"
                )
                stats.errors.append(error_msg)
                logger.exception(
                    "wb_promotions_nomenclatures_sync_failed",
                    extra={
                        "account_id": account.id,
                        "promotion_id": promo.wb_promotion_id,
                    },
                )

        return stats

    async def _fetch_all_promotions(
        self,
        client: WildberriesClient,
        start_datetime: str,
        end_datetime: str,
    ) -> list[dict[str, Any]]:
        """Fetch all promotions for the date range with pagination."""
        all_promotions: list[dict[str, Any]] = []
        offset = 0
        limit = self.settings.wb_promotions_page_limit

        while True:
            try:
                response = await client.get_calendar_promotions(
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    all_promo=False,
                    limit=limit,
                    offset=offset,
                )
            except Exception:
                logger.exception("wb_promotions_fetch_failed", extra={"offset": offset})
                break

            promotions = response.get("promotions") or response.get("data") or []
            if not isinstance(promotions, list):
                promotions = []

            all_promotions.extend(promotions)

            if len(promotions) < limit:
                break

            offset += limit

        return all_promotions

    async def _upsert_promotion(
        self,
        account: MarketplaceAccount,
        promo_data: dict[str, Any],
        now_utc: datetime,
    ) -> WbPromotion:
        """Upsert a single WB promotion."""
        wb_promotion_id = int(
            promo_data.get("id") or promo_data.get("promotionId") or 0
        )
        if not wb_promotion_id:
            raise ValueError("Missing promotion ID in WB response")

        result = await self.session.execute(
            select(WbPromotion).where(
                WbPromotion.marketplace_account_id == account.id,
                WbPromotion.wb_promotion_id == wb_promotion_id,
            )
        )
        promo = result.scalar_one_or_none()

        if promo is None:
            promo = WbPromotion(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                wb_promotion_id=wb_promotion_id,
            )
            self.session.add(promo)

        promo.name = str(
            promo_data.get("name") or promo_data.get("title") or ""
        )[:512]
        promo.promotion_type = str(
            promo_data.get("type") or promo_data.get("promoType") or ""
        )[:64]
        promo.start_datetime = _parse_datetime(
            promo_data.get("startDateTime") or promo_data.get("startDate")
        )
        promo.end_datetime = _parse_datetime(
            promo_data.get("endDateTime") or promo_data.get("endDate")
        )
        promo.is_active_today = _is_active_today(
            promo.start_datetime, promo.end_datetime, now_utc
        )
        promo.raw_payload = promo_data
        promo.synced_at = now_utc

        await self.session.flush()
        return promo

    async def _sync_promotion_nomenclatures(
        self,
        account: MarketplaceAccount,
        promotion: WbPromotion,
        client: WildberriesClient,
        now_utc: datetime,
    ) -> int:
        """Fetch and upsert nomenclatures for a promotion."""
        total_fetched = 0
        offset = 0
        limit = self.settings.wb_promotions_page_limit
        wb_promotion_id = promotion.wb_promotion_id

        # Fetch both inAction=false and inAction=true
        for in_action in (False, True):
            offset = 0
            while True:
                try:
                    response = await client.get_promotion_nomenclatures(
                        promotion_id=wb_promotion_id,
                        in_action=in_action,
                        limit=limit,
                        offset=offset,
                    )
                except Exception:
                    logger.exception(
                        "wb_promotions_nomenclatures_fetch_failed",
                        extra={
                            "promotion_id": wb_promotion_id,
                            "in_action": in_action,
                            "offset": offset,
                        },
                    )
                    break

                items = response.get("nomenclatures") or response.get("data") or []
                if not isinstance(items, list):
                    items = []

                for item in items:
                    await self._upsert_nomenclature(
                        account=account,
                        promotion=promotion,
                        item_data=item,
                        in_action=in_action,
                        now_utc=now_utc,
                    )
                    total_fetched += 1

                if len(items) < limit:
                    break

                offset += limit

        return total_fetched

    async def _upsert_nomenclature(
        self,
        account: MarketplaceAccount,
        promotion: WbPromotion,
        item_data: dict[str, Any],
        in_action: bool,
        now_utc: datetime,
    ) -> None:
        """Upsert a single nomenclature item."""
        wb_nm_id = int(item_data.get("id") or item_data.get("nmId") or item_data.get("nmID") or 0)
        if not wb_nm_id:
            return

        result = await self.session.execute(
            select(WbPromotionNomenclature).where(
                WbPromotionNomenclature.marketplace_account_id == account.id,
                WbPromotionNomenclature.wb_promotion_id == promotion.wb_promotion_id,
                WbPromotionNomenclature.wb_nm_id == wb_nm_id,
                WbPromotionNomenclature.in_action == in_action,
            )
        )
        nomenclature = result.scalar_one_or_none()

        if nomenclature is None:
            nomenclature = WbPromotionNomenclature(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                wb_promotion_id=promotion.wb_promotion_id,
                wb_nm_id=wb_nm_id,
                in_action=in_action,
            )
            self.session.add(nomenclature)

        nomenclature.current_price = _money(item_data.get("price"))
        nomenclature.currency_code = (
            str(item_data.get("currencyCode") or item_data.get("currency") or "RUB")[:16]
        )
        nomenclature.plan_price = _money(item_data.get("planPrice"))
        nomenclature.current_discount = _decimal_optional(item_data.get("discount"))
        nomenclature.plan_discount = _decimal_optional(item_data.get("planDiscount"))
        nomenclature.raw_payload = item_data
        nomenclature.synced_at = now_utc

        await self.session.flush()

    async def get_actual_promo_for_product(
        self,
        *,
        marketplace_account_id: int,
        wb_nm_id: int,
    ) -> WbPromotionNomenclature | None:
        """Get the best active promo price for a product.

        Rules for selecting best promo:
        1. Minimum planPrice (if > 0)
        2. If tied, nearest end_datetime
        3. If still tied, smallest wb_promotion_id
        """
        from sqlalchemy import and_

        now_utc = datetime.now(tz=UTC)

        # Find active promotions for this account
        active_promos_result = await self.session.execute(
            select(WbPromotion.wb_promotion_id).where(
                WbPromotion.marketplace_account_id == marketplace_account_id,
                WbPromotion.is_active_today.is_(True),
                WbPromotion.start_datetime <= now_utc,
                WbPromotion.end_datetime >= now_utc,
            )
        )
        active_promo_ids = [row[0] for row in active_promos_result.all()]

        if not active_promo_ids:
            return None

        # Find nomenclatures for this product in active promotions
        result = await self.session.execute(
            select(WbPromotionNomenclature, WbPromotion.end_datetime)
            .join(
                WbPromotion,
                and_(
                    WbPromotion.wb_promotion_id == WbPromotionNomenclature.wb_promotion_id,
                    WbPromotion.marketplace_account_id == WbPromotionNomenclature.marketplace_account_id,
                ),
            )
            .where(
                WbPromotionNomenclature.marketplace_account_id == marketplace_account_id,
                WbPromotionNomenclature.wb_nm_id == wb_nm_id,
                WbPromotionNomenclature.wb_promotion_id.in_(active_promo_ids),
                WbPromotionNomenclature.plan_price.isnot(None),
                WbPromotionNomenclature.plan_price > 0,
            )
            .order_by(
                WbPromotionNomenclature.plan_price.asc(),
                WbPromotion.end_datetime.asc(),
                WbPromotionNomenclature.wb_promotion_id.asc(),
            )
        )

        rows = result.all()
        if not rows:
            return None

        # Log if multiple promos found
        if len(rows) > 1:
            logger.info(
                "wb_promotions_multiple_promos_for_product",
                extra={
                    "marketplace_account_id": marketplace_account_id,
                    "wb_nm_id": wb_nm_id,
                    "promos_found": len(rows),
                },
            )

        return rows[0][0]


def _parse_datetime(value: Any) -> datetime | None:
    """Parse datetime string from WB API response."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _is_active_today(
    start_dt: datetime | None,
    end_dt: datetime | None,
    now_utc: datetime,
) -> bool:
    """Check if a promotion is active at the given time."""
    if start_dt is None or end_dt is None:
        return False
    return start_dt <= now_utc <= end_dt


def _money(value: Any) -> Decimal | None:
    """Parse monetary value from WB API response."""
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value).replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _decimal_optional(value: Any) -> Decimal | None:
    """Parse optional decimal value."""
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        return None
