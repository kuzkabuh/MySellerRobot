"""version: 1.0.0
description: Unit tests for WB logistics tariff sync, calculator, and volume utilities.
updated: 2026-05-20
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import MarketplaceApiError
from app.integrations.wb import WildberriesClient
from app.models.enums import EconomyConfidence
from app.services.product_dimensions import calculate_volume_liters, decimal_or_none
from app.services.wb_logistics.wb_logistics_calculator_service import (
    WbLogisticsCalculatorService,
    _calculate_base_volume_tariff,
    _calculate_kgt_logistics,
    _calculate_mgt_logistics,
    _calculate_reverse_logistics,
    _classify_volume_category,
    _safe_decimal,
)
from app.services.wb_logistics.wb_logistics_tariff_sync_service import (
    WbLogisticsTariffSyncService,
    _compute_version_hash,
    _normalize_tariff_entry,
    _parse_coefficient_expr,
)

# ============================================================
# Volume calculation tests
# ============================================================


class TestVolumeCalculation:
    def test_decimal_or_none_valid(self) -> None:
        assert decimal_or_none("12.5") == Decimal("12.5")
        assert decimal_or_none("12,5") == Decimal("12.5")
        assert decimal_or_none(12.5) == Decimal("12.5")

    def test_decimal_or_none_invalid(self) -> None:
        assert decimal_or_none(None) is None
        assert decimal_or_none("") is None
        assert decimal_or_none("abc") is None
        assert decimal_or_none(-5) is None

    def test_calculate_volume_liters(self) -> None:
        volume = calculate_volume_liters(10, 20, 30)
        assert volume == Decimal("6.000")

    def test_calculate_volume_liters_incomplete(self) -> None:
        assert calculate_volume_liters(10, 20, None) is None
        assert calculate_volume_liters(None, 20, 30) is None

    def test_calculate_volume_liters_small(self) -> None:
        volume = calculate_volume_liters(5, 5, 5)
        assert volume == Decimal("0.125")


# ============================================================
# Tariff normalization tests
# ============================================================


class TestTariffNormalization:
    def test_normalize_single_entry(self) -> None:
        entry = {
            "warehouseName": "Хабаровск",
            "geoName": "Хабаровск",
            "boxDeliveryBase": 46,
            "boxDeliveryLiter": 14,
            "boxDeliveryCoefExpr": "1.2",
            "boxDeliveryMarketplaceBase": 50,
            "boxDeliveryMarketplaceLiter": 15,
            "boxDeliveryMarketplaceCoefExpr": "1.3",
        }
        result = _normalize_tariff_entry(entry)
        assert result["warehouse_name"] == "Хабаровск"
        assert result["fbo_base_tariff"] == Decimal("46")
        assert result["fbo_liter_tariff"] == Decimal("14")
        assert result["fbs_base_tariff"] == Decimal("50")
        assert result["fbs_liter_tariff"] == Decimal("15")
        assert result["logistics_coefficient_percent"] == Decimal("1.2")

    def test_normalize_missing_fields(self) -> None:
        entry = {"warehouseName": "Тест"}
        result = _normalize_tariff_entry(entry)
        assert result["fbo_base_tariff"] is None
        assert result["fbs_base_tariff"] is None

    def test_compute_version_hash_deterministic(self) -> None:
        payload = [{"warehouseName": "A"}, {"warehouseName": "B"}]
        h1 = _compute_version_hash(payload)
        h2 = _compute_version_hash(payload)
        assert h1 == h2

    def test_compute_version_hash_different(self) -> None:
        h1 = _compute_version_hash([{"warehouseName": "A"}])
        h2 = _compute_version_hash([{"warehouseName": "B"}])
        assert h1 != h2


# ============================================================
# Coefficient parsing tests
# ============================================================


class TestCoefficientParsing:
    def test_parse_simple_decimal(self) -> None:
        assert _parse_coefficient_expr("1.2") == Decimal("1.2")
        assert _parse_coefficient_expr("1,2") == Decimal("1.2")

    def test_parse_invalid(self) -> None:
        assert _parse_coefficient_expr(None) is None
        assert _parse_coefficient_expr("") is None
        assert _parse_coefficient_expr("abc") is None


# ============================================================
# Base volume tariff tests
# ============================================================


class TestBaseVolumeTariff:
    def test_under_one_liter(self) -> None:
        tariff = _calculate_base_volume_tariff(Decimal("0.5"), Decimal("46"), Decimal("14"))
        assert tariff == Decimal("46")

    def test_exactly_one_liter(self) -> None:
        tariff = _calculate_base_volume_tariff(Decimal("1.0"), Decimal("46"), Decimal("14"))
        assert tariff == Decimal("46")

    def test_over_one_liter(self) -> None:
        tariff = _calculate_base_volume_tariff(Decimal("3.0"), Decimal("46"), Decimal("14"))
        assert tariff == Decimal("46") + Decimal("2") * Decimal("14")
        assert tariff == Decimal("74")

    def test_large_volume(self) -> None:
        tariff = _calculate_base_volume_tariff(Decimal("10.0"), Decimal("46"), Decimal("14"))
        assert tariff == Decimal("46") + Decimal("9") * Decimal("14")
        assert tariff == Decimal("172")


# ============================================================
# MGT logistics formula tests
# ============================================================


class TestMGTLogistics:
    def test_full_formula(self) -> None:
        logistics = _calculate_mgt_logistics(
            base_volume_tariff=Decimal("46"),
            warehouse_coefficient=Decimal("1.2"),
            localization_index=Decimal("1.0"),
            price_before_discount=Decimal("1000"),
            sales_distribution_index=Decimal("0.01"),
        )
        direct = Decimal("46") * Decimal("1.2") * Decimal("1.0")
        surcharge = Decimal("1000") * Decimal("0.01")
        assert logistics == direct + surcharge
        assert logistics == Decimal("55.2") + Decimal("10")
        assert logistics == Decimal("65.2")

    def test_no_distribution_index(self) -> None:
        logistics = _calculate_mgt_logistics(
            base_volume_tariff=Decimal("46"),
            warehouse_coefficient=Decimal("1.2"),
            localization_index=Decimal("1.0"),
            price_before_discount=Decimal("1000"),
            sales_distribution_index=Decimal("0"),
        )
        assert logistics == Decimal("55.2")


# ============================================================
# KGT logistics tests
# ============================================================


class TestKGTLogistics:
    def test_within_bounds(self) -> None:
        logistics = _calculate_kgt_logistics(Decimal("800"), Decimal("1.5"))
        assert logistics == Decimal("1200")

    def test_below_minimum(self) -> None:
        logistics = _calculate_kgt_logistics(Decimal("100"), Decimal("1.0"))
        assert logistics == Decimal("1000")

    def test_above_maximum(self) -> None:
        logistics = _calculate_kgt_logistics(Decimal("5000"), Decimal("1.0"))
        assert logistics == Decimal("3000")


# ============================================================
# Reverse logistics tests
# ============================================================


class TestReverseLogistics:
    def test_under_one_liter(self) -> None:
        reverse = _calculate_reverse_logistics(Decimal("0.5"), Decimal("46"), Decimal("14"))
        assert reverse == Decimal("46")

    def test_over_one_liter(self) -> None:
        reverse = _calculate_reverse_logistics(Decimal("3.0"), Decimal("46"), Decimal("14"))
        assert reverse == Decimal("74")


# ============================================================
# Volume category classification tests
# ============================================================


class TestVolumeCategory:
    def test_mgt(self) -> None:
        assert _classify_volume_category(Decimal("0.5")) == "MGT"
        assert _classify_volume_category(Decimal("1000")) == "MGT"

    def test_sgt(self) -> None:
        assert _classify_volume_category(Decimal("1001")) == "SGT"
        assert _classify_volume_category(Decimal("5000")) == "SGT"

    def test_kgt_plus(self) -> None:
        assert _classify_volume_category(Decimal("5001")) == "KGT_PLUS"

    def test_unknown(self) -> None:
        assert _classify_volume_category(None) == "unknown"
        assert _classify_volume_category(Decimal("0")) == "unknown"
        assert _classify_volume_category(Decimal("-1")) == "unknown"


# ============================================================
# Calculator service tests
# ============================================================


class TestWbLogisticsCalculatorService:
    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def calculator(self, mock_session: AsyncMock) -> WbLogisticsCalculatorService:
        return WbLogisticsCalculatorService(mock_session)

    @pytest.mark.asyncio
    async def test_no_volume_returns_not_available(
        self, calculator: WbLogisticsCalculatorService
    ) -> None:
        result = await calculator.calculate_planned_wb_logistics(
            order_date=datetime.now(UTC),
            sales_model="FBS",
            warehouse_name="Хабаровск",
            product_volume_liters=None,
            product_price_before_wb_discount=Decimal("1000"),
        )
        assert result.confidence == EconomyConfidence.NOT_AVAILABLE
        assert result.logistics_amount_planned is None

    @pytest.mark.asyncio
    async def test_no_warehouse_returns_not_available(
        self, calculator: WbLogisticsCalculatorService
    ) -> None:
        result = await calculator.calculate_planned_wb_logistics(
            order_date=datetime.now(UTC),
            sales_model="FBS",
            warehouse_name=None,
            product_volume_liters=Decimal("0.5"),
            product_price_before_wb_discount=Decimal("1000"),
        )
        assert result.confidence == EconomyConfidence.NOT_AVAILABLE
        assert result.logistics_amount_planned is None

    @pytest.mark.asyncio
    async def test_no_tariff_returns_not_available(
        self, calculator: WbLogisticsCalculatorService, mock_session: AsyncMock
    ) -> None:
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        result = await calculator.calculate_planned_wb_logistics(
            order_date=datetime.now(UTC),
            sales_model="FBS",
            warehouse_name="Хабаровск",
            product_volume_liters=Decimal("0.5"),
            product_price_before_wb_discount=Decimal("1000"),
        )
        assert result.confidence == EconomyConfidence.NOT_AVAILABLE


# ============================================================
# Sync service tests
# ============================================================


class TestWbLogisticsTariffSyncService:
    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def mock_wb_client(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def sync_service(
        self, mock_session: AsyncMock, mock_wb_client: AsyncMock
    ) -> WbLogisticsTariffSyncService:
        return WbLogisticsTariffSyncService(mock_session, mock_wb_client)

    @pytest.mark.asyncio
    async def test_api_error_returns_error_status(
        self, sync_service: WbLogisticsTariffSyncService, mock_wb_client: AsyncMock
    ) -> None:
        mock_wb_client.get_box_tariffs = AsyncMock(side_effect=Exception("API down"))
        result = await sync_service.sync()
        assert result["status"] == "error"
        assert "Не удалось обновить тарифы логистики WB" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_response_returns_error(
        self, sync_service: WbLogisticsTariffSyncService, mock_wb_client: AsyncMock
    ) -> None:
        mock_wb_client.get_box_tariffs = AsyncMock(return_value=[])
        result = await sync_service.sync()
        assert result["status"] == "error"
        assert "Wildberries вернул пустой ответ" in result["message"]
        assert "Попыток: 4" in result["message"]

    @pytest.mark.asyncio
    async def test_unchanged_tariffs_returns_no_changes(
        self,
        sync_service: WbLogisticsTariffSyncService,
        mock_wb_client: AsyncMock,
        mock_session: AsyncMock,
    ) -> None:
        mock_wb_client.get_box_tariffs = AsyncMock(
            return_value=[{"warehouseName": "Хабаровск", "boxDeliveryBase": 46}]
        )
        existing_version = MagicMock()
        existing_version.id = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=existing_version)
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await sync_service.sync()
        assert result["status"] == "no_changes"
        assert result["version_id"] == 1


class TestWbTariffsClient:
    @pytest.mark.asyncio
    async def test_box_tariffs_pass_required_moscow_date(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("app.integrations.wb.get_moscow_today", lambda: "2026-06-02")
        client = WildberriesClient("token")
        client.common.request = AsyncMock(return_value={"tariffs": [{"warehouseName": "Коледино"}]})

        rows = await client.get_box_tariffs()

        assert rows == [{"warehouseName": "Коледино"}]
        client.common.request.assert_awaited_once_with(
            "GET",
            "/api/v1/tariffs/box",
            headers=client.headers,
            params={"date": "2026-06-02"},
            retries=4,
        )

    @pytest.mark.asyncio
    async def test_box_tariffs_empty_response_raises_clear_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("app.integrations.wb.get_moscow_today", lambda: "2026-06-02")
        client = WildberriesClient("token")
        client.common.request = AsyncMock(return_value={})

        with pytest.raises(MarketplaceApiError) as exc_info:
            await client.get_box_tariffs()

        assert exc_info.value.message == "Wildberries вернул пустой ответ"
        assert exc_info.value.details["reason"] == "empty_response"
        assert exc_info.value.details["attempts"] == 4

    @pytest.mark.asyncio
    async def test_box_tariffs_invalid_json_raises_clear_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("app.integrations.wb.get_moscow_today", lambda: "2026-06-02")
        client = WildberriesClient("token")
        client.common.request = AsyncMock(return_value={"text": "<html>oops</html>"})

        with pytest.raises(MarketplaceApiError) as exc_info:
            await client.get_box_tariffs()

        assert exc_info.value.message == "Wildberries вернул не JSON-ответ"
        assert exc_info.value.details["body_preview"] == "<html>oops</html>"

    @pytest.mark.asyncio
    async def test_pallet_and_return_tariffs_pass_date_params(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.integrations.wb.get_moscow_today", lambda: "2026-06-02")
        client = WildberriesClient("token")
        client.common.request = AsyncMock(return_value={"ok": True})

        await client.get_pallet_tariffs()
        await client.get_return_tariffs(date="2026-06-03")

        assert client.common.request.await_args_list[0].kwargs["params"] == {"date": "2026-06-02"}
        assert client.common.request.await_args_list[1].kwargs["params"] == {"date": "2026-06-03"}


# ============================================================
# Safe decimal tests
# ============================================================


class TestSafeDecimal:
    def test_valid_values(self) -> None:
        assert _safe_decimal(46) == Decimal("46")
        assert _safe_decimal("46.5") == Decimal("46.5")
        assert _safe_decimal("46,5") == Decimal("46.5")

    def test_invalid_values(self) -> None:
        assert _safe_decimal(None) is None
        assert _safe_decimal("") is None
        assert _safe_decimal("abc") is None
        assert _safe_decimal(-10) is None
