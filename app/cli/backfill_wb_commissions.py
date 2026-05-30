"""version: 1.0.0
description: Backfill script to recalculate WB commissions for existing orders.

Re-syncs WB tariff data from the official API, updates per-model commission
fields on products, then recalculates profit snapshots for WB orders that
used the old single-rate commission.

Usage:
    python -m app.cli.backfill_wb_commissions --dry-run
    python -m app.cli.backfill_wb_commissions
"""

import argparse
import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionFactory
from app.core.security import TokenCipher
from app.integrations.wb import WildberriesClient
from app.models.domain import (
    MarketplaceAccount,
    Order,
    OrderItem,
    Product,
    ProfitSnapshot,
)
from app.models.enums import CalculationType, Marketplace
from app.services.marketplace_estimates import (
    calculate_planned_economics,
)
from app.services.product_sync_service import (
    WbTariffRow,
    _decimal_percent,
)

logger = logging.getLogger(__name__)

WB_COMMISSION_API_FIELDS: dict[str, str] = {
    "paidStorageKgvp": "commission_fbw",
    "kgvpMarketplace": "commission_fbs",
    "kgvpSupplier": "commission_dbs",
    "kgvpSupplierExpress": "commission_edbs",
    "kgvpPickup": "commission_pickup",
    "kgvpBooking": "commission_booking",
}


async def _load_wb_tariffs(client: WildberriesClient) -> dict[str, WbTariffRow]:
    try:
        rows = await client.get_commission_tariffs(locale="ru")
    except Exception:
        logger.exception("wb_commission_tariffs_load_failed")
        return {}

    tariffs: dict[str, WbTariffRow] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        subject_id = str(row.get("subjectID") or "").strip().lower()
        if not subject_id:
            continue
        commission_values: dict[str, Decimal | None] = {}
        for api_field, schema_field in WB_COMMISSION_API_FIELDS.items():
            commission_values[schema_field] = _decimal_percent(row.get(api_field))
        tariffs[subject_id] = WbTariffRow(
            subject_id=subject_id,
            subject_name=str(row.get("subjectName") or "").strip(),
            parent_id=str(row.get("parentID") or "").strip(),
            parent_name=str(row.get("parentName") or "").strip(),
            commission_fbw=commission_values["commission_fbw"],
            commission_fbs=commission_values["commission_fbs"],
            commission_dbs=commission_values["commission_dbs"],
            commission_edbs=commission_values["commission_edbs"],
            commission_pickup=commission_values["commission_pickup"],
            commission_booking=commission_values["commission_booking"],
        )
    return tariffs


async def _update_product_commissions(
    session: AsyncSession,
    account: MarketplaceAccount,
    tariffs: dict[str, WbTariffRow],
    dry_run: bool,
) -> int:
    result = await session.execute(
        select(Product).where(
            Product.marketplace_account_id == account.id,
            Product.marketplace == Marketplace.WB,
        )
    )
    products = list(result.scalars().all())
    updated = 0

    for product in products:
        subject_id = (product.marketplace_category_id or "").strip().lower()
        tariff = tariffs.get(subject_id)
        if tariff is None:
            continue

        changed = False
        if product.commission_fbw != tariff.commission_fbw:
            product.commission_fbw = tariff.commission_fbw
            changed = True
        if product.commission_fbs != tariff.commission_fbs:
            product.commission_fbs = tariff.commission_fbs
            changed = True
        if product.commission_dbs != tariff.commission_dbs:
            product.commission_dbs = tariff.commission_dbs
            changed = True
        if product.commission_edbs != tariff.commission_edbs:
            product.commission_edbs = tariff.commission_edbs
            changed = True
        if product.commission_pickup != tariff.commission_pickup:
            product.commission_pickup = tariff.commission_pickup
            changed = True
        if product.commission_booking != tariff.commission_booking:
            product.commission_booking = tariff.commission_booking
            changed = True

        if changed:
            updated += 1
            logger.info(
                "product_commission_updated",
                extra={
                    "product_id": product.id,
                    "nm_id": product.external_product_id,
                    "subject_id": subject_id,
                    "commission_fbs": str(tariff.commission_fbs),
                    "commission_fbw": str(tariff.commission_fbw),
                    "commission_dbs": str(tariff.commission_dbs),
                },
            )

    if updated and not dry_run:
        await session.flush()
    return updated


async def _recalculate_order_items(
    session: AsyncSession,
    account: MarketplaceAccount,
    dry_run: bool,
) -> int:
    result = await session.execute(
        select(Order)
        .where(
            Order.marketplace_account_id == account.id,
            Order.marketplace == Marketplace.WB,
        )
        .order_by(Order.order_date.desc())
        .limit(500)
    )
    orders = list(result.scalars().all())
    recalculated = 0

    for order in orders:
        items_result = await session.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
        items = list(items_result.scalars().all())

        for item in items:
            if item.product_id is None:
                continue

            product = await session.get(Product, item.product_id)
            if product is None:
                continue

            economics = calculate_planned_economics(
                order,
                item,
                product_commission_rate=product.marketplace_commission_rate,
                commission_fbw=product.commission_fbw,
                commission_fbs=product.commission_fbs,
                commission_dbs=product.commission_dbs,
                commission_edbs=product.commission_edbs,
                commission_pickup=product.commission_pickup,
                commission_booking=product.commission_booking,
            )

            new_commission = economics.commission
            if item.commission_estimated != new_commission:
                old_commission = item.commission_estimated
                item.commission_estimated = new_commission
                item.commission_source = economics.commission_source.value
                item.profit_estimated = economics.profit
                item.margin_percent_estimated = economics.margin_percent
                item.economy_confidence = economics.confidence.value
                recalculated += 1

                logger.info(
                    "order_item_commission_recalculated",
                    extra={
                        "order_id": order.id,
                        "order_external_id": order.order_external_id,
                        "item_id": item.id,
                        "nm_id": item.marketplace_article,
                        "sale_model": order.sale_model.value if order.sale_model else None,
                        "old_commission": str(old_commission),
                        "new_commission": str(new_commission),
                        "old_profit": str(item.profit_estimated),
                        "new_profit": str(economics.profit),
                    },
                )

                if not dry_run:
                    snapshot = ProfitSnapshot(
                        order_item_id=item.id,
                        calculation_type=CalculationType.ESTIMATED,
                        gross_revenue=economics.revenue,
                        marketplace_commission=new_commission,
                        logistics_cost=economics.logistics,
                        acquiring_cost=Decimal("0"),
                        storage_cost=Decimal("0"),
                        return_cost=Decimal("0"),
                        other_marketplace_costs=economics.other_marketplace_costs,
                        cost_price=economics.cost_price,
                        package_cost=economics.package_cost,
                        additional_seller_cost=Decimal("0"),
                        tax_amount=economics.tax_amount,
                        profit=economics.profit,
                        margin_percent=economics.margin_percent,
                        calculated_at=item.updated_at or order.order_date,
                        calculation_source="backfill_wb_commissions",
                        economy_confidence=economics.confidence.value,
                        raw_financial_data=None,
                    )
                    session.add(snapshot)

    if recalculated and not dry_run:
        await session.flush()
    return recalculated


async def _run(dry_run: bool) -> None:
    logging.basicConfig(level=logging.INFO)
    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info(f"wb_commission_backfill_started mode={mode}")

    async with AsyncSessionFactory() as session:
        accounts_result = await session.execute(
            select(MarketplaceAccount).where(
                MarketplaceAccount.marketplace == Marketplace.WB,
                MarketplaceAccount.is_active.is_(True),
            )
        )
        accounts = list(accounts_result.scalars().all())

        total_products_updated = 0
        total_items_recalculated = 0

        for account in accounts:
            logger.info(
                "processing_account",
                extra={
                    "account_id": account.id,
                    "account_name": account.name,
                },
            )

            cipher = TokenCipher()
            client = WildberriesClient(cipher.decrypt(account.encrypted_api_key))
            tariffs = await _load_wb_tariffs(client)
            logger.info(
                "tariffs_loaded",
                extra={"account_id": account.id, "tariff_count": len(tariffs)},
            )

            products_updated = await _update_product_commissions(session, account, tariffs, dry_run)
            total_products_updated += products_updated

            items_recalculated = await _recalculate_order_items(session, account, dry_run)
            total_items_recalculated += items_recalculated

        if not dry_run:
            await session.commit()

        logger.info(
            "wb_commission_backfill_completed",
            extra={
                "mode": mode,
                "accounts_processed": len(accounts),
                "products_updated": total_products_updated,
                "items_recalculated": total_items_recalculated,
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill WB per-model commissions")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying the database",
    )
    args = parser.parse_args()
    asyncio.run(_run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
