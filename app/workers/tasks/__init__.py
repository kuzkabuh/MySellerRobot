"""version: 1.1.0
description: Worker tasks package — canonical import path for all worker functions.
              Re-exports everything from app.workers.tasks_main for backward compatibility.
              Domain modules will be extracted incrementally.
updated: 2026-06-10
"""

# ruff: noqa: F401, F403

from app.workers.tasks.shared import *  # noqa: F401, F403
from app.workers.tasks_main import *  # noqa: F401, F403

# ── Domain module re-exports (override legacy implementations) ──
from app.workers.tasks.payments import *  # noqa: F401, F403

# ── Domain modules (extracted incrementally) ──
# Currently migrating: payments, maintenance
# Future: orders, sales, wb_reports, ozon_finance, products, alerts
