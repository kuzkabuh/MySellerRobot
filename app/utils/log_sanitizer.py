"""version: 1.0.0
description: Log sanitizer for sensitive HTTP headers and cookie values.
updated: 2026-05-31
"""

SENSITIVE_HEADERS = frozenset(
    {
        "cookie",
        "authorization",
        "x-api-key",
        "proxy-authorization",
        "set-cookie",
    }
)

SENSITIVE_COOKIE_KEYS = frozenset(
    {
        "__Secure-access-token",
        "__Secure-refresh-token",
        "__Secure-token",
        "__Secure-sid",
        "session_id",
    }
)


def sanitize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    result: dict[str, str] = {}
    for key, value in headers.items():
        lower_key = key.lower()
        if lower_key in SENSITIVE_HEADERS:
            if lower_key == "cookie":
                result[key] = _sanitize_cookie_value(value)
            else:
                result[key] = "***REDACTED***"
        else:
            result[key] = value
    return result


def _sanitize_cookie_value(cookie_string: str) -> str:
    if not cookie_string:
        return ""
    parts = cookie_string.split(";")
    sanitized: list[str] = []
    for part in parts:
        part = part.strip()
        if "=" in part:
            name, _ = part.split("=", 1)
            name = name.strip()
            if name in SENSITIVE_COOKIE_KEYS:
                sanitized.append(f"{name}=***REDACTED***")
            else:
                sanitized.append(f"{name}=***")
        else:
            sanitized.append("***")
    return f"cookies_present=True; cookies_count={len(parts)}; " + "; ".join(sanitized[:3]) + "..."


def sanitize_log_extra(extra: dict | None) -> dict:
    if not extra:
        return {}
    result = dict(extra)
    for key in ("headers", "request_headers", "response_headers"):
        if key in result and isinstance(result[key], dict):
            result[key] = sanitize_headers(result[key])
    for key in ("cookie", "cookies", "authorization", "token", "api_key"):
        if key in result:
            result[key] = "***REDACTED***"
    return result
