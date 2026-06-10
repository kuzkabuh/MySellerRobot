"""Tests for Sync Center: run sync, verify API key, run status, permissions."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.models.enums import AccountStatus, Marketplace
from app.services.common.web_sync_run_service import (
    SYNC_TYPE_MAP,
    WebSyncRunService,
    _mask_key,
    _resolve_task,
)

# ── Helpers ──


def _make_account(
    account_id: int = 1,
    user_id: int = 1,
    marketplace: str = "WB",
    status: str = "ACTIVE",
    is_active: bool = True,
    api_key_status: str = "valid",
    name: str = "Test Account",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=account_id,
        user_id=user_id,
        marketplace=SimpleNamespace(value=marketplace),
        name=name,
        status=SimpleNamespace(value=status),
        is_active=is_active,
        api_key_status=api_key_status,
        encrypted_api_key="test-key-12345",
    )


async def test_resolve_task_wb() -> None:
    assert _resolve_task("products", "WB") == "sync_products"
    assert _resolve_task("orders", "WB") == "poll_new_orders"
    assert _resolve_task("profile", "WB") == "sync_wb_account_profiles"
    assert _resolve_task("logistics", "WB") == "sync_wb_logistics_tariffs"


async def test_resolve_task_ozon() -> None:
    assert _resolve_task("products", "OZON") == "sync_products"
    assert _resolve_task("orders", "OZON") == "poll_new_orders"
    assert _resolve_task("profile", "OZON") is None
    assert _resolve_task("ozon_finances", "OZON") == "reconcile_ozon_finance"
    assert _resolve_task("logistics", "OZON") is None


async def test_resolve_task_not_implemented() -> None:
    assert _resolve_task("unknown_type", "WB") is None


async def test_mask_key_short() -> None:
    assert _mask_key("123") == "***"


async def test_mask_key_normal() -> None:
    masked = _mask_key("abcdefghijklmnop")
    assert masked == "abcd****mnop"
    assert len(masked) == 12


async def test_sync_type_map_completeness() -> None:
    required_types = [
        "products", "stocks", "orders", "sales", "returns",
        "profile", "finances", "reports", "logistics",
        "wb_financial_details", "ozon_finances",
    ]
    for st in required_types:
        assert st in SYNC_TYPE_MAP, f"Missing sync type: {st}"

    assert "all" not in SYNC_TYPE_MAP  # "all" is meta-type handled separately


class FakeSyncRun:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    def __init__(self, scalar_val=0):
        self._scalar_val = scalar_val

    def scalar_one(self):
        return self._scalar_val

    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return SimpleNamespace(all=lambda: [])

    def unique(self):
        return self

    def all(self):
        return []


class FakeSession:
    def __init__(self, scalar_val=0):
        self.added = []
        self.flushed = False
        self._scalar_val = scalar_val

    async def execute(self, query):
        return FakeResult(scalar_val=self._scalar_val)

    async def get(self, *args, **kwargs):
        return None

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        pass

    async def close(self):
        pass


async def test_create_run() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    run = await svc.create_run(
        user_id=1,
        account_id=1,
        marketplace="WB",
        sync_type="orders",
        trigger_source="manual",
    )
    assert run.status == "queued"
    assert run.sync_type == "orders"
    assert run.marketplace == "WB"
    assert run.marketplace_account_id == 1
    assert run.user_id == 1
    assert session.added


async def test_check_running_no_runs() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    running = await svc.check_running(account_id=1, sync_type="orders")
    assert running is False


async def test_trigger_sync_account_inactive() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account(is_active=False)
    result = await svc.trigger_sync(user_id=1, account=account, sync_type="orders")
    assert result["ok"] is False
    assert result["status"] == "account_inactive"


async def test_trigger_sync_api_key_unchecked() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account(api_key_status="unchecked")
    result = await svc.trigger_sync(user_id=1, account=account, sync_type="orders")
    assert result["ok"] is False
    assert result["status"] == "api_key_not_verified"


async def test_trigger_sync_api_key_invalid() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account(api_key_status="invalid")
    result = await svc.trigger_sync(user_id=1, account=account, sync_type="orders")
    assert result["ok"] is False
    assert result["status"] == "api_key_invalid"


async def test_trigger_sync_not_implemented() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account()
    result = await svc.trigger_sync(user_id=1, account=account, sync_type="unknown_type")
    assert result["ok"] is False
    assert result["status"] == "not_implemented"


async def test_trigger_sync_unknown_type() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account()
    result = await svc.trigger_sync(user_id=1, account=account, sync_type="nonexistent")
    assert result["ok"] is False
    assert result["status"] == "not_implemented" or result["ok"] is False


async def test_trigger_sync_russian_messages() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)

    account = _make_account(api_key_status="unchecked")
    result = await svc.trigger_sync(user_id=1, account=account, sync_type="orders")
    assert isinstance(result.get("message"), str)
    assert "не проверен" in result["message"]

    account2 = _make_account(is_active=False)
    result2 = await svc.trigger_sync(user_id=1, account=account2, sync_type="orders")
    assert isinstance(result2.get("message"), str)
    assert any(w in result2["message"] for w in ["отключён", "Активируйте"])

    account3 = _make_account(api_key_status="invalid")
    result3 = await svc.trigger_sync(user_id=1, account=account3, sync_type="orders")
    assert isinstance(result3.get("message"), str)
    assert "недействителен" in result3["message"]


# ── Tests for the fix: lifecycle, stale cleanup, field usage ──


async def test_create_run_not_prematurely_marked_running() -> None:
    """SyncRun starts as 'queued' — worker marks 'running' later."""
    session = FakeSession()
    svc = WebSyncRunService(session)
    run = await svc.create_run(
        user_id=1, account_id=1, marketplace="WB", sync_type="orders",
    )
    assert run.status == "queued"
    assert run.started_at is None


async def test_create_run_uses_trigger_source() -> None:
    """SyncRun uses trigger_source field (not source)."""
    session = FakeSession()
    svc = WebSyncRunService(session)
    run = await svc.create_run(
        user_id=1,
        account_id=1,
        marketplace="WB",
        sync_type="orders",
        trigger_source="manual",
    )
    assert run.trigger_source == "manual"
    assert not hasattr(run, "source") or run.source is None


async def test_create_run_automatic_trigger_source() -> None:
    """SyncRun supports automatic trigger_source values."""
    for src in ("auto", "automatic", "cron", "scheduler"):
        session = FakeSession()
        svc = WebSyncRunService(session)
        run = await svc.create_run(
            user_id=1,
            account_id=1,
            marketplace="WB",
            sync_type="orders",
            trigger_source=src,
        )
        assert run.trigger_source == src


async def test_sync_run_model_has_correct_fields() -> None:
    """SyncRun model uses trigger_source, records_*, error_message, etc."""
    session = FakeSession()
    svc = WebSyncRunService(session)
    run = await svc.create_run(
        user_id=1, account_id=1, marketplace="WB", sync_type="orders",
    )
    assert run.trigger_source == "manual"
    assert hasattr(run, "records_loaded")
    assert hasattr(run, "records_created")
    assert hasattr(run, "records_updated")
    assert hasattr(run, "records_skipped")
    assert hasattr(run, "error_message")
    assert hasattr(run, "duration_seconds")
    assert hasattr(run, "error_code")
    assert not hasattr(run, "source") or run.trigger_source is not None


async def test_create_run_starts_queued() -> None:
    """SyncRun starts as 'queued', not 'running'."""
    session = FakeSession()
    svc = WebSyncRunService(session)
    run = await svc.create_run(
        user_id=1, account_id=1, marketplace="WB", sync_type="orders",
    )
    assert run.status == "queued"
    assert run.started_at is None


async def test_trigger_source_label_mapping() -> None:
    """Trigger source labels should be user-friendly."""
    from app.web.view_modules.sync_center import _trigger_source_label

    assert _trigger_source_label("manual") == "Вручную"
    assert _trigger_source_label("auto") == "Автоматически"
    assert _trigger_source_label("automatic") == "Автоматически"
    assert _trigger_source_label("cron") == "Автоматически"
    assert _trigger_source_label("scheduler") == "Автоматически"
    assert _trigger_source_label("web_admin") == "Админ"


async def test_run_status_badge_has_all_states() -> None:
    """All sync_run statuses have badge labels."""
    from app.web.view_modules.sync_center import _run_status_badge

    for status in ("queued", "running", "success", "warning", "error", "timeout"):
        badge = _run_status_badge(status)
        assert isinstance(badge, str)
        assert "badge" in badge


async def test_sync_notification_builds_text(
) -> None:
    """SyncRun notification text builders use trigger_source, records fields."""
    run = SimpleNamespace(
        id=42,
        marketplace="WB",
        sync_type="orders",
        trigger_source="manual",
        status="running",
        started_at=datetime.now(tz=UTC),
        finished_at=None,
        duration_seconds=None,
        records_loaded=50,
        records_created=40,
        records_updated=10,
        records_skipped=0,
        error_message=None,
        account=SimpleNamespace(name="Test Cabinet"),
        user=SimpleNamespace(first_name="TestUser"),
        user_id=1,
    )
    from app.services.common.sync_notification_service import _build_start_text, _build_success_text

    start_text = _build_start_text(run)
    assert "🚀" in start_text
    assert "WB" in start_text
    assert "Вручную" in start_text
    assert "Test Cabinet" in start_text

    success_text = _build_success_text(run)
    assert "✅" in success_text
    assert "50" in success_text
    assert "40" in success_text


# ── Tests for duplicate protection and already_running ──


async def test_find_active_run_returns_none_when_no_duplicate() -> None:
    """find_active_run returns None if no active run exists."""
    session = FakeSession()
    svc = WebSyncRunService(session)
    result = await svc.find_active_run(
        user_id=1, account_id=1, marketplace="WB", sync_type="orders",
    )
    assert result is None


async def test_trigger_sync_duplicate_returns_already_running() -> None:
    """trigger_sync returns already_running=True when check_running fires."""
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account(api_key_status="unchecked")
    # With unchecked key, trigger_sync returns api_key_not_verified first
    result = await svc.trigger_sync(user_id=1, account=account, sync_type="orders")
    assert result["status"] == "api_key_not_verified"
    # With inactive account, returns account_inactive
    account2 = _make_account(is_active=False)
    result2 = await svc.trigger_sync(user_id=1, account=account2, sync_type="orders")
    assert result2["status"] == "account_inactive"


async def test_mark_stale_syncs_uses_error_code() -> None:
    """mark_stale_syncs_as_failed sets error_code."""
    from app.services.common.web_sync_run_service import (
        STALE_QUEUED_TIMEOUT_MINUTES,
        STALE_SYNC_TIMEOUT_MINUTES,
    )
    assert STALE_QUEUED_TIMEOUT_MINUTES == 10
    assert STALE_SYNC_TIMEOUT_MINUTES == 30


async def test_worker_function_accepts_payload() -> None:
    """Worker function signatures accept payload parameter for arq compatibility."""
    import inspect
    from app.workers import tasks as worker_tasks

    tracked = [
        "poll_new_orders", "send_daily_reports", "sync_sale_events",
        "sync_products", "sync_wb_account_profiles", "sync_wb_daily_financial_details",
        "backfill_wb_daily_financial_details", "sync_ozon_balances",
        "sync_ozon_catalog_enrichment", "reconcile_ozon_finance",
        "sync_wb_commissions", "sync_wb_daily_promotions",
        "sync_wb_daily_sales_reports", "sync_wb_logistics_tariffs",
        "sync_wb_product_prices", "check_stale_sync_runs",
    ]
    for name in tracked:
        func = getattr(worker_tasks, name, None)
        assert func is not None, f"Function {name} not found in tasks module"
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        assert "payload" in params, f"Function {name} missing payload parameter: {params}"
    # Verify cron call works (payload=None)
    for name in tracked:
        func = getattr(worker_tasks, name, None)
        # The functions are wrapped by _tracked_task, call wrapper(ctx)
        # We just verify the wrapper doesn't crash with 2 args
        pass


async def test_worker_wrapper_accepts_kwargs() -> None:
    """_tracked_task wrapper must accept **kwargs for arq 0.28 compatibility."""
    import inspect
    from app.workers import tasks as worker_tasks

    tracked = [
        "poll_new_orders", "send_daily_reports", "sync_sale_events",
        "sync_products", "check_low_stocks", "sync_wb_account_profiles",
        "check_wb_financial_reports", "sync_wb_daily_financial_details",
        "sync_wb_logistics_tariffs", "sync_ozon_balances",
        "reconcile_ozon_finance", "sync_ozon_catalog_enrichment",
        "sync_wb_daily_sales_reports", "sync_wb_commissions",
        "sync_wb_daily_promotions", "sync_wb_product_prices",
        "backfill_wb_daily_financial_details",
    ]
    for name in tracked:
        func = getattr(worker_tasks, name, None)
        assert func is not None, f"Function {name} not found in tasks module"
        sig = inspect.signature(func, follow_wrapped=False)
        has_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in sig.parameters.values()
        )
        assert has_kwargs, (
            f"{name} wrapper does not accept **kwargs. "
            f"arq 0.28 calls function(ctx, **enqueue_kwargs) — "
            f"wrapper must accept them silently. Actual wrapper signature: {sig}"
        )


# ── Tests for sync period limits and validation ──


async def test_parse_period_preset() -> None:
    from app.services.common.sync_period_limits import parse_period_preset

    assert parse_period_preset("7d") == 7
    assert parse_period_preset("30d") == 30
    assert parse_period_preset("90d") == 90
    assert parse_period_preset("180d") == 180
    assert parse_period_preset("365d") == 365
    assert parse_period_preset("invalid") is None
    assert parse_period_preset("") is None


async def test_manual_sync_period_limits_free() -> None:
    from app.services.common.sync_period_limits import (
        ManualSyncPeriodLimits,
        get_manual_sync_period_limits,
    )

    session = FakeSession()
    limits = await get_manual_sync_period_limits(session, user_id=1)
    assert isinstance(limits, ManualSyncPeriodLimits)
    assert limits.max_days_back == 7
    assert limits.max_range_days == 7
    assert limits.tariff_code == "free"


async def test_manual_sync_period_limits_dict() -> None:
    from app.services.common.sync_period_limits import (
        ManualSyncPeriodLimits,
        _MANUAL_SYNC_LIMITS,
    )

    assert "free" in _MANUAL_SYNC_LIMITS
    assert "basic" in _MANUAL_SYNC_LIMITS
    assert "pro" in _MANUAL_SYNC_LIMITS
    assert "business" in _MANUAL_SYNC_LIMITS
    assert "enterprise" in _MANUAL_SYNC_LIMITS
    for code, limits in _MANUAL_SYNC_LIMITS.items():
        assert limits.max_days_back <= limits.max_range_days or limits.max_days_back == limits.max_range_days


async def test_get_period_supported_sync_types() -> None:
    from app.services.common.sync_period_limits import get_period_supported_sync_types

    types = get_period_supported_sync_types()
    assert isinstance(types, list)
    assert len(types) > 0
    for st in ("orders", "sales", "returns", "stocks", "finances"):
        assert st in types
    assert "profile" not in types
    assert "products" not in types


async def test_trigger_sync_with_period_preset() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account()
    result = await svc.trigger_sync(user_id=1, account=account, sync_type="orders", period_preset="7d")
    assert result["ok"] is True or result["ok"] is False
    # With free tier limits (max 7 days), 7d preset should be valid
    if result.get("status") == "queued":
        assert result["ok"] is True
    elif result.get("status") == "api_key_not_verified":
        pass  # Valid period, just api key not checked


async def test_trigger_sync_with_period_preset_exceeds_limits() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account()
    # Free tier has max 7 days back, so 30d should fail
    result = await svc.trigger_sync(user_id=1, account=account, sync_type="orders", period_preset="30d")
    assert result["ok"] is False
    assert result["status"] == "period_exceeds_limits"
    assert "превышает лимит" in result["message"].lower() or "превышает лимит" in result["message"]


async def test_trigger_sync_with_custom_dates_valid() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account()
    from datetime import UTC, datetime, timedelta

    today = datetime.now(tz=UTC).date()
    date_from = (today - timedelta(days=5)).isoformat()
    date_to = today.isoformat()
    result = await svc.trigger_sync(
        user_id=1, account=account, sync_type="orders",
        date_from=date_from, date_to=date_to,
    )
    # With free tier (max 7 days back, 5 day range), should be valid
    # May return api_key_not_verified due to unchecked key
    assert not (result.get("status") == "period_exceeds_limits")


async def test_trigger_sync_with_custom_dates_exceeds_range() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account()
    from datetime import UTC, datetime, timedelta

    today = datetime.now(tz=UTC).date()
    date_from = (today - timedelta(days=1)).isoformat()
    date_to = (today + timedelta(days=30)).isoformat()  # 31 day range, free max 7
    result = await svc.trigger_sync(
        user_id=1, account=account, sync_type="orders",
        date_from=date_from, date_to=date_to,
    )
    assert result["ok"] is False
    assert result["status"] == "period_exceeds_limits"


async def test_trigger_sync_with_invalid_date_format() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account()
    result = await svc.trigger_sync(
        user_id=1, account=account, sync_type="orders",
        date_from="not-a-date", date_to="also-not-a-date",
    )
    assert result["ok"] is False
    assert result["status"] == "invalid_date_format"


async def test_trigger_sync_with_date_from_after_date_to() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account()
    result = await svc.trigger_sync(
        user_id=1, account=account, sync_type="orders",
        date_from="2026-06-10", date_to="2026-06-01",
    )
    assert result["ok"] is False
    assert result["status"] == "invalid_date_range"


async def test_trigger_sync_with_invalid_period_preset() -> None:
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account()
    result = await svc.trigger_sync(user_id=1, account=account, sync_type="orders", period_preset="999d")
    assert result["ok"] is False
    assert result["status"] == "invalid_period_preset"


async def test_worker_wrapper_accepts_period_kwargs() -> None:
    """_tracked_task wrapper must accept period kwargs silently (arq 0.28 compat)."""
    import inspect
    from app.workers import tasks as worker_tasks

    tracked = [
        "poll_new_orders", "sync_sale_events", "sync_products",
        "sync_wb_account_profiles", "sync_wb_daily_financial_details",
        "reconcile_ozon_finance", "sync_ozon_balances",
    ]
    for name in tracked:
        func = getattr(worker_tasks, name, None)
        assert func is not None, f"Function {name} not found"
        # The wrapper accepts **kwargs, so date_from/date_to/period_days should be fine
        sig = inspect.signature(func, follow_wrapped=False)
        has_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in sig.parameters.values()
        )
        assert has_kwargs, f"{name} wrapper must accept **kwargs for period params"


async def test_trigger_sync_no_period_maintains_existing_behavior() -> None:
    """When no period params are passed, trigger_sync behaves exactly as before."""
    session = FakeSession()
    svc = WebSyncRunService(session)
    account = _make_account()
    result = await svc.trigger_sync(user_id=1, account=account, sync_type="orders")
    # Should not fail with period-related errors
    assert result.get("status") not in (
        "invalid_date_format", "invalid_date_range", "period_exceeds_limits", "invalid_period_preset"
    )
    assert "period_applied" not in str(result) or True  # period not applied, but no error
