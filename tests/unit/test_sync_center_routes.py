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
