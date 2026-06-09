"""version: 1.0.0
description: Tests for the commission tariff system (WB sync, Ozon monitor, Ozon import, resolver).
updated: 2026-05-20
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.commissions.admin_notifications import (
    format_wb_sync_notification,
)
from app.services.commissions.commission_resolver_service import (
    CommissionResolverService,
)
from app.services.ozon.commissions.ozon_commission_source_monitor_service import (
    OzonCommissionPageParser,
)
from app.services.ozon.commissions.ozon_commission_xlsx_importer import (
    _extract_date_from_filename,
    _normalize_commission_value,
)
from app.services.wb.commissions.wb_commission_sync_service import (
    _compute_payload_hash,
    _normalize_wb_tariff_entry,
)


class TestWbTariffNormalization:
    def test_normalize_single_entry(self) -> None:
        entry = {
            "parentName": "Одежда и обувь",
            "subjectName": "Одежда",
            "parentID": 100,
            "subjectID": 200,
            "kgvpMarketplace": 25,
            "paidStorageKgvp": 19,
        }
        rates = _normalize_wb_tariff_entry(entry)
        assert len(rates) == 2
        fbs_rate = next(r for r in rates if r["sales_model"] == "fbs")
        fbw_rate = next(r for r in rates if r["sales_model"] == "fbo")
        assert fbs_rate["commission_percent"] == Decimal("25")
        assert fbw_rate["commission_percent"] == Decimal("19")

    def test_normalize_all_six_models(self) -> None:
        entry = {
            "parentName": "Бытовая техника",
            "subjectName": "Тест",
            "kgvpBooking": 14.5,
            "kgvpMarketplace": 15.5,
            "kgvpPickup": 14.5,
            "kgvpSupplier": 12.5,
            "kgvpSupplierExpress": 3,
            "paidStorageKgvp": 15.5,
        }
        rates = _normalize_wb_tariff_entry(entry)
        assert len(rates) == 6
        models = {r["sales_model"] for r in rates}
        assert models == {"booking", "fbs", "pickup", "dbs_dbw", "edbs", "fbo"}

    def test_normalize_skips_null_fields(self) -> None:
        entry = {
            "parentName": "Тест",
            "kgvpMarketplace": 15,
            "paidStorageKgvp": None,
        }
        rates = _normalize_wb_tariff_entry(entry)
        assert len(rates) == 1
        assert rates[0]["sales_model"] == "fbs"

    def test_normalize_fbs_from_kgvp_marketplace(self) -> None:
        entry = {
            "parentName": "Электроника",
            "subjectName": "Телефоны",
            "kgvpMarketplace": 18,
        }
        rates = _normalize_wb_tariff_entry(entry)
        fbs = next(r for r in rates if r["sales_model"] == "fbs")
        assert fbs["commission_percent"] == Decimal("18")
        assert fbs["category_name"] == "Электроника"
        assert fbs["subject_name"] == "Телефоны"

    def test_normalize_fbw_from_paid_storage_kgvp(self) -> None:
        entry = {
            "parentName": "Одежда",
            "subjectName": "Платья",
            "paidStorageKgvp": 19,
        }
        rates = _normalize_wb_tariff_entry(entry)
        fbw = next(r for r in rates if r["sales_model"] == "fbo")
        assert fbw["commission_percent"] == Decimal("19")
        assert fbw["category_name"] == "Одежда"

    def test_kgvp_supplier_not_used_for_fbw(self) -> None:
        """kgvpSupplier maps to dbs_dbw, NOT to fbo/fbw."""
        entry = {
            "parentName": "Тест",
            "kgvpSupplier": 12,
            "paidStorageKgvp": 19,
        }
        rates = _normalize_wb_tariff_entry(entry)
        supplier_rate = next(r for r in rates if r["sales_model"] == "dbs_dbw")
        fbw_rate = next(r for r in rates if r["sales_model"] == "fbo")
        assert supplier_rate["commission_percent"] == Decimal("12")
        assert fbw_rate["commission_percent"] == Decimal("19")
        assert supplier_rate["sales_model"] != fbw_rate["sales_model"]

    def test_normalize_preserves_parent_and_subject_in_raw(self) -> None:
        entry = {
            "parentName": "Категория",
            "subjectName": "Предмет",
            "parentID": 657,
            "subjectID": 6461,
            "kgvpMarketplace": 15,
        }
        rates = _normalize_wb_tariff_entry(entry)
        raw = rates[0]["raw_payload"]
        assert raw["parentID"] == 657
        assert raw["subjectID"] == 6461
        assert raw["parentName"] == "Категория"
        assert raw["subjectName"] == "Предмет"

    def test_normalize_empty_entry(self) -> None:
        entry = {"parentName": "Тест"}
        rates = _normalize_wb_tariff_entry(entry)
        assert rates == []

    def test_normalize_decimal_percent(self) -> None:
        entry = {
            "parentName": "Тест",
            "kgvpMarketplace": 12.5,
        }
        rates = _normalize_wb_tariff_entry(entry)
        assert rates[0]["commission_percent"] == Decimal("12.5")


class TestPayloadHash:
    def test_same_payload_same_hash(self) -> None:
        payload = [{"a": 1}, {"b": 2}]
        h1 = _compute_payload_hash(payload)
        h2 = _compute_payload_hash(payload)
        assert h1 == h2

    def test_different_payload_different_hash(self) -> None:
        h1 = _compute_payload_hash([{"a": 1}])
        h2 = _compute_payload_hash([{"a": 2}])
        assert h1 != h2


class TestOzonCommissionValueNormalization:
    def test_value_as_decimal_0_to_1(self) -> None:
        assert _normalize_commission_value("0.49") == Decimal("49")
        assert _normalize_commission_value("0.15") == Decimal("15")
        assert _normalize_commission_value("1") == Decimal("100")

    def test_value_as_percent(self) -> None:
        assert _normalize_commission_value("49") == Decimal("49")
        assert _normalize_commission_value("15.5") == Decimal("15.5")

    def test_value_with_comma(self) -> None:
        assert _normalize_commission_value("0,49") == Decimal("49")
        assert _normalize_commission_value("15,5") == Decimal("15.5")

    def test_value_with_percent_sign(self) -> None:
        assert _normalize_commission_value("49%") == Decimal("49")

    def test_invalid_values(self) -> None:
        assert _normalize_commission_value(None) is None
        assert _normalize_commission_value("") is None
        assert _normalize_commission_value("abc") is None
        assert _normalize_commission_value("-5") is None


class TestDateExtractionFromFilename:
    def test_extract_date(self) -> None:
        result = _extract_date_from_filename("Таблица_06042026-2.xlsx")
        assert result == date(2026, 4, 6)

    def test_no_date_in_filename(self) -> None:
        result = _extract_date_from_filename("commissions.xlsx")
        assert result is None

    def test_invalid_date(self) -> None:
        result = _extract_date_from_filename("file_99999999.xlsx")
        assert result is None


class TestOzonPageParser:
    def test_extract_period(self) -> None:
        parser = OzonCommissionPageParser()
        html = (
            "<h2>Таблица категорий с 6 апреля 2026 г.</h2>"
            '<a href="/files/commissions.xlsx">Скачать таблицу категорий</a>'
        )
        result = parser.parse(html)
        assert result["period_label"] is not None
        assert "6 апреля" in result["period_label"] or "апреля" in result["period_label"]

    def test_extract_download_url(self) -> None:
        parser = OzonCommissionPageParser()
        html = '<a href="https://example.com/file.xlsx">Скачать таблицу категорий</a>'
        result = parser.parse(html)
        assert result["download_url"] == "https://example.com/file.xlsx"

    def test_extract_file_name(self) -> None:
        parser = OzonCommissionPageParser()
        html = '<a href="https://example.com/path/Таблица_06042026.xlsx">link</a>'
        result = parser.parse(html)
        assert result["file_name"] == "Таблица_06042026.xlsx"

    def test_empty_page(self) -> None:
        parser = OzonCommissionPageParser()
        result = parser.parse("<html><body></body></html>")
        assert result["period_label"] is None
        assert result["download_url"] is None


class TestCommissionResolverService:
    @pytest.mark.asyncio
    async def test_not_found_without_versions(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        resolver = CommissionResolverService(session)
        result = await resolver.get_commission_rate(
            marketplace="WB",
            order_date=date(2026, 5, 20),
            sales_model="fbs",
            category_name="Одежда",
        )
        assert result.match_status == "not_found"
        assert result.commission_percent is None

    @pytest.mark.asyncio
    async def test_not_found_with_version_but_no_rates(self) -> None:
        session = AsyncMock()
        mock_version = MagicMock()
        mock_version.id = 1

        mock_rate_result = MagicMock()
        mock_rate_result.scalar_one_or_none = MagicMock(return_value=None)

        session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=mock_version)),
                mock_rate_result,
                mock_rate_result,
            ]
        )

        resolver = CommissionResolverService(session)
        result = await resolver.get_commission_rate(
            marketplace="WB",
            order_date=date(2026, 5, 20),
            sales_model="fbs",
            category_name="Nonexistent",
        )
        assert result.match_status == "not_found"


class TestWbCommissionResolver:
    """Tests for WB commission resolution with correct field mapping."""

    @pytest.mark.asyncio
    async def test_resolves_fbs_from_kgvp_marketplace(self) -> None:
        session = AsyncMock()
        mock_version = MagicMock()
        mock_version.id = 1

        mock_fbs_rate = MagicMock()
        mock_fbs_rate.id = 10
        mock_fbs_rate.commission_percent = Decimal("15.5")

        mock_found = MagicMock()
        mock_found.scalar_one_or_none = MagicMock(return_value=mock_fbs_rate)

        session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=mock_version)),
                mock_found,
            ]
        )

        resolver = CommissionResolverService(session)
        result = await resolver.get_commission_rate(
            marketplace="WB",
            order_date=date(2026, 5, 20),
            sales_model="fbs",
            category_name="Бытовая техника",
        )
        assert result.match_status == "exact"
        assert result.commission_percent == Decimal("15.5")

    @pytest.mark.asyncio
    async def test_resolves_fbw_from_paid_storage_kgvp(self) -> None:
        """FBW (internal: fbo) resolves from paidStorageKgvp, not kgvpSupplier."""
        session = AsyncMock()
        mock_version = MagicMock()
        mock_version.id = 1

        mock_fbw_rate = MagicMock()
        mock_fbw_rate.id = 20
        mock_fbw_rate.commission_percent = Decimal("19")

        mock_found = MagicMock()
        mock_found.scalar_one_or_none = MagicMock(return_value=mock_fbw_rate)

        session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=mock_version)),
                mock_found,
            ]
        )

        resolver = CommissionResolverService(session)
        result = await resolver.get_commission_rate(
            marketplace="WB",
            order_date=date(2026, 5, 20),
            sales_model="fbo",
            category_name="Одежда",
        )
        assert result.match_status == "exact"
        assert result.commission_percent == Decimal("19")


class TestWbSyncNoChanges:
    @pytest.mark.asyncio
    async def test_sync_returns_no_changes_when_hash_matches(self) -> None:
        from app.services.wb.commissions.wb_commission_sync_service import (
            WbCommissionSyncService,
        )

        session = AsyncMock()
        mock_version = MagicMock()
        mock_version.id = 1
        mock_version.source_file_sha256 = "abc123"

        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_version))
        )

        service = WbCommissionSyncService(session)

        with patch.object(
            service,
            "_get_active_version",
            return_value=mock_version,
        ):
            with patch(
                "app.services.wb.commissions.wb_commission_sync_service.WildberriesClient"
            ) as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get_commission_tariffs = AsyncMock(return_value=[{"test": "data"}])
                mock_client_cls.return_value = mock_client

                with patch(
                    "app.services.wb.commissions.wb_commission_sync_service._compute_payload_hash",
                    return_value="abc123",
                ):
                    result = await service.sync("test-api-key")

        assert result["success"] is True
        assert result["changed"] is False

    @pytest.mark.asyncio
    async def test_sync_creates_rates_from_real_payload(self) -> None:
        """Sync with real-structure payload must not create version with 0 rates."""
        from app.services.wb.commissions.wb_commission_sync_service import (
            _normalize_wb_tariff_entry,
        )

        real_payload = [
            {
                "kgvpBooking": 14.5,
                "kgvpMarketplace": 15.5,
                "kgvpPickup": 14.5,
                "kgvpSupplier": 12.5,
                "kgvpSupplierExpress": 3,
                "paidStorageKgvp": 15.5,
                "parentID": 657,
                "parentName": "Бытовая техника",
                "subjectID": 6461,
                "subjectName": "Оборудование",
            }
        ]

        all_rates = []
        for entry in real_payload:
            all_rates.extend(_normalize_wb_tariff_entry(entry))

        assert len(all_rates) == 6
        models = {r["sales_model"] for r in all_rates}
        assert "fbs" in models
        assert "fbo" in models

        fbs_rate = next(r for r in all_rates if r["sales_model"] == "fbs")
        assert fbs_rate["commission_percent"] == Decimal("15.5")

        fbw_rate = next(r for r in all_rates if r["sales_model"] == "fbo")
        assert fbw_rate["commission_percent"] == Decimal("15.5")

    @pytest.mark.asyncio
    async def test_sync_empty_report_returns_error(self) -> None:
        """Sync with empty report must not create a version."""
        from app.services.wb.commissions.wb_commission_sync_service import (
            WbCommissionSyncService,
        )

        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        service = WbCommissionSyncService(session)

        with patch.object(service, "_get_active_version", return_value=None):
            with patch(
                "app.services.wb.commissions.wb_commission_sync_service.WildberriesClient"
            ) as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get_commission_tariffs = AsyncMock(return_value=[])
                mock_client_cls.return_value = mock_client

                result = await service.sync("test-api-key")

        assert result["success"] is False
        assert result["error_type"] == "WBCommissionEmptyReportError"

    @pytest.mark.asyncio
    async def test_sync_unparseable_report_returns_error(self) -> None:
        """Sync with report that cannot be parsed must not create a version."""
        from app.services.wb.commissions.wb_commission_sync_service import (
            WbCommissionSyncService,
        )

        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        service = WbCommissionSyncService(session)

        with patch.object(service, "_get_active_version", return_value=None):
            with patch(
                "app.services.wb.commissions.wb_commission_sync_service.WildberriesClient"
            ) as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get_commission_tariffs = AsyncMock(
                    return_value=[{"unknown_field": "no_commission_data"}]
                )
                mock_client_cls.return_value = mock_client

                result = await service.sync("test-api-key")

        assert result["success"] is False
        assert result["error_type"] == "WBCommissionParseError"

    @pytest.mark.asyncio
    async def test_cleanup_empty_versions_deactivates_them(self) -> None:
        """Cleanup must deactivate active versions with 0 rates."""
        from app.services.wb.commissions.wb_commission_sync_service import (
            WbCommissionSyncService,
        )

        session = AsyncMock()
        empty_version = MagicMock()
        empty_version.id = 99
        empty_version.is_active = True

        valid_version = MagicMock()
        valid_version.id = 100
        valid_version.is_active = True

        call_count = {"count": 0}

        def mock_execute(query):
            call_count["count"] += 1
            result = MagicMock()
            if call_count["count"] == 1:
                result.scalars = MagicMock(
                    return_value=MagicMock(
                        all=MagicMock(return_value=[empty_version, valid_version])
                    )
                )
            else:
                if call_count["count"] == 2:
                    result.scalar_one_or_none = MagicMock(return_value=None)
                else:
                    result.scalar_one_or_none = MagicMock(return_value=MagicMock())
            return result

        session.execute = AsyncMock(side_effect=mock_execute)

        service = WbCommissionSyncService(session)
        cleaned = await service.cleanup_empty_versions()

        assert cleaned == 1
        assert empty_version.is_active is False
        assert valid_version.is_active is True


class TestOzonMonitorDetectsChanges:
    def test_detects_new_period(self) -> None:
        from app.services.ozon.commissions.ozon_commission_source_monitor_service import (
            OzonCommissionSourceMonitorService,
        )

        last_check = MagicMock()
        last_check.current_detected_period_label = "Таблица с 1 марта 2026"
        last_check.current_detected_file_url = "https://example.com/old.xlsx"

        parsed = {
            "period_label": "Таблица с 6 апреля 2026",
            "download_url": "https://example.com/new.xlsx",
            "file_name": "new.xlsx",
        }

        change_type, has_changes = OzonCommissionSourceMonitorService._detect_changes(
            last_check, parsed
        )
        assert has_changes is True
        assert change_type == "new_period_detected"

    def test_detects_no_changes(self) -> None:
        from app.services.ozon.commissions.ozon_commission_source_monitor_service import (
            OzonCommissionSourceMonitorService,
        )

        last_check = MagicMock()
        last_check.current_detected_period_label = "Таблица с 6 апреля 2026"
        last_check.current_detected_file_url = "https://example.com/file.xlsx"

        parsed = {
            "period_label": "Таблица с 6 апреля 2026",
            "download_url": "https://example.com/file.xlsx",
            "file_name": "file.xlsx",
        }

        change_type, has_changes = OzonCommissionSourceMonitorService._detect_changes(
            last_check, parsed
        )
        assert has_changes is False
        assert change_type == "no_change"

    def test_detects_url_change(self) -> None:
        from app.services.ozon.commissions.ozon_commission_source_monitor_service import (
            OzonCommissionSourceMonitorService,
        )

        last_check = MagicMock()
        last_check.current_detected_period_label = "Таблица с 6 апреля 2026"
        last_check.current_detected_file_url = "https://example.com/old.xlsx"

        parsed = {
            "period_label": "Таблица с 6 апреля 2026",
            "download_url": "https://example.com/new.xlsx",
            "file_name": "new.xlsx",
        }

        change_type, has_changes = OzonCommissionSourceMonitorService._detect_changes(
            last_check, parsed
        )
        assert has_changes is True
        assert change_type == "file_url_changed"


class TestWbSyncNotificationFormatter:
    def test_success_with_rates(self) -> None:
        result = {
            "success": True,
            "changed": True,
            "version_label": "WB tariffs sync 2026-05-20",
            "rates_count": 1200,
            "version_id": 3,
        }
        msg = format_wb_sync_notification(result)
        assert "Обновлены комиссии Wildberries" in msg
        assert "Ставок: 1200" in msg
        assert "⚠️" not in msg

    def test_success_with_zero_rates_shows_warning(self) -> None:
        result = {
            "success": True,
            "changed": True,
            "version_label": "WB tariffs sync 2026-05-20",
            "rates_count": 0,
            "version_id": 2,
        }
        msg = format_wb_sync_notification(result)
        assert "0 ставок" in msg
        assert "Обновлены комиссии Wildberries" not in msg
        assert "⚠️" in msg

    def test_no_changes(self) -> None:
        result = {"success": True, "changed": False}
        msg = format_wb_sync_notification(result)
        assert "изменений нет" in msg

    def test_error_shows_details(self) -> None:
        result = {
            "success": False,
            "error_type": "WBCommissionParseError",
            "error": "Тестовая ошибка",
        }
        msg = format_wb_sync_notification(result)
        assert "Ошибка синхронизации" in msg
        assert "WBCommissionParseError" in msg


class TestChangeTypeBadge:
    def test_no_change_shows_green(self) -> None:
        from app.web.route_modules.commissions_admin import _change_type_badge

        badge = _change_type_badge("no_change")
        assert "Без изменений" in badge
        assert "good" in badge

    def test_new_period_shows_action(self) -> None:
        from app.web.route_modules.commissions_admin import _change_type_badge

        badge = _change_type_badge("new_period_detected")
        assert "Есть изменения" in badge
        assert "action" in badge

    def test_file_url_changed_shows_action(self) -> None:
        from app.web.route_modules.commissions_admin import _change_type_badge

        badge = _change_type_badge("file_url_changed")
        assert "Есть изменения" in badge
        assert "action" in badge

    def test_parse_error_shows_red(self) -> None:
        from app.web.route_modules.commissions_admin import _change_type_badge

        badge = _change_type_badge("parse_error")
        assert "Ошибка парсинга" in badge
        assert "bad" in badge

    def test_unavailable_shows_neutral(self) -> None:
        from app.web.route_modules.commissions_admin import _change_type_badge

        badge = _change_type_badge("unavailable")
        assert "Источник недоступен" in badge
        assert "unavailable" not in badge.lower().split(">")[1]

    def test_rate_limited_shows_warning(self) -> None:
        from app.web.route_modules.commissions_admin import _change_type_badge

        badge = _change_type_badge("rate_limited")
        assert "недоступен" in badge.lower()
        assert "warn" in badge

    def test_unknown_type_shows_escaped(self) -> None:
        from app.web.route_modules.commissions_admin import _change_type_badge

        badge = _change_type_badge("some_new_type")
        assert "some_new_type" in badge


class TestOzonPageParserFallbacks:
    def test_parse_empty_html(self) -> None:
        parser = OzonCommissionPageParser()
        result = parser.parse("<html><body></body></html>")
        assert result["period_label"] is None
        assert result["download_url"] is None
        assert result["file_name"] is None

    def test_parse_xlsx_link(self) -> None:
        parser = OzonCommissionPageParser()
        html = (
            "<html><body>"
            "<h2>Таблица категорий с 6 апреля 2026 г.</h2>"
            '<p><a href="/files/commissions.xlsx">Скачать таблицу категорий</a></p>'
            "</body></html>"
        )
        result = parser.parse(html)
        assert result["download_url"] is not None
        assert "commissions.xlsx" in result["download_url"]

    def test_parse_period_label(self) -> None:
        parser = OzonCommissionPageParser()
        html = (
            "<html><body>"
            "<h2>Таблица категорий с 1 июня 2026 г.</h2>"
            '<p><a href="/files/commissions.xlsx">Скачать таблицу категорий</a></p>'
            "</body></html>"
        )
        result = parser.parse(html)
        assert result["period_label"] is not None
        assert "категорий" in result["period_label"].lower()

    def test_extract_file_name_from_url(self) -> None:
        name = OzonCommissionPageParser._extract_file_name(
            "https://example.com/files/ozon_commissions_06042026.xlsx"
        )
        assert name is not None
        assert ".xlsx" in name

    def test_extract_file_name_none(self) -> None:
        assert OzonCommissionPageParser._extract_file_name(None) is None


class TestChecksTableRendering:
    def test_empty_checks_renders_table(self) -> None:
        from app.web.route_modules.commissions_admin import _checks_table

        html = _checks_table([])
        assert "История проверок" in html
        assert "<table" in html

    def test_unavailable_check_renders_russian(self) -> None:
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        from app.web.route_modules.commissions_admin import _checks_table

        check = MagicMock()
        check.checked_at = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
        check.current_detected_period_label = None
        check.change_type = "unavailable"
        check.has_changes = False
        check.current_detected_file_url = None
        check.current_detected_file_name = None
        check.details = {"error": "HTTP 403: Forbidden"}

        html = _checks_table([check])
        assert "Источник недоступен" in html
        assert "unavailable" not in html.split("<td>")[3]

    def test_check_with_file_url_shows_link(self) -> None:
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        from app.web.route_modules.commissions_admin import _checks_table

        check = MagicMock()
        check.checked_at = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
        check.current_detected_period_label = "с 01.06.2026"
        check.change_type = "new_period_detected"
        check.has_changes = True
        check.current_detected_file_url = "https://example.com/commissions.xlsx"
        check.current_detected_file_name = "ozon_commissions.xlsx"
        check.details = {}

        html = _checks_table([check])
        assert "Скачать актуальный файл" in html
        assert "https://example.com/commissions.xlsx" in html


class TestOzonLowPriceSpecialRates:
    """Test special commission rates for Ozon items up to 300 RUB."""

    def test_fbo_up_to_100_rub(self) -> None:
        from app.services.commissions.commission_resolver_service import (
            CommissionResolverService,
        )

        rate = CommissionResolverService._get_ozon_low_price_special_rate(
            sales_model="fbo",
            product_price=Decimal("50"),
        )
        assert rate == Decimal("14")

    def test_fbs_up_to_100_rub(self) -> None:
        from app.services.commissions.commission_resolver_service import (
            CommissionResolverService,
        )

        rate = CommissionResolverService._get_ozon_low_price_special_rate(
            sales_model="fbs",
            product_price=Decimal("100"),
        )
        assert rate == Decimal("14")

    def test_fbo_fresh_up_to_100_rub(self) -> None:
        from app.services.commissions.commission_resolver_service import (
            CommissionResolverService,
        )

        rate = CommissionResolverService._get_ozon_low_price_special_rate(
            sales_model="fbo_fresh",
            product_price=Decimal("99"),
        )
        assert rate == Decimal("17")

    def test_fbo_101_to_300_rub(self) -> None:
        from app.services.commissions.commission_resolver_service import (
            CommissionResolverService,
        )

        rate = CommissionResolverService._get_ozon_low_price_special_rate(
            sales_model="fbo",
            product_price=Decimal("150"),
        )
        assert rate == Decimal("20")

    def test_fbs_101_to_300_rub(self) -> None:
        from app.services.commissions.commission_resolver_service import (
            CommissionResolverService,
        )

        rate = CommissionResolverService._get_ozon_low_price_special_rate(
            sales_model="fbs",
            product_price=Decimal("300"),
        )
        assert rate == Decimal("20")

    def test_fbo_fresh_101_to_300_rub(self) -> None:
        from app.services.commissions.commission_resolver_service import (
            CommissionResolverService,
        )

        rate = CommissionResolverService._get_ozon_low_price_special_rate(
            sales_model="fbo_fresh",
            product_price=Decimal("250"),
        )
        assert rate == Decimal("23")

    def test_rfbs_not_supported(self) -> None:
        from app.services.commissions.commission_resolver_service import (
            CommissionResolverService,
        )

        rate = CommissionResolverService._get_ozon_low_price_special_rate(
            sales_model="rfbs",
            product_price=Decimal("50"),
        )
        assert rate is None

    def test_above_300_rub_not_supported(self) -> None:
        from app.services.commissions.commission_resolver_service import (
            CommissionResolverService,
        )

        rate = CommissionResolverService._get_ozon_low_price_special_rate(
            sales_model="fbo",
            product_price=Decimal("301"),
        )
        assert rate is None


class TestOzonPageParserAdvanced:
    """Test advanced Ozon page parser scenarios."""

    def test_parse_selects_latest_period(self) -> None:
        parser = OzonCommissionPageParser()
        html = (
            "<html><body>"
            "<h2>Таблица категорий с 13 марта 2026 г.</h2>"
            '<p><a href="/files/old.xlsx">Скачать таблицу категорий</a></p>'
            "<h2>Таблица категорий с 6 апреля 2026 г.</h2>"
            '<p><a href="/files/new.xlsx">Скачать таблицу категорий</a></p>'
            "</body></html>"
        )
        result = parser.parse(html)
        assert result["download_url"] is not None
        assert "new.xlsx" in result["download_url"]
        assert "апреля" in result["period_label"].lower()

    def test_parse_ignores_select_platform_link(self) -> None:
        parser = OzonCommissionPageParser()
        html = (
            "<html><body>"
            "<h2>Таблица категорий с 6 апреля 2026 г.</h2>"
            '<p><a href="/files/regular.xlsx">Скачать таблицу категорий</a></p>'
            '<p><a href="/files/select.xlsx">Скачать таблицу категорий на платформе Селект</a></p>'
            "</body></html>"
        )
        result = parser.parse(html)
        assert result["download_url"] is not None
        assert "regular.xlsx" in result["download_url"]

    def test_parse_extracts_active_from_date(self) -> None:
        parser = OzonCommissionPageParser()
        html = (
            "<html><body>"
            "<h2>Таблица категорий с 6 апреля 2026 г.</h2>"
            '<p><a href="/files/commissions.xlsx">Скачать таблицу категорий</a></p>'
            "</body></html>"
        )
        result = parser.parse(html)
        assert result["active_from"] == "2026-04-06"
