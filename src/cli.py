"""Command line entry point.

    python -m src.cli ingest --source vietlott_official [--full] [--start 2017-08-01] [--end 2026-09-24]
    python -m src.cli curate --source vietlott_official
    python -m src.cli reconcile --left vietlott_official --right github_mirror
    python -m src.cli verify-raw
    python -m src.cli quality-report [--as-of ISO8601] [--out-dir reports] [--known-issues configs/known_issues.json]
    python -m src.cli refresh [--lock-timeout-minutes 120] [--as-of ISO8601]
    python -m src.cli status
    python -m src.cli eda [--through-draw 01190] [--out-dir outputs/eda] [--windows 50,100,200]
                           [--n-blocks 5] [--mc-reps 10000] [--override-ceiling REF]
    python -m src.cli m4 [--through-draw 01190] [--out-dir outputs/m4] [--reps 10000]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from pathlib import Path

import pandas as pd

from src.api.registry import SOURCES, get_source
from src.config import LOCAL_TZ, Paths
from src.ingestion.loader import build_curated, read_staging, run_ingestion, staging_path
from src.ingestion.lock import LockHeldError, RunLock
from src.ingestion.raw_archive import RawArchive
from src.ingestion.refresh import append_locked_refresh_log_row, run_refresh
from src.logging_utils import configure_logging
from src.reporting.data_quality import build_quality_report, write_quality_report
from src.reporting import eda as eda_reporting
from src.reporting import m4 as m4_reporting
from src.transformation import tables
from src.validation.lineage import check_frozen_prefix
from src.validation.reconcile import reconcile
from src.validation.schedule import scheduled_draw_dates

LOCK_COMMANDS = {"refresh", "ingest", "curate"}


def _date(s: str) -> date:
    return date.fromisoformat(s)


def _iso_datetime_with_tz(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError(f"--as-of {s!r} must include a UTC offset")
    return dt


def main(argv: list[str] | None = None, paths: Paths | None = None) -> int:
    paths_injected = paths is not None

    parser = argparse.ArgumentParser(prog="power655")
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="fetch draws from a source into raw + staging")
    p.add_argument("--source", choices=sorted(SOURCES), default="vietlott_official")
    p.add_argument("--full", action="store_true", help="re-fetch the whole history instead of only new draws")
    p.add_argument("--start", type=_date)
    p.add_argument("--end", type=_date)

    p = sub.add_parser("curate", help="build curated tables from a source's staging data")
    p.add_argument("--source", choices=sorted(SOURCES), default="vietlott_official")

    p = sub.add_parser("reconcile", help="compare two sources draw by draw")
    p.add_argument("--left", choices=sorted(SOURCES), default="vietlott_official")
    p.add_argument("--right", choices=sorted(SOURCES), default="github_mirror")

    sub.add_parser("verify-raw", help="check raw archive checksums against manifests")

    p = sub.add_parser("quality-report", help="generate the deterministic data quality report")
    p.add_argument("--as-of", type=_iso_datetime_with_tz, default=None)
    p.add_argument("--out-dir", type=str, default=None)
    p.add_argument("--known-issues", type=str, default=None)

    p = sub.add_parser("refresh", help="incremental ingest (both sources) + reconcile + curate + quality report")
    p.add_argument("--lock-timeout-minutes", type=int, default=120)
    p.add_argument("--as-of", type=_iso_datetime_with_tz, default=None)

    sub.add_parser("status", help="print refresh health (last run, alert, next scheduled draw)")

    p = sub.add_parser("eda", help="descriptive EDA (M3 spec); range gated at 01190 unless overridden")
    p.add_argument("--through-draw", type=str, default="01190")
    p.add_argument("--out-dir", type=str, default=None)
    p.add_argument("--windows", type=str, default="50,100,200")
    p.add_argument("--n-blocks", type=int, default=5)
    p.add_argument("--mc-reps", type=int, default=10_000)
    p.add_argument("--override-ceiling", dest="override_ceiling", type=str, default=None)

    p = sub.add_parser("m4", help="M4 confirmatory family C1-C13 (SPECIFICATION section 6); range gated at 01190")
    p.add_argument("--through-draw", type=str, default="01190")
    p.add_argument("--out-dir", type=str, default=None)
    p.add_argument("--reps", type=int, default=10_000)

    args = parser.parse_args(argv)
    paths = paths if paths is not None else Paths()

    if args.cmd == "ingest" and (args.start or args.end) and not args.full:
        parser.error("--start/--end require --full: incremental ingest must stay unfiltered")

    if args.cmd == "refresh" and args.as_of is not None and not paths_injected:
        # R3 N5: an unrestricted --as-of is a test-only affordance (paths injection implies a test).
        now = datetime.now(timezone.utc)
        if args.as_of < now - timedelta(hours=1):
            parser.error(f"--as-of {args.as_of.isoformat()!r} is more than 1h in the past")

    configure_logging(args.log_level, paths.logs / "app.log")

    lock: RunLock | None = None
    if args.cmd in LOCK_COMMANDS:
        stale_after = timedelta(minutes=getattr(args, "lock_timeout_minutes", 120))
        lock = RunLock(paths.data / ".refresh.lock", stale_after=stale_after, command=args.cmd)
        try:
            lock.acquire()
        except LockHeldError as exc:
            if args.cmd == "refresh":
                append_locked_refresh_log_row(paths, f"locked by {exc.holder}")
            print(json.dumps({"exit_code": 40, "message": "another run holds the lock", "holder": exc.holder}, default=str, indent=2))
            return 40

    try:
        if args.cmd == "ingest":
            result = run_ingestion(get_source(args.source), paths, mode="full" if args.full else "incremental",
                                   start_date=args.start, end_date=args.end)
            errors = [q for q in result.issues if q.severity == "error"]
            warnings = [q for q in result.issues if q.severity == "warning"]
            print(json.dumps({"run_id": result.run_id, "status": result.status, "received": result.rows_received,
                              "inserted": result.rows_inserted, "skipped": result.rows_skipped,
                              "errors": len(errors), "warnings": len(warnings)}, indent=2))
            for q in errors[:20]:
                print(f"  ERROR {q.rule} draw={q.draw_id}: {q.detail}")
            return 0 if result.status == "success" else 1

        if args.cmd == "curate":
            # R3 N4: the frozen prefix gate always checks *official* staging, regardless of --source.
            official_path = staging_path(paths, "vietlott_official")
            if official_path.exists():
                official_staging = read_staging(paths, "vietlott_official")
                if not official_staging.empty:
                    frozen_findings = check_frozen_prefix(official_staging)
                    if frozen_findings:
                        print(json.dumps({
                            "error": "frozen_prefix violation on official staging; nothing written",
                            "findings": [f.detail for f in frozen_findings],
                        }, indent=2))
                        return 30
            print(json.dumps(build_curated(paths, args.source), indent=2, ensure_ascii=False))
            return 0

        if args.cmd == "reconcile":
            report = reconcile(read_staging(paths, args.left), read_staging(paths, args.right), args.left, args.right)
            print(json.dumps(report.summary(), indent=2))
            if report.only_left:
                print(f"only in {args.left}: {report.only_left[:20]}")
            if report.only_right:
                print(f"only in {args.right}: {report.only_right[:20]}")
            if not report.ok:
                print(report.mismatches.to_string(index=False))
            return 0 if report.ok else 1

        if args.cmd == "verify-raw":
            archive = RawArchive(paths.raw)
            bad_total = 0
            for manifest in sorted(paths.raw.glob("*/*/manifest.jsonl")):
                source, run_id = manifest.parent.parent.name, manifest.parent.name
                bad = archive.verify(source, run_id)
                bad_total += len(bad)
                print(f"{source}/{run_id}: {'OK' if not bad else 'CORRUPT ' + ', '.join(bad)}")
            return 0 if bad_total == 0 else 1

        if args.cmd == "quality-report":
            as_of = args.as_of or datetime.now(LOCAL_TZ)
            out_dir = Path(args.out_dir) if args.out_dir else paths.reports
            known_issues_path = Path(args.known_issues) if args.known_issues else None
            try:
                report = build_quality_report(paths, as_of, known_issues_path=known_issues_path, run_context="standalone")
                md_path, json_path, _sha = write_quality_report(report, out_dir)
            except Exception as exc:
                print(json.dumps({"overall_status": "INTERNAL", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
                return 50
            print(json.dumps({"overall_status": report["overall_status"], "json": str(json_path), "md": str(md_path)}, indent=2))
            return {"PASS": 0, "WARN": 10, "FAIL": 30}[report["overall_status"]]

        if args.cmd == "refresh":
            # `get_source` is looked up here (not via run_refresh's own default) so tests can
            # monkeypatch `src.cli.get_source` to avoid any real network access.
            result = run_refresh(paths, as_of=args.as_of, source_factory=get_source)
            print("REFRESH_RESULT " + json.dumps(asdict(result), sort_keys=True, default=str))
            return result.exit_code

        if args.cmd == "status":
            return _print_status(paths)

        if args.cmd == "eda":
            out_dir = Path(args.out_dir) if args.out_dir else (paths.root / "outputs" / "eda")
            try:
                windows = [int(w) for w in args.windows.split(",") if w.strip()]
            except ValueError:
                print(json.dumps({"exit_code": 2, "error": f"--windows {args.windows!r} must be a comma-separated list of ints"}, indent=2))
                return 2
            code = eda_reporting.run_eda(
                paths, args.through_draw, out_dir, windows, args.n_blocks, args.mc_reps, args.override_ceiling,
            )
            print(json.dumps({"exit_code": code, "through_draw": args.through_draw, "out_dir": str(out_dir)}, indent=2))
            return code

        if args.cmd == "m4":
            out_dir = Path(args.out_dir) if args.out_dir else (paths.root / "outputs" / "m4")
            code = m4_reporting.run_m4(paths, args.through_draw, out_dir, R=args.reps)
            print(json.dumps({"exit_code": code, "through_draw": args.through_draw, "out_dir": str(out_dir)}, indent=2))
            return code

        return 2
    finally:
        if lock is not None:
            lock.release()


def _print_status(paths: Paths) -> int:
    info: dict = {}
    exit_code = 0
    now = datetime.now(timezone.utc)

    refresh_log_path = paths.logs / "refresh_log.csv"
    if not refresh_log_path.exists():
        info["last_refresh"] = None
        info["consecutive_non_zero_exits"] = 0
        exit_code = 10
    else:
        log = pd.read_csv(refresh_log_path, dtype=str).fillna("")
        if log.empty:
            info["last_refresh"] = None
            info["consecutive_non_zero_exits"] = 0
            exit_code = 10
        else:
            last = log.iloc[-1]
            try:
                started = datetime.fromisoformat(last["started_at"])
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                age_seconds = (now - started).total_seconds()
            except (TypeError, ValueError):
                age_seconds = None
            last_exit = last.get("exit_code", "")
            info["last_refresh"] = {
                "refresh_id": last.get("refresh_id", ""), "started_at": last.get("started_at", ""),
                "exit_code": last_exit, "overall_status": last.get("overall_status", ""),
                "age_seconds": age_seconds,
            }
            consecutive = 0
            for exit_code_str in reversed(log["exit_code"].tolist()):
                if exit_code_str not in ("0", ""):
                    consecutive += 1
                else:
                    break
            info["consecutive_non_zero_exits"] = consecutive
            if last_exit != "0":
                exit_code = 10
            if age_seconds is not None and age_seconds > timedelta(days=4).total_seconds():
                exit_code = 10

    latest_json = paths.reports / "data_quality_latest.json"
    if latest_json.exists():
        try:
            info["latest_report_status"] = json.loads(latest_json.read_text(encoding="utf-8")).get("overall_status")
        except (OSError, ValueError):
            info["latest_report_status"] = None
    else:
        info["latest_report_status"] = None

    info["next_scheduled_draw"] = None
    try:
        fact = tables.read_fact_draw(paths.curated)
        if not fact.empty:
            last_draw_date = date.fromisoformat(str(fact["draw_date"].iloc[-1]))
            upcoming = scheduled_draw_dates(last_draw_date + timedelta(days=1), last_draw_date + timedelta(days=14))
            if upcoming:
                info["next_scheduled_draw"] = upcoming[0].isoformat()
    except FileNotFoundError:
        pass

    alert_path = paths.logs / "ALERT.txt"
    info["alert_active"] = alert_path.exists()
    if info["alert_active"]:
        info["alert_text"] = alert_path.read_text(encoding="utf-8")
        exit_code = 10

    print(json.dumps(info, indent=2, ensure_ascii=False, default=str))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
