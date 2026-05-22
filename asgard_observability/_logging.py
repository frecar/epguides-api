"""Cluster-baseline JSON logging — Loki/Grafana ingestion format.

Extracted from the duplicated ``JSONFormatter`` + ``setup_logging`` in
llm-router, potato, and epguides-api. Single shape so Loki dashboards key
off the same fields across services.

JSON output (one event per line, Loki ingestion):

.. code-block:: json

    {
      "timestamp": "2026-05-21T11:30:00",
      "level": "INFO",
      "logger": "portal.access",
      "message": "request completed",
      "service": "portal",
      "pid": 4242,
      "<extra fields from extra={...}>": "..."
    }

DEBUG mode (``LOG_LEVEL=DEBUG``) falls back to human-readable formatting for
dev convenience — same pattern llm-router/potato/epguides already used.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

# Standard LogRecord attributes — every key NOT in this set is treated as
# user-supplied `extra=` context and pulled into the JSON output. This is
# how Loki queries find structured fields (e.g. {service="portal"} | json |
# duration_ms > 500).
_STANDARD_LOG_RECORD_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured Loki/Grafana ingestion.

    Emits standard fields (timestamp/level/logger/message/service/pid) plus
    any keys passed via ``logger.info(..., extra={...})`` that aren't
    LogRecord builtins.

    The ``service`` field is embedded by binding ``service_name`` at
    construction time — Loki queries can then key by service without
    relying on docker labels or external metadata.
    """

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
            "pid": record.process,
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            log_data["stack_info"] = self.formatStack(record.stack_info)
        # Extra fields from extra={} kwarg — anything not a LogRecord builtin.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRS:
                log_data[key] = value
        # default=str keeps Decimal, datetime, UUID, etc. from crashing
        # the formatter. Loki ingests strings; lossy is OK for log output.
        return json.dumps(log_data, default=str)


def setup_logging(
    service_name: str,
    *,
    log_level: str | None = None,
    force_format: str | None = None,
) -> None:
    """Configure root logger with JSON output (production) or text (dev).

    Args:
        service_name: Injected as the ``service`` field in every JSON log
            line. Must match the service_name used by Sentry init.
        log_level: Override the level. Default reads ``LOG_LEVEL`` env
            (``INFO`` if unset). Case-insensitive.
        force_format: Force ``"json"`` or ``"text"``. Default: text if
            level is DEBUG, otherwise JSON. Honours ``LOG_FORMAT`` env when
            ``force_format`` is None.

    Side effects:
        - Removes existing root handlers (idempotent re-init safe).
        - Sets uvicorn.access / httpx loggers to WARNING (cluster baseline:
          access-log noise via reverse proxy, not the app).
    """
    level_str = (log_level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_str, logging.INFO)

    if force_format is not None:
        use_json = force_format.lower() == "json"
    else:
        env_format = os.environ.get("LOG_FORMAT", "").lower()
        if env_format in ("json", "text"):
            use_json = env_format == "json"
        else:
            # Dev convenience: DEBUG defaults to human-readable text.
            use_json = level_str != "DEBUG"

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # Idempotent: a re-init from a process restart shouldn't double-handler.
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)  # let root_logger gate; handler stays open

    if use_json:
        handler.setFormatter(JSONFormatter(service_name))
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    root_logger.addHandler(handler)

    # Cluster baseline: silence noisy third-party loggers. Adding more
    # services / patterns here is a single shared edit instead of N copy-
    # paste edits in service settings.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
