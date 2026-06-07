"""version: 1.0.0
description: Тесты Origin/Referer-защиты web-форм MP Control.
updated: 2026-06-07
"""

from types import SimpleNamespace

from app.core.config import Settings
from app.web.csrf import is_valid_web_origin, requires_web_csrf_check


class _Headers:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = {key.lower(): value for key, value in (values or {}).items()}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.values.get(key.lower(), default)


def _request(
    *,
    method: str = "POST",
    path: str = "/web/settings/profile",
    headers: dict[str, str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path), headers=_Headers(headers))


def test_post_web_form_requires_origin_check() -> None:
    assert requires_web_csrf_check(_request()) is True


def test_get_web_page_does_not_require_origin_check() -> None:
    assert requires_web_csrf_check(_request(method="GET")) is False


def test_api_webhook_route_is_not_under_web_csrf() -> None:
    assert requires_web_csrf_check(_request(path="/webhooks/yookassa")) is False


def test_webhook_compat_route_is_exempt_from_web_csrf() -> None:
    assert requires_web_csrf_check(_request(path="/web/webhooks/yookassa")) is False


def test_frontend_error_route_is_exempt_from_web_csrf() -> None:
    assert requires_web_csrf_check(_request(path="/web/frontend-error")) is False


def test_missing_origin_is_rejected() -> None:
    request = _request(headers={})
    assert is_valid_web_origin(request, Settings(web_base_url="http://localhost:8000")) is False


def test_trusted_origin_is_accepted() -> None:
    request = _request(headers={"Origin": "https://app.mpcontrol.online"})
    assert is_valid_web_origin(request, Settings(web_base_url="http://localhost:8000")) is True


def test_untrusted_origin_is_rejected() -> None:
    request = _request(headers={"Origin": "https://evil.example"})
    assert is_valid_web_origin(request, Settings(web_base_url="http://localhost:8000")) is False


def test_local_development_origin_is_accepted() -> None:
    request = _request(headers={"Origin": "http://127.0.0.1:8000"})
    assert is_valid_web_origin(request, Settings(web_base_url="http://localhost:8000")) is True
