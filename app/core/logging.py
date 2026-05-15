"""version: 1.1.0
description: Enhanced structured logging with context and error tracking.
updated: 2026-05-15
"""

import logging
import logging.config
import sys
from pathlib import Path
from typing import Any

import structlog
from pythonjsonlogger import jsonlogger

from app.core.config import Settings


class MaskSecretsFilter(logging.Filter):
    """Prevent accidental full token leakage in logs."""

    SECRET_MARKERS = ("api-key", "authorization", "client-id", "token", "secret", "password")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        lowered = message.lower()
        if any(marker in lowered for marker in self.SECRET_MARKERS):
            record.msg = "[masked sensitive log message]"
            record.args = ()
        return True


class CustomJsonFormatter(jsonlogger.JsonFormatter):  # type: ignore[misc]
    """Custom JSON formatter with additional context fields."""

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name

        for field in ("user_id", "account_id", "marketplace", "order_id", "request_id"):
            if hasattr(record, field):
                log_record[field] = getattr(record, field)


def configure_logging(settings: Settings) -> None:
    """Configure console and file JSON logs with structlog."""

    Path("logs").mkdir(exist_ok=True)

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    formatter = CustomJsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(module)s %(funcName)s"
    )

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/app.log", encoding="utf-8"),
    ]
    error_handler = logging.FileHandler("logs/errors.log", encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    handlers.append(error_handler)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(log_level)
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(MaskSecretsFilter())
        root.addHandler(handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


class LogContext:
    """Context manager for adding structured logging context."""

    def __init__(self, **kwargs: Any) -> None:
        self.context = kwargs
        self.token: Any = None

    def __enter__(self) -> "LogContext":
        self.token = structlog.contextvars.bind_contextvars(**self.context)
        return self

    def __exit__(self, *args: Any) -> None:
        structlog.contextvars.unbind_contextvars(*self.context.keys())


def log_exception(
    logger: structlog.BoundLogger,
    exc: Exception,
    message: str = "Exception occurred",
    **extra: Any,
) -> None:
    """Log an exception with full context."""
    logger.exception(
        message,
        exc_type=type(exc).__name__,
        exc_message=str(exc),
        **extra,
    )
