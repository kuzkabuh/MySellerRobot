# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.


## Project Overview

Seller Profit Bot (KUZ'KA.SELLER BOT) — Telegram bot for Wildberries and Ozon sellers that shows planned profit/loss for each order immediately upon notification. Built with Python 3.12, FastAPI, aiogram 3, SQLAlchemy 2, Alembic, PostgreSQL, Redis, and arq.

Current version: **1.4.17** (stored in `VERSION` and `pyproject.toml`)

## Development Commands

### Local Development (without Docker)

```bash
# Install dependencies
pip install -e ".[dev]"

# Apply migrations
alembic upgrade head

# Run services individually
make api      # FastAPI on port 8000
make bot      # Telegram bot
make worker   # arq background worker

# Quality checks
make test     # pytest
make lint     # ruff + mypy
make format   # black + ruff --fix
```

### Docker Development

```bash
# Start all services
docker compose up --build

# Apply migrations in container
docker compose run --rm api alembic upgrade head

# Run tests in container
docker compose run --rm api pytest

# Check logs
docker compose logs api --tail=100
docker compose logs bot --tail=100
docker compose logs worker --tail=100
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"
# or
make revision m="description"

# Apply migrations
alembic upgrade head

# Check migration history
alembic history
alembic heads
```

### Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/unit/test_profit_calculator.py

# Run with coverage
pytest --cov=app --cov-report=html
```

## Architecture

### Layer Structure

```
app/
  api/                 FastAPI health/admin endpoints, web routes
  bot/                 aiogram handlers, keyboards, states, FSM
  core/                config, database, security (Fernet encryption), logging
  integrations/        Wildberries and Ozon async API clients
  models/              SQLAlchemy 2.0 models, enums, domain entities
  repositories/        Data access layer with idempotency helpers
  schemas/             Pydantic DTOs for validation and serialization
  services/            Business logic (profit, alerts, notifications, Excel import)
  utils/               Shared utilities (datetime with timezone support)
  workers/             arq background tasks and cron schedules
  web/                 Web cabinet routes (server-rendered HTML)
  cli/                 CLI commands (admin notifications)
migrations/            Alembic migrations
tests/                 unit, integration, smoke tests
```

### Key Principles

**Separation of concerns**: Telegram handlers do not calculate profit or call marketplace APIs directly. They invoke services and repositories. Integration clients return normalized DTOs so WB/Ozon differences don't leak into business logic.

**Idempotency**: Orders, financial rows, sales events, and alerts use unique constraints to prevent duplicates. Repeated syncs upsert existing records rather than creating duplicates.

**Timezone awareness**: All timestamps stored in UTC. User-facing dates converted to user's IANA timezone via `format_datetime_for_user` helper.

**Encryption**: API keys and Ozon Client IDs encrypted with Fernet before storage in `marketplace_accounts.encrypted_api_key`.

**Async-first**: All I/O operations use async/await. Database sessions are `AsyncSession`, HTTP clients use `httpx.AsyncClient`.

## Database Schema

Core tables:
- `users` — Telegram users with timezone, subscription status
- `marketplace_accounts` — WB/Ozon accounts with encrypted API keys
- `products` — Product catalog with external IDs, SKUs, images
- `product_cost_history` — Cost history with validity periods
- `master_products` — Unified product cards across marketplaces
- `master_product_links` — Links between WB/Ozon products
- `orders`, `order_items` — Orders and line items
- `profit_snapshots` — Planned and actual profit calculations
- `financial_report_rows` — Normalized financial data from marketplaces
- `sales_events` — Buyouts and completed sales
- `returns_events` — Returns
- `stock_snapshots` — Stock levels and out-of-stock forecasts
- `notification_settings` — Per-user notification preferences
- `alert_rules`, `alert_events` — Alert configuration and events
- `sync_jobs` — Historical backfill job tracking
- `one_time_login_tokens`, `user_web_sessions` — Web cabinet authentication

## Marketplace API Integration

### Wildberries

Base URLs configured in `app/core/config.py`:
- `wb_base_marketplace_url` — FBS orders and supplies
- `wb_base_content_url` — Product cards
- `wb_base_analytics_url` — Analytics and stock reports
- `wb_base_statistics_url` — Historical orders and sales/buyouts
- `wb_base_finance_url` — Financial reports

Key methods:
- `GET /api/v3/orders/new` — New FBS orders
- `GET /api/v3/orders` — FBS orders for period
- `POST /content/v2/get/cards/list` — Product cards
- `POST /api/analytics/v1/stocks-report/wb-warehouses` — Current stock levels (replaces deprecated `/api/v1/supplier/stocks`)
- `GET /api/v1/supplier/orders` — Historical orders from statistics
- `GET /api/v1/supplier/sales` — Sales/buyouts from statistics
- `POST /api/finance/v1/sales-reports/detailed` — Financial reports (replaces deprecated `/api/v5/supplier/reportDetailByPeriod`)

**Important**: Old WB finance API (`/api/v5/supplier/reportDetailByPeriod`) deprecated as of 2026-07-15. Use new v1 finance endpoints.

### Ozon

Base URL: `ozon_base_url` = `https://api-seller.ozon.ru`

Key methods:
- `POST /v3/posting/fbs/list` — FBS shipments
- `POST /v2/posting/fbo/list` — FBO orders
- `POST /v3/posting/fbs/unfulfilled/list` — Unfulfilled FBS for deadline control
- `POST /v3/product/list` — Product list
- `POST /v4/product/info/stocks` — Stock levels
- `POST /v1/returns/list` — Returns

**Important**: Old Ozon finance methods (`/v3/finance/transaction/list`) deprecated as of 2026-07-06. Use report-based architecture instead.

## Background Workers (arq)

Worker tasks defined in `app/workers/tasks.py`, scheduled in `app/workers/settings.py`:

- `poll_new_orders` — Every 3 minutes, polls WB/Ozon for new orders
- `sync_sale_events` — Every 15 minutes, syncs buyouts and completed sales
- `send_fbo_digests` — Every 30 minutes, sends FBO order digests
- `process_history_backfills` — Every 10 minutes, processes historical sync jobs
- `check_fbs_deadlines` — Every 15 minutes, checks FBS/rFBS deadlines
- `check_low_stocks` — 3x daily (8:00, 14:00, 20:00), checks low stock alerts
- `send_daily_reports` — Daily at configured hour (default 9:00)

Run worker locally: `arq app.workers.settings.WorkerSettings`

## Profit Calculation

Centralized in `OrderProfitService` and `ProfitCalculator`:

```
Profit = Revenue - MP Commission - Logistics - Acquiring - Storage - Returns
         - Other MP Costs - COGS - Packaging - Additional Seller Costs - Tax
```

- Revenue is gross sale price (not `expected_payout`)
- COGS retrieved from `product_cost_history` valid on order date
- If MP commission unavailable, calculation proceeds with warning flag
- Both planned (at order time) and actual (from financial reports) snapshots stored in `profit_snapshots`

## Web Cabinet

Server-rendered HTML via FastAPI routes in `app/web/routes.py`. No separate frontend build.

Authentication flow:
1. User clicks "🌐 Web-кабинет" in Telegram
2. Bot generates one-time login token (SHA-256 hash stored in DB)
3. User visits `/web/login?token=...`
4. On success, creates HttpOnly session cookie, redirects to `/web/`
5. Session valid for `WEB_SESSION_TTL_HOURS` (default 168h = 7 days)

Key routes:
- `/web/` — Dashboard with KPIs and charts
- `/web/orders` — Order list with filters
- `/web/orders/{order_id}` — Order detail card
- `/web/profit` — Profit by SKU table
- `/web/plan-fact` — Plan vs actual analysis

## Environment Variables

Critical variables (see `.env.example`):
- `BOT_TOKEN` — Telegram Bot API token
- `DATABASE_URL` — PostgreSQL async connection string
- `REDIS_URL` — Redis for arq and aiogram storage
- `ENCRYPTION_KEY` — Fernet key for API key encryption (generate with `python -c "from app.core.security import generate_encryption_key; print(generate_encryption_key())"`)
- `APP_SECRET_KEY` — Secret for admin endpoints
- `ADMIN_TELEGRAM_IDS` — Comma-separated admin user IDs
- `WEB_BASE_URL` — Public HTTPS URL for web cabinet links
- `BACKFILL_DEFAULT_DAYS` — Historical sync period (default 30)
- `ORDER_POLL_INTERVAL_SECONDS` — Base polling interval (default 180)

## Common Patterns

### Adding a New Service

1. Create service class in `app/services/`
2. Inject dependencies via constructor (session, settings, repositories)
3. Write unit tests in `tests/unit/test_<service_name>.py`
4. Import and use in handlers or workers

### Adding a New Telegram Handler

1. Define handler function in `app/bot/handlers/`
2. Use `@router.message()` or `@router.callback_query()` decorators
3. Call services for business logic, never access DB directly
4. Register router in `app/bot/main.py`

### Adding a New Worker Task

1. Define async function in `app/workers/tasks.py`
2. Add to `WorkerSettings.functions` list
3. Add cron schedule to `WorkerSettings.cron_jobs`
4. Test locally with `arq app.workers.settings.WorkerSettings`

### Adding a Database Migration

1. Modify models in `app/models/`
2. Generate migration: `alembic revision --autogenerate -m "description"`
3. Review generated migration in `migrations/versions/`
4. Apply: `alembic upgrade head`
5. Test rollback: `alembic downgrade -1` then `alembic upgrade head`

## Testing Strategy

- **Unit tests**: Business logic in services, normalizers, calculators
- **Integration tests**: Marketplace API clients with mocked httpx responses
- **Smoke tests**: Import checks, factory functions, basic routes
- **Contract tests**: Telegram callback handlers have registered routes

Run specific test categories:
```bash
pytest tests/unit/
pytest tests/integration/
pytest -k "test_profit"
```

## Production Deployment

Deployment scripts in `deploy/`:
- `install.sh` — Initial server setup (Ubuntu 22.04/24.04)
- `update.sh` — Pull latest code, backup DB, apply migrations, restart services
- `backup.sh` — Manual PostgreSQL backup

Production compose: `docker-compose.prod.yml`

Deployment checklist:
- Set real `ENCRYPTION_KEY` (never commit to git)
- Configure `WEB_BASE_URL` to public HTTPS domain
- Set `ADMIN_TELEGRAM_IDS` to real admin user IDs
- Enable PostgreSQL backups (automated in `update.sh`)
- Configure log rotation for `logs/*.log`
- Restrict access to `/admin/errors` endpoint
- Set up monitoring for worker health

## Troubleshooting

### Bot not receiving updates
- Check `BOT_TOKEN` is valid
- Verify bot process is running: `docker compose logs bot`
- Check Redis connection: `redis-cli ping`

### Worker tasks not running
- Check worker logs: `docker compose logs worker`
- Verify Redis connection
- Check cron schedule in `app/workers/settings.py`

### Database connection errors
- Verify PostgreSQL is running: `docker compose ps postgres`
- Check `DATABASE_URL` format: `postgresql+asyncpg://user:pass@host:port/db`
- Test connection: `docker compose run --rm api python -c "from app.core.db import get_session; print('OK')"`

### Migration conflicts
- Check current head: `alembic heads`
- View history: `alembic history`
- If multiple heads, merge: `alembic merge -m "merge heads" <rev1> <rev2>`

### Web cabinet login fails
- Verify `WEB_BASE_URL` is publicly accessible HTTPS URL (not localhost)
- Check token hasn't expired (`WEB_LOGIN_TOKEN_TTL_MINUTES`)
- Verify session cookie domain matches web URL

## Code Style

- Line length: 100 characters
- Formatter: black
- Linter: ruff (E, F, I, UP, B, ASYNC, C4)
- Type checker: mypy (strict mode)
- Async: Always use `async`/`await` for I/O operations
- Imports: Absolute imports from `app.*`, sorted by ruff
- Docstrings: Only for public APIs and complex logic (not every function)
- Comments: Minimal, explain "why" not "what"

## Version History

Current: **1.4.17** — Plan/fact analysis service and web section

Recent milestones:
- 1.4.16 — MasterProduct for unified WB/Ozon product cards
- 1.4.15 — Extended order notifications, timezone support, web session cookies
- 1.4.14 — Fixed WB FBS price normalization, order detail buttons, timezone settings
- 1.4.13 — Full project refactor, web cabinet login fix
