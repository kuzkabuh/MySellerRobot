"""Tests for request logging sanitization: query redaction and Referer masking."""

from urllib.parse import unquote

from app.api.main import _redact_query, _sanitize_headers, _sanitize_url


def _decoded(value: str) -> str:
    """URL-decode a string for easier test assertions."""
    return unquote(value)


class TestRedactQuery:
    """Test query string parameter redaction."""

    def test_redacts_token(self) -> None:
        result = _decoded(_redact_query("token=abc123&foo=bar"))
        assert "token=***REDACTED***" in result
        assert "foo=bar" in result
        assert "abc123" not in result

    def test_redacts_api_key(self) -> None:
        result = _decoded(_redact_query("api_key=secret123"))
        assert "api_key=***REDACTED***" in result
        assert "secret123" not in result

    def test_redacts_secret(self) -> None:
        result = _decoded(_redact_query("secret=mysecret"))
        assert "secret=***REDACTED***" in result
        assert "mysecret" not in result

    def test_redacts_password(self) -> None:
        result = _decoded(_redact_query("password=pass123"))
        assert "password=***REDACTED***" in result
        assert "pass123" not in result

    def test_redacts_client_id(self) -> None:
        result = _decoded(_redact_query("client_id=ci-123"))
        assert "client_id=***REDACTED***" in result
        assert "ci-123" not in result

    def test_redacts_case_insensitive(self) -> None:
        result = _decoded(_redact_query("TOKEN=abc&Api_Key=xyz"))
        assert "TOKEN=***REDACTED***" in result
        assert "Api_Key=***REDACTED***" in result
        assert "abc" not in result
        assert "xyz" not in result

    def test_does_not_redact_safe_params(self) -> None:
        result = _decoded(_redact_query("page=1&sort=date&direction=desc"))
        assert "page=1" in result
        assert "sort=date" in result
        assert "direction=desc" in result

    def test_empty_query(self) -> None:
        assert _redact_query("") == ""

    def test_no_query_params(self) -> None:
        # parse_qsl treats bare strings as key=empty_value
        result = _decoded(_redact_query("not_a_query_string_without_equals"))
        assert "not_a_query_string_without_equals" in result

    def test_multiple_sensitive_params(self) -> None:
        result = _decoded(_redact_query("token=abc&password=pass&foo=bar&secret=s"))
        assert "token=***REDACTED***" in result
        assert "password=***REDACTED***" in result
        assert "secret=***REDACTED***" in result
        assert "foo=bar" in result
        assert "token=abc" not in result
        assert "password=pass" not in result

    def test_blank_sensitive_value(self) -> None:
        result = _decoded(_redact_query("token="))
        assert "token=***REDACTED***" in result


class TestSanitizeUrl:
    """Test URL sanitization for Referer and similar headers."""

    def test_redacts_token_in_referer_url(self) -> None:
        url = "https://app.mpcontrol.online/web/login?token=REAL_TOKEN"
        result = _decoded(_sanitize_url(url))
        assert "token=***REDACTED***" in result
        assert "REAL_TOKEN" not in result

    def test_redacts_multiple_params_in_url(self) -> None:
        url = "https://example.com/page?token=abc&foo=bar&password=secret123"
        result = _decoded(_sanitize_url(url))
        assert "token=***REDACTED***" in result
        assert "foo=bar" in result
        assert "password=***REDACTED***" in result
        assert "token=abc" not in result
        assert "secret123" not in result

    def test_url_without_query_unchanged(self) -> None:
        url = "https://app.mpcontrol.online/web/"
        assert _sanitize_url(url) == url

    def test_empty_url(self) -> None:
        assert _sanitize_url("") == ""

    def test_url_with_safe_params_unchanged(self) -> None:
        url = "https://app.mpcontrol.online/web/orders?page=1&sort=date"
        assert _sanitize_url(url) == url

    def test_malformed_url_returns_as_is(self) -> None:
        result = _sanitize_url("not-a-valid-url-at-all")
        assert isinstance(result, str)

    def test_preserves_url_path_and_fragment(self) -> None:
        url = "https://app.mpcontrol.online/web/plan-fact?token=abc#section"
        result = _decoded(_sanitize_url(url))
        assert "token=***REDACTED***" in result
        assert "#section" in result
        assert "abc" not in result


class TestSanitizeHeaders:
    """Test full header sanitization in request logging."""

    def test_redacts_authorization(self) -> None:
        headers = {"authorization": "Bearer secret-token"}
        result = _sanitize_headers(headers)
        assert result["authorization"] == "***REDACTED***"

    def test_redacts_cookie(self) -> None:
        headers = {"cookie": "session=abc123"}
        result = _sanitize_headers(headers)
        assert result["cookie"] == "***REDACTED***"

    def test_redacts_x_api_key(self) -> None:
        headers = {"x-api-key": "my-api-key"}
        result = _sanitize_headers(headers)
        assert result["x-api-key"] == "***REDACTED***"

    def test_redacts_x_admin_secret(self) -> None:
        headers = {"x-admin-secret": "admin-secret"}
        result = _sanitize_headers(headers)
        assert result["x-admin-secret"] == "***REDACTED***"

    def test_sanitizes_referer_with_token(self) -> None:
        headers = {"referer": "https://app.mpcontrol.online/web/login?token=REAL_TOKEN"}
        result = _decoded(_sanitize_headers(headers)["referer"])
        assert "token=***REDACTED***" in result
        assert "REAL_TOKEN" not in result

    def test_sanitizes_referrer_header(self) -> None:
        headers = {"referrer": "https://example.com/page?token=secret"}
        result = _decoded(_sanitize_headers(headers)["referrer"])
        assert "token=***REDACTED***" in result
        assert "secret" not in result

    def test_referer_without_sensitive_params_unchanged(self) -> None:
        headers = {"referer": "https://app.mpcontrol.online/web/orders?page=1"}
        result = _sanitize_headers(headers)
        assert result["referer"] == headers["referer"]

    def test_referer_without_query_unchanged(self) -> None:
        headers = {"referer": "https://app.mpcontrol.online/web/"}
        result = _sanitize_headers(headers)
        assert result["referer"] == headers["referer"]

    def test_does_not_modify_safe_headers(self) -> None:
        headers = {
            "user-agent": "Mozilla/5.0",
            "accept": "text/html",
            "content-type": "application/json",
        }
        result = _sanitize_headers(headers)
        assert result == headers

    def test_multiple_sensitive_headers(self) -> None:
        headers = {
            "authorization": "Bearer tok",
            "cookie": "sess=1",
            "referer": "https://example.com/login?token=abc",
            "user-agent": "test",
        }
        result = _sanitize_headers(headers)
        assert result["authorization"] == "***REDACTED***"
        assert result["cookie"] == "***REDACTED***"
        decoded_referer = _decoded(result["referer"])
        assert "token=***REDACTED***" in decoded_referer
        assert "abc" not in decoded_referer
        assert result["user-agent"] == "test"

    def test_does_not_mutate_original_headers(self) -> None:
        headers = {"authorization": "secret", "referer": "https://example.com?token=abc"}
        original_auth = headers["authorization"]
        original_referer = headers["referer"]
        _sanitize_headers(headers)
        assert headers["authorization"] == original_auth
        assert headers["referer"] == original_referer

    def test_empty_headers(self) -> None:
        assert _sanitize_headers({}) == {}
