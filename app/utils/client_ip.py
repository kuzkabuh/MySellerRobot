"""version: 1.0.0
description: Resolves external client IP behind reverse proxies (Nginx, Traefik, Cloudflare).
updated: 2026-06-07
"""
from __future__ import annotations

import ipaddress
from collections.abc import Iterable

from fastapi import Request

_TRUSTED_PROXY_HEADERS: tuple[str, ...] = (
    "cf-connecting-ip",
    "x-real-ip",
    "x-forwarded-for",
    "forwarded",
    "true-client-ip",
)

_INTERNAL_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("100::/64"),
    ipaddress.ip_network("2001::/32"),
    ipaddress.ip_network("2001:db8::/32"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
)


def _is_internal(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return True
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return True
    if isinstance(parsed, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return any(parsed in network for network in _INTERNAL_NETWORKS)
    return True


def _is_public(value: str) -> bool:
    return not _is_internal(value)


def _normalize_chain(value: str) -> list[str]:
    parts: list[str] = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ";" in chunk and "=" in chunk:
            for pair in chunk.split(";"):
                key, _, rest = pair.partition("=")
                if key.strip().lower() == "for" and rest:
                    parts.append(rest.strip().strip('"'))
                    break
            else:
                parts.append(chunk)
        else:
            parts.append(chunk)
    return parts


def _first_public(candidates: Iterable[str]) -> str | None:
    for raw in candidates:
        if _is_public(raw):
            return raw
    return None


def get_client_ip(request: Request) -> str:
    """Return the best-effort external client IP for the given request.

    Header order:
    1. CF-Connecting-IP
    2. X-Real-IP
    3. X-Forwarded-For (first public IP in chain)
    4. RFC 7239 Forwarded
    5. True-Client-IP
    6. request.client.host (fallback)
    """
    for header in _TRUSTED_PROXY_HEADERS:
        raw_value = request.headers.get(header)
        if not raw_value:
            continue
        chain = _normalize_chain(raw_value)
        public = _first_public(chain) or _first_public([raw_value.strip()])
        if public:
            return public

    if request.client is not None:
        host = request.client.host
        if host and (not _is_public(host)) and host not in {"", "0.0.0.0"}:
            return host
        if host:
            return host

    return "unknown"
