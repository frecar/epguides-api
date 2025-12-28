"""
Enhanced logging configuration with structured logging.

Supports JSON logging for production and human-readable logging for development.
"""

import json
import logging
import sys
from typing import Any

from app.core.config import settings


class StructuredFormatter(logging.Formatter):
    """Structured JSON formatter for production logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured JSON."""
        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields if present (using getattr for type safety)
        method = getattr(record, "method", None)
        if method is not None:
            log_data["method"] = method
        path = getattr(record, "path", None)
        if path is not None:
            log_data["path"] = path
        status_code = getattr(record, "status_code", None)
        if status_code is not None:
            log_data["status_code"] = status_code
        process_time = getattr(record, "process_time", None)
        if process_time is not None:
            log_data["process_time"] = process_time
        client = getattr(record, "client", None)
        if client is not None:
            log_data["client"] = client

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging():
    """Configure application logging based on environment."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    # Use structured formatter in production, simple formatter in development
    if settings.LOG_LEVEL.upper() == "DEBUG":
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    else:
        formatter = StructuredFormatter()

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Suppress noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    return root_logger
