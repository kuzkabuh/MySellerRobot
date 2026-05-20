"""Repair WB duplicate orders created by srid vs order_external_id mismatch.

Usage:
    python -m app.cli.repair_wb_duplicate_orders
    python -m app.cli.repair_wb_duplicate_orders --dry-run
    python -m app.cli.repair_wb_duplicate_orders --apply
"""

import argparse
import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionFactory
from app.models.domain import Order, OrderItem, ProfitSnapshot, SalesEvent
from app.models.enums import Marketplace, SourceEventType

logger = logging.getLogger(__name__)


async def find_duplicates(session: AsyncSession) -> list[dict]:
    """Find WB duplicate pairs where LIVE_ORDER and STATISTICS_ORDER share the same srid."""
    result = await session.execute(
        text("""
            SELECT
                live.id AS live_id,
                live.order_external_id AS live_external_id,
                live.srid AS live_srid,
                live.source_event_type AS live_source,
                stat.id AS stat_id,
                stat.order_external_id AS stat_external_id,
                stat.srid AS stat_srid,
                stat.source_event_type AS stat_source,
                live.marketplace_account_id
            FROM orders live
            JOIN orders stat
              ON stat.marketplace_account_id = live.marketplace_account_id
              AND stat.marketplace = live.marketplace
              AND stat.srid = live.srid
              AND stat.id != live.id
            WHERE live.marketplace = 'wb'
              AND live.srid IS NOT NULL
              AND live.srid != ''
              AND live.source_event_type = 'LIVE_ORDER'
              AND stat.source_event_type = 'STATISTICS_ORDER'
            ORDER BY live.marketplace_account_id, live.srid
        """)
    )
    duplicates = []
    for row in result:
        duplicates.append({
            "live_id": row.live_id,
            "live_external_id": row.live_external_id,
            "live_srid": row.live_srid,
            "stat_id": row.stat_id,
            "stat_external_id": row.stat_external_id,
            "stat_srid": row.stat_srid,
            "account_id": row.marketplace_account_id,
        })
    return duplicates


async def merge_and_delete(
    session: AsyncSession,
    dup: dict,
    *,
    dry_run: bool = False,
) -> dict:
    """Merge statistics data into LIVE_ORDER and delete the duplicate.

    Returns a summary of actions taken.
    """
    live_id = dup["live_id"]
    stat_id = dup["stat_id"]
    actions: dict = {"live_id": live_id, "stat_id": stat_id, "steps": []}

    live_order = await session.get(Order, live_id)
    stat_order = await session.get(Order, stat_id)

    if live_order is None or stat_order is None:
        actions["steps"].append("skip: order not found")
        return actions

    # Merge enrichment data from statistics order into live order
    if stat_order.raw_payload:
        if not live_order.raw_payload:
            live_order.raw_payload = {}
        enrichment = live_order.raw_payload.get("_enrichment", {})
        enrichment["wb_statistics_order"] = stat_order.raw_payload
        live_order.raw_payload["_enrichment"] = enrichment
        actions["steps"].append("enrichment_payload_merged")
        logger.info(
            "wb_duplicate_orders_repair_merged",
            extra={
                "live_order_id": live_id,
                "stat_order_id": stat_id,
                "public_order_number": live_order.order_external_id,
                "srid": live_order.srid,
            },
        )

    # Merge order items data if live order has no items but stat order does
    if not live_order.items and stat_order.items:
        for stat_item in stat_order.items:
            new_item = OrderItem(
                order_id=live_id,
                product_id=stat_item.product_id,
                seller_article=stat_item.seller_article,
                marketplace_article=stat_item.marketplace_article,
                title=stat_item.title,
                quantity=stat_item.quantity,
                buyer_price=stat_item.buyer_price,
                seller_price=stat_item.seller_price,
                discounted_price=stat_item.discounted_price,
                payout_amount_estimated=stat_item.payout_amount_estimated,
                seller_payout_estimated=stat_item.seller_payout_estimated,
                commission_estimated=stat_item.commission_estimated,
                logistics_estimated=stat_item.logistics_estimated,
                other_marketplace_expenses_estimated=stat_item.other_marketplace_expenses_estimated,
                cost_price_used=stat_item.cost_price_used,
                package_cost_used=stat_item.package_cost_used,
                tax_rate=stat_item.tax_rate,
                tax_amount_estimated=stat_item.tax_amount_estimated,
                profit_estimated=stat_item.profit_estimated,
                margin_percent_estimated=stat_item.margin_percent_estimated,
                economy_confidence=stat_item.economy_confidence,
            )
            session.add(new_item)
            actions["steps"].append("order_items_moved")

    # Re-link profit snapshots from stat order items to live order items
    if stat_order.items and live_order.items:
        stat_item_ids = [item.id for item in stat_order.items]
        if stat_item_ids:
            await session.execute(
                text("""
                    UPDATE profit_snapshots
                    SET order_item_id = :live_item_id
                    WHERE order_item_id = ANY(:stat_item_ids)
                """),
                {
                    "live_item_id": live_order.items[0].id,
                    "stat_item_ids": stat_item_ids,
                },
            )
            actions["steps"].append("profit_snapshots_relinked")

    # Re-link sales events that reference the stat order
    await session.execute(
        text("""
            UPDATE sales_events
            SET related_order_id = :live_id
            WHERE related_order_id = :stat_id
        """),
        {"live_id": live_id, "stat_id": stat_id},
    )
    actions["steps"].append("sales_events_relinked")

    if not dry_run:
        # Delete stat order items first
        for item in stat_order.items:
            await session.delete(item)
        # Delete the duplicate order
        await session.delete(stat_order)
        await session.commit()
        actions["steps"].append("stat_order_deleted")
    else:
        actions["steps"].append("dry_run: no deletion")

    return actions


async def run_repair(*, dry_run: bool = False) -> list[dict]:
    """Main repair function. Returns list of action summaries."""
    async with AsyncSessionFactory() as session:
        duplicates = await find_duplicates(session)
        logger.info(
            "wb_duplicate_orders_repair_found",
            extra={"count": len(duplicates), "dry_run": dry_run},
        )
        results = []
        for dup in duplicates:
            result = await merge_and_delete(session, dup, dry_run=dry_run)
            results.append(result)
        return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair WB duplicate orders")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without changes")
    parser.add_argument("--apply", action="store_true", help="Actually apply the repair")
    args = parser.parse_args()

    dry_run = args.dry_run or not args.apply

    logging.basicConfig(level=logging.INFO)
    results = asyncio.run(run_repair(dry_run=dry_run))

    if not results:
        print("No duplicate WB orders found.")
        return

    print(f"Found {len(results)} duplicate pair(s):")
    for r in results:
        print(f"  LIVE order #{r['live_id']} (external_id={r.get('live_external_id', 'n/a')})")
        print(f"  STAT order #{r['stat_id']} (external_id={r.get('stat_external_id', 'n/a')})")
        print(f"  Actions: {', '.join(r['steps'])}")
        print()

    if dry_run:
        print("DRY RUN — no changes made. Use --apply to execute.")
    else:
        print("Repair completed successfully.")


if __name__ == "__main__":
    main()
