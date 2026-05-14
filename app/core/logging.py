"""version: 1.0.0
description: Structured logging setup.
updated: 2026-05-14
"""

import logging
import logging.config
from pathlib import Path

from pythonjsonlogger import jsonlogger

from app.core.config import Settings


class MaskSecretsFilter(logging.Filter):
    """Prevent accidental full token leakage in logs."""

    SECRET_MARKERS = ("api-key", "authorization", "client-id", "token", "secret")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        lowered = message.lower()
        if any(marker in lowered for marker in self.SECRET_MARKERS):
            record.msg = "[masked sensitive log message]"
            record.args = ()
        return True


def configure_logging(settings: Settings) -> None:
    """Configure console and file JSON logs."""

    Path("logs").mkdir(exist_ok=True)
    formatter = jsonlogger.JsonFormatter(  # type: ignore[no-untyped-call]
        "%(asctime)s %(levelname)s %(name)s %(message)s %(module)s %(funcName)s"
    )
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler("logs/app.log", encoding="utf-8"),
    ]
    error_handler = logging.FileHandler("logs/errors.log", encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    handlers.append(error_handler)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(settings.log_level.upper())
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(MaskSecretsFilter())
        root.addHandler(handler)
