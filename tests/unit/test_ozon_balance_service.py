"""Unit tests for Ozon balance synchronization via POST /v1/finance/balance."""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.models.domain import AccountBalanceSnapshot, MarketplaceAccount
from app.models.enums import Marketplace
from app.services.ozon.finance.ozon_balance_service import (
    OzonBalanceService,
    _decimal_or_none,
    _error_snapshot,
    _safe_nested_value,
    _sum_payments,
)


def _make_ozon_account() -> MarketplaceAccount:
    return MarketplaceAccount(
        id=1,
        user_id=10,
        marketplace=Marketplace.OZON,
        name="Ozon Test",
        encrypted_api_key="encrypted-key",
        encrypted_client_id="encrypted-client-id",
    )


class TestOzonBalanceServiceParseResponse:
    def test_parses_closing_balance_as_current(self) -> None:
        payload = {
            "result": {
                "closing_balance": {"value": "12345.67", "currency_code": "RUB"},
                "opening_balance": {"value": "10000.00", "currency_code": "RUB"},
                "accrued": {"value": "3000.00", "currency_code": "RUB"},
                "payments": [
                    {"date": "2026-05-10", "amount": {"value": "1500.00", "currency_code": "RUB"}},
                    {"date": "2026-05-15", "amount": {"value": "2000.00", "currency_code": "RUB"}},
                ],
            }
        }
        account = _make_ozon_account()
        now = datetime.now(tz=UTC)
        date_from = date(2026, 4, 21)
        date_to = date(2026, 5, 20)

        snapshot = OzonBalanceService._parse_balance_response(
            account, payload, date_from, date_to, now
        )

        assert snapshot.current == Decimal("12345.67")
        assert snapshot.currency == "RUB"
        assert snapshot.status == "OK"
        assert snapshot.opening_balance == Decimal("10000.00")
        assert snapshot.accrued == Decimal("3000.00")
        assert snapshot.payments_total == Decimal("3500.00")
        assert snapshot.period_from == date_from
        assert snapshot.period_to == date_to
        assert snapshot.for_withdraw is None

    def test_uses_closing_balance_not_accrued(self) -> None:
        payload = {
            "result": {
                "closing_balance": {"value": "5000.00", "currency_code": "RUB"},
                "accrued": {"value": "99999.99", "currency_code": "RUB"},
            }
        }
        account = _make_ozon_account()
        now = datetime.now(tz=UTC)

        snapshot = OzonBalanceService._parse_balance_response(
            account, payload, date(2026, 4, 21), date(2026, 5, 20), now
        )

        assert snapshot.current == Decimal("5000.00")
        assert snapshot.accrued == Decimal("99999.99")

    def test_saves_currency_code(self) -> None:
        payload = {
            "result": {
                "closing_balance": {"value": "100.00", "currency_code": "USD"},
            }
        }
        account = _make_ozon_account()
        now = datetime.now(tz=UTC)

        snapshot = OzonBalanceService._parse_balance_response(
            account, payload, date(2026, 4, 21), date(2026, 5, 20), now
        )

        assert snapshot.currency == "USD"

    def test_handles_empty_payments(self) -> None:
        payload = {
            "result": {
                "closing_balance": {"value": "100.00", "currency_code": "RUB"},
                "payments": [],
            }
        }
        account = _make_ozon_account()
        now = datetime.now(tz=UTC)

        snapshot = OzonBalanceService._parse_balance_response(
            account, payload, date(2026, 4, 21), date(2026, 5, 20), now
        )

        assert snapshot.payments_total is None

    def test_handles_missing_services(self) -> None:
        payload = {
            "result": {
                "closing_balance": {"value": "100.00", "currency_code": "RUB"},
            }
        }
        account = _make_ozon_account()
        now = datetime.now(tz=UTC)

        snapshot = OzonBalanceService._parse_balance_response(
            account, payload, date(2026, 4, 21), date(2026, 5, 20), now
        )

        assert snapshot.current == Decimal("100.00")
        assert snapshot.opening_balance is None
        assert snapshot.accrued is None
        assert snapshot.payments_total is None

    def test_missing_closing_balance_returns_error(self) -> None:
        payload = {
            "result": {
                "accrued": {"value": "100.00", "currency_code": "RUB"},
            }
        }
        account = _make_ozon_account()
        now = datetime.now(tz=UTC)

        snapshot = OzonBalanceService._parse_balance_response(
            account, payload, date(2026, 4, 21), date(2026, 5, 20), now
        )

        assert snapshot.status == "PARSE_ERROR"
        assert snapshot.current is None
        assert "ozon_balance_invalid_response" in (snapshot.error_message or "")

    def test_result_null_returns_error(self) -> None:
        payload = {"result": None}
        account = _make_ozon_account()
        now = datetime.now(tz=UTC)

        snapshot = OzonBalanceService._parse_balance_response(
            account, payload, date(2026, 4, 21), date(2026, 5, 20), now
        )

        assert snapshot.status == "PARSE_ERROR"
        assert snapshot.current is None
        assert "ozon_balance_invalid_response" in (snapshot.error_message or "")

    def test_result_not_dict_returns_error(self) -> None:
        payload = {"result": "not a dict"}
        account = _make_ozon_account()
        now = datetime.now(tz=UTC)

        snapshot = OzonBalanceService._parse_balance_response(
            account, payload, date(2026, 4, 21), date(2026, 5, 20), now
        )

        assert snapshot.status == "PARSE_ERROR"
        assert "ozon_balance_invalid_response" in (snapshot.error_message or "")

    def test_missing_result_key_returns_error(self) -> None:
        payload = {"something_else": {}}
        account = _make_ozon_account()
        now = datetime.now(tz=UTC)

        snapshot = OzonBalanceService._parse_balance_response(
            account, payload, date(2026, 4, 21), date(2026, 5, 20), now
        )

        assert snapshot.status == "PARSE_ERROR"
        assert "ozon_balance_invalid_response" in (snapshot.error_message or "")

    def test_malformed_payload_returns_error(self) -> None:
        payload = {"result": []}
        account = _make_ozon_account()
        now = datetime.now(tz=UTC)

        snapshot = OzonBalanceService._parse_balance_response(
            account, payload, date(2026, 4, 21), date(2026, 5, 20), now
        )

        assert snapshot.status == "PARSE_ERROR"
        assert "ozon_balance_invalid_response" in (snapshot.error_message or "")

    def test_non_dict_payload_returns_error(self) -> None:
        account = _make_ozon_account()
        now = datetime.now(tz=UTC)

        snapshot = OzonBalanceService._parse_balance_response(
            account, "not a dict", date(2026, 4, 21), date(2026, 5, 20), now
        )

        assert snapshot.status == "PARSE_ERROR"
        assert "ozon_balance_invalid_response" in (snapshot.error_message or "")


class TestHelperFunctions:
    def test_safe_nested_value(self) -> None:
        data = {"a": {"b": {"c": 42}}}
        assert _safe_nested_value(data, "a", "b", "c") == 42
        assert _safe_nested_value(data, "a", "x") is None
        assert _safe_nested_value(data, "missing") is None

    def test_decimal_or_none(self) -> None:
        assert _decimal_or_none("123.45") == Decimal("123.45")
        assert _decimal_or_none(123.45) == Decimal("123.45")
        assert _decimal_or_none(None) is None
        assert _decimal_or_none("bad") is None
        assert _decimal_or_none("") is None

    def test_sum_payments(self) -> None:
        payments = [
            {"amount": {"value": "100.00"}},
            {"amount": {"value": "200.50"}},
        ]
        assert _sum_payments(payments) == Decimal("300.50")

    def test_sum_payments_empty_list(self) -> None:
        assert _sum_payments([]) is None

    def test_sum_payments_non_list(self) -> None:
        assert _sum_payments(None) is None
        assert _sum_payments("not a list") is None

    def test_sum_payments_malformed_entries(self) -> None:
        payments = [
            {"amount": {"value": "100.00"}},
            "not a dict",
            {"amount": {"value": "bad"}},
            {"amount": {"value": "50.00"}},
        ]
        assert _sum_payments(payments) == Decimal("150.00")

    def test_error_snapshot(self) -> None:
        account = _make_ozon_account()
        now = datetime.now(tz=UTC)
        date_from = date(2026, 4, 21)
        date_to = date(2026, 5, 20)

        snapshot = _error_snapshot(account, date_from, date_to, now, "test error")

        assert snapshot.status == "PARSE_ERROR"
        assert snapshot.current is None
        assert snapshot.error_message == "test error"
        assert snapshot.marketplace == Marketplace.OZON
        assert snapshot.period_from == date_from
        assert snapshot.period_to == date_to


class TestOzonBalanceSnapshotModel:
    def test_snapshot_has_new_fields(self) -> None:
        snapshot = AccountBalanceSnapshot(
            user_id=1,
            marketplace_account_id=1,
            marketplace=Marketplace.OZON,
            currency="RUB",
            current=Decimal("100.00"),
            opening_balance=Decimal("50.00"),
            accrued=Decimal("60.00"),
            payments_total=Decimal("10.00"),
            period_from=date(2026, 4, 21),
            period_to=date(2026, 5, 20),
            status="OK",
            fetched_at=datetime.now(tz=UTC),
        )

        assert snapshot.current == Decimal("100.00")
        assert snapshot.opening_balance == Decimal("50.00")
        assert snapshot.accrued == Decimal("60.00")
        assert snapshot.payments_total == Decimal("10.00")
        assert snapshot.period_from == date(2026, 4, 21)
        assert snapshot.period_to == date(2026, 5, 20)
