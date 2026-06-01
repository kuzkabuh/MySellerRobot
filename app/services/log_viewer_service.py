"""version: 1.0.0
description: Log viewer service for admin web interface.
"""

import gzip
import json
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)

ALLOWED_LOG_FILES = {"app.log", "errors.log"}
LOGS_DIR = Path("logs")
ARCHIVE_DIR = LOGS_DIR / "archive"

SECRET_PATTERNS = [
    (r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", "Bearer ***MASKED***"),
    (r"Basic\s+[A-Za-z0-9+/]+=*", "Basic ***MASKED***"),
    (r"(api[_-]?key|apikey|api-key)[\s:=]+[^\s,;'\"]+", r"\1=***MASKED***"),
    (r"(authorization|auth)[\s:=]+[^\s,;'\"]+[\s,;'\"]*[^\s,;'\"]*", r"\1=***MASKED***"),
    (r"(token|access_token|refresh_token)[\s:=]+[^\s,;'\"]+", r"\1=***MASKED***"),
    (r"(password|passwd|pwd)[\s:=]+[^\s,;'\"]+", r"\1=***MASKED***"),
    (r"(secret|secret_key)[\s:=]+[^\s,;'\"]+", r"\1=***MASKED***"),
    (r"(client[_-]?id|clientid)[\s:=]+[^\s,;'\"]+", r"\1=***MASKED***"),
]


@dataclass
class LogEntry:
    timestamp: datetime | None
    level: str
    logger_name: str
    message: str
    raw_line: str
    user_id: int | None = None
    telegram_id: int | None = None
    traceback: str | None = None


@dataclass
class LogStats:
    file_size: int
    total_lines: int
    level_counts: dict[str, int]
    last_error: LogEntry | None
    last_entry: LogEntry | None


class LogViewerService:
    def __init__(self) -> None:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    def _validate_log_name(self, log_name: str) -> Path:
        if log_name not in ALLOWED_LOG_FILES:
            raise ValueError(f"Log file not allowed: {log_name}")
        log_path = LOGS_DIR / log_name
        if not log_path.exists():
            raise FileNotFoundError(f"Log file not found: {log_name}")
        return log_path

    def _mask_secrets(self, text: str) -> str:
        result = text
        for pattern, replacement in SECRET_PATTERNS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result

    def _parse_log_line(self, line: str) -> LogEntry | None:
        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
            timestamp = None
            if "asctime" in data:
                try:
                    timestamp = datetime.fromisoformat(data["asctime"])
                except (ValueError, TypeError):
                    pass
            elif "timestamp" in data:
                try:
                    timestamp = datetime.fromisoformat(data["timestamp"])
                except (ValueError, TypeError):
                    pass

            level = data.get("level", data.get("levelname", "INFO")).upper()
            logger_name = data.get("logger", data.get("name", "unknown"))
            message = data.get("message", data.get("msg", ""))

            user_id = data.get("user_id")
            telegram_id = data.get("telegram_id")

            traceback = None
            if "exc_info" in data:
                traceback = str(data["exc_info"])
            elif "exception" in data:
                traceback = str(data["exception"])

            return LogEntry(
                timestamp=timestamp,
                level=level,
                logger_name=logger_name,
                message=message,
                raw_line=line,
                user_id=user_id,
                telegram_id=telegram_id,
                traceback=traceback,
            )
        except json.JSONDecodeError:
            match = re.match(
                r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+)\s+(\w+)\s+(\S+)\s+(.*)",
                line,
            )
            if match:
                timestamp_str, level, logger_name, message = match.groups()
                try:
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
                except ValueError:
                    timestamp = None
                return LogEntry(
                    timestamp=timestamp,
                    level=level.upper(),
                    logger_name=logger_name,
                    message=message,
                    raw_line=line,
                )

            return LogEntry(
                timestamp=None,
                level="INFO",
                logger_name="unknown",
                message=line,
                raw_line=line,
            )

    def read_logs(
        self,
        log_name: str,
        limit: int = 100,
        level: str | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        user_id: int | None = None,
        telegram_id: int | None = None,
    ) -> list[LogEntry]:
        log_path = self._validate_log_name(log_name)

        with open(log_path, encoding="utf-8") as f:
            lines = deque(f, maxlen=limit * 10)

        entries = []
        for line in reversed(lines):
            entry = self._parse_log_line(line)
            if entry is None:
                continue

            entry.message = self._mask_secrets(entry.message)
            entry.raw_line = self._mask_secrets(entry.raw_line)
            if entry.traceback:
                entry.traceback = self._mask_secrets(entry.traceback)

            if level and entry.level != level.upper():
                continue
            if search and search.lower() not in entry.message.lower():
                continue
            if date_from and entry.timestamp and entry.timestamp < date_from:
                continue
            if date_to and entry.timestamp and entry.timestamp > date_to:
                continue
            if user_id and entry.user_id != user_id:
                continue
            if telegram_id and entry.telegram_id != telegram_id:
                continue

            entries.append(entry)
            if len(entries) >= limit:
                break

        return entries

    def get_stats(self, log_name: str) -> LogStats:
        log_path = self._validate_log_name(log_name)
        file_size = log_path.stat().st_size

        level_counts: dict[str, int] = {
            "DEBUG": 0,
            "INFO": 0,
            "WARNING": 0,
            "ERROR": 0,
            "CRITICAL": 0,
        }
        last_error = None
        last_entry = None
        total_lines = 0

        with open(log_path, encoding="utf-8") as f:
            for line in f:
                total_lines += 1
                entry = self._parse_log_line(line)
                if entry is None:
                    continue

                if entry.level in level_counts:
                    level_counts[entry.level] += 1

                last_entry = entry
                if entry.level in ("ERROR", "CRITICAL"):
                    last_error = entry

        return LogStats(
            file_size=file_size,
            total_lines=total_lines,
            level_counts=level_counts,
            last_error=last_error,
            last_entry=last_entry,
        )

    def download_log(self, log_name: str) -> tuple[Path, str]:
        log_path = self._validate_log_name(log_name)
        return log_path, log_name

    def archive_log(self, log_name: str) -> Path:
        log_path = self._validate_log_name(log_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"{log_path.stem}_{timestamp}.log.gz"
        archive_path = ARCHIVE_DIR / archive_name

        with open(log_path, "rb") as f_in:
            with gzip.open(archive_path, "wb") as f_out:
                f_out.writelines(f_in)

        log_path.write_text("", encoding="utf-8")

        logger.info(
            "log_archived",
            log_name=log_name,
            archive_path=str(archive_path),
        )

        return archive_path

    def clear_log(self, log_name: str) -> None:
        log_path = self._validate_log_name(log_name)
        log_path.write_text("", encoding="utf-8")
        logger.info("log_cleared", log_name=log_name)
