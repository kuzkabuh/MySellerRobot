"""version: 1.0.0
description: Централизованная Origin/Referer-защита web-форм MP Control.
updated: 2026-06-07
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

from app.core.config import Settings

_STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_CSRF_EXEMPT_PATH_PREFIXES = (
    "/web/login",
    "/web/webhooks/",
    "/web/frontend-error",
)


def requires_web_csrf_check(request: Request) -> bool:
    if request.method.upper() not in _STATE_CHANGING_METHODS:
        return False
    path = request.url.path
    if path != "/web" and not path.startswith("/web/"):
        return False
    return not any(path.startswith(prefix) for prefix in _CSRF_EXEMPT_PATH_PREFIXES)


def is_valid_web_origin(request: Request, settings: Settings) -> bool:
    origin = _origin_from_header(request.headers.get("origin"))
    if origin:
        return origin in settings.trusted_web_origins

    referer = _origin_from_header(request.headers.get("referer"))
    if referer:
        return referer in settings.trusted_web_origins

    return False


def _origin_from_header(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}".rstrip("/")
