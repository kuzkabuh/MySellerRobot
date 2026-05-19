"""Tests for production error fixes from log analysis."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRubFormatter:
    """Test _rub() handles None and edge cases safely."""

    def test_rub_none_returns_na(self):
        from app.web.routes import _rub

        assert _rub(None) == "н/д"

    def test_rub_zero(self):
        from app.web.routes import _rub

        assert _rub(Decimal("0")) == "0 ₽"

    def test_rub_positive_decimal(self):
        from app.web.routes import _rub

        result = _rub(Decimal("12345.67"))
        assert "12 346" in result
        assert "₽" in result

    def test_rub_negative_decimal(self):
        from app.web.routes import _rub

        result = _rub(Decimal("-500"))
        assert "-500" in result
        assert "₽" in result

    def test_rub_int_value(self):
        from app.web.routes import _rub

        result = _rub(1000)
        assert "1 000" in result

    def test_rub_float_value(self):
        from app.web.routes import _rub

        result = _rub(999.99)
        assert "₽" in result

    def test_rub_string_numeric(self):
        from app.web.routes import _rub

        result = _rub("1234")
        assert "1 234" in result

    def test_rub_invalid_string_returns_na(self):
        from app.web.routes import _rub

        assert _rub("not_a_number") == "н/д"

    def test_rub_optional_none(self):
        from app.web.routes import _rub_optional

        assert _rub_optional(None) == "н/д"

    def test_rub_optional_value(self):
        from app.web.routes import _rub_optional

        result = _rub_optional(Decimal("100"))
        assert "100" in result


class TestRequestLogging:
    """Test request logging redacts sensitive query values."""

    def test_redact_query_hides_web_login_token(self):
        from app.api.main import _redact_query

        redacted = _redact_query("token=raw-login-token&period=7d")

        assert "raw-login-token" not in redacted
        assert "token=%2A%2A%2AREDACTED%2A%2A%2A" in redacted
        assert "period=7d" in redacted


class TestParseSaleModel:
    """Test parse_sale_model() handles non-string values safely."""

    def test_parse_sale_model_none(self):
        from app.services.web_dashboard_service import parse_sale_model

        assert parse_sale_model(None) is None

    def test_parse_sale_model_all(self):
        from app.services.web_dashboard_service import parse_sale_model

        assert parse_sale_model("all") is None

    def test_parse_sale_model_fbo(self):
        from app.models.enums import SaleModel
        from app.services.web_dashboard_service import parse_sale_model

        assert parse_sale_model("FBO") == SaleModel.FBO

    def test_parse_sale_model_fbs(self):
        from app.models.enums import SaleModel
        from app.services.web_dashboard_service import parse_sale_model

        assert parse_sale_model("FBS") == SaleModel.FBS

    def test_parse_sale_model_invalid(self):
        from app.services.web_dashboard_service import parse_sale_model

        assert parse_sale_model("INVALID") is None

    def test_parse_sale_model_empty_string(self):
        from app.services.web_dashboard_service import parse_sale_model

        assert parse_sale_model("") is None

    def test_parse_sale_model_non_string_object(self):
        from app.services.web_dashboard_service import parse_sale_model

        mock_query = MagicMock()
        mock_query.upper = MagicMock(side_effect=AttributeError)
        result = parse_sale_model(mock_query)
        assert result is None


class TestParseMarketplace:
    """Test parse_marketplace() handles non-string values safely."""

    def test_parse_marketplace_none(self):
        from app.services.web_dashboard_service import parse_marketplace

        assert parse_marketplace(None) is None

    def test_parse_marketplace_all(self):
        from app.services.web_dashboard_service import parse_marketplace

        assert parse_marketplace("all") is None

    def test_parse_marketplace_wb(self):
        from app.models.enums import Marketplace
        from app.services.web_dashboard_service import parse_marketplace

        assert parse_marketplace("WB") == Marketplace.WB

    def test_parse_marketplace_ozon(self):
        from app.models.enums import Marketplace
        from app.services.web_dashboard_service import parse_marketplace

        assert parse_marketplace("OZON") == Marketplace.OZON

    def test_parse_marketplace_invalid(self):
        from app.services.web_dashboard_service import parse_marketplace

        assert parse_marketplace("INVALID") is None

    def test_parse_marketplace_non_string_object(self):
        from app.services.web_dashboard_service import parse_marketplace

        mock_query = MagicMock()
        result = parse_marketplace(mock_query)
        assert result is None


class TestSafeEditText:
    """Test _safe_edit_text helper falls back to answer on media messages."""

    @pytest.mark.asyncio
    async def test_safe_edit_text_success(self):
        from app.bot.handlers.common import _safe_edit_text

        message = AsyncMock()
        message.edit_text = AsyncMock()
        await _safe_edit_text(message, "test text")
        message.edit_text.assert_called_once_with("test text")

    @pytest.mark.asyncio
    async def test_safe_edit_text_fallback_on_no_text(self):
        from app.bot.handlers.common import _safe_edit_text

        message = AsyncMock()
        message.edit_text = AsyncMock(
            side_effect=Exception("there is no text in the message to edit")
        )
        message.answer = AsyncMock()
        await _safe_edit_text(message, "test text")
        message.answer.assert_called_once_with("test text")

    @pytest.mark.asyncio
    async def test_safe_edit_text_raises_other_errors(self):
        from app.bot.handlers.common import _safe_edit_text

        message = AsyncMock()
        message.edit_text = AsyncMock(side_effect=Exception("some other error"))
        message.answer = AsyncMock()
        with pytest.raises(Exception, match="some other error"):
            await _safe_edit_text(message, "test text")


class TestYookassaCredentialsCheck:
    """Test YooKassa credential validation."""

    def test_payment_service_checks_empty_credentials(self):
        from app.services.payment_service import PaymentService

        mock_session = AsyncMock()
        with patch("app.services.payment_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.yookassa_shop_id = ""
            settings.yookassa_secret_key = MagicMock()
            settings.yookassa_secret_key.get_secret_value.return_value = ""
            mock_settings.return_value = settings

            service = PaymentService(mock_session)
            assert service._credentials_valid is False

    def test_payment_service_valid_credentials(self):
        from app.services.payment_service import PaymentService

        mock_session = AsyncMock()
        with patch("app.services.payment_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key = MagicMock()
            settings.yookassa_secret_key.get_secret_value.return_value = "test_key"
            mock_settings.return_value = settings

            service = PaymentService(mock_session)
            assert service._credentials_valid is True

    def test_check_credentials_raises_when_invalid(self):
        from app.services.payment_service import PaymentService

        mock_session = AsyncMock()
        with patch("app.services.payment_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.yookassa_shop_id = ""
            settings.yookassa_secret_key = MagicMock()
            settings.yookassa_secret_key.get_secret_value.return_value = ""
            mock_settings.return_value = settings

            service = PaymentService(mock_session)
            with pytest.raises(RuntimeError, match="Платёжная система не настроена"):
                service._check_credentials()


class TestSellerProfileWeb:
    """Test _seller_profile_web handles None balance fields."""

    def test_seller_profile_web_with_none_balance(self):
        from app.web.routes import _seller_profile_web

        account = MagicMock()
        account.seller_name = "Test Seller"
        account.seller_legal_name = "Test Legal"
        account.seller_info_payload = {}

        result = _seller_profile_web(account, None)
        assert "Баланс не загружен" in result

    def test_seller_profile_web_with_none_for_withdraw(self):
        from app.web.routes import _seller_profile_web

        account = MagicMock()
        account.seller_name = "Test Seller"
        account.seller_legal_name = "Test Legal"
        account.seller_info_payload = {}

        balance = MagicMock()
        balance.status = "OK"
        balance.current = Decimal("1000")
        balance.for_withdraw = None

        result = _seller_profile_web(account, balance)
        assert "н/д" in result
        assert "1 000" in result

    def test_seller_profile_web_with_valid_balance(self):
        from app.web.routes import _seller_profile_web

        account = MagicMock()
        account.seller_name = "Test Seller"
        account.seller_legal_name = "Test Legal"
        account.seller_info_payload = {"tin": "1234567890"}

        balance = MagicMock()
        balance.status = "OK"
        balance.current = Decimal("5000")
        balance.for_withdraw = Decimal("3000")

        result = _seller_profile_web(account, balance)
        assert "5 000" in result
        assert "3 000" in result
        assert "1234567890" in result


class TestYookassaIdempotenceKey:
    """Test idempotence key is valid UUID v4 and within 64-char limit."""

    def test_idempotence_key_is_uuid_v4_format(self):
        import uuid

        from app.services.payment_service import PaymentService

        mock_session = AsyncMock()
        with patch("app.services.payment_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            service = PaymentService(mock_session)
            key = service._generate_idempotence_key(
                user_id=100, tier_code="basic", period="monthly"
            )
            uuid.UUID(key, version=4)

    def test_idempotence_key_within_64_chars(self):
        from app.services.payment_service import PaymentService

        mock_session = AsyncMock()
        with patch("app.services.payment_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            service = PaymentService(mock_session)
            key = service._generate_idempotence_key(
                user_id=100, tier_code="basic", period="monthly"
            )
            assert len(key) <= 64

    def test_idempotence_key_unique_per_call(self):
        from app.services.payment_service import PaymentService

        mock_session = AsyncMock()
        with patch("app.services.payment_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            service = PaymentService(mock_session)
            key1 = service._generate_idempotence_key(
                user_id=100, tier_code="basic", period="monthly"
            )
            key2 = service._generate_idempotence_key(
                user_id=100, tier_code="basic", period="monthly"
            )
            assert key1 != key2


class TestExtractReportRows:
    """Test _extract_report_rows handles all payload formats safely."""

    def test_payload_is_list_of_dicts(self):
        from app.services.wb_report_service import _extract_report_rows

        payload = [
            {"reportId": "1", "dateFrom": "2026-05-01"},
            {"reportId": "2", "dateFrom": "2026-05-02"},
        ]
        result = _extract_report_rows(payload)
        assert len(result) == 2
        assert result[0]["reportId"] == "1"

    def test_payload_is_list_with_non_dict_items(self):
        from app.services.wb_report_service import _extract_report_rows

        payload = [{"reportId": "1"}, "string_item", 42, None]
        result = _extract_report_rows(payload)
        assert len(result) == 1
        assert result[0]["reportId"] == "1"

    def test_payload_is_empty_list(self):
        from app.services.wb_report_service import _extract_report_rows

        result = _extract_report_rows([])
        assert result == []

    def test_payload_is_none(self):
        from app.services.wb_report_service import _extract_report_rows

        result = _extract_report_rows(None)
        assert result == []

    def test_payload_is_dict_with_reports_key(self):
        from app.services.wb_report_service import _extract_report_rows

        payload = {
            "reports": [
                {"reportId": "1"},
                {"reportId": "2"},
            ]
        }
        result = _extract_report_rows(payload)
        assert len(result) == 2

    def test_payload_is_dict_with_data_key(self):
        from app.services.wb_report_service import _extract_report_rows

        payload = {
            "data": [
                {"id": "a"},
                {"id": "b"},
            ]
        }
        result = _extract_report_rows(payload)
        assert len(result) == 2

    def test_payload_is_dict_with_result_key(self):
        from app.services.wb_report_service import _extract_report_rows

        payload = {
            "result": {
                "reports": [{"reportId": "x"}]
            }
        }
        result = _extract_report_rows(payload)
        assert len(result) == 1
        assert result[0]["reportId"] == "x"

    def test_payload_is_dict_with_result_items(self):
        from app.services.wb_report_service import _extract_report_rows

        payload = {
            "result": {
                "items": [{"id": "1"}, {"id": "2"}]
            }
        }
        result = _extract_report_rows(payload)
        assert len(result) == 2

    def test_payload_is_empty_dict(self):
        from app.services.wb_report_service import _extract_report_rows

        result = _extract_report_rows({})
        assert result == []

    def test_payload_is_unexpected_type_logs_warning(self):
        from app.services.wb_report_service import _extract_report_rows

        result = _extract_report_rows("unexpected_string")
        assert result == []

    def test_payload_is_int_returns_empty(self):
        from app.services.wb_report_service import _extract_report_rows

        result = _extract_report_rows(42)
        assert result == []
