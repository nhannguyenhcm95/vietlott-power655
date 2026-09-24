"""M2-T4: structured-logging tests (fast-follow from M2-T1 finding #3)."""
from __future__ import annotations

import json
import logging

import pytest

from src.logging_utils import configure_logging


@pytest.fixture(autouse=True)
def _restore_root_handlers():
    """configure_logging() clears the root handlers; restore them so tests don't leak state."""
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield
    root.handlers.clear()
    root.handlers.extend(original_handlers)
    root.setLevel(original_level)


def test_configure_logging_writes_json_lines_to_file(tmp_path):
    log_file = tmp_path / "app.log"
    configure_logging("INFO", log_file)
    logging.getLogger("test.logger").info("hello_test", extra={"foo": "bar", "run_id": "abc123"})

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "hello_test"
    assert record["level"] == "INFO"
    assert record["logger"] == "test.logger"
    assert "ts" in record
    assert record["foo"] == "bar"
    assert record["run_id"] == "abc123"


def test_configure_logging_ts_is_iso8601(tmp_path):
    log_file = tmp_path / "app.log"
    configure_logging("INFO", log_file)
    logging.getLogger("test.logger").info("an_event")
    record = json.loads(log_file.read_text(encoding="utf-8").splitlines()[0])
    from datetime import datetime
    datetime.fromisoformat(record["ts"])  # must not raise


def test_configure_logging_creates_parent_directories(tmp_path):
    log_file = tmp_path / "nested" / "dir" / "app.log"
    configure_logging("INFO", log_file)
    logging.getLogger("test.logger").info("event")
    assert log_file.exists()


def test_configure_logging_respects_level(tmp_path):
    log_file = tmp_path / "app.log"
    configure_logging("WARNING", log_file)
    logging.getLogger("test.logger").info("should_not_appear")
    assert log_file.read_text(encoding="utf-8") == ""
    logging.getLogger("test.logger").warning("should_appear")
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "should_appear"


def test_configure_logging_no_file_handler_when_log_file_is_none():
    configure_logging("INFO", None)
    root = logging.getLogger()
    assert not any(isinstance(h, logging.FileHandler) for h in root.handlers)
    assert any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers)


def test_configure_logging_multiple_calls_do_not_duplicate_handlers(tmp_path):
    log_file = tmp_path / "app.log"
    configure_logging("INFO", log_file)
    configure_logging("INFO", log_file)
    logging.getLogger("test.logger").info("once")
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_configure_logging_includes_exception_info(tmp_path):
    log_file = tmp_path / "app.log"
    configure_logging("INFO", log_file)
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("test.logger").exception("failure_event")
    record = json.loads(log_file.read_text(encoding="utf-8").splitlines()[0])
    assert record["event"] == "failure_event"
    assert "ValueError: boom" in record["exc"]
