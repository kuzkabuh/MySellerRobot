"""version: 1.0.0
description: Unit tests for client IP detection behind reverse proxies.
updated: 2026-06-07
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.utils.client_ip import get_client_ip


class _HeaderMap:
    def __init__(self, items: dict[str, str]) -> None:
        self._items = {k.lower(): v for k, v in items.items()}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._items.get(key.lower(), default)


def _make_request(
    *,
    x_forwarded_for: str | None = None,
    x_real_ip: str | None = None,
    cf_connecting_ip: str | None = None,
    true_client_ip: str | None = None,
    forwarded: str | None = None,
    client_host: str | None = "172.18.0.1",
) -> MagicMock:
    headers_dict: dict[str, str] = {}
    if x_forwarded_for is not None:
        headers_dict["x-forwarded-for"] = x_forwarded_for
    if x_real_ip is not None:
        headers_dict["x-real-ip"] = x_real_ip
    if cf_connecting_ip is not None:
        headers_dict["cf-connecting-ip"] = cf_connecting_ip
    if true_client_ip is not None:
        headers_dict["true-client-ip"] = true_client_ip
    if forwarded is not None:
        headers_dict["forwarded"] = forwarded

    headers = _HeaderMap(headers_dict)
    request = MagicMock()
    request.headers = headers
    request.client = SimpleNamespace(host=client_host) if client_host else None
    return request


def test_uses_first_public_ip_from_xff() -> None:
    request = _make_request(
        x_forwarded_for="172.18.0.1, 10.0.0.5, 8.8.8.8",
        client_host="172.18.0.1",
    )
    assert get_client_ip(request) == "8.8.8.8"


def test_falls_back_to_x_real_ip_when_xff_has_no_public() -> None:
    request = _make_request(
        x_forwarded_for="172.18.0.1, 10.0.0.5",
        x_real_ip="1.1.1.1",
        client_host="172.18.0.1",
    )
    assert get_client_ip(request) == "1.1.1.1"


def test_uses_cf_connecting_ip_when_set() -> None:
    request = _make_request(
        cf_connecting_ip="104.16.0.1",
        client_host="172.18.0.1",
    )
    assert get_client_ip(request) == "104.16.0.1"


def test_returns_client_host_when_no_headers() -> None:
    request = _make_request(client_host="172.18.0.1")
    assert get_client_ip(request) == "172.18.0.1"


def test_returns_unknown_when_nothing_available() -> None:
    request = _make_request(client_host=None)
    assert get_client_ip(request) == "unknown"


def test_handles_rfc7239_forwarded() -> None:
    request = _make_request(
        forwarded="for=1.1.1.1; proto=https; by=203.0.113.1",
        client_host="172.18.0.1",
    )
    assert get_client_ip(request) == "1.1.1.1"


def test_ignores_malformed_ip_in_chain() -> None:
    request = _make_request(
        x_forwarded_for="not-an-ip, 10.0.0.1, 8.8.4.4",
        client_host="172.18.0.1",
    )
    assert get_client_ip(request) == "8.8.4.4"


def test_loopback_is_not_public() -> None:
    request = _make_request(
        x_forwarded_for="127.0.0.1, 10.0.0.1",
        client_host="172.18.0.1",
    )
    assert get_client_ip(request) == "172.18.0.1"


def test_ipv6_address_is_preserved() -> None:
    request = _make_request(
        x_forwarded_for="2001:4860:4860::8888, 10.0.0.1",
        client_host="172.18.0.1",
    )
    assert get_client_ip(request) == "2001:4860:4860::8888"


def test_ipv6_loopback_is_treated_as_private() -> None:
    request = _make_request(
        x_forwarded_for="::1, 10.0.0.1",
        client_host="172.18.0.1",
    )
    assert get_client_ip(request) == "172.18.0.1"


def test_documentation_range_is_skipped() -> None:
    request = _make_request(
        x_forwarded_for="203.0.113.42, 10.0.0.1, 1.1.1.1",
        client_host="172.18.0.1",
    )
    assert get_client_ip(request) == "1.1.1.1"
