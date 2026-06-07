"""version: 1.0.0
description: Unit tests for strip_telegram_html helper.
updated: 2026-06-07
"""
from __future__ import annotations

from app.utils.telegram_html import html_to_lines, strip_telegram_html


def test_strips_basic_telegram_tags() -> None:
    text = "<b>Заголовок</b>: <code>code</code> и <i>italic</i>"
    assert strip_telegram_html(text) == "Заголовок: code и italic"


def test_unescapes_html_entities() -> None:
    text = "Цена &quot;100&quot; &amp; доставка &lt; 5 дней"
    assert strip_telegram_html(text) == 'Цена "100" & доставка < 5 дней'


def test_replaces_br_with_newline() -> None:
    text = "Первая строка<br>Вторая строка<br/>Третья"
    result = strip_telegram_html(text)
    assert result == "Первая строка\nВторая строка\nТретья"


def test_returns_empty_for_none() -> None:
    assert strip_telegram_html(None) == ""


def test_returns_empty_for_empty_string() -> None:
    assert strip_telegram_html("") == ""


def test_preserves_preformatted_code() -> None:
    text = "<pre>if x:\n    pass</pre>"
    result = strip_telegram_html(text)
    assert "if x" in result
    assert "pass" in result
    assert "<" not in result
    assert ">" not in result


def test_keeps_ampersand_literal_after_unquoting() -> None:
    text = "WB & Ozon"
    result = strip_telegram_html(text)
    assert "WB & Ozon" in result


def test_html_to_lines_splits_long_text() -> None:
    text = "<b>" + ("очень " * 50) + "</b>"
    lines = html_to_lines(text, max_line_length=20)
    assert all(len(line) <= 20 for line in lines)
    assert "очень" in " ".join(lines)


def test_html_to_lines_splits_newlines() -> None:
    text = "<b>Первый</b>\n<i>Второй</i>\nТретий"
    lines = html_to_lines(text)
    assert lines == ["Первый", "Второй", "Третий"]


def test_strips_self_closing_tags() -> None:
    text = "Текст с <br/> переносом и <img src='x'/> картинкой"
    result = strip_telegram_html(text)
    assert "<" not in result
    assert "Текст с" in result
    assert "переносом" in result
