"""A run lock so `refresh`/`ingest`/`curate` never overlap (M2-T3 §2.4).

The lock is taken only by the CLI layer, never inside `run_ingestion`/`build_curated`/
`run_refresh` themselves, so library calls and most tests stay lock-free.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_STALE_AFTER = timedelta(minutes=120)


class LockHeldError(RuntimeError):
    """Another process holds the lock (or won the race to break a stale one)."""

    def __init__(self, holder: dict):
        super().__init__(f"lock held by {holder}")
        self.holder = holder


@dataclass
class RunLock:
    path: Path
    stale_after: timedelta = DEFAULT_STALE_AFTER
    command: str = ""
    lock_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    broke_stale: bool = field(default=False, init=False)
    _acquired: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def _payload(self) -> bytes:
        payload = {
            "pid": os.getpid(),
            "lock_id": self.lock_id,
            "command": self.command,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        return json.dumps(payload).encode("utf-8")

    def _create(self) -> None:
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, self._payload())
        finally:
            os.close(fd)

    def _read_holder(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _is_stale(self) -> bool:
        holder = self._read_holder()
        started_at = holder.get("started_at")
        started: datetime | None = None
        if started_at:
            try:
                started = datetime.fromisoformat(started_at)
            except ValueError:
                started = None
        if started is None:
            # The JSON is unreadable/missing started_at: fall back to the file mtime.
            try:
                started = datetime.fromtimestamp(self.path.stat().st_mtime, tz=timezone.utc)
            except FileNotFoundError:
                return False
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - started) > self.stale_after

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._create()
            self._acquired = True
            return
        except FileExistsError:
            pass

        if not self._is_stale():
            raise LockHeldError(self._read_holder())

        stale_target = self.path.with_name(f"{self.path.name}.stale.{os.getpid()}")
        try:
            os.replace(self.path, stale_target)
        except FileNotFoundError:
            # Another process broke or released it first.
            raise LockHeldError(self._read_holder()) from None

        log.warning("stale_lock_broken", extra={"lock_path": str(self.path), "moved_to": str(stale_target)})
        self.broke_stale = True
        try:
            self._create()
            self._acquired = True
        except FileExistsError:
            # Lost the race to recreate the lock after breaking the stale one.
            raise LockHeldError(self._read_holder()) from None

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._acquired = False

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False
