"""Structured (JSON lines) logging."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(JsonFormatter())
    root.addHandler(stream)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)
