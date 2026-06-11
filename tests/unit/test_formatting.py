"""version: 1.0.0
description: Unit tests for web cabinet formatting helpers.
updated: 2026-06-11
"""

from decimal import Decimal

from app.web.view_modules.formatting import _percent_optional


def test_percent_optional_none() -> None:
    assert _percent_optional(None) == "—"


def test_percent_optional_decimal() -> None:
    assert _percent_optional(Decimal("12.345")) == "12.3%"


def test_percent_optional_int() -> None:
    assert _percent_optional(12) == "12.0%"


def test_percent_optional_float() -> None:
    assert _percent_optional(12.345) == "12.3%"


def test_percent_optional_str() -> None:
    assert _percent_optional("12.345") == "12.3%"


def test_percent_optional_invalid_str() -> None:
    assert _percent_optional("abc") == "—"


def test_percent_optional_zero() -> None:
    assert _percent_optional(Decimal("0")) == "0.0%"


def test_percent_optional_negative() -> None:
    assert _percent_optional(Decimal("-5.5")) == "-5.5%"


def test_percent_optional_rounded() -> None:
    assert _percent_optional(Decimal("99.99")) == "100.0%"
