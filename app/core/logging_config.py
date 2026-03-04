"""
Structured logging configuration.

Provides JSON logging for production and human-readable logging for development.
Configure via LOG_FORMAT env var ("json" or "text") and LOG_LEVEL env var.
"""

import json
import logging
import sys
from typing import Any

from app.core.config import settings

# Fields to extract from log records for structured output
_EXTRA_FIELDS = ("method", "path", "status_code", "process_time_seconds", "client")


class StructuredFormatter(logging.Formatter):
    """JSON formatter for production logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields if present
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                log_data[field] = value

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class DevelopmentFormatter(logging.Formatter):
    """Human-readable formatter for development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def _use_json_format() -> bool:
    """
    Determine whether to use JSON log format.

    Uses LOG_FORMAT env var: "json" (default) for structured JSON output,
    "text" for human-readable development output.
    Falls back to text format when LOG_LEVEL is DEBUG for convenience.
    """
    log_format = settings.LOG_FORMAT.lower()
    if log_format == "text":
        return False
    if log_format == "json":
        return True
    # Fallback: DEBUG level defaults to text for dev convenience
    return settings.LOG_LEVEL.upper() != "DEBUG"


def setup_logging() -> logging.Logger:
    """
    Configure application logging based on environment.

    Returns:
        Configured root logger.
    """
    root_logger = logging.getLogger()
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Configure console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    # Select formatter based on LOG_FORMAT setting
    if _use_json_format():
        formatter: logging.Formatter = StructuredFormatter()
    else:
        formatter = DevelopmentFormatter()

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    return root_logger
