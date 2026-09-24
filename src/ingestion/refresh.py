"""`refresh`: one idempotent command that brings staging/curated/report up to date (M2-T3 §2).

The CLI acquires the run lock (`src/ingestion/lock.py`) *before* calling `run_refresh`.
`run_refresh` itself never locks, so it stays usable from tests and other library code.
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.api.registry import get_source
from src.config import LOCAL_TZ, Paths
from src.ingestion.loader import build_curated, new_run_id, read_staging, run_ingestion, staging_path
from src.reporting.data_quality import build_quality_report, write_quality_report
from src.transformation import tables
from src.validation.known_issues import load_known_issues
from src.validation.lineage import check_frozen_prefix
from src.validation.reconcile import assess_reconcile, reconcile

log = logging.getLogger(__name__)

OFFICIAL = "vietlott_official"
MIRROR = "github_mirror"

REFRESH_LOG_COLS = [
    "refresh_id", "started_at", "finished_at", "exit_code", "overall_status",
    "official_run_id", "official_status", "official_new_draws",
    "mirror_run_id", "mirror_status",
    "reconcile_status", "curate_action",
    "dataset_version_before", "dataset_version_after",
    "report_json", "report_sha256",
    "message",
]


@dataclass
class RefreshResult:
    refresh_id: str
    started_at: str
    finished_at: str
    exit_code: int
    overall_status: str
    official_run_id: str
    official_status: str
    official_new_draws: int
    mirror_run_id: str
    mirror_status: str
    reconcile_status: str
    curate_action: str
    dataset_version_before: str
    dataset_version_after: str
    report_json: str
    report_sha256: str
    message: str


def _manifest_version(paths: Paths) -> str:
    manifest_path = paths.curated / "dataset_manifest.json"
    if not manifest_path.exists():
        return ""
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")).get("dataset_version", "")
    except (OSError, ValueError):
        return ""


def _append_refresh_log(paths: Paths, row: dict) -> None:
    path = paths.logs / "refresh_log.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REFRESH_LOG_COLS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in REFRESH_LOG_COLS})


def append_locked_refresh_log_row(paths: Paths, message: str) -> None:
    """A lock-contention run (CLI exit 40): a refresh_log row with empty run columns, no ALERT.txt touch."""
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "refresh_id": "", "started_at": now, "finished_at": now, "exit_code": 40, "overall_status": "",
        "official_run_id": "", "official_status": "", "official_new_draws": "",
        "mirror_run_id": "", "mirror_status": "",
        "reconcile_status": "", "curate_action": "",
        "dataset_version_before": "", "dataset_version_after": "",
        "report_json": "", "report_sha256": "",
        "message": message,
    }
    _append_refresh_log(paths, row)


def _ingest_status(status: str, rows_received: int) -> str:
    """success | partial | failed | empty (a successful run that received 0 rows, D3)."""
    if status == "success" and rows_received == 0:
        return "empty"
    return status


def _compute_exit_code(official_status: str, curate_action: str, overall_status: str) -> int:
    """§2.3: 50 > 30 > 10 > 0."""
    if not overall_status or overall_status not in ("PASS", "WARN", "FAIL"):
        return 50
    if overall_status == "FAIL" or official_status in ("failed", "empty") or curate_action in ("blocked", "failed"):
        return 30
    if overall_status == "WARN":
        return 10
    return 0


def _write_alert(paths: Paths, text: str) -> None:
    (paths.logs / "ALERT.txt").parent.mkdir(parents=True, exist_ok=True)
    (paths.logs / "ALERT.txt").write_text(text, encoding="utf-8")


def _clear_alert(paths: Paths) -> None:
    try:
        (paths.logs / "ALERT.txt").unlink()
    except FileNotFoundError:
        pass


def run_refresh(
    paths: Paths,
    as_of: datetime | None = None,
    source_factory=get_source,
    known_issues_path: Path | None = None,
) -> RefreshResult:
    refresh_id = new_run_id()
    started_at_dt = datetime.now(timezone.utc)
    as_of_dt = as_of if as_of is not None else started_at_dt
    as_of_ict = as_of_dt.astimezone(LOCAL_TZ)
    known_issues_path = known_issues_path or (paths.config / "known_issues.json")

    _write_alert(paths, f"started, not finished {refresh_id} {started_at_dt.isoformat()}")
    log.info("refresh_start", extra={"refresh_id": refresh_id, "as_of": as_of_ict.isoformat()})

    dataset_version_before = _manifest_version(paths)

    official_run_id = official_status = ""
    official_new_draws = 0
    mirror_run_id = mirror_status = ""
    reconcile_status = "skipped"
    curate_action = "skipped"
    messages: list[str] = []
    blocking_ids: set = set()

    # --- step 1: official (always attempted first) ------------------------
    try:
        official_source = source_factory(OFFICIAL)
        result = run_ingestion(official_source, paths, mode="incremental", today=as_of_ict.date())
        official_run_id = result.run_id
        official_new_draws = result.rows_inserted
        official_status = _ingest_status(result.status, result.rows_received)
    except Exception as exc:  # every step is isolated: one failure must not stop the others
        official_status = "failed"
        messages.append(f"official: {type(exc).__name__}: {exc}")
        log.exception("refresh_official_failed", extra={"refresh_id": refresh_id})

    # --- step 2: mirror (always attempted, even if step 1 failed) ---------
    try:
        mirror_source = source_factory(MIRROR)
        result = run_ingestion(mirror_source, paths, mode="incremental", today=as_of_ict.date())
        mirror_run_id = result.run_id
        mirror_status = _ingest_status(result.status, result.rows_received)
    except Exception as exc:
        mirror_status = "failed"
        messages.append(f"mirror: {type(exc).__name__}: {exc}")
        log.exception("refresh_mirror_failed", extra={"refresh_id": refresh_id})

    # --- step 3: reconcile --------------------------------------------------
    try:
        if staging_path(paths, OFFICIAL).exists() and staging_path(paths, MIRROR).exists():
            official_df = read_staging(paths, OFFICIAL)
            mirror_df = read_staging(paths, MIRROR)
            try:
                published_ids = set(tables.read_fact_draw(paths.curated)["draw_id"])  # R3 N7
            except FileNotFoundError:
                published_ids = set()
            issues = load_known_issues(known_issues_path)
            rep = reconcile(official_df, mirror_df, OFFICIAL, MIRROR)
            assessment = assess_reconcile(rep, issues, as_of_ict, published_ids)
            reconcile_status = assessment.status
            blocking_ids = assessment.blocking_ids
        else:
            reconcile_status = "skipped"
    except Exception as exc:
        reconcile_status = "failed"
        messages.append(f"reconcile: {type(exc).__name__}: {exc}")
        log.exception("refresh_reconcile_failed", extra={"refresh_id": refresh_id})

    # --- step 4: curate -------------------------------------------------------
    try:
        if official_status in ("failed", "empty"):
            curate_action = "skipped"
        else:
            official_df = read_staging(paths, OFFICIAL)
            frozen_findings = check_frozen_prefix(official_df) if not official_df.empty else []
            if frozen_findings:
                curate_action = "blocked"
                messages.append("curate blocked: frozen_prefix violation on official staging")
            elif blocking_ids:
                curate_action = "blocked"
                messages.append(f"curate blocked: unaccepted mismatch on unpublished draw_id(s) {sorted(blocking_ids)}")
            else:
                staging_version = tables.dataset_version(official_df)
                if staging_version == _manifest_version(paths):
                    curate_action = "unchanged"
                else:
                    build_curated(paths, OFFICIAL)
                    curate_action = "rebuilt"
    except Exception as exc:
        curate_action = "failed"
        messages.append(f"curate: {type(exc).__name__}: {exc}")
        log.exception("refresh_curate_failed", extra={"refresh_id": refresh_id})

    dataset_version_after = _manifest_version(paths)

    # --- step 5: report (always run) ------------------------------------------
    report_json_path = ""
    report_sha256 = ""
    overall_status = ""
    try:
        report = build_quality_report(paths, as_of_ict, known_issues_path=known_issues_path, run_context="refresh")
        _md_path, json_path, sha = write_quality_report(report, paths.reports)
        report_json_path = str(json_path)
        report_sha256 = sha
        overall_status = report["overall_status"]
    except Exception as exc:
        messages.append(f"report: {type(exc).__name__}: {exc}")
        log.exception("refresh_report_failed", extra={"refresh_id": refresh_id})

    # --- step 6: exit code, log row, ALERT -------------------------------------
    exit_code = _compute_exit_code(official_status, curate_action, overall_status)
    finished_at_dt = datetime.now(timezone.utc)

    result = RefreshResult(
        refresh_id=refresh_id,
        started_at=started_at_dt.isoformat(),
        finished_at=finished_at_dt.isoformat(),
        exit_code=exit_code,
        overall_status=overall_status or "INTERNAL",
        official_run_id=official_run_id,
        official_status=official_status,
        official_new_draws=official_new_draws,
        mirror_run_id=mirror_run_id,
        mirror_status=mirror_status,
        reconcile_status=reconcile_status,
        curate_action=curate_action,
        dataset_version_before=dataset_version_before,
        dataset_version_after=dataset_version_after,
        report_json=report_json_path,
        report_sha256=report_sha256,
        message="; ".join(messages),
    )
    _append_refresh_log(paths, asdict(result))

    if exit_code == 0:
        _clear_alert(paths)
    else:
        _write_alert(
            paths,
            f"{result.overall_status} exit={exit_code} refresh_id={refresh_id} "
            f"report={report_json_path or '(none)'} message={result.message}",
        )

    log.info("refresh_finished", extra={
        "refresh_id": refresh_id, "exit_code": exit_code,
        "curate_action": curate_action, "overall_status": result.overall_status,
    })
    return result
