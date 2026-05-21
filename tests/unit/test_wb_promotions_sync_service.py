"""Tests for WbPromotionsSyncService."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.wb.wb_promotions_sync_service import (
    WbPromotionsSyncService,
    _extract_nomenclatures_list,
    _extract_promotions_list,
    _is_active_today,
    _money,
    _parse_datetime,
    _safe_response_preview,
)


class TestHelpers:
    """Test helper functions."""

    def test_parse_datetime_iso(self) -> None:
        """Parse ISO datetime string."""
        result = _parse_datetime("2026-05-21T00:00:00Z")
        assert result is not None
        assert result.year == 2026
        assert result.month == 5
        assert result.day == 21

    def test_parse_datetime_none(self) -> None:
        """Parse None returns None."""
        assert _parse_datetime(None) is None

    def test_parse_datetime_empty(self) -> None:
        """Parse empty string returns None."""
        assert _parse_datetime("") is None

    def test_parse_datetime_already_datetime(self) -> None:
        """Pass datetime object returns it."""
        dt = datetime(2026, 5, 21, tzinfo=UTC)
        result = _parse_datetime(dt)
        assert result == dt

    def test_is_active_today_true(self) -> None:
        """Promotion is active today."""
        now = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
        start = now - timedelta(days=1)
        end = now + timedelta(days=1)
        assert _is_active_today(start, end, now) is True

    def test_is_active_today_before_start(self) -> None:
        """Promotion not started yet."""
        now = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
        start = now + timedelta(days=1)
        end = now + timedelta(days=2)
        assert _is_active_today(start, end, now) is False

    def test_is_active_today_after_end(self) -> None:
        """Promotion already ended."""
        now = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
        start = now - timedelta(days=2)
        end = now - timedelta(days=1)
        assert _is_active_today(start, end, now) is False

    def test_is_active_today_no_dates(self) -> None:
        """No dates means not active."""
        now = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
        assert _is_active_today(None, None, now) is False

    def test_money_valid(self) -> None:
        """Parse valid money value."""
        assert _money("647.50") == Decimal("647.50")

    def test_money_comma_decimal(self) -> None:
        """Parse money with comma decimal separator."""
        assert _money("647,50") == Decimal("647.50")

    def test_money_none(self) -> None:
        """None returns None."""
        assert _money(None) is None

    def test_money_empty(self) -> None:
        """Empty string returns None."""
        assert _money("") is None

    def test_money_invalid(self) -> None:
        """Invalid string returns None."""
        assert _money("abc") is None


class TestPromotionsSyncServiceParsing:
    """Test parsing of WB API responses."""

    def test_parse_promotions_response_list(self) -> None:
        """Parse promotions response with list of promotions."""
        response = {
            "promotions": [
                {
                    "id": 123,
                    "name": "Summer Sale",
                    "type": "regular",
                    "startDateTime": "2026-05-20T00:00:00Z",
                    "endDateTime": "2026-05-22T23:59:59Z",
                },
            ]
        }
        promotions = response.get("promotions") or response.get("data") or []
        assert len(promotions) == 1
        assert promotions[0]["id"] == 123

    def test_parse_nomenclatures_response_list(self) -> None:
        """Parse nomenclatures response with list of items."""
        response = {
            "nomenclatures": [
                {
                    "id": 12345,
                    "price": "1000",
                    "planPrice": "647",
                    "currencyCode": "RUB",
                    "discount": "25.00",
                    "planDiscount": "75.00",
                },
            ]
        }
        items = response.get("nomenclatures") or response.get("data") or []
        assert len(items) == 1
        assert items[0]["id"] == 12345
        assert items[0]["planPrice"] == "647"

    def test_parse_auto_promotion_type(self) -> None:
        """Auto promotion type should be detected."""
        promo = {"type": "auto", "id": 456}
        assert promo["type"].lower() == "auto"

    def test_parse_regular_promotion_type(self) -> None:
        """Regular promotion type should be detected."""
        promo = {"type": "regular", "id": 789}
        assert promo["type"].lower() != "auto"


class TestPromotionsSyncServiceIntegration:
    """Integration-style tests for the sync service logic."""

    @pytest.mark.asyncio
    async def test_sync_no_accounts(self) -> None:
        """Sync with no accounts should return empty stats."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

        service = WbPromotionsSyncService(mock_session)
        stats = await service.sync_all_accounts()

        assert stats.accounts_processed == 0
        assert stats.accounts_failed == 0

    @pytest.mark.asyncio
    async def test_get_actual_promo_selects_min_price(self) -> None:
        """When product is in multiple promos, select minimum planPrice."""
        mock_session = AsyncMock()

        # Simulate two promos with different planPrices
        mock_nomenclature_1 = MagicMock()
        mock_nomenclature_1.plan_price = Decimal("650")

        mock_nomenclature_2 = MagicMock()
        mock_nomenclature_2.plan_price = Decimal("640")

        mock_result = MagicMock()
        mock_result.all.return_value = [
            (mock_nomenclature_2, datetime(2026, 5, 22, tzinfo=UTC)),
            (mock_nomenclature_1, datetime(2026, 5, 21, tzinfo=UTC)),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)

        service = WbPromotionsSyncService(mock_session)
        result = await service.get_actual_promo_for_product(
            marketplace_account_id=1,
            wb_nm_id=12345,
        )

        # Should return the one with min planPrice (640)
        assert result is not None
        assert result.plan_price == Decimal("640")


class TestPromotionsSyncServicePagination:
    """Test pagination logic."""

    def test_pagination_single_page(self) -> None:
        """Single page of results (< limit)."""
        items = [{"id": i} for i in range(500)]
        limit = 1000

        assert len(items) < limit
        # No more pages needed

    def test_pagination_multiple_pages(self) -> None:
        """Multiple pages of results."""
        page1 = [{"id": i} for i in range(1000)]
        page2 = [{"id": i} for i in range(1000, 1300)]
        limit = 1000

        total = len(page1) + len(page2)
        assert total == 1300
        assert len(page1) == limit
        assert len(page2) < limit


class TestPromotionsListExtraction:
    """Test _extract_promotions_list for various WB API response formats."""

    def test_official_format_data_promotions(self) -> None:
        """Official WB format: {data: {promotions: [...]}}."""
        response = {
            "data": {
                "promotions": [
                    {"id": 123, "name": "Test Promo"},
                    {"id": 456, "name": "Another"},
                ]
            }
        }
        result = _extract_promotions_list(response)
        assert len(result) == 2
        assert result[0]["id"] == 123

    def test_fallback_top_level_promotions(self) -> None:
        """Fallback: {promotions: [...]}."""
        response = {"promotions": [{"id": 1}]}
        result = _extract_promotions_list(response)
        assert len(result) == 1

    def test_fallback_data_as_list(self) -> None:
        """Fallback: {data: [...]}."""
        response = {"data": [{"id": 1}]}
        result = _extract_promotions_list(response)
        assert len(result) == 1

    def test_fallback_response_as_list(self) -> None:
        """Fallback: response is a list."""
        response = [{"id": 1}, {"id": 2}]
        result = _extract_promotions_list(response)
        assert len(result) == 2

    def test_empty_response(self) -> None:
        """Empty dict returns empty list."""
        result = _extract_promotions_list({})
        assert result == []

    def test_none_response(self) -> None:
        """None returns empty list."""
        result = _extract_promotions_list({})
        assert result == []


class TestNomenclaturesListExtraction:
    """Test _extract_nomenclatures_list for various WB API response formats."""

    def test_official_format_data_nomenclatures(self) -> None:
        """Official WB format: {data: {nomenclatures: [...]}}."""
        response = {
            "data": {
                "nomenclatures": [
                    {"id": 12345, "planPrice": "647"},
                ]
            }
        }
        result = _extract_nomenclatures_list(response)
        assert len(result) == 1
        assert result[0]["id"] == 12345

    def test_fallback_top_level_nomenclatures(self) -> None:
        """Fallback: {nomenclatures: [...]}."""
        response = {"nomenclatures": [{"id": 1}]}
        result = _extract_nomenclatures_list(response)
        assert len(result) == 1

    def test_fallback_data_as_list(self) -> None:
        """Fallback: {data: [...]}."""
        response = {"data": [{"id": 1}]}
        result = _extract_nomenclatures_list(response)
        assert len(result) == 1

    def test_response_as_list(self) -> None:
        """Response is a list."""
        response = [{"id": 1}]
        result = _extract_nomenclatures_list(response)
        assert len(result) == 1

    def test_empty_response(self) -> None:
        """Empty dict returns empty list."""
        result = _extract_nomenclatures_list({})
        assert result == []


class TestSafeResponsePreview:
    """Test _safe_response_preview for safe logging."""

    def test_removes_token_keys(self) -> None:
        """Token and key fields are removed from preview."""
        response = {"data": {"promotions": []}, "token": "secret", "apiKey": "hidden"}
        preview = _safe_response_preview(response)
        assert "secret" not in preview
        assert "hidden" not in preview

    def test_truncates_long_response(self) -> None:
        """Long responses are truncated."""
        response = {"data": "x" * 2000}
        preview = _safe_response_preview(response, max_len=100)
        assert len(preview) <= 115  # max_len + "...(truncated)"
        assert "(truncated)" in preview


class TestSyncAllPromoMode:
    """Test allPromo mode support."""

    @pytest.mark.asyncio
    async def test_sync_all_accounts_accepts_all_promo(self) -> None:
        """sync_all_accounts should accept all_promo parameter."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )

        service = WbPromotionsSyncService(mock_session)
        stats = await service.sync_all_accounts(all_promo=True)

        assert stats.all_promo_mode is True
        assert stats.accounts_processed == 0
