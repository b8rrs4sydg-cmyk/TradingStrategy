"""JSON logging config — plug into uvicorn via APP_LOG_JSON=1.

When enabled, every log record becomes a single-line JSON object (timestamp,
level, logger, message, plus any ``extra`` kwargs the caller passed). Keeps
logs machine-greppable in Render/Cloud Logging without pulling structlog.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, ClassVar


class JsonFormatter(logging.Formatter):
    _RESERVED: ClassVar[set[str]] = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _iso(record.created),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        return json.dumps(payload, ensure_ascii=False)


def _iso(created: float) -> str:
    gm = time.gmtime(created)
    msec = int((created - int(created)) * 1000)
    return f"{time.strftime('%Y-%m-%dT%H:%M:%S', gm)}.{msec:03d}Z"


def install() -> None:
    """Call at app startup to turn on JSON logging when APP_LOG_JSON=1."""

    if os.getenv("APP_LOG_JSON", "0") != "1":
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("APP_LOG_LEVEL", "INFO"))
