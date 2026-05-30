"""version: 1.0.0
description: Tests for per-sync-type timestamps and WEB sync status display.
updated: 2026-05-20
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.web import routes


class TestLastSyncLabel:
    def test_returns_never_when_no_dates(self) -> None:
        data = SimpleNamespace(rows=[], active_accounts=0)
        assert routes._last_sync_label(data) == "ещё не было"

    def test_returns_max_of_all_sync_fields(self) -> None:
        old = datetime(2026, 5, 19, 10, 0, tzinfo=UTC)
        recent = datetime(2026, 5, 20, 15, 30, tzinfo=UTC)
        account = SimpleNamespace(
            last_orders_sync_at=old,
            last_sales_sync_at=old,
            last_stocks_sync_at=old,
            last_products_sync_at=old,
            last_profile_sync_at=old,
            last_ozon_enrichment_sync_at=old,
            last_wb_reports_sync_at=recent,
        )
        row = SimpleNamespace(account=account)
        data = SimpleNamespace(rows=[row], active_accounts=1)
        label = routes._last_sync_label(data, "Europe/Moscow")
        assert "20.05.2026" in label
        assert "18:30" in label

    def test_ignores_none_fields(self) -> None:
        recent = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
        account = SimpleNamespace(
            last_orders_sync_at=recent,
            last_sales_sync_at=None,
            last_stocks_sync_at=None,
            last_products_sync_at=None,
            last_profile_sync_at=None,
            last_ozon_enrichment_sync_at=None,
            last_wb_reports_sync_at=None,
        )
        row = SimpleNamespace(account=account)
        data = SimpleNamespace(rows=[row], active_accounts=1)
        label = routes._last_sync_label(data, "Europe/Moscow")
        assert "20.05.2026" in label

    def test_uses_orders_sync_when_newest(self) -> None:
        orders_ts = datetime(2026, 5, 20, 14, 0, tzinfo=UTC)
        sales_ts = datetime(2026, 5, 19, 10, 0, tzinfo=UTC)
        account = SimpleNamespace(
            last_orders_sync_at=orders_ts,
            last_sales_sync_at=sales_ts,
            last_stocks_sync_at=None,
            last_products_sync_at=None,
            last_profile_sync_at=None,
            last_ozon_enrichment_sync_at=None,
            last_wb_reports_sync_at=None,
        )
        row = SimpleNamespace(account=account)
        data = SimpleNamespace(rows=[row], active_accounts=1)
        label = routes._last_sync_label(data, "Europe/Moscow")
        assert "20.05.2026" in label


class TestSyncStatus:
    def test_needs_setup_when_no_active_accounts(self) -> None:
        data = SimpleNamespace(rows=[], active_accounts=0)
        assert routes._sync_status(data) == "нужна настройка"

    def test_has_errors_when_error_message_present(self) -> None:
        account = SimpleNamespace(
            is_active=True,
            last_error_message="API timeout",
            last_orders_sync_at=datetime.now(tz=UTC) - timedelta(minutes=5),
            last_sales_sync_at=datetime.now(tz=UTC) - timedelta(minutes=10),
        )
        row = SimpleNamespace(account=account)
        data = SimpleNamespace(rows=[row], active_accounts=1)
        assert routes._sync_status(data) == "есть ошибки"

    def test_actual_when_orders_and_sales_recent(self) -> None:
        now = datetime.now(tz=UTC)
        account = SimpleNamespace(
            is_active=True,
            last_error_message=None,
            last_orders_sync_at=now - timedelta(minutes=5),
            last_sales_sync_at=now - timedelta(minutes=10),
        )
        row = SimpleNamespace(account=account)
        data = SimpleNamespace(rows=[row], active_accounts=1)
        assert routes._sync_status(data) == "актуальна"

    def test_needs_check_when_only_orders_recent(self) -> None:
        now = datetime.now(tz=UTC)
        account = SimpleNamespace(
            is_active=True,
            last_error_message=None,
            last_orders_sync_at=now - timedelta(minutes=5),
            last_sales_sync_at=now - timedelta(hours=2),
        )
        row = SimpleNamespace(account=account)
        data = SimpleNamespace(rows=[row], active_accounts=1)
        assert routes._sync_status(data) == "требует проверки"

    def test_needs_check_when_only_sales_recent(self) -> None:
        now = datetime.now(tz=UTC)
        account = SimpleNamespace(
            is_active=True,
            last_error_message=None,
            last_orders_sync_at=now - timedelta(hours=2),
            last_sales_sync_at=now - timedelta(minutes=5),
        )
        row = SimpleNamespace(account=account)
        data = SimpleNamespace(rows=[row], active_accounts=1)
        assert routes._sync_status(data) == "требует проверки"

    def test_waiting_for_data_when_no_sync_timestamps(self) -> None:
        account = SimpleNamespace(
            is_active=True,
            last_error_message=None,
            last_orders_sync_at=None,
            last_sales_sync_at=None,
        )
        row = SimpleNamespace(account=account)
        data = SimpleNamespace(rows=[row], active_accounts=1)
        assert routes._sync_status(data) == "ожидает данных"

    def test_ignores_inactive_accounts(self) -> None:
        now = datetime.now(tz=UTC)
        active_account = SimpleNamespace(
            is_active=True,
            last_error_message=None,
            last_orders_sync_at=now - timedelta(minutes=5),
            last_sales_sync_at=now - timedelta(minutes=10),
        )
        inactive_account = SimpleNamespace(
            is_active=False,
            last_error_message="old error",
            last_orders_sync_at=None,
            last_sales_sync_at=None,
        )
        rows = [
            SimpleNamespace(account=active_account),
            SimpleNamespace(account=inactive_account),
        ]
        data = SimpleNamespace(rows=rows, active_accounts=1)
        assert routes._sync_status(data) == "актуальна"


class TestSyncDetailCell:
    def test_shows_not_started_for_none_timestamps(self) -> None:
        account = SimpleNamespace(
            marketplace=SimpleNamespace(value="wb"),
            last_orders_sync_at=None,
            last_sales_sync_at=None,
            last_stocks_sync_at=None,
            last_products_sync_at=None,
            last_profile_sync_at=None,
            last_ozon_enrichment_sync_at=None,
            last_wb_reports_sync_at=None,
        )
        html = routes._sync_detail_cell(account, "Europe/Moscow")
        assert "ещё не запускалась" in html

    def test_shows_formatted_date_for_set_timestamps(self) -> None:
        ts = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
        account = SimpleNamespace(
            marketplace=SimpleNamespace(value="wb"),
            last_orders_sync_at=ts,
            last_sales_sync_at=ts,
            last_stocks_sync_at=ts,
            last_products_sync_at=ts,
            last_profile_sync_at=ts,
            last_ozon_enrichment_sync_at=None,
            last_wb_reports_sync_at=ts,
        )
        html = routes._sync_detail_cell(account, "Europe/Moscow")
        assert "20.05.2026" in html
        assert "Заказы:" in html
        assert "Продажи:" in html
        assert "Отчёты WB:" in html

    def test_shows_ozon_enrichment_for_ozon_accounts(self) -> None:
        ts = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
        account = SimpleNamespace(
            marketplace=SimpleNamespace(value="ozon"),
            last_orders_sync_at=ts,
            last_sales_sync_at=ts,
            last_stocks_sync_at=ts,
            last_products_sync_at=ts,
            last_profile_sync_at=ts,
            last_ozon_enrichment_sync_at=ts,
            last_wb_reports_sync_at=None,
        )
        html = routes._sync_detail_cell(account, "Europe/Moscow")
        assert "Ozon каталог:" in html
        assert "Отчёты WB:" not in html


class TestSyncActions:
    def test_includes_products_button(self) -> None:
        html = routes._sync_actions()
        assert 'action="/web/sync/products"' in html
        assert ">Товары</button>" in html

    def test_includes_all_sync_types(self) -> None:
        html = routes._sync_actions()
        for sync_type in ("orders", "sales", "stocks", "products", "wb-reports", "ozon-enrichment"):
            assert f"/web/sync/{sync_type}" in html


class TestWorkerCronConfig:
    def test_sync_products_in_cron_jobs(self) -> None:
        from app.workers.settings import WorkerSettings

        cron_job_names = {job.coroutine.__name__ for job in WorkerSettings.cron_jobs}
        assert "sync_products" in cron_job_names

    def test_sync_products_in_functions(self) -> None:
        from app.workers.settings import WorkerSettings

        func_names = {f.__name__ for f in WorkerSettings.functions}
        assert "sync_products" in func_names
