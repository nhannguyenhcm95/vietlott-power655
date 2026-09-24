"""Deterministic, offline data-quality report (M2-T2).

Turns curated + staging + raw + logs + known issues into one PASS/WARN/FAIL verdict,
`reports/data_quality_<date>.md` and `.json`. See
docs/design/M2-data-quality-and-refresh.md section 1.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from src.config import LOCAL_TZ, Paths
from src.ingestion.raw_archive import RawArchive
from src.transformation import tables
from src.validation import schedule
from src.validation.findings import Finding
from src.validation.known_issues import (
    KnownIssue,
    KnownIssuesError,
    RULES,
    apply_known_issue,
    issue_state,
    load_known_issues,
)
from src.validation.lineage import check_frozen_prefix, check_raw_lineage, received_ids
from src.validation.reconcile import assess_reconcile, reconcile
from src.validation.rules import validate_dataset, validate_record

SCHEMA_VERSION = "1.0"
DRAW_TIME_LOCAL = schedule.DRAW_TIME_LOCAL
OFFICIAL = "vietlott_official"
MIRROR = "github_mirror"

FACT_DRAW_COLS = ["draw_id", "draw_date", *tables.MAIN_COLS, "special_number", "source", "retrieved_at", "dataset_version"]
FACT_DRAW_NUMBER_COLS = ["draw_id", "draw_date", "position", "number", "is_special"]
DIM_NUMBER_COLS = ["number", "parity", "band", "decade_group"]
MANIFEST_KEYS = {"dataset_version", "source", "built_at", "draws", "first_draw", "last_draw", "files"}


@dataclass
class CheckResult:
    check_id: str
    status: str
    summary: str
    metrics: dict
    findings: list[Finding]


@dataclass
class _Ctx:
    paths: Paths
    as_of: datetime           # ICT, second precision
    known_issues_path: Path
    issues: list[KnownIssue] = field(default_factory=list)
    matched: dict = field(default_factory=dict)   # {ki_id: {rule: count}}
    inputs: list = field(default_factory=list)
    official_staging: pd.DataFrame | None = None
    mirror_staging: pd.DataFrame | None = None
    curated_fact_draw: pd.DataFrame | None = None
    curated_fact_draw_number: pd.DataFrame | None = None
    curated_dim_number: pd.DataFrame | None = None
    curated_manifest: dict | None = None
    ingestion_log: pd.DataFrame | None = None
    quality_log: pd.DataFrame | None = None
    refresh_log: pd.DataFrame | None = None

    def record_input(self, path: Path, rows: int | None = None) -> None:
        if not path.exists():
            return
        data = path.read_bytes()
        self.inputs.append({
            "path": _relpath(path, self.paths.root),
            "sha256": hashlib.sha256(data).hexdigest(),
            "rows": rows,
        })

    def last_draw_date(self) -> date | None:
        if self.curated_fact_draw is not None and not self.curated_fact_draw.empty:
            return date.fromisoformat(str(self.curated_fact_draw["draw_date"].iloc[-1]))
        if self.official_staging is not None and not self.official_staging.empty:
            return date.fromisoformat(str(self.official_staging["draw_date"].iloc[-1]))
        return None


def _relpath(path: Path, root: Path) -> str:
    try:
        rel = Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        rel = Path(path)
    return rel.as_posix()


def _annotate(ctx: _Ctx, findings: list[Finding]) -> list[Finding]:
    for f in findings:
        if f.known_issue_id is None:
            apply_known_issue(f, ctx.issues, ctx.as_of)
        if f.known_issue_id:
            per_rule = ctx.matched.setdefault(f.known_issue_id, {})
            per_rule[f.rule] = per_rule.get(f.rule, 0) + 1
    return findings


def _status_of(findings: list[Finding]) -> str:
    levels = {f.level for f in findings if not f.accepted}
    if "FAIL" in levels:
        return "FAIL"
    if "WARN" in levels:
        return "WARN"
    return "PASS"


def _finalize(ctx: _Ctx, check_id: str, findings: list[Finding], metrics: dict | None = None) -> CheckResult:
    findings = _annotate(ctx, findings)
    findings = sorted(findings, key=lambda f: f.sort_key())
    status = _status_of(findings)
    unaccepted = sum(1 for f in findings if not f.accepted and f.level in ("FAIL", "WARN"))
    summary = f"{status}: {len(findings)} finding(s), {unaccepted} unaccepted"
    return CheckResult(check_id, status, summary, metrics or {}, findings)


def _read_csv(path: Path, dtype: dict | None = None) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path, dtype=dtype)


# --------------------------------------------------------------------------- known_issues.file
def check_known_issues_file(ctx: _Ctx) -> CheckResult:
    path = ctx.known_issues_path
    findings: list[Finding] = []
    if not path.exists():
        findings.append(Finding("system", None, None, "known_issues_absent", "INFO",
                                 "configs/known_issues.json is absent"))
        ctx.issues = []
        return _finalize(ctx, "known_issues.file", findings)

    ctx.record_input(path)
    try:
        ctx.issues = load_known_issues(path)
    except KnownIssuesError as exc:
        findings.append(Finding("system", None, None, "known_issues_file", "FAIL", str(exc)))
        ctx.issues = []
        return _finalize(ctx, "known_issues.file", findings)
    return _finalize(ctx, "known_issues.file", findings)


def _finish_known_issues_file(ctx: _Ctx, result: CheckResult) -> CheckResult:
    """Append per-entry proposed/expired/unused findings once all checks have matched."""
    findings = list(result.findings)
    seen_rules_used: set[str] = set()
    for ki in ctx.issues:
        state = issue_state(ki, ctx.as_of)
        total_matched = sum(ctx.matched.get(ki.id, {}).values())
        elapsed = ki.draw_date_to is not None and ctx.as_of.astimezone(LOCAL_TZ).date() > ki.draw_date_to
        level = "INFO" if elapsed else "WARN"
        if state == "proposed":
            findings.append(Finding("system", None, None, "known_issue_proposed", level, f"{ki.id} is proposed, not approved",
                                     observed={"known_issue_id": ki.id}))
        elif state == "expired":
            findings.append(Finding("system", None, None, "known_issue_expired", level, f"{ki.id} is past review_by {ki.review_by}",
                                     observed={"known_issue_id": ki.id}))
        if total_matched == 0:
            findings.append(Finding("system", None, None, "known_issue_unused", level, f"{ki.id} matched no findings",
                                     observed={"known_issue_id": ki.id}))
        for rule in ki.rules:
            if ctx.matched.get(ki.id, {}).get(rule, 0) == 0:
                findings.append(Finding("system", None, None, "known_issue_rule_unused", "INFO",
                                         f"{ki.id}: rule {rule!r} matched no findings",
                                         observed={"known_issue_id": ki.id, "rule": rule}))
    findings = _annotate(ctx, findings)
    findings = sorted(findings, key=lambda f: f.sort_key())
    status = _status_of(findings)
    unaccepted = sum(1 for f in findings if not f.accepted and f.level in ("FAIL", "WARN"))
    summary = f"{status}: {len(findings)} finding(s), {unaccepted} unaccepted"
    return CheckResult("known_issues.file", status, summary, result.metrics, findings)


# --------------------------------------------------------------------------- curated.schema
def check_curated_schema(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    curated = ctx.paths.curated
    manifest_path = curated / "dataset_manifest.json"
    files = {"fact_draw.csv": FACT_DRAW_COLS, "fact_draw_number.csv": FACT_DRAW_NUMBER_COLS, "dim_number.csv": DIM_NUMBER_COLS}
    missing = [name for name in list(files) + ["dataset_manifest.json"] if not (curated / name).exists()]
    if missing:
        findings.append(Finding(OFFICIAL, None, None, "input_missing", "FAIL",
                                 f"curated files missing: {missing}"))
        return _finalize(ctx, "curated.schema", findings)

    for name in files:
        ctx.record_input(curated / name, rows=len(pd.read_csv(curated / name)))
    ctx.record_input(manifest_path)
    ctx.curated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for name, expected_cols in files.items():
        actual = list(pd.read_csv(curated / name, nrows=0).columns)
        if actual != expected_cols:
            findings.append(Finding(OFFICIAL, None, None, "curated_schema", "FAIL",
                                     f"{name} columns {actual} != expected {expected_cols}"))
    manifest_keys = set(ctx.curated_manifest)
    if manifest_keys != MANIFEST_KEYS:
        findings.append(Finding(OFFICIAL, None, None, "curated_schema", "FAIL",
                                 f"manifest keys {sorted(manifest_keys)} != expected {sorted(MANIFEST_KEYS)}"))

    if not findings:
        # Only load the tables for later checks once the schema is known to be sound;
        # a malformed schema must not crash downstream checks.
        ctx.curated_fact_draw = tables.read_fact_draw(curated)
        ctx.curated_fact_draw_number = pd.read_csv(curated / "fact_draw_number.csv", dtype={"draw_id": str, "draw_date": str})
        ctx.curated_dim_number = pd.read_csv(curated / "dim_number.csv")
    return _finalize(ctx, "curated.schema", findings)


# --------------------------------------------------------------------------- curated.lineage
def check_curated_lineage(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    if ctx.curated_fact_draw is None:
        return _finalize(ctx, "curated.lineage", findings)  # already FAILed by curated.schema

    fact = ctx.curated_fact_draw
    manifest = ctx.curated_manifest or {}
    if ctx.official_staging is not None and not ctx.official_staging.empty:
        staging_version = tables.dataset_version(ctx.official_staging)
        curated_version = tables.dataset_version(fact)
        manifest_version = manifest.get("dataset_version")
        if not (staging_version == curated_version == manifest_version):
            findings.append(Finding(OFFICIAL, None, None, "curated_matches_staging", "FAIL",
                                     f"versions differ: staging={staging_version} curated={curated_version} manifest={manifest_version}"))

    if manifest:
        expected_files = manifest.get("files", {})
        actual_files = {
            "fact_draw.csv": len(fact),
            "fact_draw_number.csv": len(ctx.curated_fact_draw_number) if ctx.curated_fact_draw_number is not None else -1,
            "dim_number.csv": len(ctx.curated_dim_number) if ctx.curated_dim_number is not None else -1,
        }
        if expected_files != actual_files:
            findings.append(Finding(OFFICIAL, None, None, "manifest_consistency", "FAIL",
                                     f"manifest file counts {expected_files} != actual {actual_files}"))
        n_special = int(fact["special_number"].notna().sum())
        expected_number_rows = 6 * len(fact) + n_special
        if ctx.curated_fact_draw_number is not None and len(ctx.curated_fact_draw_number) != expected_number_rows:
            findings.append(Finding(OFFICIAL, None, None, "manifest_consistency", "FAIL",
                                     f"fact_draw_number has {len(ctx.curated_fact_draw_number)} rows, expected {expected_number_rows}"))
        if fact["dataset_version"].nunique() != 1:
            findings.append(Finding(OFFICIAL, None, None, "manifest_consistency", "FAIL", "fact_draw has more than one dataset_version"))
        if not (fact["source"] == manifest.get("source")).all():
            findings.append(Finding(OFFICIAL, None, None, "manifest_consistency", "FAIL", "fact_draw.source does not match the manifest source"))

    findings.extend(check_frozen_prefix(fact))
    if ctx.official_staging is not None and not ctx.official_staging.empty:
        findings.extend(check_frozen_prefix(ctx.official_staging))
        findings.extend(check_raw_lineage(ctx.official_staging, ctx.paths, OFFICIAL))
    if ctx.mirror_staging is not None and not ctx.mirror_staging.empty:
        findings.extend(check_raw_lineage(ctx.mirror_staging, ctx.paths, MIRROR))

    return _finalize(ctx, "curated.lineage", findings)


# --------------------------------------------------------------------------- curated.missing
def check_curated_missing(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    if ctx.curated_fact_draw is None:
        return _finalize(ctx, "curated.missing", findings)
    fact = ctx.curated_fact_draw
    required = ["draw_id", "draw_date", *tables.MAIN_COLS]
    for col in required:
        n_null = int(fact[col].isna().sum())
        if n_null:
            findings.append(Finding(OFFICIAL, None, None, "null_required", "FAIL", f"{n_null} null value(s) in {col}"))
    for row in fact[fact["special_number"].isna()].itertuples(index=False):
        findings.append(Finding(OFFICIAL, row.draw_id, row.draw_date, "special_present", "WARN", "special number missing"))
    return _finalize(ctx, "curated.missing", findings, metrics={"rows": len(fact)})


# --------------------------------------------------------------------------- curated.duplicates
def check_curated_duplicates(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    if ctx.curated_fact_draw is None:
        return _finalize(ctx, "curated.duplicates", findings)
    fact = ctx.curated_fact_draw
    for draw_id, count in fact["draw_id"].value_counts().items():
        if count > 1:
            findings.append(Finding(OFFICIAL, draw_id, None, "draw_id_unique", "FAIL", f"{count} rows for draw_id {draw_id}"))
    for draw_date, count in fact["draw_date"].value_counts().items():
        if count > 1:
            findings.append(Finding(OFFICIAL, None, draw_date, "draw_date_unique", "FAIL", f"{count} rows for draw_date {draw_date}"))
    if ctx.curated_fact_draw_number is not None:
        dupes = ctx.curated_fact_draw_number.groupby(["draw_id", "position"]).size()
        for (draw_id, position), count in dupes[dupes > 1].items():
            findings.append(Finding(OFFICIAL, draw_id, None, "position_unique", "FAIL", f"{count} rows for (draw_id={draw_id}, position={position})"))
    records = tables.frame_to_records(fact)
    for q in validate_dataset(records):
        if q.rule == "duplicate_content":
            findings.append(Finding(OFFICIAL, q.draw_id, None, "duplicate_content", "WARN", q.detail))
    return _finalize(ctx, "curated.duplicates", findings)


# --------------------------------------------------------------------------- curated.ranges
def check_curated_ranges(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    if ctx.curated_fact_draw is None:
        return _finalize(ctx, "curated.ranges", findings)
    fact = ctx.curated_fact_draw
    records = tables.frame_to_records(fact)
    today = ctx.as_of.astimezone(LOCAL_TZ).date()
    for r in records:
        for q in validate_record(r, today=today):
            level = "FAIL" if q.severity == "error" else "WARN"
            findings.append(Finding(OFFICIAL, r.draw_id, r.draw_date.isoformat(), q.rule, level, q.detail))
    for q in validate_dataset(records):
        if q.rule in ("chronological_order", "draw_id_continuity"):
            level = "FAIL" if q.severity == "error" else "WARN"
            findings.append(Finding(OFFICIAL, q.draw_id, None, q.rule, level, q.detail))

    deadline = pd.to_datetime(fact["draw_date"]).dt.tz_localize(LOCAL_TZ) + timedelta(hours=DRAW_TIME_LOCAL.hour)
    retrieved = pd.to_datetime(fact["retrieved_at"], utc=True, format="ISO8601").dt.tz_convert(LOCAL_TZ)
    late = fact[(retrieved < deadline).to_numpy()]
    for row in late.itertuples(index=False):
        findings.append(Finding(OFFICIAL, row.draw_id, row.draw_date, "retrieved_after_draw", "FAIL",
                                 f"retrieved_at {row.retrieved_at} is before draw {row.draw_date} 18:00 ICT"))
    return _finalize(ctx, "curated.ranges", findings)


# --------------------------------------------------------------------------- coverage.gaps
def check_coverage_gaps(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    if ctx.curated_fact_draw is None or ctx.curated_fact_draw.empty:
        return _finalize(ctx, "coverage.gaps", findings)
    fact = ctx.curated_fact_draw
    first_id, first_date = fact["draw_id"].iloc[0], fact["draw_date"].iloc[0]
    if not (first_id == "00001" and first_date == "2017-08-01"):
        findings.append(Finding(OFFICIAL, first_id, first_date, "first_draw", "FAIL",
                                 f"first curated row is {first_id} on {first_date}, expected 00001 on 2017-08-01"))

    dates = [date.fromisoformat(str(d)) for d in fact["draw_date"]]
    for prev, cur in zip(dates, dates[1:]):
        if schedule.scheduled_draw_dates(prev + timedelta(days=1), cur - timedelta(days=1)):
            findings.append(Finding(OFFICIAL, None, cur.isoformat(), "draw_cadence", "INFO",
                                     f"gap from {prev} to {cur} skips at least one scheduled draw date"))
    return _finalize(ctx, "coverage.gaps", findings, metrics={"draws": len(fact)})


# --------------------------------------------------------------------------- coverage.freshness
def check_coverage_freshness(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    last = ctx.last_draw_date()
    if last is None:
        return _finalize(ctx, "coverage.freshness", findings)

    missed = schedule.missed_scheduled_draws(last, ctx.as_of)
    for d in missed:
        findings.append(Finding(OFFICIAL, None, d.isoformat(), "freshness", "WARN", f"no draw recorded for scheduled date {d}"))
    findings = _annotate(ctx, findings)

    unaccepted = sum(1 for f in findings if not f.accepted)
    if unaccepted > 6:
        for f in findings:
            if not f.accepted:
                f.level = "FAIL"

    next_scheduled = schedule.scheduled_draw_dates(last + timedelta(days=1), last + timedelta(days=14))
    next_scheduled = [d for d in next_scheduled if d not in missed]
    if next_scheduled:
        nxt = next_scheduled[0]
        deadline = datetime.combine(nxt, schedule.PUBLICATION_DEADLINE_LOCAL, tzinfo=LOCAL_TZ)
        if deadline > ctx.as_of.astimezone(LOCAL_TZ):
            findings.append(Finding(OFFICIAL, None, nxt.isoformat(), "freshness_pending", "INFO",
                                     f"draw scheduled for {nxt} has not yet reached its 21:00 ICT publication deadline"))

    findings = sorted(_annotate(ctx, findings), key=lambda f: f.sort_key())
    status = _status_of(findings)
    unacc = sum(1 for f in findings if not f.accepted and f.level in ("FAIL", "WARN"))
    return CheckResult("coverage.freshness", status, f"{status}: {len(findings)} finding(s), {unacc} unaccepted", {"missed": len(missed)}, findings)


# --------------------------------------------------------------------------- staging.schema
def check_staging_schema(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    for source, path in ((OFFICIAL, ctx.paths.staging / OFFICIAL / "draws.csv"), (MIRROR, ctx.paths.staging / MIRROR / "draws.csv")):
        level = "FAIL" if source == OFFICIAL else "WARN"
        if not path.exists():
            findings.append(Finding(source, None, None, "input_missing", level, f"{path} is absent"))
            continue
        df = pd.read_csv(path, dtype={"draw_id": str, "draw_date": str}, nrows=0)
        ctx.record_input(path, rows=sum(1 for _ in open(path, encoding="utf-8")) - 1)
        actual = list(df.columns)
        if actual != tables.STAGING_COLS:
            findings.append(Finding(source, None, None, "staging_schema", level,
                                     f"{source} staging columns {actual} != expected {tables.STAGING_COLS}"))
        full = pd.read_csv(path, dtype={"draw_id": str, "draw_date": str})
        full = tables.normalize_staging(full) if actual == tables.STAGING_COLS else full
        if source == OFFICIAL:
            ctx.official_staging = full
        else:
            ctx.mirror_staging = full
    return _finalize(ctx, "staging.schema", findings)


# --------------------------------------------------------------------------- ingestion.runs
def _has_stored_rows(log: pd.DataFrame, source: str, before_run_id: str | None = None) -> bool:
    rows = log[log["source"] == source]
    if before_run_id is not None:
        rows = rows[rows["run_id"] != before_run_id]
    return bool((rows["rows_inserted"] > 0).any())


def check_ingestion_runs(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    path = ctx.paths.logs / "ingestion_log.csv"
    if not path.exists():
        findings.append(Finding("system", None, None, "input_missing", "FAIL", f"{path} is absent"))
        return _finalize(ctx, "ingestion.runs", findings)
    log = pd.read_csv(path, dtype={"run_id": str, "source": str})
    ctx.ingestion_log = log
    ctx.record_input(path, rows=len(log))

    for source in (OFFICIAL, MIRROR):
        runs = log[log["source"] == source]
        if runs.empty:
            continue
        latest = runs.iloc[-1]
        level = "FAIL" if source == OFFICIAL else "WARN"
        if latest["status"] == "failed":
            findings.append(Finding(source, None, None, "run_failed", level, f"latest {source} run {latest['run_id']} failed: {latest.get('error_message', '')}"))
        elif latest["status"] == "partial":
            plevel = "WARN" if source == OFFICIAL else "INFO"
            findings.append(Finding(source, None, None, "run_partial", plevel, f"latest {source} run {latest['run_id']} is partial"))
        if latest["mode"] == "incremental" and int(latest["rows_received"]) == 0 and _has_stored_rows(log, source, latest["run_id"]):
            findings.append(Finding(source, None, None, "incremental_empty_fetch", level,
                                     f"latest {source} incremental run {latest['run_id']} received 0 rows"))

        if source == MIRROR:
            manifest_runs = [rid for rid in runs["run_id"] if (ctx.paths.raw / MIRROR / rid / "manifest.jsonl").exists()]
            if manifest_runs:
                latest_manifest_run = manifest_runs[-1]
                received = received_ids(ctx.paths, MIRROR, latest_manifest_run)
                staged = set(ctx.mirror_staging["draw_id"]) if ctx.mirror_staging is not None else set()
                if received and staged:
                    shrink = (max(int(i) for i in received) < max(int(i) for i in staged)) or not staged.issubset(received)
                    if shrink:
                        findings.append(Finding(MIRROR, None, None, "mirror_shrink", "WARN",
                                                 f"mirror run {latest_manifest_run} received {len(received)} ids, fewer/different than staged {len(staged)}"))
    return _finalize(ctx, "ingestion.runs", findings, metrics={"runs": len(log)})


# --------------------------------------------------------------------------- quality_log.open
def check_quality_log_open(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    path = ctx.paths.logs / "quality_log.csv"
    any_partial = False
    partial_source = None
    if ctx.ingestion_log is not None:
        partial = ctx.ingestion_log[ctx.ingestion_log["status"] == "partial"]
        any_partial = not partial.empty
        if any_partial:
            partial_source = partial.iloc[-1]["source"]

    if not path.exists():
        if not any_partial:
            findings.append(Finding("system", None, None, "input_missing", "INFO", f"{path} is absent"))
        else:
            level = "FAIL" if partial_source == OFFICIAL else "WARN"
            findings.append(Finding("system", None, None, "log_integrity", level,
                                     f"{path} is absent while a {partial_source} run is partial"))
        return _finalize(ctx, "quality_log.open", findings)

    qlog = pd.read_csv(path, dtype={"run_id": str, "draw_id": str})
    ctx.quality_log = qlog
    ctx.record_input(path, rows=len(qlog))

    run_source = {}
    if ctx.ingestion_log is not None:
        run_source = dict(zip(ctx.ingestion_log["run_id"], ctx.ingestion_log["source"]))

    errors = qlog[qlog["status"] == "error"]
    for row in errors.itertuples(index=False):
        source = run_source.get(row.run_id)
        if source is None:
            findings.append(Finding("system", row.run_id, None, "log_integrity", "WARN",
                                     f"quality_log row references unknown run_id {row.run_id}"))
            continue
        staging = ctx.official_staging if source == OFFICIAL else ctx.mirror_staging
        staged_ids = set(staging["draw_id"]) if staging is not None else set()
        if row.rule == "stored_row_conflict":
            resolved = row.draw_id in received_run_ids_cache(ctx, source, row.run_id, run_source, qlog)
        else:
            resolved = row.draw_id in staged_ids
        level = "INFO" if resolved else ("FAIL" if source == OFFICIAL else "WARN")
        detail = f"{'resolved' if resolved else 'open'}: {row.rule} on draw {row.draw_id} ({row.detail})"
        findings.append(Finding(source, row.draw_id, None, row.rule, level, detail))
    return _finalize(ctx, "quality_log.open", findings, metrics={"rows": len(qlog)})


def received_run_ids_cache(ctx: _Ctx, source: str, run_id: str, run_source: dict, qlog: pd.DataFrame) -> set:
    """draw_ids `source` has received in any run after `run_id`, with no conflict logged for them."""
    if ctx.ingestion_log is None:
        return set()
    later_runs = ctx.ingestion_log[(ctx.ingestion_log["source"] == source) & (ctx.ingestion_log["run_id"] > run_id)]
    conflicted = set(qlog[(qlog["rule"] == "stored_row_conflict") & (qlog["run_id"].isin(later_runs["run_id"]))]["draw_id"])
    ok: set = set()
    for later_run_id in later_runs["run_id"]:
        if (ctx.paths.raw / source / later_run_id / "manifest.jsonl").exists():
            try:
                ok |= received_ids(ctx.paths, source, later_run_id) - conflicted
            except FileNotFoundError:
                continue
    return ok


# --------------------------------------------------------------------------- reconcile.sources
def check_reconcile_sources(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    if ctx.official_staging is None or ctx.official_staging.empty:
        return _finalize(ctx, "reconcile.sources", findings)
    if ctx.mirror_staging is None or ctx.mirror_staging.empty:
        findings.append(Finding(MIRROR, None, None, "reconcile.not_run", "WARN", "mirror staging is absent or empty; reconcile not run"))
        return _finalize(ctx, "reconcile.sources", findings)

    published_ids = set(ctx.curated_fact_draw["draw_id"]) if ctx.curated_fact_draw is not None else set()
    rep = reconcile(ctx.official_staging, ctx.mirror_staging, OFFICIAL, MIRROR)
    assessment = assess_reconcile(rep, ctx.issues, ctx.as_of, published_ids)
    findings.extend(assessment.findings)
    for f in findings:
        if f.known_issue_id:
            per_rule = ctx.matched.setdefault(f.known_issue_id, {})
            per_rule[f.rule] = per_rule.get(f.rule, 0) + 1
    findings = sorted(findings, key=lambda f: f.sort_key())
    status = _status_of(findings)
    unacc = sum(1 for f in findings if not f.accepted and f.level in ("FAIL", "WARN"))
    return CheckResult("reconcile.sources", status, f"{status}: {len(findings)} finding(s), {unacc} unaccepted",
                        {"matched": rep.matched, "mirror_lag_draws": assessment.mirror_lag_draws}, findings)


# --------------------------------------------------------------------------- raw.checksums
def check_raw_checksums(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    archive = RawArchive(ctx.paths.raw)
    manifests = sorted(ctx.paths.raw.glob("*/*/manifest.jsonl"))
    for manifest in manifests:
        source, run_id = manifest.parent.parent.name, manifest.parent.name
        ctx.record_input(manifest)
        try:
            bad = archive.verify(source, run_id)
        except FileNotFoundError:
            findings.append(Finding(source, None, None, "raw_manifest_missing", "WARN", f"a file referenced by {source}/{run_id} is missing"))
            continue
        for name in bad:
            findings.append(Finding(source, None, None, "raw_checksum", "FAIL", f"{source}/{run_id}/{name} checksum mismatch"))
    return _finalize(ctx, "raw.checksums", findings, metrics={"runs": len(manifests)})


# --------------------------------------------------------------------------- refresh.history
def check_refresh_history(ctx: _Ctx) -> CheckResult:
    findings: list[Finding] = []
    path = ctx.paths.logs / "refresh_log.csv"
    if not path.exists():
        findings.append(Finding("system", None, None, "input_missing", "INFO", f"{path} is absent"))
        return _finalize(ctx, "refresh.history", findings)
    log = pd.read_csv(path, dtype=str)
    ctx.refresh_log = log
    ctx.record_input(path, rows=len(log))
    tail = log.tail(10)
    for row in tail.itertuples(index=False):
        findings.append(Finding("system", None, None, "refresh_history", "INFO",
                                 f"refresh {row.refresh_id}: exit={row.exit_code} status={row.overall_status}"))
    return _finalize(ctx, "refresh.history", findings, metrics={"rows": len(log)})


CHECK_FUNCS = [
    check_known_issues_file,
    check_staging_schema,   # loads official/mirror staging, needed by later checks
    check_curated_schema,
    check_curated_lineage,
    check_curated_missing,
    check_curated_duplicates,
    check_curated_ranges,
    check_coverage_gaps,
    check_coverage_freshness,
    check_ingestion_runs,
    check_quality_log_open,
    check_reconcile_sources,
    check_raw_checksums,
    check_refresh_history,
]

# The output order follows section 1.3 exactly.
CHECK_ORDER = [
    "known_issues.file", "curated.schema", "curated.lineage", "curated.missing", "curated.duplicates",
    "curated.ranges", "coverage.gaps", "coverage.freshness", "staging.schema", "ingestion.runs",
    "quality_log.open", "reconcile.sources", "raw.checksums", "refresh.history",
]


def _summary_counts(checks: dict) -> dict:
    def findings_of(check_id):
        return checks[check_id].findings if check_id in checks else []

    def unaccepted(fs):
        return [f for f in fs if not f.accepted and f.level in ("FAIL", "WARN")]

    missing = len(unaccepted(findings_of("curated.missing")))
    duplicate = len(unaccepted(findings_of("curated.duplicates")))
    invalid_ranges = len(unaccepted(findings_of("curated.ranges")))
    schema_errors = len(unaccepted(findings_of("curated.schema"))) + len(unaccepted(findings_of("staging.schema")))
    ingestion_failures_log = 0  # filled by caller using ingestion_log rows
    accepted = sum(len([f for f in cr.findings if f.accepted]) for cr in checks.values())
    proposed = sum(len([f for f in cr.findings if f.known_issue_state in ("proposed", "expired")]) for cr in checks.values())
    return {
        "missing": missing, "duplicate": duplicate, "invalid_ranges": invalid_ranges,
        "schema_errors": schema_errors, "ingestion_failures": ingestion_failures_log,
        "accepted": accepted, "proposed": proposed,
    }


def build_quality_report(paths: Paths, as_of: datetime, known_issues_path: Path | None = None, run_context: str = "standalone") -> dict:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    as_of_ict = as_of.astimezone(LOCAL_TZ).replace(microsecond=0)
    report_date = as_of_ict.date()
    ki_path = Path(known_issues_path) if known_issues_path is not None else paths.config / "known_issues.json"

    ctx = _Ctx(paths=paths, as_of=as_of_ict, known_issues_path=ki_path)

    checks: dict[str, CheckResult] = {}
    for fn in CHECK_FUNCS:
        result = fn(ctx)
        checks[result.check_id] = result
    checks["known_issues.file"] = _finish_known_issues_file(ctx, checks["known_issues.file"])

    ingestion_failures = 0
    if ctx.ingestion_log is not None:
        ingestion_failures += int((ctx.ingestion_log["status"] == "failed").sum())
    ingestion_failures += sum(
        1 for f in checks["ingestion.runs"].findings if f.rule == "incremental_empty_fetch" and not f.accepted
    )
    summary = _summary_counts(checks)
    summary["ingestion_failures"] = ingestion_failures

    statuses = [cr.status for cr in checks.values()]
    overall_status = "FAIL" if "FAIL" in statuses else ("WARN" if "WARN" in statuses else "PASS")

    dataset = {}
    if ctx.curated_manifest:
        dataset = {
            "dataset_version": ctx.curated_manifest.get("dataset_version"),
            "source": ctx.curated_manifest.get("source"),
            "draws": ctx.curated_manifest.get("draws"),
            "first_draw_id": ctx.curated_manifest.get("first_draw", {}).get("draw_id"),
            "first_draw_date": ctx.curated_manifest.get("first_draw", {}).get("draw_date"),
            "last_draw_id": ctx.curated_manifest.get("last_draw", {}).get("draw_id"),
            "last_draw_date": ctx.curated_manifest.get("last_draw", {}).get("draw_date"),
        }

    ingestion_runs = []
    if ctx.ingestion_log is not None:
        for row in ctx.ingestion_log.itertuples(index=False):
            d = row._asdict() if hasattr(row, "_asdict") else dict(zip(ctx.ingestion_log.columns, row))
            rejected = 0
            if ctx.quality_log is not None:
                rejected = int(ctx.quality_log[(ctx.quality_log["run_id"] == d["run_id"]) & (ctx.quality_log["status"] == "error")]["draw_id"].nunique())
            d["rows_rejected"] = rejected
            ingestion_runs.append({k: (None if pd.isna(v) else v) for k, v in d.items()})

    known_issues_out = [
        {"id": ki.id, "state": issue_state(ki, as_of_ict), "matched": ctx.matched.get(ki.id, {})}
        for ki in ctx.issues
    ]

    report = {
        "schema_version": SCHEMA_VERSION,
        "report_date": report_date.isoformat(),
        "as_of": as_of_ict.isoformat(),
        "run_context": run_context,
        "lock_held": (paths.data / ".refresh.lock").exists(),
        "overall_status": overall_status,
        "summary": summary,
        "dataset": dataset,
        "inputs": sorted(ctx.inputs, key=lambda i: i["path"]),
        "checks": [
            {
                "check_id": cid,
                "status": checks[cid].status,
                "summary": checks[cid].summary,
                "metrics": checks[cid].metrics,
                "findings": [f.to_dict() for f in checks[cid].findings],
            }
            for cid in CHECK_ORDER
        ],
        "ingestion_runs": ingestion_runs,
        "known_issues": known_issues_out,
    }
    return report


def render_markdown(report: dict) -> str:
    lines = []
    lines.append(f"# Data quality report — {report['report_date']}")
    lines.append("")
    lines.append(f"Overall status: **{report['overall_status']}** (as of {report['as_of']}, run_context={report['run_context']})")
    lines.append("")
    s = report["summary"]
    lines.append(f"Summary: missing={s['missing']} duplicate={s['duplicate']} invalid_ranges={s['invalid_ranges']} "
                 f"schema_errors={s['schema_errors']} ingestion_failures={s['ingestion_failures']} "
                 f"accepted={s['accepted']} proposed={s['proposed']}")
    lines.append("")
    if report["dataset"]:
        d = report["dataset"]
        lines.append(f"Dataset: {d.get('dataset_version')} — {d.get('draws')} draws, "
                     f"{d.get('first_draw_id')} ({d.get('first_draw_date')}) .. {d.get('last_draw_id')} ({d.get('last_draw_date')})")
        lines.append("")

    for check in report["checks"]:
        accepted_n = sum(1 for f in check["findings"] if f["accepted"])
        proposed_n = sum(1 for f in check["findings"] if f["known_issue_state"] in ("proposed", "expired"))
        lines.append(f"## {check['check_id']} — {check['status']} — {accepted_n} accepted, {proposed_n} proposed")
        lines.append("")
        shown = check["findings"][:20]
        if shown:
            lines.append("| source | draw_id | draw_date | rule | level | accepted | detail |")
            lines.append("|---|---|---|---|---|---|---|")
            for f in shown:
                lines.append(f"| {f['source']} | {f['draw_id'] or ''} | {f['draw_date'] or ''} | {f['rule']} | "
                              f"{f['level']} | {f['accepted']} | {f['detail']} |")
            if len(check["findings"]) > 20:
                lines.append("")
                lines.append(f"+{len(check['findings']) - 20} more; see JSON")
        else:
            lines.append("No findings.")
        lines.append("")

    lines.append("## Ingestion runs (last 20)")
    lines.append("")
    runs = report["ingestion_runs"][-20:]
    if runs:
        lines.append("| run_id | source | mode | status | received | inserted | skipped | rejected |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in runs:
            lines.append(f"| {r.get('run_id')} | {r.get('source')} | {r.get('mode')} | {r.get('status')} | "
                          f"{r.get('rows_received')} | {r.get('rows_inserted')} | {r.get('rows_skipped')} | {r.get('rows_rejected')} |")
    else:
        lines.append("No ingestion runs.")
    lines.append("")

    lines.append("## Known issues: accepted / proposed / expired")
    lines.append("")
    if report["known_issues"]:
        lines.append("| id | state | matched |")
        lines.append("|---|---|---|")
        for ki in report["known_issues"]:
            lines.append(f"| {ki['id']} | {ki['state']} | {ki['matched']} |")
    else:
        lines.append("No known issues registered.")
    lines.append("")

    return "\n".join(lines) + "\n"


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    for attempt in range(4):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 3:
                raise
            import time as _time
            _time.sleep(1)


def write_quality_report(report: dict, out_dir: Path) -> tuple[Path, Path, str]:
    out_dir = Path(out_dir)
    json_bytes = (json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n").replace("\r\n", "\n").encode("utf-8")
    sha256 = hashlib.sha256(json_bytes).hexdigest()
    md_bytes = render_markdown(report).encode("utf-8")

    json_path = out_dir / f"data_quality_{report['report_date']}.json"
    md_path = out_dir / f"data_quality_{report['report_date']}.md"
    latest_path = out_dir / "data_quality_latest.json"

    _write_atomic(json_path, json_bytes)
    _write_atomic(md_path, md_bytes)
    _write_atomic(latest_path, json_bytes)
    return md_path, json_path, sha256
