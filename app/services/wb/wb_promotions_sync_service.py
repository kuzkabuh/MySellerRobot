"""version: 5.0.0
description: Wildberries daily promotions synchronization service.
    Supports allPromo=true mode, proper data.promotions/data.nomenclatures parsing,
    rate limiting, extended date range, auto promotion details sync, and detailed diagnostics.
    Fetches promotions from yesterday to 90 days ahead.
    Includes Redis-based sync lock to prevent concurrent runs.
updated: 2026-05-22
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import TokenCipher
from app.integrations.wb import WildberriesClient
from app.models.domain import (
    MarketplaceAccount,
    Product,
    WbAutoPromotionCondition,
    WbPromotion,
    WbPromotionNomenclature,
)
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)

PROMOTIONS_SYNC_LOCK_KEY = "wb-promotions-sync:lock"
PROMOTIONS_SYNC_LOCK_TTL = 300  # 5 minutes max lock duration
PROMOTIONS_SYNC_COOLDOWN = 60  # 60 seconds cooldown between manual syncs


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
    all_promo_mode: bool = False
    sync_period_start: str = ""
    sync_period_end: str = ""
    errors: list[str] = field(default_factory=list)
    rate_limit_hits: int = 0
    regular_promotions_processed: int = 0
    regular_nomenclatures_empty: int = 0
    auto_details_failed: int = 0
    auto_details_success: int = 0
    sync_in_progress: bool = False


@dataclass(slots=True)
class AutoPromoConditionDTO:
    """Normalized auto promotion condition extracted from WB API details."""
    wb_nm_id: int
    required_price: Decimal | None
    current_wb_price: Decimal | None
    is_participating: bool | None
    promotion_id: int | None
    promotion_name: str | None
    raw_payload: dict[str, Any]


class WbPromotionsSyncService:
    """Synchronize WB calendar promotions and product nomenclatures.

    Runs daily at configured time (default 00:15 Moscow time).
    Fetches promotions active today, then fetches product lists for
    regular (non-auto) promotions.
    """

    def __init__(
        self,
        session: AsyncSession,
        cipher: TokenCipher | None = None,
        redis: Redis | None = None,
    ) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()
        self.settings = get_settings()
        self.redis = redis
        self._owns_redis = redis is None

    async def _get_redis(self) -> Redis:
        """Get Redis client, creating one if needed."""
        if self.redis is None:
            from redis.asyncio import Redis as AsyncRedis
            self.redis = AsyncRedis.from_url(
                self.settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            self._owns_redis = True
        return self.redis

    async def _close_redis(self) -> None:
        """Close Redis client if we own it."""
        if self._owns_redis and self.redis is not None:
            try:
                await self.redis.aclose()
            except Exception:
                pass
            self.redis = None
            self._owns_redis = False

    async def try_acquire_sync_lock(self) -> tuple[bool, str]:
        """Try to acquire sync lock. Returns (success, message)."""
        try:
            redis = await self._get_redis()

            # Check cooldown
            cooldown_key = f"{PROMOTIONS_SYNC_LOCK_KEY}:cooldown"
            last_sync = await redis.get(cooldown_key)
            if last_sync:
                remaining = PROMOTIONS_SYNC_COOLDOWN - (int(time.time()) - int(last_sync))
                if remaining > 0:
                    return False, f"Синхронизация уже запускалась. Подождите {remaining} сек."

            # Try to acquire lock
            acquired = await redis.set(PROMOTIONS_SYNC_LOCK_KEY, "1", ex=PROMOTIONS_SYNC_LOCK_TTL, nx=True)
            if not acquired:
                return False, "Синхронизация уже выполняется. Подождите завершения."

            # Set cooldown
            await redis.set(cooldown_key, str(int(time.time())), ex=PROMOTIONS_SYNC_COOLDOWN * 2)
            return True, ""
        except Exception as e:
            logger.warning("wb_promotions_sync_lock_error", extra={"error": str(e)})
            return True, ""  # Allow sync if Redis is unavailable

    async def release_sync_lock(self) -> None:
        """Release sync lock."""
        try:
            redis = await self._get_redis()
            await redis.delete(PROMOTIONS_SYNC_LOCK_KEY)
        except Exception as e:
            logger.warning("wb_promotions_sync_unlock_error", extra={"error": str(e)})
        finally:
            await self._close_redis()

    async def sync_all_accounts(
        self,
        all_promo: bool = True,
    ) -> WbPromotionsSyncStats:
        """Run promotions sync for all active WB accounts.

        Default all_promo=True to get all promotions including ones
        the seller is already participating in.
        """
        logger.info("sync_wb_daily_promotions_started")

        stats = WbPromotionsSyncStats()
        stats.all_promo_mode = all_promo

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

        # Determine extended date range in UTC: yesterday to 90 days ahead
        sync_tz_name = self.settings.wb_promotions_sync_timezone
        try:
            from zoneinfo import ZoneInfo
            sync_tz = ZoneInfo(sync_tz_name)
        except Exception:
            sync_tz = UTC

        now_in_sync_tz = datetime.now(tz=sync_tz)
        start_date = (now_in_sync_tz - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = (now_in_sync_tz + timedelta(days=90)).replace(hour=23, minute=59, second=59, microsecond=0)

        # Convert to UTC ISO format for WB API
        start_datetime = start_date.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_datetime = end_date.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        stats.sync_period_start = start_datetime
        stats.sync_period_end = end_datetime

        logger.info(
            "wb_promotions_sync_period",
            extra={
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "accounts_count": len(accounts),
                "all_promo": all_promo,
            },
        )

        for account in accounts:
            try:
                account_stats = await self._sync_account(
                    account=account,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    all_promo=all_promo,
                )
                stats.accounts_processed += 1
                stats.promotions_fetched += account_stats.promotions_fetched
                stats.promotions_upserted += account_stats.promotions_upserted
                stats.promotions_skipped_auto += account_stats.promotions_skipped_auto
                stats.nomenclatures_fetched += account_stats.nomenclatures_fetched
                stats.nomenclatures_upserted += account_stats.nomenclatures_upserted
                stats.products_matched += account_stats.products_matched
                stats.errors.extend(account_stats.errors)
                stats.rate_limit_hits += account_stats.rate_limit_hits
                stats.regular_promotions_processed += account_stats.regular_promotions_processed
                stats.regular_nomenclatures_empty += account_stats.regular_nomenclatures_empty
                stats.auto_details_failed += account_stats.auto_details_failed
                stats.auto_details_success += account_stats.auto_details_success
            except Exception:
                stats.accounts_failed += 1
                error_msg = f"Account {account.id} sync failed"
                stats.errors.append(error_msg)
                logger.exception(
                    "wb_promotions_account_sync_failed",
                    extra={"account_id": account.id},
                )
                await self.session.rollback()

        # After syncing all accounts, auto-generate price recommendations
        # for accounts that have auto promotion conditions
        if stats.promotions_skipped_auto > 0 or stats.auto_details_success > 0:
            await self._auto_generate_recommendations_for_all_accounts(accounts)

        logger.info(
            "sync_wb_daily_promotions_completed",
            extra={
                "accounts_processed": stats.accounts_processed,
                "accounts_failed": stats.accounts_failed,
                "promotions_fetched": stats.promotions_fetched,
                "promotions_upserted": stats.promotions_upserted,
                "regular_promotions_processed": stats.regular_promotions_processed,
                "auto_promotions_found": stats.promotions_skipped_auto,
                "nomenclatures_fetched": stats.nomenclatures_fetched,
                "nomenclatures_upserted": stats.nomenclatures_upserted,
                "regular_nomenclatures_empty": stats.regular_nomenclatures_empty,
                "auto_details_success": stats.auto_details_success,
                "auto_details_failed": stats.auto_details_failed,
                "products_matched": stats.products_matched,
                "rate_limit_hits": stats.rate_limit_hits,
                "errors_count": len(stats.errors),
                "all_promo": all_promo,
            },
        )

        return stats

    async def _sync_account(
        self,
        account: MarketplaceAccount,
        start_datetime: str,
        end_datetime: str,
        all_promo: bool = True,
    ) -> WbPromotionsSyncStats:
        """Sync promotions for a single WB account."""
        stats = WbPromotionsSyncStats()

        logger.info(
            "sync_wb_daily_promotions_account_started",
            extra={
                "account_id": account.id,
                "user_id": account.user_id,
                "account_name": account.name,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "all_promo": all_promo,
            },
        )

        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client = WildberriesClient(api_key)

        # Step 1: Fetch promotions for the date range
        all_promotions = await self._fetch_all_promotions(
            client=client,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            all_promo=all_promo,
        )
        stats.promotions_fetched = len(all_promotions)

        logger.info(
            "wb_promotions_list_fetched",
            extra={
                "account_id": account.id,
                "promotions_count": len(all_promotions),
                "all_promo": all_promo,
            },
        )

        if not all_promotions:
            logger.info(
                "wb_promotions_no_promotions_for_account",
                extra={
                    "account_id": account.id,
                    "all_promo": all_promo,
                    "start_datetime": start_datetime,
                    "end_datetime": end_datetime,
                },
            )
            # Don't wipe existing data — WB API may be temporarily unavailable
            return stats

        # Step 2: Upsert promotions and collect auto promotion IDs
        now_utc = datetime.now(tz=UTC)
        auto_promotion_ids: list[int] = []
        auto_promotion_map: dict[int, WbPromotion] = {}
        regular_promotion_count = 0

        for promo_data in all_promotions:
            try:
                promo = await self._upsert_promotion(
                    account=account,
                    promo_data=promo_data,
                    now_utc=now_utc,
                )
                stats.promotions_upserted += 1
            except Exception:
                error_msg = f"Failed to upsert promotion {promo_data.get('id', 'unknown')}"
                stats.errors.append(error_msg)
                logger.exception(
                    "wb_promotions_upsert_failed",
                    extra={"account_id": account.id, "promotion_data": promo_data.get("id")},
                )
                continue

            # Check if this is an auto promotion
            promo_type = promo_data.get("type") or promo_data.get("promoType", "")
            is_auto = promo_type.lower() == "auto"

            if is_auto:
                stats.promotions_skipped_auto += 1
                auto_promotion_ids.append(promo.wb_promotion_id)
                auto_promotion_map[promo.wb_promotion_id] = promo
                logger.info(
                    "wb_promotions_auto_promotion_found",
                    extra={
                        "account_id": account.id,
                        "promotion_id": promo.wb_promotion_id,
                        "promotion_name": promo.name,
                    },
                )
                continue

            regular_promotion_count += 1
            stats.regular_promotions_processed += 1

            # Step 3: Fetch nomenclatures for regular promotions only
            logger.info(
                "wb_promotion_nomenclatures_sync_promotion_started",
                extra={
                    "account_id": account.id,
                    "promotion_id": promo.wb_promotion_id,
                    "promotion_name": promo.name,
                    "promotion_type": promo.promotion_type,
                },
            )
            try:
                nomenclature_count = await self._sync_promotion_nomenclatures(
                    account=account,
                    promotion=promo,
                    client=client,
                    now_utc=now_utc,
                    stats=stats,
                )
                stats.nomenclatures_fetched += nomenclature_count
                if nomenclature_count == 0:
                    stats.regular_nomenclatures_empty += 1
                    logger.info(
                        "wb_promotion_nomenclatures_empty",
                        extra={
                            "account_id": account.id,
                            "promotion_id": promo.wb_promotion_id,
                            "promotion_name": promo.name,
                        },
                    )
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

        logger.info(
            "wb_promotions_saved",
            extra={
                "account_id": account.id,
                "promotions_upserted": stats.promotions_upserted,
                "regular_promotions": regular_promotion_count,
                "auto_promotions": stats.promotions_skipped_auto,
                "nomenclatures_fetched": stats.nomenclatures_fetched,
            },
        )

        # Log skipped auto promotions summary
        if auto_promotion_ids:
            logger.info(
                "wb_promotion_nomenclatures_sync_skipped_auto",
                extra={
                    "account_id": account.id,
                    "auto_promotion_ids": auto_promotion_ids,
                    "auto_promotions_count": len(auto_promotion_ids),
                    "reason": "Auto promotions do not support nomenclatures upload endpoint",
                },
            )

        # Step 4: Fetch auto promotion details and extract product participation
        if auto_promotion_ids:
            auto_stats = await self._sync_auto_promotion_details(
                account=account,
                client=client,
                auto_promotion_ids=auto_promotion_ids,
                auto_promotion_map=auto_promotion_map,
                now_utc=now_utc,
            )
            stats.nomenclatures_fetched += auto_stats.nomenclatures_fetched
            stats.nomenclatures_upserted += auto_stats.nomenclatures_upserted
            stats.errors.extend(auto_stats.errors)
            stats.rate_limit_hits += auto_stats.rate_limit_hits
            stats.auto_details_failed += auto_stats.auto_details_failed
            stats.auto_details_success += auto_stats.auto_details_success

        return stats

    async def _sync_auto_promotion_details(
        self,
        account: MarketplaceAccount,
        client: WildberriesClient,
        auto_promotion_ids: list[int],
        auto_promotion_map: dict[int, WbPromotion],
        now_utc: datetime,
    ) -> WbPromotionsSyncStats:
        """Fetch details for auto promotions and extract product participation data."""
        stats = WbPromotionsSyncStats()
        last_request_time = 0.0

        logger.info(
            "wb_auto_promotion_details_sync_started",
            extra={
                "account_id": account.id,
                "auto_promotion_ids_count": len(auto_promotion_ids),
            },
        )

        # Fetch details in batches
        batch_size = 50
        for i in range(0, len(auto_promotion_ids), batch_size):
            batch_ids = auto_promotion_ids[i:i + batch_size]

            # Rate limiting
            elapsed = time.monotonic() - last_request_time
            if elapsed < 0.6:
                await asyncio.sleep(0.6 - elapsed)
            last_request_time = time.monotonic()

            try:
                details_response = await client.get_promotion_details(promotion_ids=batch_ids)
                stats.auto_details_success += 1
            except Exception as exc:
                error_text = str(exc)
                stats.auto_details_failed += 1
                if "400" in error_text or "Invalid query params" in error_text:
                    logger.warning(
                        "wb_promotion_details_query_invalid",
                        extra={
                            "account_id": account.id,
                            "promotion_ids": batch_ids,
                            "error": error_text,
                        },
                    )
                    logger.info(
                        "wb_auto_promotions_details_unavailable",
                        extra={
                            "account_id": account.id,
                            "promotion_ids": batch_ids,
                            "reason": "WB API does not support details for these auto promotions",
                        },
                    )
                    continue
                if "429" in error_text or "rate" in error_text.lower():
                    stats.rate_limit_hits += 1
                    logger.warning(
                        "wb_auto_promotions_details_rate_limited",
                        extra={
                            "account_id": account.id,
                            "promotion_ids": batch_ids,
                        },
                    )
                    await asyncio.sleep(2)
                    continue
                error_msg = f"Failed to fetch details for auto promotions {batch_ids}"
                stats.errors.append(error_msg)
                logger.exception(
                    "wb_auto_promotions_details_fetch_failed",
                    extra={"account_id": account.id, "promotion_ids": batch_ids},
                )
                continue

            # Log response structure for debugging
            if isinstance(details_response, dict):
                response_keys = list(details_response.keys())
                data = details_response.get("data")
                data_keys = list(data.keys()) if isinstance(data, dict) else []
                logger.info(
                    "wb_auto_promotion_details_response_structure",
                    extra={
                        "account_id": account.id,
                        "batch_ids": batch_ids,
                        "response_keys": response_keys,
                        "data_keys": data_keys,
                        "has_data_list": isinstance(data, list),
                    },
                )

            # Parse details
            promo_details = _extract_promotion_details_from_response(details_response)

            logger.info(
                "wb_auto_promotion_details_parsed",
                extra={
                    "account_id": account.id,
                    "batch_ids": batch_ids,
                    "parsed_promo_ids": list(promo_details.keys()),
                },
            )

            for promo_id, detail in promo_details.items():
                promotion = auto_promotion_map.get(promo_id)
                if not promotion:
                    continue

                # Update promotion with details
                await self._update_auto_promotion_with_details(promotion, detail, now_utc)

                # Extract and save nomenclature data from details
                nomenclatures = _extract_nomenclatures_from_auto_detail(detail)

                # Log detail structure for debugging
                detail_keys = list(detail.keys()) if isinstance(detail, dict) else []
                logger.info(
                    "wb_auto_promotion_detail_nomenclatures_extracted",
                    extra={
                        "account_id": account.id,
                        "promotion_id": promo_id,
                        "detail_keys": detail_keys,
                        "nomenclatures_count": len(nomenclatures),
                    },
                )

                for nom_data in nomenclatures:
                    wb_nm_id = int(nom_data.get("id") or nom_data.get("nmId") or nom_data.get("nmID") or 0)
                    if not wb_nm_id:
                        continue

                    await self._upsert_auto_promo_nomenclature(
                        account=account,
                        promotion=promotion,
                        item_data=nom_data,
                        now_utc=now_utc,
                    )
                    stats.nomenclatures_fetched += 1

                # Extract and save auto promotion conditions (required prices) from WB API
                auto_conditions = extract_auto_promo_required_prices(
                    detail=detail,
                    promotion_id=promo_id,
                    promotion_name=promotion.name,
                )
                for cond_dto in auto_conditions:
                    if cond_dto.required_price is None:
                        continue
                    await self._upsert_auto_promo_condition_from_api(
                        account=account,
                        condition_dto=cond_dto,
                        now_utc=now_utc,
                    )

        logger.info(
            "wb_auto_promotion_details_sync_completed",
            extra={
                "account_id": account.id,
                "nomenclatures_fetched": stats.nomenclatures_fetched,
                "errors_count": len(stats.errors),
            },
        )

        return stats

    async def _update_auto_promotion_with_details(
        self,
        promotion: WbPromotion,
        detail: dict[str, Any],
        now_utc: datetime,
    ) -> None:
        """Update auto promotion with details data."""
        if promotion.raw_payload is None:
            promotion.raw_payload = {}
        promotion.raw_payload["_details"] = detail
        promotion.synced_at = now_utc
        await self.session.flush()

    async def _upsert_auto_promo_nomenclature(
        self,
        account: MarketplaceAccount,
        promotion: WbPromotion,
        item_data: dict[str, Any],
        now_utc: datetime,
    ) -> None:
        """Upsert nomenclature for auto promotion product."""
        wb_nm_id = int(item_data.get("id") or item_data.get("nmId") or item_data.get("nmID") or 0)
        if not wb_nm_id:
            return

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

        nomenclature.current_price = _money(item_data.get("price"))
        nomenclature.plan_price = _money(
            item_data.get("planPrice") or item_data.get("requiredPrice") or item_data.get("maxPrice")
        )
        nomenclature.current_discount = _decimal_optional(item_data.get("discount"))
        nomenclature.plan_discount = _decimal_optional(item_data.get("planDiscount"))
        nomenclature.raw_payload = item_data
        nomenclature.synced_at = now_utc

        await self.session.flush()

    async def _upsert_auto_promo_condition_from_api(
        self,
        account: MarketplaceAccount,
        condition_dto: AutoPromoConditionDTO,
        now_utc: datetime,
    ) -> None:
        """Upsert auto promotion condition extracted from WB API details.

        Saves conditions with source='wb_api' so they can be used
        automatically for price recommendations without manual input.
        """
        wb_nm_id = condition_dto.wb_nm_id
        if not wb_nm_id or condition_dto.required_price is None:
            return

        result = await self.session.execute(
            select(WbAutoPromotionCondition).where(
                WbAutoPromotionCondition.marketplace_account_id == account.id,
                WbAutoPromotionCondition.wb_nm_id == wb_nm_id,
                WbAutoPromotionCondition.promotion_name == (condition_dto.promotion_name or ""),
                WbAutoPromotionCondition.source == "wb_api",
            )
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            existing = WbAutoPromotionCondition(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                wb_nm_id=wb_nm_id,
                promotion_name=condition_dto.promotion_name,
                wb_promotion_id=condition_dto.promotion_id,
                source="wb_api",
            )
            self.session.add(existing)

        existing.required_price = condition_dto.required_price
        existing.current_wb_price = condition_dto.current_wb_price
        existing.is_participating = condition_dto.is_participating
        existing.raw_payload = condition_dto.raw_payload
        existing.synced_at = now_utc

        await self.session.flush()

    async def _auto_generate_recommendations_for_all_accounts(
        self,
        accounts: list[MarketplaceAccount],
    ) -> None:
        """Auto-generate price recommendations after auto promotion sync.

        For each account that has wb_auto_promotion_conditions with
        required_price, builds recommendations and saves them.
        """
        from app.services.pricing.wb_auto_promo_price_service import (
            WbAutoPromoPriceService,
        )

        price_service = WbAutoPromoPriceService(self.session)
        total_recs = 0

        for account in accounts:
            try:
                recs = await price_service.build_recommendations_for_conditions(
                    user_id=account.user_id,
                    marketplace_account_id=account.id,
                )
                for rec in recs:
                    await price_service.save_recommendation(
                        rec=rec,
                        user_id=account.user_id,
                        marketplace_account_id=account.id,
                    )
                total_recs += len(recs)
                logger.info(
                    "wb_auto_promo_recommendations_auto_generated",
                    extra={
                        "account_id": account.id,
                        "user_id": account.user_id,
                        "recommendations_count": len(recs),
                    },
                )
            except Exception:
                logger.exception(
                    "wb_auto_promo_recommendations_auto_generate_failed",
                    extra={"account_id": account.id},
                )

        if total_recs > 0:
            await self.session.flush()

        logger.info(
            "wb_auto_promo_recommendations_auto_generation_completed",
            extra={"total_recommendations": total_recs},
        )

    async def _fetch_all_promotions(
        self,
        client: WildberriesClient,
        start_datetime: str,
        end_datetime: str,
        all_promo: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch all promotions for the date range with pagination.

        Official WB API response format: {"data": {"promotions": [...]}}
        """
        all_promotions: list[dict[str, Any]] = []
        offset = 0
        limit = self.settings.wb_promotions_page_limit
        last_request_time = 0.0

        while True:
            # Rate limiting: 600ms between requests
            elapsed = time.monotonic() - last_request_time
            if elapsed < 0.6:
                await asyncio.sleep(0.6 - elapsed)
            last_request_time = time.monotonic()

            try:
                response = await client.get_calendar_promotions(
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    all_promo=all_promo,
                    limit=limit,
                    offset=offset,
                )
            except Exception:
                logger.exception("wb_promotions_fetch_failed", extra={"offset": offset, "all_promo": all_promo})
                break

            # Parse official format: {"data": {"promotions": [...]}}
            promotions = _extract_promotions_list(response)

            raw_count = len(promotions)

            # Diagnostic logging
            log_extra = {
                "offset": offset,
                "limit": limit,
                "all_promo": all_promo,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "http_status": response.get("_http_status", "unknown"),
                "response_type": type(response.get("data", response)).__name__,
                "raw_promotions_count_before_filter": raw_count,
            }

            if raw_count == 0:
                response_keys = list(response.keys()) if isinstance(response, dict) else []
                data_keys = list(response.get("data", {}).keys()) if isinstance(response.get("data"), dict) else []
                log_extra["response_keys"] = response_keys
                log_extra["data_keys"] = data_keys
                log_extra["response_preview"] = _safe_response_preview(response)

                if response.get("_http_status") == 200:
                    logger.info("wb_promotions_empty_response", extra=log_extra)
                break

            all_promotions.extend(promotions)

            if raw_count < limit:
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
        stats: WbPromotionsSyncStats | None = None,
    ) -> int:
        """Fetch and upsert nomenclatures for a promotion.

        Official WB API response format: {"data": {"nomenclatures": [...]}}
        """
        total_fetched = 0
        total_saved = 0
        limit = self.settings.wb_promotions_page_limit
        wb_promotion_id = promotion.wb_promotion_id
        last_request_time = 0.0

        logger.info(
            "wb_promotion_nomenclatures_sync_started",
            extra={
                "account_id": account.id,
                "user_id": account.user_id,
                "promotion_id": wb_promotion_id,
                "promotion_name": promotion.name,
                "promotion_type": promotion.promotion_type,
            },
        )

        # Fetch both inAction=false and inAction=true
        for in_action in (False, True):
            offset = 0
            page = 0
            while True:
                page += 1
                # Rate limiting
                elapsed = time.monotonic() - last_request_time
                if elapsed < 0.6:
                    await asyncio.sleep(0.6 - elapsed)
                last_request_time = time.monotonic()

                try:
                    response = await client.get_promotion_nomenclatures(
                        promotion_id=wb_promotion_id,
                        in_action=in_action,
                        limit=limit,
                        offset=offset,
                    )
                except Exception as exc:
                    error_text = str(exc)
                    if "429" in error_text or "rate" in error_text.lower():
                        if stats:
                            stats.rate_limit_hits += 1
                        logger.warning(
                            "wb_promotions_nomenclatures_rate_limited",
                            extra={
                                "account_id": account.id,
                                "promotion_id": wb_promotion_id,
                                "in_action": in_action,
                                "offset": offset,
                            },
                        )
                        await asyncio.sleep(2)
                        continue
                    if "422" in error_text or "Unprocessable" in error_text:
                        logger.warning(
                            "wb_promotion_nomenclatures_unavailable",
                            extra={
                                "account_id": account.id,
                                "promotion_id": wb_promotion_id,
                                "in_action": in_action,
                                "error": error_text,
                            },
                        )
                        break
                    error_msg = (
                        f"Failed to fetch nomenclatures for promotion "
                        f"{wb_promotion_id}, in_action={in_action}, "
                        f"offset={offset}"
                    )
                    logger.warning(
                        "wb_promotions_nomenclatures_fetch_failed",
                        extra={
                            "account_id": account.id,
                            "promotion_id": wb_promotion_id,
                            "in_action": in_action,
                            "offset": offset,
                            "page": page,
                            "error": error_text,
                        },
                    )
                    break

                # Parse official format: {"data": {"nomenclatures": [...]}}
                items = _extract_nomenclatures_list(response)

                logger.info(
                    "wb_promotion_nomenclatures_sync_page_fetched",
                    extra={
                        "account_id": account.id,
                        "promotion_id": wb_promotion_id,
                        "in_action": in_action,
                        "page": page,
                        "offset": offset,
                        "fetched_count": len(items),
                        "limit": limit,
                    },
                )

                if not items:
                    # Log response structure for debugging
                    if isinstance(response, dict):
                        response_keys = list(response.keys())
                        data = response.get("data")
                        data_keys = list(data.keys()) if isinstance(data, dict) else []
                        logger.info(
                            "wb_promotion_nomenclatures_empty_response",
                            extra={
                                "account_id": account.id,
                                "promotion_id": wb_promotion_id,
                                "in_action": in_action,
                                "page": page,
                                "response_keys": response_keys,
                                "data_keys": data_keys,
                                "http_status": response.get("_http_status", "unknown"),
                            },
                        )
                    break

                for item in items:
                    await self._upsert_nomenclature(
                        account=account,
                        promotion=promotion,
                        item_data=item,
                        in_action=in_action,
                        now_utc=now_utc,
                    )
                    total_fetched += 1
                    total_saved += 1

                if len(items) < limit:
                    break

                offset += limit

        logger.info(
            "wb_promotion_nomenclatures_sync_completed",
            extra={
                "account_id": account.id,
                "promotion_id": wb_promotion_id,
                "fetched_count": total_fetched,
                "saved_count": total_saved,
            },
        )

        logger.info(
            "wb_promotion_nomenclatures_sync_saved",
            extra={
                "account_id": account.id,
                "promotion_id": wb_promotion_id,
                "nomenclatures_upserted": total_saved,
            },
        )

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

        # Find active promotions for this account (overlapping with current time)
        active_promos_result = await self.session.execute(
            select(WbPromotion.wb_promotion_id).where(
                WbPromotion.marketplace_account_id == marketplace_account_id,
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


def _extract_promotions_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract promotions list from WB API response.

    Official format: {"data": {"promotions": [...]}}
    Fallback formats: {"promotions": [...]}, {"data": [...]}, [...]
    """
    if isinstance(response, list):
        return response

    if not isinstance(response, dict):
        return []

    # Official: data.promotions
    data = response.get("data")
    if isinstance(data, dict):
        promotions = data.get("promotions")
        if isinstance(promotions, list):
            return promotions

    # Fallback: top-level promotions
    promotions = response.get("promotions")
    if isinstance(promotions, list):
        return promotions

    # Fallback: data as list
    if isinstance(data, list):
        return data

    # Unknown format — log warning
    response_keys = list(response.keys())
    data_keys = list(data.keys()) if isinstance(data, dict) else []
    logger.warning(
        "wb_promotions_unknown_response_format",
        extra={
            "response_keys": response_keys,
            "data_keys": data_keys,
            "response_preview": _safe_response_preview(response),
        },
    )
    return []


def _extract_nomenclatures_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract nomenclatures list from WB API response.

    Official format: {"data": {"nomenclatures": [...]}}
    Fallback formats: {"nomenclatures": [...]}, {"data": [...]}, [...]
    """
    if isinstance(response, list):
        return response

    if not isinstance(response, dict):
        return []

    # Official: data.nomenclatures
    data = response.get("data")
    if isinstance(data, dict):
        nomenclatures = data.get("nomenclatures")
        if isinstance(nomenclatures, list):
            return nomenclatures

    # Fallback: top-level nomenclatures
    nomenclatures = response.get("nomenclatures")
    if isinstance(nomenclatures, list):
        return nomenclatures

    # Fallback: data as list
    if isinstance(data, list):
        return data

    # Unknown format
    response_keys = list(response.keys())
    data_keys = list(data.keys()) if isinstance(data, dict) else []
    logger.warning(
        "wb_promotions_nomenclatures_unknown_response_format",
        extra={
            "response_keys": response_keys,
            "data_keys": data_keys,
            "response_preview": _safe_response_preview(response),
        },
    )
    return []


def _safe_response_preview(response: Any, max_len: int = 1000) -> str:
    """Create a safe preview of response without tokens."""
    if isinstance(response, dict):
        safe = {k: v for k, v in response.items() if "token" not in k.lower() and "key" not in k.lower()}
        preview = str(safe)
    else:
        preview = str(response)
    if len(preview) > max_len:
        preview = preview[:max_len] + "...(truncated)"
    return preview


def _extract_promotion_details_from_response(response: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Extract promotion details from WB API response.

    Response format may vary. Try multiple formats:
    - {"data": {"promotions": [...]}}
    - {"data": [...]}
    - {"promotions": [...]}
    """
    result: dict[int, dict[str, Any]] = {}

    if not isinstance(response, dict):
        return result

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


def _extract_nomenclatures_from_auto_detail(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract nomenclature/product list from auto promotion details.

    Try multiple field names since WB API structure may vary.
    """
    for key in ("nomenclatures", "products", "items", "goods"):
        items = detail.get(key)
        if isinstance(items, list):
            return items

    data = detail.get("data")
    if isinstance(data, dict):
        for key in ("nomenclatures", "products", "items", "goods"):
            items = data.get(key)
            if isinstance(items, list):
                return items

    return []


def extract_auto_promo_required_prices(
    detail: dict[str, Any],
    promotion_id: int | None = None,
    promotion_name: str | None = None,
) -> list[AutoPromoConditionDTO]:
    """Extract auto promotion conditions (required prices) from WB API detail response.

    Searches for product entries in multiple possible structures:
    - detail["nomenclatures"], detail["products"], detail["items"], detail["goods"]
    - detail["data"]["nomenclatures"], etc.
    - detail["params"]["nomenclatures"], etc.
    - detail["conditions"]["nomenclatures"], etc.

    For each product entry, looks for price fields:
    - planPrice, requiredPrice, maxPrice, price, discountPrice
    - actionPrice, participationPrice, targetPrice, thresholdPrice, autoActionPrice

    Returns a list of AutoPromoConditionDTO objects.
    """
    conditions: list[AutoPromoConditionDTO] = []

    items_list = _extract_nomenclatures_from_auto_detail(detail)

    for item in items_list:
        if not isinstance(item, dict):
            continue

        wb_nm_id = int(item.get("id") or item.get("nmId") or item.get("nmID") or 0)
        if not wb_nm_id:
            continue

        required_price = _extract_required_price_from_item(item)
        current_wb_price = _money(item.get("price"))
        is_participating = item.get("inAction") or item.get("isParticipating") or item.get("participating")

        if isinstance(is_participating, str):
            is_participating = is_participating.lower() in ("true", "yes", "1", "да", "участвует")

        conditions.append(AutoPromoConditionDTO(
            wb_nm_id=wb_nm_id,
            required_price=required_price,
            current_wb_price=current_wb_price,
            is_participating=bool(is_participating) if is_participating is not None else None,
            promotion_id=promotion_id,
            promotion_name=promotion_name,
            raw_payload=item,
        ))

    # Diagnostic logging: if no items found, log structure for debugging
    if not items_list:
        detail_keys = list(detail.keys()) if isinstance(detail, dict) else []
        data = detail.get("data") if isinstance(detail, dict) else None
        data_keys = list(data.keys()) if isinstance(data, dict) else []
        logger.info(
            "wb_auto_promo_detail_no_items_found",
            extra={
                "promotion_id": promotion_id,
                "detail_keys": detail_keys,
                "data_keys": data_keys,
                "detail_preview": _safe_response_preview(detail, max_len=500),
            },
        )

    return conditions


def _extract_required_price_from_item(item: dict[str, Any]) -> Decimal | None:
    """Extract required/entry price from a single auto promotion product item.

    Searches for price fields in priority order:
    1. planPrice — planned price for the promotion
    2. requiredPrice — explicitly required price
    3. maxPrice — maximum allowed price (often the entry threshold)
    4. actionPrice — promotional action price
    5. participationPrice — price for participation
    6. targetPrice — target price
    7. thresholdPrice — threshold price
    8. autoActionPrice — auto action price
    9. discountPrice — discounted price
    10. price — current price (fallback, only if nothing else found)
    """
    price_keys = [
        "planPrice", "requiredPrice", "maxPrice",
        "actionPrice", "participationPrice", "targetPrice",
        "thresholdPrice", "autoActionPrice", "discountPrice",
    ]

    for key in price_keys:
        value = item.get(key)
        if value is not None:
            parsed = _money(value)
            if parsed is not None and parsed > 0:
                return parsed

    # Fallback: check nested price objects
    for key in ("priceInfo", "pricing", "conditions"):
        nested = item.get(key)
        if isinstance(nested, dict):
            for sub_key in ("planPrice", "requiredPrice", "maxPrice", "price"):
                value = nested.get(sub_key)
                if value is not None:
                    parsed = _money(value)
                    if parsed is not None and parsed > 0:
                        return parsed

    return None
