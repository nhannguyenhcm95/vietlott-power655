import json
from datetime import datetime, timedelta, timezone

import pytest

from src.ingestion.lock import LockHeldError, RunLock


def test_acquire_creates_lock_file_with_json(paths):
    lock_path = paths.data / ".refresh.lock"
    lock = RunLock(lock_path, command="refresh")
    lock.acquire()
    try:
        assert lock_path.exists()
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert "pid" in payload and "started_at" in payload and payload["command"] == "refresh"
    finally:
        lock.release()
    assert not lock_path.exists()


def test_second_acquire_raises_lock_held_error(paths):
    lock_path = paths.data / ".refresh.lock"
    first = RunLock(lock_path, command="refresh")
    first.acquire()
    try:
        second = RunLock(lock_path, command="refresh")
        with pytest.raises(LockHeldError) as exc_info:
            second.acquire()
        assert exc_info.value.holder["command"] == "refresh"
    finally:
        first.release()


def test_lock_released_after_use_via_context_manager(paths):
    lock_path = paths.data / ".refresh.lock"
    with RunLock(lock_path, command="refresh"):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_lock_released_after_exception_in_with_block(paths):
    lock_path = paths.data / ".refresh.lock"
    with pytest.raises(ValueError):
        with RunLock(lock_path, command="refresh"):
            raise ValueError("boom")
    assert not lock_path.exists()


def test_stale_lock_broken_and_logged(paths, caplog):
    lock_path = paths.data / ".refresh.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    old_started = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    lock_path.write_text(json.dumps({"pid": 999999, "command": "refresh", "started_at": old_started}), encoding="utf-8")

    lock = RunLock(lock_path, stale_after=timedelta(minutes=120), command="refresh")
    with caplog.at_level("WARNING"):
        lock.acquire()
    try:
        assert lock.broke_stale is True
        assert lock_path.exists()
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["command"] == "refresh"
        assert any("stale_lock_broken" in r.message for r in caplog.records)
        # the broken lock file was moved aside, not deleted
        stale_files = list(paths.data.glob(".refresh.lock.stale.*"))
        assert len(stale_files) == 1
    finally:
        lock.release()


def test_stale_lock_break_race(paths, monkeypatch):
    """The loser of the race to recreate the lock after breaking a stale one gets LockHeldError."""
    import os as os_module

    lock_path = paths.data / ".refresh.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    old_started = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    lock_path.write_text(json.dumps({"pid": 999999, "command": "refresh", "started_at": old_started}), encoding="utf-8")

    winner = RunLock(lock_path, stale_after=timedelta(minutes=120), command="winner")
    loser = RunLock(lock_path, stale_after=timedelta(minutes=120), command="loser")

    real_replace = os_module.replace
    call_count = {"n": 0}

    def racing_replace(src, dst):
        call_count["n"] += 1
        real_replace(src, dst)
        if call_count["n"] == 1:
            # winner recreates the lock immediately after breaking the stale one, before the loser gets a turn
            winner._create()
            winner._acquired = True

    monkeypatch.setattr("src.ingestion.lock.os.replace", racing_replace)
    with pytest.raises(LockHeldError):
        loser.acquire()
    winner.release()


def test_unreadable_lock_json_falls_back_to_mtime(paths):
    lock_path = paths.data / ".refresh.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("not json", encoding="utf-8")
    import os
    old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).timestamp()
    os.utime(lock_path, (old_time, old_time))

    lock = RunLock(lock_path, stale_after=timedelta(minutes=120), command="refresh")
    lock.acquire()
    try:
        assert lock.broke_stale is True
    finally:
        lock.release()


def test_lock_not_stale_before_timeout(paths):
    lock_path = paths.data / ".refresh.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    recent = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    lock_path.write_text(json.dumps({"pid": 999999, "command": "refresh", "started_at": recent}), encoding="utf-8")

    lock = RunLock(lock_path, stale_after=timedelta(minutes=120), command="refresh")
    with pytest.raises(LockHeldError):
        lock.acquire()
