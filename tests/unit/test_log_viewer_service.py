"""Tests for log_viewer_service."""

import gzip
import json
from unittest.mock import patch

import pytest

from app.services.log_viewer_service import (
    ALLOWED_LOG_FILES,
    LogViewerService,
)


@pytest.fixture
def temp_logs_dir(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    archive_dir = logs_dir / "archive"
    archive_dir.mkdir()

    app_log = logs_dir / "app.log"
    app_log.write_text(
        json.dumps({
            "asctime": "2026-06-01T10:00:00",
            "level": "INFO",
            "logger": "app.test",
            "message": "Test info message",
            "user_id": 123,
        }) + "\n"
        + json.dumps({
            "asctime": "2026-06-01T10:01:00",
            "level": "ERROR",
            "logger": "app.test",
            "message": "Test error message",
            "exc_info": "Traceback: something failed",
        }) + "\n"
        + json.dumps({
            "asctime": "2026-06-01T10:02:00",
            "level": "WARNING",
            "logger": "app.test",
            "message": "Test warning with api_key=secret123",
        }) + "\n"
        + json.dumps({
            "asctime": "2026-06-01T10:03:00",
            "level": "DEBUG",
            "logger": "app.test",
            "message": "Debug message",
        }) + "\n",
        encoding="utf-8",
    )

    errors_log = logs_dir / "errors.log"
    errors_log.write_text(
        json.dumps({
            "asctime": "2026-06-01T10:01:00",
            "level": "ERROR",
            "logger": "app.test",
            "message": "Error in errors.log",
        }) + "\n",
        encoding="utf-8",
    )

    return logs_dir


@pytest.fixture
def service(temp_logs_dir):
    with patch("app.services.log_viewer_service.LOGS_DIR", temp_logs_dir), \
         patch("app.services.log_viewer_service.ARCHIVE_DIR", temp_logs_dir / "archive"):
        svc = LogViewerService()
        yield svc


class TestLogViewerServiceValidation:
    def test_allowed_log_files(self):
        assert "app.log" in ALLOWED_LOG_FILES
        assert "errors.log" in ALLOWED_LOG_FILES

    def test_validate_log_name_rejects_path_traversal(self, service):
        with pytest.raises(ValueError, match="not allowed"):
            service._validate_log_name("../etc/passwd")

    def test_validate_log_name_rejects_arbitrary_files(self, service):
        with pytest.raises(ValueError, match="not allowed"):
            service._validate_log_name("config.py")

    def test_validate_log_name_accepts_allowed(self, service):
        path = service._validate_log_name("app.log")
        assert path.name == "app.log"


class TestLogViewerServiceMasking:
    def test_mask_api_key(self, service):
        text = "Using api_key=super_secret_token_12345"
        masked = service._mask_secrets(text)
        assert "super_secret_token_12345" not in masked
        assert "MASKED" in masked

    def test_mask_authorization(self, service):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9"
        masked = service._mask_secrets(text)
        assert "eyJhbGciOiJIUzI1NiJ9" not in masked
        assert "MASKED" in masked

    def test_mask_password(self, service):
        text = "password=mysecretpass123"
        masked = service._mask_secrets(text)
        assert "mysecretpass123" not in masked
        assert "MASKED" in masked

    def test_mask_token(self, service):
        text = "token=abc123def456"
        masked = service._mask_secrets(text)
        assert "abc123def456" not in masked
        assert "MASKED" in masked

    def test_mask_client_id(self, service):
        text = "client_id=12345"
        masked = service._mask_secrets(text)
        assert "MASKED" in masked


class TestLogViewerServiceParsing:
    def test_parse_json_log_line(self, service):
        line = json.dumps({
            "asctime": "2026-06-01T10:00:00",
            "level": "INFO",
            "logger": "app.test",
            "message": "Test message",
        })
        entry = service._parse_log_line(line)
        assert entry is not None
        assert entry.level == "INFO"
        assert entry.logger_name == "app.test"
        assert entry.message == "Test message"

    def test_parse_empty_line(self, service):
        assert service._parse_log_line("") is None
        assert service._parse_log_line("   ") is None

    def test_parse_plain_text_line(self, service):
        entry = service._parse_log_line("Some plain text log line")
        assert entry is not None
        assert entry.level == "INFO"
        assert "plain text" in entry.message


class TestLogViewerServiceReadLogs:
    def test_read_all_logs(self, service):
        entries = service.read_logs("app.log", limit=100)
        assert len(entries) == 4

    def test_read_logs_with_limit(self, service):
        entries = service.read_logs("app.log", limit=2)
        assert len(entries) == 2

    def test_filter_by_level(self, service):
        entries = service.read_logs("app.log", limit=100, level="ERROR")
        assert len(entries) == 1
        assert entries[0].level == "ERROR"

    def test_filter_by_search(self, service):
        entries = service.read_logs("app.log", limit=100, search="warning")
        assert len(entries) == 1

    def test_secrets_masked_in_output(self, service):
        entries = service.read_logs("app.log", limit=100, search="warning")
        assert len(entries) == 1
        assert "secret123" not in entries[0].message
        assert "MASKED" in entries[0].message

    def test_read_errors_log(self, service):
        entries = service.read_logs("errors.log", limit=100)
        assert len(entries) == 1
        assert entries[0].level == "ERROR"


class TestLogViewerServiceStats:
    def test_get_stats(self, service):
        stats = service.get_stats("app.log")
        assert stats.file_size > 0
        assert stats.total_lines == 4
        assert stats.level_counts["INFO"] == 1
        assert stats.level_counts["ERROR"] == 1
        assert stats.level_counts["WARNING"] == 1
        assert stats.level_counts["DEBUG"] == 1

    def test_get_stats_last_error(self, service):
        stats = service.get_stats("app.log")
        assert stats.last_error is not None
        assert stats.last_error.level == "ERROR"


class TestLogViewerServiceArchive:
    def test_archive_log(self, service, temp_logs_dir):
        archive_path = service.archive_log("app.log")
        assert archive_path.exists()
        assert archive_path.suffix == ".gz"

        original = temp_logs_dir / "app.log"
        assert original.read_text(encoding="utf-8") == ""

        with gzip.open(archive_path, "rt", encoding="utf-8") as f:
            content = f.read()
            assert "Test info message" in content

    def test_archive_rejects_invalid_name(self, service):
        with pytest.raises(ValueError):
            service.archive_log("../etc/passwd")


class TestLogViewerServiceClear:
    def test_clear_log(self, service, temp_logs_dir):
        service.clear_log("app.log")
        original = temp_logs_dir / "app.log"
        assert original.read_text(encoding="utf-8") == ""

    def test_clear_rejects_invalid_name(self, service):
        with pytest.raises(ValueError):
            service.clear_log("../etc/passwd")


class TestLogViewerServiceDownload:
    def test_download_log(self, service):
        path, name = service.download_log("app.log")
        assert path.exists()
        assert name == "app.log"

    def test_download_rejects_invalid_name(self, service):
        with pytest.raises(ValueError):
            service.download_log("../etc/passwd")
