"""Idempotent incremental ingestion: SOURCE -> RAW -> VALIDATE -> STAGING -> CURATED."""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from src.api.base import DrawSource, filter_by_date
from src.api.models import DrawRecord
from src.config import Paths
from src.ingestion.raw_archive import RawArchive
from src.transformation import tables
from src.validation.rules import QualityIssue, dedupe_exact, today_local, validate_dataset, validate_record

log = logging.getLogger(__name__)

INGESTION_LOG_COLS = ["run_id", "source", "mode", "started_at", "finished_at", "rows_received", "rows_inserted", "rows_skipped", "status", "error_message"]
QUALITY_LOG_COLS = ["check_id", "run_id", "draw_id", "rule", "status", "detail"]


@dataclass
class IngestionResult:
    run_id: str
    source: str
    mode: str
    started_at: str
    finished_at: str
    rows_received: int
    rows_inserted: int
    rows_skipped: int
    status: str
    error_message: str
    issues: list[QualityIssue]


def new_run_id() -> str:
    return f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:6]}"


def staging_path(paths: Paths, source: str) -> Path:
    return paths.staging / source / "draws.csv"


def read_staging(paths: Paths, source: str) -> pd.DataFrame:
    path = staging_path(paths, source)
    if not path.exists():
        return pd.DataFrame(columns=tables.STAGING_COLS)
    return tables.normalize_staging(pd.read_csv(path, dtype={"draw_id": str, "draw_date": str}))


def _append_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def _write_quality_log(paths: Paths, run_id: str, issues: list[QualityIssue]) -> None:
    rows = [
        {"check_id": f"{run_id}-{i:05d}", "run_id": run_id, "draw_id": q.draw_id or "", "rule": q.rule, "status": q.severity, "detail": q.detail}
        for i, q in enumerate(issues)
    ]
    _append_csv(paths.logs / "quality_log.csv", QUALITY_LOG_COLS, rows)


def _content_key(r: DrawRecord) -> tuple:
    return (r.draw_date, tuple(sorted(r.main_numbers)), r.special_number)


def run_ingestion(
    source: DrawSource,
    paths: Paths,
    mode: str = "incremental",
    start_date: date | None = None,
    end_date: date | None = None,
    today: date | None = None,
) -> IngestionResult:
    if mode not in {"incremental", "full"}:
        raise ValueError(f"mode must be 'incremental' or 'full', got {mode!r}")
    today = today or today_local()
    run_id = new_run_id()
    started_at = datetime.now(timezone.utc).isoformat()
    archive = RawArchive(paths.raw)
    existing_df = read_staging(paths, source.name)
    existing = {r.draw_id: r for r in tables.frame_to_records(existing_df)}
    stop_at = max(existing, key=int) if (mode == "incremental" and existing) else None
    log.info("ingestion_start", extra={"run_id": run_id, "source": source.name, "mode": mode, "existing_rows": len(existing), "stop_at_draw_id": stop_at})

    issues: list[QualityIssue] = []
    received: list[DrawRecord] = []
    try:
        pages = 0
        for page in source.iter_raw_pages(start_date, end_date, stop_at_draw_id=stop_at):
            archive.write(run_id, page)  # raw is persisted before parsing
            received.extend(source.parse(page))
            pages += 1
        received = filter_by_date(received, start_date, end_date)
        log.info("fetch_done", extra={"run_id": run_id, "pages": pages, "rows_received": len(received)})

        candidates = dedupe_exact(received)
        # 1) record-level rules
        valid: list[DrawRecord] = []
        for r in candidates:
            rec_issues = validate_record(r, today=today)
            issues.extend(rec_issues)
            if not any(q.severity == "error" for q in rec_issues):
                valid.append(r)

        # 2) compare with already-stored rows: stored history is never rewritten
        fresh: list[DrawRecord] = []
        for r in valid:
            old = existing.get(r.draw_id)
            if old is None:
                fresh.append(r)
            elif _content_key(old) != _content_key(r):
                issues.append(QualityIssue("stored_row_conflict", "error", r.draw_id,
                                           f"source now reports {_content_key(r)} but staging has {_content_key(old)}"))

        # 3) dataset-level rules over stored + fresh rows; reject fresh rows implicated in errors
        fresh_ids = {r.draw_id for r in fresh}
        ds_issues = [q for q in validate_dataset(list(existing.values()) + fresh) if q.draw_id in fresh_ids]
        issues.extend(ds_issues)
        bad_ids = {q.draw_id for q in ds_issues if q.severity == "error"}
        inserted = [r for r in fresh if r.draw_id not in bad_ids]

        if inserted:
            merged = pd.concat([existing_df, tables.records_to_frame(inserted, run_id)], ignore_index=True)
            merged = tables.normalize_staging(merged)
            path = staging_path(paths, source.name)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            merged.to_csv(tmp, index=False)
            tmp.replace(path)  # atomic swap

        errors = sum(q.severity == "error" for q in issues)
        status = "success" if errors == 0 else "partial"
        error_message = ""
    except Exception as exc:
        log.exception("ingestion_failed", extra={"run_id": run_id})
        inserted, status, error_message = [], "failed", f"{type(exc).__name__}: {exc}"

    result = IngestionResult(
        run_id=run_id,
        source=source.name,
        mode=mode,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc).isoformat(),
        rows_received=len(received),
        rows_inserted=len(inserted),
        rows_skipped=len(received) - len(inserted),
        status=status,
        error_message=error_message,
        issues=issues,
    )
    _append_csv(paths.logs / "ingestion_log.csv", INGESTION_LOG_COLS, [{k: v for k, v in asdict(result).items() if k in INGESTION_LOG_COLS}])
    _write_quality_log(paths, run_id, issues)
    log.info("ingestion_finished", extra={k: v for k, v in asdict(result).items() if k != "issues"} | {"issues": len(issues)})
    if status == "failed":
        raise RuntimeError(f"ingestion run {run_id} failed: {error_message}")
    return result


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path` via a temp file + `os.replace` (atomic on the same filesystem).

    On Windows a `PermissionError` (e.g. an antivirus/indexer holding the file briefly) is
    retried 3 times with 1s sleeps before giving up.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    attempts = 4
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(1)


def _atomic_write_csv(path: Path, df: pd.DataFrame) -> None:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    _atomic_write_bytes(path, buf.getvalue().encode("utf-8"))


def build_curated(paths: Paths, source: str) -> dict:
    """Rebuild curated tables deterministically from one source's staging data.

    Every file is written temp + `os.replace`; `dataset_manifest.json` is written last, so it
    is the commit marker: a failure partway through leaves the previous manifest (and thus
    `curated_matches_staging`) pointing at the old, still-consistent set of files.
    """
    staging = read_staging(paths, source)
    if staging.empty:
        raise RuntimeError(f"no staging data for source {source!r}; run ingestion first")
    ds_errors = [q for q in validate_dataset(tables.frame_to_records(staging)) if q.severity == "error"]
    if ds_errors:
        raise RuntimeError(f"staging for {source!r} fails dataset rules: {ds_errors[:5]}")
    version = tables.dataset_version(staging)
    fact_draw = tables.build_fact_draw(staging, version)
    outputs = {
        "fact_draw.csv": fact_draw,
        "fact_draw_number.csv": tables.build_fact_draw_number(fact_draw),
        "dim_number.csv": tables.build_dim_number(),
    }
    paths.curated.mkdir(parents=True, exist_ok=True)
    for name, df in outputs.items():
        _atomic_write_csv(paths.curated / name, df)
    manifest = {
        "dataset_version": version,
        "source": source,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "draws": int(len(fact_draw)),
        "first_draw": {"draw_id": fact_draw["draw_id"].iloc[0], "draw_date": fact_draw["draw_date"].iloc[0]},
        "last_draw": {"draw_id": fact_draw["draw_id"].iloc[-1], "draw_date": fact_draw["draw_date"].iloc[-1]},
        "files": {name: int(len(df)) for name, df in outputs.items()},
    }
    _atomic_write_bytes(paths.curated / "dataset_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
    return manifest
