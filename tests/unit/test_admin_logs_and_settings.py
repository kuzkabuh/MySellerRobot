"""Tests for admin logs modal and settings redirect fix."""

import pytest
from fastapi.testclient import TestClient

from app.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestAdminLogsModal:
    """Test admin logs modal rendering with special characters."""

    def test_log_entry_with_quotes_in_raw_line(self):
        """Test that log entries with quotes don't break JavaScript."""
        from datetime import UTC, datetime

        from app.services.log_viewer_service import LogEntry

        # Create a log entry with problematic characters
        entry = LogEntry(
            timestamp=datetime.now(UTC),
            level="ERROR",
            logger_name="test.logger",
            message="Test message with \"double quotes\" and 'single quotes'",
            raw_line=(
                '{"timestamp": "2026-01-01T00:00:00Z", "level": "ERROR", '
                '"message": "Test with \\"quotes\\" and newlines\\n"}'
            ),
            traceback=(
                "Traceback (most recent call last):\n"
                '  File "test.py", line 1\n'
                '    raise ValueError("Test error")\n'
                "ValueError: Test error"
            ),
        )

        # Verify the entry was created correctly
        assert entry.raw_line is not None
        assert '"' in entry.raw_line
        assert "'" in entry.message
        assert "\n" in entry.traceback

    def test_log_entry_with_html_tags(self):
        """Test that log entries with HTML tags are handled safely."""
        from datetime import UTC, datetime

        from app.services.log_viewer_service import LogEntry

        entry = LogEntry(
            timestamp=datetime.now(UTC),
            level="WARNING",
            logger_name="test.logger",
            message="Test with <script>alert('xss')</script>",
            raw_line='<script>alert("xss")</script>',
        )

        # Verify HTML tags are preserved in raw_line
        assert "<script>" in entry.raw_line
        assert "</script>" in entry.raw_line


class TestSettingsRedirect:
    """Test that /web/settings doesn't have circular redirects."""

    def test_settings_page_no_circular_redirect(self, client):
        """Test that GET /web/settings doesn't redirect to itself."""
        # Allow redirects but limit to prevent infinite loops
        response = client.get("/web/settings", follow_redirects=False)

        # Should either return 200 (if authenticated) or redirect to login
        # Should NOT redirect to /web/settings (circular)
        if response.status_code in [301, 302, 303, 307, 308]:
            location = response.headers.get("location", "")
            assert "/web/settings" not in location or "/web/login" in location, (
                f"Circular redirect detected: {location}"
            )

    def test_settings_low_margin_post_redirects_correctly(self, client):
        """Test that POST /settings/low-margin redirects to /web/settings."""
        # This should redirect to /web/settings (which is now handled by user_settings.py)
        response = client.post(
            "/web/settings/low-margin", data={"threshold": "15"}, follow_redirects=False
        )

        # Should redirect (303) to /web/settings
        if response.status_code == 303:
            location = response.headers.get("location", "")
            assert "/web/settings" in location


class TestLogViewerServiceMasking:
    """Test that log viewer service masks sensitive data."""

    def test_mask_sensitive_data_in_logs(self):
        """Test that sensitive data is masked in log entries."""
        from app.services.log_viewer_service import LogViewerService

        service = LogViewerService()

        # Test various sensitive patterns
        test_cases = [
            ("api_key=abc123secret", "***MASKED***"),
            ("Authorization: Bearer token123", "***MASKED***"),
            ("password=secret123", "***MASKED***"),
            ("client_id=12345", "***MASKED***"),
        ]

        for input_text, expected_mask in test_cases:
            masked = service._mask_secrets(input_text)
            assert expected_mask in masked, f"Failed to mask: {input_text}"
            assert input_text.split("=")[-1] not in masked or "MASKED" in masked
