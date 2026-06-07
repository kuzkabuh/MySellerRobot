"""version: 1.0.0
description: Helpers for stripping Telegram-flavored HTML for safe display in web UI.
updated: 2026-06-07
"""
from __future__ import annotations

import html
import re

_TAG_PATTERN = re.compile(r"<[^>]+>")
_ENTITY_PATTERN = re.compile(r"&(?!#?\w+;)")
_WHITESPACE_PATTERN = re.compile(r"[ \t]+")
_BREAK_PATTERN = re.compile(r"(?:\s*<br\s*/?>)+", re.IGNORECASE)


def strip_telegram_html(value: str | None, *, unescape_entities: bool = True) -> str:
    """Remove Telegram-style HTML tags and decode HTML entities.

    Used for displaying Telegram messages in the web cabinet where rendering
    of <b>, <code>, <pre>, <i>, etc. as raw markup is undesirable.
    """
    if not value:
        return ""

    text = value
    text = _BREAK_PATTERN.sub("\n", text)
    text = _TAG_PATTERN.sub("", text)
    text = _ENTITY_PATTERN.sub("&amp;", text)
    if unescape_entities:
        text = html.unescape(text)
    text = _WHITESPACE_PATTERN.sub(" ", text)
    return text.strip()


def html_to_lines(value: str | None, *, max_line_length: int = 120) -> list[str]:
    """Strip Telegram HTML and return a list of display-friendly lines.

    Long words are wrapped so they don't break the layout.
    """
    text = strip_telegram_html(value)
    if not text:
        return []

    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw_lines:
        return []

    out: list[str] = []
    for line in raw_lines:
        if len(line) <= max_line_length:
            out.append(line)
            continue
        for start in range(0, len(line), max_line_length):
            chunk = line[start : start + max_line_length]
            if chunk:
                out.append(chunk)
    return out
