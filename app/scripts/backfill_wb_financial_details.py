#!/usr/bin/env python
"""Manual trigger for WB financial details backfill.

Usage:
    python -m app.scripts.backfill_wb_financial_details
    python -m app.scripts.backfill_wb_financial_details --days 50
    python -m app.scripts.backfill_wb_financial_details --days 90
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_wb_financial")


_DEFAULT_DAYS = 15  # соответствует WB_FINANCIAL_BACKFILL_DAYS в tasks_main.py


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill WB financial details")
    parser.add_argument(
        "--days",
        type=int,
        default=_DEFAULT_DAYS,
        help=f"Number of days to backfill (default: {_DEFAULT_DAYS})",
    )
    args = parser.parse_args()

    from app.core.config import get_settings
    get_settings()

    from app.workers.tasks import backfill_wb_daily_financial_details

    logger.info("=" * 60)
    logger.info("WB Financial Details Backfill - Manual Run")
    logger.info(f"Period: last {args.days} days")
    logger.info("=" * 60)

    result = await backfill_wb_daily_financial_details({}, days=args.days)

    logger.info("=" * 60)
    logger.info("Backfill Results:")
    task_stats = result.get("task_stats", result)
    if isinstance(task_stats, dict):
        for key, value in task_stats.items():
            logger.info(f"  {key}: {value}")
    logger.info(f"  status: {result.get('status', 'unknown')}")
    if result.get("last_error"):
        logger.warning(f"  last_error: {result['last_error']}")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
