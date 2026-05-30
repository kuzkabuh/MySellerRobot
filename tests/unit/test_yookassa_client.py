"""Tests for YooKassa client data extraction."""

from unittest.mock import MagicMock

from app.integrations.yookassa import _payment_to_dict


class TestPaymentToDict:
    """Test _payment_to_dict correctly extracts data from SDK Payment object."""

    def test_extract_from_data_attribute(self):
        payment = MagicMock()
        payment._data = {
            "id": "test-id-123",
            "status": "pending",
            "amount": {"value": "490", "currency": "RUB"},
            "confirmation": {"confirmation_url": "https://pay.yookassa.ru/abc"},
            "description": "Test payment",
            "metadata": {"user_id": "1"},
        }
        result = _payment_to_dict(payment)
        assert result["id"] == "test-id-123"
        assert result["status"] == "pending"
        assert result["amount"]["value"] == "490"
        assert result["confirmation"]["confirmation_url"] == "https://pay.yookassa.ru/abc"

    def test_extract_from_direct_attributes(self):
        confirmation = MagicMock()
        confirmation.confirmation_url = "https://pay.yookassa.ru/xyz"
        amount = MagicMock()
        amount.value = "990"
        amount.currency = "RUB"

        payment = MagicMock()
        payment._data = {}
        payment.id = "attr-id-456"
        payment.status = "succeeded"
        payment.confirmation = confirmation
        payment.amount = amount
        payment.description = "Attr-based payment"
        payment.metadata = {"key": "value"}

        result = _payment_to_dict(payment)
        assert result["id"] == "attr-id-456"
        assert result["status"] == "succeeded"
        assert result["amount"]["value"] == "990"
        assert result["confirmation"]["confirmation_url"] == "https://pay.yookassa.ru/xyz"

    def test_extract_from_dict_confirmation(self):
        payment = MagicMock()
        payment._data = {}
        payment.id = "dict-conf-id"
        payment.status = "pending"
        payment.confirmation = {"confirmation_url": "https://dict.url"}
        payment.amount = {"value": "100", "currency": "RUB"}
        payment.description = ""
        payment.metadata = {}

        result = _payment_to_dict(payment)
        assert result["confirmation"]["confirmation_url"] == "https://dict.url"

    def test_empty_data_returns_defaults(self):
        payment = MagicMock()
        payment._data = {}
        payment.id = ""
        payment.status = ""
        payment.confirmation = None
        payment.amount = None
        payment.description = ""
        payment.metadata = None

        result = _payment_to_dict(payment)
        assert result["id"] == ""
        assert result["status"] == ""
        assert result["confirmation"]["confirmation_url"] == ""
        assert result["amount"]["value"] == "0"

    def test_no_keyerror_on_access(self):
        """Ensure accessing result['id'] never raises KeyError."""
        payment = MagicMock()
        payment._data = {"id": "safe-id", "status": "pending"}
        result = _payment_to_dict(payment)
        _ = result["id"]
        _ = result["status"]
        _ = result["amount"]
        _ = result["confirmation"]
        _ = result["description"]
        _ = result["metadata"]
