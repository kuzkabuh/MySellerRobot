"""version: 1.0.0
description: Tests for the commission tariff system (WB sync, Ozon monitor, Ozon import, resolver).
updated: 2026-05-20
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import Marketplace
from app.services.commission_tariffs.commission_resolver_service import (
    CommissionResolutionResult,
    CommissionResolverService,
)
from app.services.commission_tariffs.ozon_commission_source_monitor_service import (
    OzonCommissionPageParser,
)
from app.services.commission_tariffs.ozon_commission_xlsx_importer import (
    _normalize_commission_value,
    _extract_date_from_filename,
)
from app.services.commission_tariffs.wb_commission_sync_service import (
    _compute_payload_hash,
    _normalize_wb_tariff_entry,
)


class TestWbTariffNormalization:
    def test_normalize_single_entry(self) -> None:
        entry = {
            "subject": "Одежда",
            "categoryName": "Одежда и обувь",
            "tariffs": [
                {"salesModel": "FBO", "commissionPercent": 19},
                {"salesModel": "FBS", "commissionPercent": 25},
            ],
        }
        rates = _normalize_wb_tariff_entry(entry)
        assert len(rates) == 2
        assert rates[0]["sales_model"] == "fbo"
        assert rates[0]["commission_percent"] == Decimal("19")
        assert rates[1]["sales_model"] == "fbs"
        assert rates[1]["commission_percent"] == Decimal("25")

    def test_normalize_maps_kvv_to_fbo(self) -> None:
        entry = {
            "subject": "Тест",
            "tariffs": [{"salesModel": "KVV", "commissionPercent": 15}],
        }
        rates = _normalize_wb_tariff_entry(entry)
        assert rates[0]["sales_model"] == "fbo"

    def test_normalize_empty_tariffs(self) -> None:
        entry = {"subject": "Тест", "tariffs": []}
        rates = _normalize_wb_tariff_entry(entry)
        assert rates == []

    def test_normalize_decimal_percent(self) -> None:
        entry = {
            "subject": "Тест",
            "tariffs": [{"salesModel": "FBO", "commissionPercent": 12.5}],
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
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
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

        session.execute = AsyncMock(side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_version)),
            mock_rate_result,
            mock_rate_result,
        ])

        resolver = CommissionResolverService(session)
        result = await resolver.get_commission_rate(
            marketplace="WB",
            order_date=date(2026, 5, 20),
            sales_model="fbs",
            category_name="Nonexistent",
        )
        assert result.match_status == "not_found"


class TestWbSyncNoChanges:
    @pytest.mark.asyncio
    async def test_sync_returns_no_changes_when_hash_matches(self) -> None:
        from app.services.commission_tariffs.wb_commission_sync_service import WbCommissionSyncService

        session = AsyncMock()
        mock_version = MagicMock()
        mock_version.id = 1
        mock_version.source_file_sha256 = "abc123"

        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_version)))

        service = WbCommissionSyncService(session)

        with patch.object(
            service,
            "_get_active_version",
            return_value=mock_version,
        ):
            with patch(
                "app.services.commission_tariffs.wb_commission_sync_service.WildberriesClient"
            ) as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get_commission_tariffs = AsyncMock(return_value=[{"test": "data"}])
                mock_client_cls.return_value = mock_client

                with patch(
                    "app.services.commission_tariffs.wb_commission_sync_service._compute_payload_hash",
                    return_value="abc123",
                ):
                    result = await service.sync("test-api-key")

        assert result["success"] is True
        assert result["changed"] is False


class TestOzonMonitorDetectsChanges:
    def test_detects_new_period(self) -> None:
        from app.services.commission_tariffs.ozon_commission_source_monitor_service import (
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

        change_type, has_changes = OzonCommissionSourceMonitorService._detect_changes(last_check, parsed)
        assert has_changes is True
        assert change_type == "new_period_detected"

    def test_detects_no_changes(self) -> None:
        from app.services.commission_tariffs.ozon_commission_source_monitor_service import (
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

        change_type, has_changes = OzonCommissionSourceMonitorService._detect_changes(last_check, parsed)
        assert has_changes is False
        assert change_type == "no_change"

    def test_detects_url_change(self) -> None:
        from app.services.commission_tariffs.ozon_commission_source_monitor_service import (
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

        change_type, has_changes = OzonCommissionSourceMonitorService._detect_changes(last_check, parsed)
        assert has_changes is True
        assert change_type == "file_url_changed"
