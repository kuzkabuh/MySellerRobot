#!/usr/bin/env python
"""Diagnostic script for WB promotion nomenclatures sync.

Usage:
    python -m app.scripts.sync_wb_promotion_nomenclatures_once --account-id 2
    python -m app.scripts.sync_wb_promotion_nomenclatures_once --account-id 2 --all-promo true
    python -m app.scripts.sync_wb_promotion_nomenclatures_once --account-id 2 --limit 10
    python -m app.scripts.sync_wb_promotion_nomenclatures_once --account-id 2 --promotion-id 12345
"""

# ruff: noqa: E402, E501

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import AsyncSessionFactory
from app.core.security import TokenCipher
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount, WbPromotion, WbPromotionNomenclature
from app.models.enums import Marketplace
from app.services.wb.wb_promotions_sync_service import WbPromotionsSyncService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wb_promo_nomenclatures_sync")


async def sync_nomenclatures_once(
    account_id: int,
    promotion_id: int | None = None,
    limit: int = 100,
    all_promo: bool = True,
) -> dict:
    """Sync nomenclatures for a specific account."""
    get_settings()
    cipher = TokenCipher()

    async with AsyncSessionFactory() as session:
        # Load account
        account = await session.get(MarketplaceAccount, account_id)
        if account is None:
            logger.error(f"Account {account_id} not found")
            return {"error": "Account not found"}

        if account.marketplace != Marketplace.WB:
            logger.error(f"Account {account_id} is not WB")
            return {"error": "Not a WB account"}

        if not account.is_active:
            logger.error(f"Account {account_id} is not active")
            return {"error": "Account not active"}

        logger.info(f"Account loaded: {account.name} (id={account.id})")

        # If all_promo=True, use the full sync service
        if all_promo and promotion_id is None:
            logger.info(f"Using full sync service with allPromo={all_promo}")
            service = WbPromotionsSyncService(session, cipher)
            stats = await service.sync_all_accounts(all_promo=True)
            await session.commit()

            return {
                "promotions_fetched": stats.promotions_fetched,
                "regular_promotions": stats.promotions_upserted - stats.promotions_skipped_auto,
                "auto_promotions": stats.promotions_skipped_auto,
                "nomenclatures_fetched": stats.nomenclatures_fetched,
                "nomenclatures_upserted": stats.nomenclatures_upserted,
                "products_matched": stats.products_matched,
                "errors_count": len(stats.errors),
                "all_promo": stats.all_promo_mode,
                "errors": stats.errors,
            }

        # Otherwise, use the legacy per-promotion approach
        # Decrypt API key and create client
        api_key = cipher.decrypt(account.encrypted_api_key)
        client = WildberriesClient(api_key)

        # Get active regular promotions
        now_utc = datetime.now(tz=UTC)
        start_date = (now_utc - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_date = (now_utc + timedelta(days=90)).replace(
            hour=23, minute=59, second=59, microsecond=0
        )
        start_date.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_date.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        if promotion_id:
            # Get specific promotion
            result = await session.execute(
                select(WbPromotion).where(
                    WbPromotion.marketplace_account_id == account_id,
                    WbPromotion.wb_promotion_id == promotion_id,
                )
            )
            promotions = list(result.scalars().all())
            logger.info(f"Fetching nomenclatures for specific promotion: {promotion_id}")
        else:
            # Get active regular promotions
            result = await session.execute(
                select(WbPromotion)
                .where(
                    WbPromotion.marketplace_account_id == account_id,
                    WbPromotion.start_datetime <= now_utc,
                    WbPromotion.end_datetime >= now_utc,
                    WbPromotion.promotion_type != "auto",
                )
                .order_by(WbPromotion.wb_promotion_id)
            )
            promotions = list(result.scalars().all())
            logger.info(f"Found {len(promotions)} active regular promotions")

        stats = {
            "account_id": account_id,
            "active_promotions": len(promotions),
            "regular_promotions_processed": 0,
            "auto_promotions_skipped": 0,
            "rows_fetched": 0,
            "rows_saved": 0,
            "errors": [],
        }

        for promo in promotions:
            logger.info(
                f"Processing promotion: {promo.wb_promotion_id} - {promo.name or 'Unknown'}"
            )

            # Fetch nomenclatures for both in_action states
            for in_action in (True, False):
                offset = 0
                page = 0
                while True:
                    page += 1
                    try:
                        logger.info(
                            f"  Fetching nomenclatures: promotion_id={promo.wb_promotion_id}, "
                            f"in_action={in_action}, limit={limit}, offset={offset}"
                        )
                        response = await client.get_promotion_nomenclatures(
                            promotion_id=promo.wb_promotion_id,
                            in_action=in_action,
                            limit=limit,
                            offset=offset,
                        )

                        # Log response structure
                        response_keys = list(response.keys()) if isinstance(response, dict) else []
                        logger.info(f"  Response keys: {response_keys}")

                        # Parse response
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

                        logger.info(f"  Page {page}: fetched {len(items_data)} items")

                        if not items_data:
                            # Log first item structure if available
                            if isinstance(data, dict):
                                data_keys = list(data.keys())
                                logger.info(f"  Data keys: {data_keys}")
                                if data_keys:
                                    sample_key = data_keys[0]
                                    sample_value = data.get(sample_key)
                                    if isinstance(sample_value, list) and sample_value:
                                        logger.info(f"  Sample {sample_key}[0]: {sample_value[0]}")
                                    elif isinstance(sample_value, dict):
                                        logger.info(
                                            f"  Sample {sample_value}: {dict(list(sample_value.items())[:5])}"
                                        )
                            break

                        # Save items
                        now_utc = datetime.now(tz=UTC)
                        for item in items_data:
                            wb_nm_id = int(
                                item.get("id") or item.get("nmId") or item.get("nmID") or 0
                            )
                            if not wb_nm_id:
                                logger.warning(f"  Skipping item with no nmID: {item}")
                                continue

                            # Upsert
                            result = await session.execute(
                                select(WbPromotionNomenclature).where(
                                    WbPromotionNomenclature.marketplace_account_id == account_id,
                                    WbPromotionNomenclature.wb_promotion_id
                                    == promo.wb_promotion_id,
                                    WbPromotionNomenclature.wb_nm_id == wb_nm_id,
                                    WbPromotionNomenclature.in_action == in_action,
                                )
                            )
                            nomenclature = result.scalar_one_or_none()

                            if nomenclature is None:
                                nomenclature = WbPromotionNomenclature(
                                    user_id=account.user_id,
                                    marketplace_account_id=account_id,
                                    wb_promotion_id=promo.wb_promotion_id,
                                    wb_nm_id=wb_nm_id,
                                    in_action=in_action,
                                )
                                session.add(nomenclature)
                                stats["rows_saved"] += 1
                            else:
                                stats["rows_saved"] += 1

                            # Parse values
                            from decimal import Decimal, InvalidOperation

                            def _money(val):
                                if val in (None, "", "null"):
                                    return None
                                try:
                                    return Decimal(str(val).replace(",", ".")).quantize(
                                        Decimal("0.01")
                                    )
                                except (InvalidOperation, ValueError, TypeError):
                                    return None

                            def _decimal_optional(val):
                                if val in (None, "", "null"):
                                    return None
                                try:
                                    return Decimal(str(val).replace(",", "."))
                                except (InvalidOperation, ValueError, TypeError):
                                    return None

                            nomenclature.current_price = _money(item.get("price"))
                            nomenclature.currency_code = str(
                                item.get("currencyCode") or item.get("currency") or "RUB"
                            )[:16]
                            nomenclature.plan_price = _money(item.get("planPrice"))
                            nomenclature.current_discount = _decimal_optional(item.get("discount"))
                            nomenclature.plan_discount = _decimal_optional(item.get("planDiscount"))
                            nomenclature.raw_payload = item
                            nomenclature.synced_at = now_utc

                        stats["rows_fetched"] += len(items_data)

                        if len(items_data) < limit:
                            break

                        offset += limit

                    except Exception as e:
                        error_msg = f"Failed to fetch nomenclatures for promotion {promo.wb_promotion_id}, in_action={in_action}, offset={offset}: {e}"
                        logger.error(error_msg)
                        stats["errors"].append(error_msg)
                        break

            stats["regular_promotions_processed"] += 1

        # Commit
        await session.commit()
        logger.info(f"Committed {stats['rows_saved']} rows to database")

        return stats


async def main():
    parser = argparse.ArgumentParser(description="Sync WB promotion nomenclatures once")
    parser.add_argument("--account-id", type=int, required=True, help="Marketplace account ID")
    parser.add_argument(
        "--promotion-id", type=int, default=None, help="Specific promotion ID (optional)"
    )
    parser.add_argument("--limit", type=int, default=100, help="Page size for API requests")
    parser.add_argument(
        "--all-promo",
        type=str,
        default="true",
        help="Use allPromo=true for full sync (default: true)",
    )
    args = parser.parse_args()

    all_promo = args.all_promo.lower() in ("true", "1", "yes")

    logger.info("=" * 60)
    logger.info("WB Promotion Nomenclatures Sync - Manual Run")
    logger.info(f"allPromo={all_promo}")
    logger.info("=" * 60)

    stats = await sync_nomenclatures_once(
        account_id=args.account_id,
        promotion_id=args.promotion_id,
        limit=args.limit,
        all_promo=all_promo,
    )

    logger.info("=" * 60)
    logger.info("Sync Statistics:")
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")
    logger.info("=" * 60)

    if stats.get("errors"):
        logger.warning(f"Errors occurred: {len(stats['errors'])}")
        for error in stats["errors"]:
            logger.warning(f"  - {error}")


if __name__ == "__main__":
    asyncio.run(main())
