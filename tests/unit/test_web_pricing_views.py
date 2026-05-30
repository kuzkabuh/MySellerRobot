"""Tests for web pricing views helper functions."""

from decimal import Decimal

from app.web.route_modules.pricing import (
    _badge,
    _confidence_tone,
    _dt,
    _money,
    _product_title,
    _safe_json,
    _status_label,
    _status_tone,
)


class TestBadgeHelper:
    def test_badge_with_string_label(self) -> None:
        result = _badge("Тест", "green")
        assert "Тест" in result
        assert "green" in result

    def test_badge_with_none_label(self) -> None:
        result = _badge(None, "gray")
        assert "—" in result
        assert "gray" in result

    def test_badge_escapes_html(self) -> None:
        result = _badge("<script>alert(1)</script>", "red")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


class TestMoneyHelper:
    def test_money_with_value(self) -> None:
        assert "100" in _money(Decimal("100"))
        assert "₽" in _money(Decimal("100"))

    def test_money_with_none(self) -> None:
        assert _money(None) == ""

    def test_money_with_zero(self) -> None:
        assert "0" in _money(Decimal("0"))


class TestDtHelper:
    def test_dt_with_none(self) -> None:
        assert _dt(None) == ""

    def test_dt_with_datetime(self) -> None:
        from datetime import datetime

        dt = datetime(2026, 5, 30, 12, 0)
        result = _dt(dt)
        assert "30.05.2026" in result


class TestSafeJson:
    def test_safe_json_with_none(self) -> None:
        result = _safe_json(None)
        assert result == "{}"

    def test_safe_json_with_dict(self) -> None:
        result = _safe_json({"category": "Одежда", "count": 42})
        assert "category" in result
        assert "Одежда" in result


class TestProductTitle:
    def test_product_title_with_none(self) -> None:
        result = _product_title(None)
        assert "Товар не найден" in result


class TestStatusLabel:
    def test_can_apply(self) -> None:
        assert _status_label("CAN_APPLY") == "Можно применить"

    def test_blocked_by_mrc(self) -> None:
        assert _status_label("BLOCKED_BY_MRC") == "Ниже МРЦ"

    def test_unknown_status(self) -> None:
        assert _status_label("UNKNOWN_STATUS") == "UNKNOWN_STATUS"


class TestStatusTone:
    def test_can_apply_is_green(self) -> None:
        assert _status_tone("CAN_APPLY") == "green"

    def test_blocked_is_red(self) -> None:
        assert _status_tone("BLOCKED_BY_MRC") == "red"

    def test_unknown_is_gray(self) -> None:
        assert _status_tone("UNKNOWN") == "gray"


class TestConfidenceTone:
    def test_high_is_green(self) -> None:
        assert _confidence_tone("high") == "green"

    def test_none_is_gray(self) -> None:
        assert _confidence_tone(None) == "gray"
