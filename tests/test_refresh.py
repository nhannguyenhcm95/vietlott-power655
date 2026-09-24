import hashlib
import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.cli import main
from src.config import LOCAL_TZ
from src.ingestion import loader as loader_module
from src.ingestion.lock import RunLock
from src.ingestion.refresh import run_refresh
from src.transformation import tables
from tests.conftest import build_fixture, refresh_source_factory

DRAWS = [
    ("00001", date(2017, 8, 1), (1, 2, 3, 4, 5, 6), 7),
    ("00002", date(2017, 8, 3), (2, 3, 4, 5, 6, 7), 8),
    ("00003", date(2017, 8, 5), (3, 4, 5, 6, 7, 8), 9),
    ("00004", date(2017, 8, 8), (4, 5, 6, 7, 8, 9), 10),
    ("00005", date(2017, 8, 10), (5, 6, 7, 8, 9, 10), 11),
]
NEW_DRAW = ("00006", date(2017, 8, 12), (6, 7, 8, 9, 10, 11), 12)


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=LOCAL_TZ)


@pytest.fixture(autouse=True)
def _restore_root_handlers():
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield
    root.handlers.clear()
    root.handlers.extend(original_handlers)
    root.setLevel(original_level)


def manifest_bytes(paths):
    return (paths.curated / "dataset_manifest.json").read_bytes()


# ------------------------------------------------------------- refresh outcomes
def test_happy_new_draw_mirror_lag_exit0(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    official_rows = DRAWS + [NEW_DRAW]
    factory = refresh_source_factory(official=official_rows, mirror=DRAWS)  # mirror lags (O5)
    as_of = at(NEW_DRAW[1], 21, 30)

    result = run_refresh(paths, as_of=as_of, source_factory=factory)

    assert result.exit_code == 0
    assert result.overall_status == "PASS"
    assert result.official_status == "success"
    assert result.official_new_draws == 1
    assert result.mirror_status == "success"
    assert result.curate_action == "rebuilt"
    assert result.dataset_version_after != result.dataset_version_before


def test_no_new_draw_before_deadline_exit0_unchanged(paths, frozen):
    as_of_fixture = build_fixture(paths, DRAWS)
    frozen(paths)
    factory = refresh_source_factory(official=DRAWS, mirror=DRAWS)
    as_of = at(date(2017, 8, 12), 10, 0)  # before that Saturday's 21:00 deadline

    result = run_refresh(paths, as_of=as_of, source_factory=factory)

    assert result.exit_code == 0
    assert result.curate_action == "unchanged"
    assert result.dataset_version_after == result.dataset_version_before


def test_missing_after_deadline_exit10(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    factory = refresh_source_factory(official=DRAWS, mirror=DRAWS)
    as_of = at(date(2017, 8, 15), 22, 0)  # Sat 08-12 missed, now Tue 08-15 evening

    result = run_refresh(paths, as_of=as_of, source_factory=factory)

    assert result.exit_code == 10
    assert result.overall_status == "WARN"
    assert result.curate_action == "unchanged"


def test_mirror_down_exit10_curated_updated(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    factory = refresh_source_factory(official=DRAWS + [NEW_DRAW], mirror="down")
    as_of = at(NEW_DRAW[1], 21, 30)

    result = run_refresh(paths, as_of=as_of, source_factory=factory)

    assert result.exit_code == 10
    assert result.mirror_status == "failed"
    assert result.curate_action == "rebuilt"
    assert result.dataset_version_after != result.dataset_version_before


def test_official_down_exit30_mirror_still_ingested(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    version_before = tables.read_fact_draw(paths.curated)["dataset_version"].iloc[0]
    factory = refresh_source_factory(official="down", mirror=DRAWS)
    as_of = at(DRAWS[-1][1], 21, 30)

    result = run_refresh(paths, as_of=as_of, source_factory=factory)

    assert result.exit_code == 30
    assert result.official_status == "failed"
    assert result.mirror_status == "success"  # mirror was still attempted
    assert result.curate_action == "skipped"
    assert result.dataset_version_after == version_before  # curated untouched


def test_official_empty_fail_exit30(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    version_before = tables.read_fact_draw(paths.curated)["dataset_version"].iloc[0]
    factory = refresh_source_factory(official=[], mirror=DRAWS)
    as_of = at(DRAWS[-1][1], 21, 30)

    result = run_refresh(paths, as_of=as_of, source_factory=factory)

    assert result.exit_code == 30
    assert result.official_status == "empty"
    assert result.curate_action == "skipped"
    assert result.dataset_version_after == version_before


def test_mirror_shrink_warn_exit10(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    # The mirror "loses" a middle draw: this fetch has fewer rows than what is already staged.
    shrunk_mirror = [d for d in DRAWS if d[0] != "00003"]
    factory = refresh_source_factory(official=DRAWS, mirror=shrunk_mirror)
    as_of = at(DRAWS[-1][1], 21, 30)

    result = run_refresh(paths, as_of=as_of, source_factory=factory)

    assert result.exit_code == 10
    assert result.overall_status == "WARN"


def test_realistic_mismatch_2000_then_0830_not_blocked_exit30(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    # 20:00: official publishes 00006, mirror lags (doesn't have it yet).
    factory1 = refresh_source_factory(official=DRAWS + [NEW_DRAW], mirror=DRAWS)
    r1 = run_refresh(paths, as_of=at(NEW_DRAW[1], 20, 0), source_factory=factory1)
    assert r1.curate_action == "rebuilt"  # 00006 is now published

    # 08:30 next day: the mirror catches up but disagrees on 00006 (already published -> not blocked).
    mismatched_new_draw = (NEW_DRAW[0], NEW_DRAW[1], NEW_DRAW[2], 1)  # different special
    factory2 = refresh_source_factory(official=DRAWS + [NEW_DRAW], mirror=DRAWS + [mismatched_new_draw])
    r2 = run_refresh(paths, as_of=at(NEW_DRAW[1] + timedelta(days=1), 8, 30), source_factory=factory2)

    assert r2.exit_code == 30
    assert r2.curate_action in ("unchanged", "rebuilt")  # not "blocked": 00006 was already published


def test_mismatch_on_unpublished_draw_blocks(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    version_before = tables.read_fact_draw(paths.curated)["dataset_version"].iloc[0]
    # Both sources gain 00006 in the same run, but disagree on it -> not yet published, so blocked.
    mismatched_new_draw = (NEW_DRAW[0], NEW_DRAW[1], NEW_DRAW[2], 1)
    factory = refresh_source_factory(official=DRAWS + [NEW_DRAW], mirror=DRAWS + [mismatched_new_draw])
    as_of = at(NEW_DRAW[1], 21, 30)

    result = run_refresh(paths, as_of=as_of, source_factory=factory)

    assert result.exit_code == 30
    assert result.curate_action == "blocked"
    assert result.dataset_version_after == version_before  # previous version kept


def test_mismatch_accepted_by_pinned_ki_curates(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    mismatched_new_draw = (NEW_DRAW[0], NEW_DRAW[1], NEW_DRAW[2], 1)
    factory = refresh_source_factory(official=DRAWS + [NEW_DRAW], mirror=DRAWS + [mismatched_new_draw])
    as_of = at(NEW_DRAW[1], 21, 30)

    paths.config.mkdir(parents=True, exist_ok=True)
    (paths.config / "known_issues.json").write_text(json.dumps({
        "schema_version": "1.0",
        "issues": [{
            "id": "KI-001", "source": "github_mirror", "draw_id": "00006",
            "rules": ["reconcile.field_mismatch"],
            "pins": {"reconcile.field_mismatch": {"special_number": {"vietlott_official": "12", "github_mirror": "1"}}},
            "reason": "r", "evidence": "e",
            "approved_by": "a", "approved_on": "2017-08-01", "approval_ref": "ref", "review_by": "2099-01-01",
        }],
    }), encoding="utf-8")

    result = run_refresh(paths, as_of=as_of, source_factory=factory)

    assert result.curate_action == "rebuilt"
    assert result.exit_code in (0, 10)


def test_frozen_prefix_violation_blocks_curate(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    version_before = tables.read_fact_draw(paths.curated)["dataset_version"].iloc[0]

    # Tamper a frozen (already-committed) row directly in official staging.
    staging_path = paths.staging / "vietlott_official" / "draws.csv"
    df = pd.read_csv(staging_path, dtype={"draw_id": str, "draw_date": str})
    df.loc[df["draw_id"] == "00001", "n1"] = 55
    df.to_csv(staging_path, index=False)

    factory = refresh_source_factory(official=DRAWS, mirror=DRAWS)  # no new data
    as_of = at(DRAWS[-1][1], 21, 30)

    result = run_refresh(paths, as_of=as_of, source_factory=factory)

    assert result.curate_action == "blocked"
    assert result.exit_code == 30
    assert result.dataset_version_after == version_before


def test_second_run_idempotent(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    factory = refresh_source_factory(official=DRAWS, mirror=DRAWS)
    as_of = at(date(2017, 8, 12), 10, 0)

    r1 = run_refresh(paths, as_of=as_of, source_factory=factory)
    manifest1 = manifest_bytes(paths)

    r2 = run_refresh(paths, as_of=as_of, source_factory=refresh_source_factory(official=DRAWS, mirror=DRAWS))
    manifest2 = manifest_bytes(paths)

    assert r1.exit_code == r2.exit_code
    assert manifest1 == manifest2
    assert r1.dataset_version_after == r2.dataset_version_after


# ------------------------------------------------------------- failure handling and outputs
def test_refresh_catches_non_runtime_error_and_still_reports(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    factory = refresh_source_factory(official="down", mirror=DRAWS)
    # BrokenSource raises ConnectionError by default; use a plain Exception subtype instead.

    def bad_factory(name):
        if name == "vietlott_official":
            from tests.conftest import BrokenSource
            return BrokenSource(name, exc=ValueError("unexpected"))
        return factory(name)

    result = run_refresh(paths, as_of=at(DRAWS[-1][1], 21, 30), source_factory=bad_factory)

    assert result.official_status == "failed"
    assert result.report_json  # the report step still ran despite the earlier failure
    assert result.overall_status in ("PASS", "WARN", "FAIL")


def test_curated_manifest_written_last(paths, frozen, monkeypatch):
    build_fixture(paths, DRAWS)
    frozen(paths)
    manifest_before = manifest_bytes(paths)

    calls = {"n": 0}
    real_write = loader_module._atomic_write_csv

    def flaky_write(path, df):
        calls["n"] += 1
        if calls["n"] == 2:  # fail while writing fact_draw_number.csv (2nd file)
            raise RuntimeError("injected failure")
        return real_write(path, df)

    monkeypatch.setattr(loader_module, "_atomic_write_csv", flaky_write)
    factory = refresh_source_factory(official=DRAWS + [NEW_DRAW], mirror=DRAWS)

    result = run_refresh(paths, as_of=at(NEW_DRAW[1], 21, 30), source_factory=factory)

    assert result.curate_action == "failed"
    assert manifest_bytes(paths) == manifest_before  # old manifest untouched


def test_permission_error_retried_then_failed(paths, frozen, monkeypatch):
    build_fixture(paths, DRAWS)
    frozen(paths)

    sleeps = []
    monkeypatch.setattr(loader_module.time, "sleep", lambda s: sleeps.append(s))

    real_replace = loader_module.os.replace

    def denied_only_for_curated(src, dst):
        if str(paths.curated) in str(dst):
            raise PermissionError("denied")
        return real_replace(src, dst)

    monkeypatch.setattr(loader_module.os, "replace", denied_only_for_curated)
    factory = refresh_source_factory(official=DRAWS + [NEW_DRAW], mirror=DRAWS)

    result = run_refresh(paths, as_of=at(NEW_DRAW[1], 21, 30), source_factory=factory)

    assert result.curate_action == "failed"
    assert sleeps == [1, 1, 1]  # 3 retries with 1s sleeps before giving up


def test_alert_started_then_final_then_cleared(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    alert_path = paths.logs / "ALERT.txt"

    captured = {}

    def spy_official(name):
        from tests.conftest import make_official_source

        class Spy:
            name = "vietlott_official"

            def __init__(self, inner):
                self.inner = inner

            def iter_raw_pages(self, *a, **k):
                captured["alert_during_run"] = alert_path.read_text(encoding="utf-8") if alert_path.exists() else None
                yield from self.inner.iter_raw_pages(*a, **k)

            def parse(self, page):
                return self.inner.parse(page)

        return Spy(make_official_source(DRAWS + [NEW_DRAW]))

    def factory(name):
        if name == "vietlott_official":
            return spy_official(name)
        from tests.conftest import make_mirror_source
        return make_mirror_source(DRAWS)

    result = run_refresh(paths, as_of=at(NEW_DRAW[1], 21, 30), source_factory=factory)

    assert captured["alert_during_run"] is not None
    assert captured["alert_during_run"].startswith("started, not finished")
    assert result.exit_code == 0
    assert not alert_path.exists()  # cleared on a clean (exit 0) run

    # now force a non-zero exit and check the final alert holds the cause
    factory2 = refresh_source_factory(official="down", mirror=DRAWS)
    result2 = run_refresh(paths, as_of=at(NEW_DRAW[1], 21, 30), source_factory=factory2)
    assert result2.exit_code != 0
    assert alert_path.exists()
    final_text = alert_path.read_text(encoding="utf-8")
    assert "started, not finished" not in final_text
    assert str(result2.exit_code) in final_text or result2.overall_status in final_text


def test_refresh_log_has_report_sha256(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    factory = refresh_source_factory(official=DRAWS, mirror=DRAWS)
    result = run_refresh(paths, as_of=at(date(2017, 8, 12), 10, 0), source_factory=factory)

    log = pd.read_csv(paths.logs / "refresh_log.csv", dtype=str)
    row = log.iloc[-1]
    assert row["report_sha256"] == result.report_sha256
    actual_sha = hashlib.sha256(Path(result.report_json).read_bytes()).hexdigest()
    assert row["report_sha256"] == actual_sha


def test_internal_error_exit50_lock_released(paths, frozen, monkeypatch):
    build_fixture(paths, DRAWS)
    frozen(paths)
    monkeypatch.setattr("src.cli.get_source", refresh_source_factory(official=DRAWS, mirror=DRAWS))
    monkeypatch.setattr("src.ingestion.refresh.build_quality_report", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("report boom")))

    exit_code = main(["refresh"], paths=paths)

    assert exit_code == 50
    assert not (paths.data / ".refresh.lock").exists()


def test_refresh_logging_events(paths, frozen, caplog, monkeypatch):
    build_fixture(paths, DRAWS)
    frozen(paths)
    monkeypatch.setattr("src.cli.get_source", refresh_source_factory(official=DRAWS, mirror=DRAWS))
    with caplog.at_level("INFO"):
        exit_code = main(["refresh"], paths=paths)
    assert exit_code in (0, 10, 30, 50)

    lines = (paths.logs / "app.log").read_text(encoding="utf-8").splitlines()
    events = [json.loads(l) for l in lines]
    start = next(e for e in events if e["event"] == "refresh_start")
    finished = next(e for e in events if e["event"] == "refresh_finished")
    assert "refresh_id" in start
    assert {"refresh_id", "exit_code", "curate_action", "overall_status"} <= set(finished)
    assert start["refresh_id"] == finished["refresh_id"]


# ------------------------------------------------------------- lock + CLI
def test_lock_held_exit40_no_source_calls(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    lock = RunLock(paths.data / ".refresh.lock", command="refresh")
    lock.acquire()
    try:
        ingestion_log_before = (paths.logs / "ingestion_log.csv").read_bytes()
        exit_code = main(["refresh"], paths=paths)
        assert exit_code == 40
        assert (paths.logs / "ingestion_log.csv").read_bytes() == ingestion_log_before  # no source was called

        refresh_log = pd.read_csv(paths.logs / "refresh_log.csv", dtype=str)
        last = refresh_log.iloc[-1]
        assert last["exit_code"] == "40"
        assert last["official_run_id"] in ("", None) or pd.isna(last["official_run_id"])
    finally:
        lock.release()


def test_exit40_does_not_touch_alert(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    alert_path = paths.logs / "ALERT.txt"
    alert_path.parent.mkdir(parents=True, exist_ok=True)
    alert_path.write_text("pre-existing sentinel", encoding="utf-8")

    lock = RunLock(paths.data / ".refresh.lock", command="refresh")
    lock.acquire()
    try:
        exit_code = main(["refresh"], paths=paths)
        assert exit_code == 40
        assert alert_path.read_text(encoding="utf-8") == "pre-existing sentinel"
    finally:
        lock.release()


def test_ingest_cli_respects_lock(paths):
    lock = RunLock(paths.data / ".refresh.lock", command="refresh")
    lock.acquire()
    try:
        exit_code = main(["ingest", "--source", "vietlott_official"], paths=paths)
        assert exit_code == 40
    finally:
        lock.release()


def test_ingest_rejects_start_without_full(paths):
    with pytest.raises(SystemExit) as exc_info:
        main(["ingest", "--start", "2020-01-01"], paths=paths)
    assert exc_info.value.code == 2


def test_curate_cli_frozen_prefix_exit30_writes_nothing(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    manifest_before = manifest_bytes(paths)

    staging_path = paths.staging / "vietlott_official" / "draws.csv"
    df = pd.read_csv(staging_path, dtype={"draw_id": str, "draw_date": str})
    df.loc[df["draw_id"] == "00001", "n1"] = 55
    df.to_csv(staging_path, index=False)

    exit_code = main(["curate", "--source", "vietlott_official"], paths=paths)

    assert exit_code == 30
    assert manifest_bytes(paths) == manifest_before


def test_cli_uses_injected_paths(paths, frozen, monkeypatch):
    build_fixture(paths, DRAWS)
    frozen(paths)
    monkeypatch.setattr("src.cli.get_source", refresh_source_factory(official=DRAWS, mirror=DRAWS))
    main(["status"], paths=paths)
    exit_code = main(["refresh"], paths=paths)
    assert exit_code in (0, 10, 30, 50)
    assert (paths.logs / "refresh_log.csv").exists()  # only the injected tmp path was touched


def test_status_exit_codes(paths, frozen):
    # no refresh_log.csv at all -> 10
    assert main(["status"], paths=paths) == 10

    build_fixture(paths, DRAWS)
    frozen(paths)
    from src.ingestion.refresh import _append_refresh_log

    now = datetime.now(timezone.utc).isoformat()
    _append_refresh_log(paths, {
        "refresh_id": "r1", "started_at": now, "finished_at": now, "exit_code": 0, "overall_status": "PASS",
        "official_run_id": "x", "official_status": "success", "official_new_draws": 0,
        "mirror_run_id": "y", "mirror_status": "success",
        "reconcile_status": "PASS", "curate_action": "unchanged",
        "dataset_version_before": "v", "dataset_version_after": "v",
        "report_json": "", "report_sha256": "", "message": "",
    })
    assert main(["status"], paths=paths) == 0  # a healthy recent run, no alert

    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    _append_refresh_log(paths, {
        "refresh_id": "r2", "started_at": old, "finished_at": old, "exit_code": 0, "overall_status": "PASS",
        "official_run_id": "x", "official_status": "success", "official_new_draws": 0,
        "mirror_run_id": "y", "mirror_status": "success",
        "reconcile_status": "PASS", "curate_action": "unchanged",
        "dataset_version_before": "v", "dataset_version_after": "v",
        "report_json": "", "report_sha256": "", "message": "",
    })
    assert main(["status"], paths=paths) == 10  # last refresh older than 4 days

    _append_refresh_log(paths, {
        "refresh_id": "r3", "started_at": now, "finished_at": now, "exit_code": 30, "overall_status": "FAIL",
        "official_run_id": "x", "official_status": "failed", "official_new_draws": 0,
        "mirror_run_id": "y", "mirror_status": "success",
        "reconcile_status": "PASS", "curate_action": "skipped",
        "dataset_version_before": "v", "dataset_version_after": "v",
        "report_json": "", "report_sha256": "", "message": "official down",
    })
    assert main(["status"], paths=paths) == 10  # last exit was not 0

    _append_refresh_log(paths, {
        "refresh_id": "r4", "started_at": now, "finished_at": now, "exit_code": 0, "overall_status": "PASS",
        "official_run_id": "x", "official_status": "success", "official_new_draws": 0,
        "mirror_run_id": "y", "mirror_status": "success",
        "reconcile_status": "PASS", "curate_action": "unchanged",
        "dataset_version_before": "v", "dataset_version_after": "v",
        "report_json": "", "report_sha256": "", "message": "",
    })
    (paths.logs / "ALERT.txt").write_text("something is wrong", encoding="utf-8")
    assert main(["status"], paths=paths) == 10  # ALERT.txt exists


def test_refresh_as_of_in_past_rejected_without_injection():
    with pytest.raises(SystemExit) as exc_info:
        main(["refresh", "--as-of", "2000-01-01T00:00:00+07:00"])  # no paths injected -> real Paths() default
    assert exc_info.value.code == 2
