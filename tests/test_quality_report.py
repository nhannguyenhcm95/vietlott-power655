import csv
import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from src.cli import main
from src.config import LOCAL_TZ
from src.reporting.data_quality import build_quality_report, write_quality_report
from src.transformation import tables
from src.validation.known_issues import KnownIssuesError, load_known_issues
from tests.conftest import build_fixture

DRAWS = [
    ("00001", date(2017, 8, 1), (1, 2, 3, 4, 5, 6), 7),
    ("00002", date(2017, 8, 3), (2, 3, 4, 5, 6, 7), 8),
    ("00003", date(2017, 8, 5), (3, 4, 5, 6, 7, 8), 9),
    ("00004", date(2017, 8, 8), (4, 5, 6, 7, 8, 9), 10),
    ("00005", date(2017, 8, 10), (5, 6, 7, 8, 9, 10), 11),
]


def _report(paths, as_of, **kw):
    return build_quality_report(paths, as_of, known_issues_path=paths.config / "known_issues.json", **kw)


def _staging_path(paths, source="vietlott_official"):
    return paths.staging / source / "draws.csv"


def _rewrite_staging(paths, df, source="vietlott_official"):
    df.to_csv(_staging_path(paths, source), index=False)


def _rewrite_curated_fact(paths, df):
    df.to_csv(paths.curated / "fact_draw.csv", index=False)


def _append_csv(path, cols, rows):
    new_file = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        if new_file:
            w.writeheader()
        w.writerows(rows)


INGESTION_COLS = ["run_id", "source", "mode", "started_at", "finished_at", "rows_received", "rows_inserted", "rows_skipped", "status", "error_message"]
QUALITY_COLS = ["check_id", "run_id", "draw_id", "rule", "status", "detail"]


# ------------------------------------------------------------- determinism & output
def test_clean_fixture_passes(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    r = _report(paths, as_of)
    assert r["overall_status"] == "PASS"


def test_byte_deterministic(paths, tmp_path, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    r1 = _report(paths, as_of)
    _md1, json1, sha1 = write_quality_report(r1, tmp_path / "out1")
    r2 = _report(paths, as_of)
    _md2, json2, sha2 = write_quality_report(r2, tmp_path / "out2")
    assert json1.read_bytes() == json2.read_bytes()
    assert sha1 == sha2


def test_as_of_utc_equals_ict(paths, frozen):
    as_of_ict = build_fixture(paths, DRAWS)
    frozen(paths)
    as_of_utc = as_of_ict.astimezone(timezone.utc)
    r1 = _report(paths, as_of_ict)
    r2 = _report(paths, as_of_utc)
    assert r1["as_of"] == r2["as_of"]
    assert r1 == r2


def test_findings_sort_with_null_draw_id(paths):
    from src.validation.findings import Finding
    fs = [
        Finding("vietlott_official", None, None, "z_rule", "INFO", "d"),
        Finding("vietlott_official", "00002", None, "a_rule", "INFO", "d"),
        Finding("vietlott_official", "00001", None, "a_rule", "INFO", "d"),
    ]
    fs.sort(key=lambda f: f.sort_key())
    # "" (from a null draw_id) sorts before any non-empty draw_id string
    assert [f.draw_id for f in fs] == [None, "00001", "00002"]


def test_json_top_level_keys(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    r = _report(paths, as_of)
    assert set(r) == {
        "schema_version", "report_date", "as_of", "run_context", "lock_held", "overall_status",
        "summary", "dataset", "inputs", "checks", "ingestion_runs", "known_issues",
    }


def test_summary_counts(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    r = _report(paths, as_of)
    assert set(r["summary"]) == {
        "missing", "duplicate", "invalid_ranges", "schema_errors", "ingestion_failures", "accepted", "proposed",
    }
    assert all(isinstance(v, int) for v in r["summary"].values())


def test_cli_quality_report_exit_codes(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    rc = main(["quality-report", "--as-of", "2017-08-10T21:30:00+07:00"], paths=paths)
    assert rc == 0
    # WARN: freshness gaps after the deadline (1-6 missed scheduled draws)
    rc_warn = main(["quality-report", "--as-of", "2017-08-20T22:00:00+07:00"], paths=paths)
    assert rc_warn == 10
    # FAIL: more than 6 missed scheduled draws
    rc_fail = main(["quality-report", "--as-of", "2017-09-20T22:00:00+07:00"], paths=paths)
    assert rc_fail == 30


def test_cli_uses_injected_paths(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    rc = main(["quality-report", "--as-of", "2017-08-10T21:30:00+07:00"], paths=paths)
    assert rc == 0
    assert (paths.reports / "data_quality_2017-08-10.json").exists()
    assert (paths.reports / "data_quality_latest.json").exists()


# ------------------------------------------------------------- absent inputs
def test_absent_inputs_curated_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    for f in paths.curated.glob("*"):
        f.unlink()
    r = _report(paths, as_of)
    assert r["overall_status"] == "FAIL"
    cs = next(c for c in r["checks"] if c["check_id"] == "curated.schema")
    assert cs["status"] == "FAIL"
    assert any(f["rule"] == "input_missing" for f in cs["findings"])


def test_absent_inputs_official_staging_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    _staging_path(paths).unlink()
    r = _report(paths, as_of)
    assert r["overall_status"] == "FAIL"


def test_absent_inputs_mirror_staging_warn(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    _staging_path(paths, "github_mirror").unlink()
    r = _report(paths, as_of)
    ss = next(c for c in r["checks"] if c["check_id"] == "staging.schema")
    assert ss["status"] == "WARN"
    rs = next(c for c in r["checks"] if c["check_id"] == "reconcile.sources")
    assert any(f["rule"] == "reconcile.not_run" for f in rs["findings"])


def test_absent_inputs_ingestion_log_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    (paths.logs / "ingestion_log.csv").unlink()
    r = _report(paths, as_of)
    assert r["overall_status"] == "FAIL"


def test_absent_inputs_quality_log_info_when_no_partial(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    # a clean fixture never writes quality_log.csv (no issues to log)
    assert not (paths.logs / "quality_log.csv").exists()
    r = _report(paths, as_of)
    ql = next(c for c in r["checks"] if c["check_id"] == "quality_log.open")
    assert ql["status"] == "PASS"
    assert any(f["rule"] == "input_missing" and f["level"] == "INFO" for f in ql["findings"])


def test_absent_inputs_refresh_log_info(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    r = _report(paths, as_of)
    rh = next(c for c in r["checks"] if c["check_id"] == "refresh.history")
    assert rh["status"] == "PASS"
    assert any(f["rule"] == "input_missing" and f["level"] == "INFO" for f in rh["findings"])


def test_absent_inputs_known_issues_info(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    r = build_quality_report(paths, as_of, known_issues_path=paths.config / "missing.json")
    kf = next(c for c in r["checks"] if c["check_id"] == "known_issues.file")
    assert kf["status"] == "PASS"
    assert any(f["rule"] == "known_issues_absent" for f in kf["findings"])


# ------------------------------------------------------------- curated checks
def test_duplicate_draw_id_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    fact = tables.read_fact_draw(paths.curated)
    dup = pd.concat([fact, fact.iloc[[0]]], ignore_index=True)
    _rewrite_curated_fact(paths, dup)
    r = _report(paths, as_of)
    cd = next(c for c in r["checks"] if c["check_id"] == "curated.duplicates")
    assert cd["status"] == "FAIL"
    assert any(f["rule"] == "draw_id_unique" for f in cd["findings"])


def test_duplicate_content_warn(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    fact = tables.read_fact_draw(paths.curated)
    fact.loc[1, ["n1", "n2", "n3", "n4", "n5", "n6"]] = fact.loc[0, ["n1", "n2", "n3", "n4", "n5", "n6"]].to_numpy()
    fact.loc[1, "special_number"] = fact.loc[0, "special_number"]
    _rewrite_curated_fact(paths, fact)
    r = _report(paths, as_of)
    cd = next(c for c in r["checks"] if c["check_id"] == "curated.duplicates")
    assert any(f["rule"] == "duplicate_content" and f["level"] == "WARN" for f in cd["findings"])
    assert cd["status"] == "WARN"


def test_duplicate_main_only_not_flagged(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    fact = tables.read_fact_draw(paths.curated)
    fact.loc[1, ["n1", "n2", "n3", "n4", "n5", "n6"]] = fact.loc[0, ["n1", "n2", "n3", "n4", "n5", "n6"]].to_numpy()
    # special stays different -> must not fire duplicate_content
    _rewrite_curated_fact(paths, fact)
    r = _report(paths, as_of)
    cd = next(c for c in r["checks"] if c["check_id"] == "curated.duplicates")
    assert not any(f["rule"] == "duplicate_content" for f in cd["findings"])


def test_out_of_range_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    fact = tables.read_fact_draw(paths.curated)
    fact.loc[0, "n6"] = 99
    _rewrite_curated_fact(paths, fact)
    r = _report(paths, as_of)
    cr = next(c for c in r["checks"] if c["check_id"] == "curated.ranges")
    assert cr["status"] == "FAIL"
    assert any(f["rule"] == "main_range" for f in cr["findings"])


def test_null_required_fail_null_special_warn(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    fact = tables.read_fact_draw(paths.curated)
    fact.loc[0, "special_number"] = pd.NA
    _rewrite_curated_fact(paths, fact)
    r = _report(paths, as_of)
    cm = next(c for c in r["checks"] if c["check_id"] == "curated.missing")
    assert any(f["rule"] == "special_present" and f["level"] == "WARN" for f in cm["findings"])
    assert cm["status"] == "WARN"  # not a FAIL: special_present is only WARN-level


def test_missing_column_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    fact = pd.read_csv(paths.curated / "fact_draw.csv")
    fact = fact.drop(columns=["special_number"])
    _rewrite_curated_fact(paths, fact)
    r = _report(paths, as_of)
    cs = next(c for c in r["checks"] if c["check_id"] == "curated.schema")
    assert cs["status"] == "FAIL"
    assert any(f["rule"] == "curated_schema" for f in cs["findings"])


def test_curated_stale_vs_staging_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    fact = tables.read_fact_draw(paths.curated)
    fact.loc[0, "n1"] = 55
    _rewrite_curated_fact(paths, fact)
    r = _report(paths, as_of)
    cl = next(c for c in r["checks"] if c["check_id"] == "curated.lineage")
    assert cl["status"] == "FAIL"
    assert any(f["rule"] == "curated_matches_staging" for f in cl["findings"])


def test_manifest_count_mismatch_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    manifest_path = paths.curated / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["fact_draw.csv"] = manifest["files"]["fact_draw.csv"] + 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    r = _report(paths, as_of)
    cl = next(c for c in r["checks"] if c["check_id"] == "curated.lineage")
    assert any(f["rule"] == "manifest_consistency" for f in cl["findings"])
    assert cl["status"] == "FAIL"


def test_retrieved_before_draw_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    fact = tables.read_fact_draw(paths.curated)
    bad_time = datetime.combine(date.fromisoformat(fact.loc[0, "draw_date"]), datetime.min.time(), tzinfo=LOCAL_TZ) + timedelta(hours=17)
    fact.loc[0, "retrieved_at"] = bad_time.astimezone(timezone.utc).isoformat()
    _rewrite_curated_fact(paths, fact)
    r = _report(paths, as_of)
    cr = next(c for c in r["checks"] if c["check_id"] == "curated.ranges")
    assert any(f["rule"] == "retrieved_after_draw" for f in cr["findings"])
    assert cr["status"] == "FAIL"


def test_first_draw_wrong_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS[1:])
    frozen(paths)  # starts at 00002
    r = _report(paths, as_of)
    cg = next(c for c in r["checks"] if c["check_id"] == "coverage.gaps")
    assert cg["status"] == "FAIL"
    assert any(f["rule"] == "first_draw" for f in cg["findings"])


# ------------------------------------------------------------- raw & ingestion
def test_corrupt_raw_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    run_dir = next((paths.raw / "vietlott_official").iterdir())
    page = next(run_dir.glob("page_*"))
    page.write_text("tampered", encoding="utf-8")
    r = _report(paths, as_of)
    rc = next(c for c in r["checks"] if c["check_id"] == "raw.checksums")
    assert rc["status"] == "FAIL"
    assert any(f["rule"] == "raw_checksum" for f in rc["findings"])


def test_missing_raw_file_fail_not_crash(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    run_dir = next((paths.raw / "vietlott_official").iterdir())
    page = next(run_dir.glob("page_*"))
    page.unlink()
    r = _report(paths, as_of)  # must not raise
    rc = next(c for c in r["checks"] if c["check_id"] == "raw.checksums")
    assert rc["status"] == "WARN"
    assert any(f["rule"] == "raw_manifest_missing" for f in rc["findings"])


def test_latest_official_failed_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    _append_csv(paths.logs / "ingestion_log.csv", INGESTION_COLS, [{
        "run_id": "zzz_failed", "source": "vietlott_official", "mode": "incremental",
        "started_at": as_of.isoformat(), "finished_at": as_of.isoformat(),
        "rows_received": 0, "rows_inserted": 0, "rows_skipped": 0, "status": "failed", "error_message": "boom",
    }])
    r = _report(paths, as_of)
    assert r["overall_status"] == "FAIL"
    ir = next(c for c in r["checks"] if c["check_id"] == "ingestion.runs")
    assert any(f["rule"] == "run_failed" and f["level"] == "FAIL" for f in ir["findings"])


def test_latest_mirror_failed_warn(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    _append_csv(paths.logs / "ingestion_log.csv", INGESTION_COLS, [{
        "run_id": "zzz_failed_mir", "source": "github_mirror", "mode": "incremental",
        "started_at": as_of.isoformat(), "finished_at": as_of.isoformat(),
        "rows_received": 0, "rows_inserted": 0, "rows_skipped": 0, "status": "failed", "error_message": "boom",
    }])
    r = _report(paths, as_of)
    ir = next(c for c in r["checks"] if c["check_id"] == "ingestion.runs")
    assert any(f["rule"] == "run_failed" and f["level"] == "WARN" for f in ir["findings"])
    assert r["overall_status"] != "FAIL"


def test_official_empty_fetch_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    _append_csv(paths.logs / "ingestion_log.csv", INGESTION_COLS, [{
        "run_id": "zzz_empty", "source": "vietlott_official", "mode": "incremental",
        "started_at": as_of.isoformat(), "finished_at": as_of.isoformat(),
        "rows_received": 0, "rows_inserted": 0, "rows_skipped": 0, "status": "success", "error_message": "",
    }])
    r = _report(paths, as_of)
    ir = next(c for c in r["checks"] if c["check_id"] == "ingestion.runs")
    assert any(f["rule"] == "incremental_empty_fetch" and f["level"] == "FAIL" for f in ir["findings"])
    assert r["overall_status"] == "FAIL"


def test_mirror_empty_fetch_warn(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    _append_csv(paths.logs / "ingestion_log.csv", INGESTION_COLS, [{
        "run_id": "zzz_empty_mir", "source": "github_mirror", "mode": "incremental",
        "started_at": as_of.isoformat(), "finished_at": as_of.isoformat(),
        "rows_received": 0, "rows_inserted": 0, "rows_skipped": 0, "status": "success", "error_message": "",
    }])
    r = _report(paths, as_of)
    ir = next(c for c in r["checks"] if c["check_id"] == "ingestion.runs")
    assert any(f["rule"] == "incremental_empty_fetch" and f["level"] == "WARN" for f in ir["findings"])
    assert r["overall_status"] != "FAIL"


def _mirror_raw_page(paths):
    log = pd.read_csv(paths.logs / "ingestion_log.csv", dtype=str)
    mirror_run_id = log[log["source"] == "github_mirror"].iloc[-1]["run_id"]
    run_dir = paths.raw / "github_mirror" / mirror_run_id
    return next(run_dir.glob("page_*"))


def _rewrite_page_and_manifest(page, text):
    """Write new raw-page content and re-stamp its manifest checksum, so only mirror_shrink/
    raw_lineage are exercised (not the unrelated raw_checksum integrity check)."""
    import hashlib

    page.write_text(text, encoding="utf-8", newline="")  # newline="" avoids Windows \r\n translation
    manifest_path = page.parent / "manifest.jsonl"
    entries = [json.loads(l) for l in manifest_path.read_text(encoding="utf-8").splitlines()]
    data = text.encode("utf-8")
    for entry in entries:
        if entry["file"] == page.name:
            entry["bytes"] = len(data)
            entry["sha256"] = hashlib.sha256(data).hexdigest()
    manifest_path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8", newline=""
    )


def test_mirror_shrink_warn(paths, frozen):
    """§1.3/§1.4: mirror_shrink is WARN, never KI-acceptable, and skipped when received is empty."""
    as_of = build_fixture(paths, DRAWS)  # 5 draws, 00001..00005
    frozen(paths)
    page = _mirror_raw_page(paths)
    original_lines = [l for l in page.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(original_lines) == 5

    # condition 1: max(received) < max(staged) -- the raw run no longer has the highest staged id
    _rewrite_page_and_manifest(page, "\n".join(original_lines[:4]) + "\n")
    r1 = _report(paths, as_of)
    ir1 = next(c for c in r1["checks"] if c["check_id"] == "ingestion.runs")
    f1 = next(f for f in ir1["findings"] if f["rule"] == "mirror_shrink")
    assert f1["level"] == "WARN"
    assert ir1["status"] == "WARN"
    assert r1["overall_status"] != "FAIL"
    assert f1["accepted"] is False  # no known_issues.json present -> nothing to accept it anyway

    # condition 2: staged ids are not a subset of received, even though max matches (a middle id vanished)
    reordered = [original_lines[0], original_lines[1], original_lines[3], original_lines[4]]  # drop 00003, keep 00005
    _rewrite_page_and_manifest(page, "\n".join(reordered) + "\n")
    r2 = _report(paths, as_of)
    ir2 = next(c for c in r2["checks"] if c["check_id"] == "ingestion.runs")
    f2 = next(f for f in ir2["findings"] if f["rule"] == "mirror_shrink")
    assert f2["level"] == "WARN"

    # not evaluated when `received` is empty (an empty fetch is `incremental_empty_fetch`, not `mirror_shrink`)
    _rewrite_page_and_manifest(page, "")
    r3 = _report(paths, as_of)
    ir3 = next(c for c in r3["checks"] if c["check_id"] == "ingestion.runs")
    assert not any(f["rule"] == "mirror_shrink" for f in ir3["findings"])

    # a known issue can never accept mirror_shrink (RULES["mirror_shrink"].acceptable_sources is empty)
    (paths.config).mkdir(parents=True, exist_ok=True)
    ki_path = paths.config / "known_issues.json"
    ki_path.write_text(json.dumps({
        "schema_version": "1.0",
        "issues": [{
            "id": "KI-001", "source": "github_mirror", "draw_id": "00005",
            "rules": ["mirror_shrink"], "pins": {}, "reason": "r", "evidence": "e",
            "approved_by": "a", "approved_on": "2017-08-01", "approval_ref": "ref", "review_by": "2099-01-01",
        }],
    }), encoding="utf-8")
    with pytest.raises(KnownIssuesError):
        load_known_issues(ki_path)

    _rewrite_page_and_manifest(page, "\n".join(original_lines) + "\n")  # leave the tmp fixture clean


def test_orphan_quality_log_warn(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    _append_csv(paths.logs / "quality_log.csv", QUALITY_COLS, [{
        "check_id": "x-1", "run_id": "no-such-run", "draw_id": "00001", "rule": "main_range", "status": "error", "detail": "d",
    }])
    r = _report(paths, as_of)
    ql = next(c for c in r["checks"] if c["check_id"] == "quality_log.open")
    assert any(f["rule"] == "log_integrity" for f in ql["findings"])


def test_quality_log_open_vs_resolved(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    log = pd.read_csv(paths.logs / "ingestion_log.csv", dtype=str)
    run_id = log[log["source"] == "vietlott_official"].iloc[-1]["run_id"]
    _append_csv(paths.logs / "quality_log.csv", QUALITY_COLS, [{
        "check_id": "x-2", "run_id": run_id, "draw_id": "09999", "rule": "main_range", "status": "error", "detail": "d",
    }])
    r = _report(paths, as_of)
    ql = next(c for c in r["checks"] if c["check_id"] == "quality_log.open")
    f = next(f for f in ql["findings"] if f["draw_id"] == "09999")
    assert "open" in f["detail"]
    assert f["level"] == "FAIL"  # official source, still open (draw not in staging)


def test_stored_row_conflict_resolved_by_clean_rerun(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    log = pd.read_csv(paths.logs / "ingestion_log.csv", dtype=str)
    run_id = log[log["source"] == "github_mirror"].iloc[-1]["run_id"]
    _append_csv(paths.logs / "quality_log.csv", QUALITY_COLS, [{
        "check_id": "x-3", "run_id": run_id, "draw_id": "00001", "rule": "stored_row_conflict", "status": "error", "detail": "d",
    }])
    _append_csv(paths.logs / "ingestion_log.csv", INGESTION_COLS, [{
        "run_id": "zzz_rerun", "source": "github_mirror", "mode": "incremental",
        "started_at": as_of.isoformat(), "finished_at": as_of.isoformat(),
        "rows_received": 1, "rows_inserted": 0, "rows_skipped": 1, "status": "success", "error_message": "",
    }])
    from src.ingestion.raw_archive import RawArchive
    from src.api.models import RawPage
    page = RawPage("github_mirror", 0, "u", {}, 200, json.dumps({"date": "2017-08-01", "id": "00001", "result": [1, 2, 3, 4, 5, 6, 7]}), "text/plain", as_of)
    RawArchive(paths.raw).write("zzz_rerun", page)
    r = _report(paths, as_of)
    ql = next(c for c in r["checks"] if c["check_id"] == "quality_log.open")
    f = next(f for f in ql["findings"] if f["draw_id"] == "00001" and f["rule"] == "stored_row_conflict")
    assert "resolved" in f["detail"]
    assert f["level"] == "INFO"


def test_missing_quality_log_with_partial_run(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    assert not (paths.logs / "quality_log.csv").exists()
    _append_csv(paths.logs / "ingestion_log.csv", INGESTION_COLS, [{
        "run_id": "zzz_partial_off", "source": "vietlott_official", "mode": "incremental",
        "started_at": as_of.isoformat(), "finished_at": as_of.isoformat(),
        "rows_received": 1, "rows_inserted": 0, "rows_skipped": 0, "status": "partial", "error_message": "",
    }])
    r = _report(paths, as_of)
    ql = next(c for c in r["checks"] if c["check_id"] == "quality_log.open")
    assert ql["status"] == "FAIL"
    assert any(f["rule"] == "log_integrity" and f["level"] == "FAIL" for f in ql["findings"])


# ------------------------------------------------------------- reconcile
def test_reconcile_mismatch_fail(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    mirror = pd.read_csv(_staging_path(paths, "github_mirror"), dtype={"draw_id": str, "draw_date": str})
    mirror.loc[0, "special_number"] = 99
    _rewrite_staging(paths, mirror, "github_mirror")
    r = _report(paths, as_of)
    rs = next(c for c in r["checks"] if c["check_id"] == "reconcile.sources")
    assert rs["status"] == "FAIL"
    assert any(f["rule"] == "reconcile.field_mismatch" for f in rs["findings"])
    assert r["overall_status"] == "FAIL"


def test_only_right_warn(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    mirror = pd.read_csv(_staging_path(paths, "github_mirror"), dtype={"draw_id": str, "draw_date": str})
    extra = mirror.iloc[[0]].copy()
    extra["draw_id"] = "09999"
    mirror = pd.concat([mirror, extra], ignore_index=True)
    _rewrite_staging(paths, mirror, "github_mirror")
    r = _report(paths, as_of)
    rs = next(c for c in r["checks"] if c["check_id"] == "reconcile.sources")
    assert any(f["rule"] == "reconcile.only_right" and f["level"] == "WARN" for f in rs["findings"])


def test_mirror_lag_info_then_warn(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    mirror = pd.read_csv(_staging_path(paths, "github_mirror"), dtype={"draw_id": str, "draw_date": str})
    mirror = mirror[mirror["draw_id"] != "00005"]  # mirror lags by one draw
    _rewrite_staging(paths, mirror, "github_mirror")
    r = _report(paths, as_of)
    rs = next(c for c in r["checks"] if c["check_id"] == "reconcile.sources")
    lag = next(f for f in rs["findings"] if f["rule"] == "reconcile.mirror_lag")
    assert lag["level"] == "INFO"


# ------------------------------------------------------------- freshness
def test_freshness_pending_before_deadline(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    pending_as_of = datetime.combine(date(2017, 8, 12), datetime.min.time(), tzinfo=LOCAL_TZ) + timedelta(hours=10)
    r = _report(paths, pending_as_of)
    cf = next(c for c in r["checks"] if c["check_id"] == "coverage.freshness")
    assert any(f["rule"] == "freshness_pending" for f in cf["findings"])
    assert cf["status"] == "PASS"


def test_freshness_warn(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    later = datetime.combine(date(2017, 8, 20), datetime.min.time(), tzinfo=LOCAL_TZ) + timedelta(hours=22)
    r = _report(paths, later)
    cf = next(c for c in r["checks"] if c["check_id"] == "coverage.freshness")
    assert cf["status"] == "WARN"
    assert r["overall_status"] != "FAIL"


def test_freshness_fail_over_6(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    much_later = datetime.combine(date(2017, 9, 20), datetime.min.time(), tzinfo=LOCAL_TZ) + timedelta(hours=22)
    r = _report(paths, much_later)
    cf = next(c for c in r["checks"] if c["check_id"] == "coverage.freshness")
    assert cf["status"] == "FAIL"
    assert r["overall_status"] == "FAIL"


# ------------------------------------------------------------- known issues integration
def test_ki_accepts_but_lists(paths, frozen):
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    mirror = pd.read_csv(_staging_path(paths, "github_mirror"), dtype={"draw_id": str, "draw_date": str})
    mirror = mirror[mirror["draw_id"] != "00003"]
    _rewrite_staging(paths, mirror, "github_mirror")
    (paths.config).mkdir(parents=True, exist_ok=True)
    (paths.config / "known_issues.json").write_text(json.dumps({
        "schema_version": "1.0",
        "issues": [{
            "id": "KI-001", "source": "github_mirror", "draw_id": "00003",
            "rules": ["reconcile.only_left"], "pins": {}, "reason": "r", "evidence": "e",
            "approved_by": "a", "approved_on": "2017-08-01", "approval_ref": "ref", "review_by": "2099-01-01",
        }],
    }), encoding="utf-8")
    r = _report(paths, as_of)
    rs = next(c for c in r["checks"] if c["check_id"] == "reconcile.sources")
    f = next(f for f in rs["findings"] if f["draw_id"] == "00003")
    assert f["accepted"] is True and f["known_issue_id"] == "KI-001"
    assert r["overall_status"] == "PASS"
    ki_out = next(k for k in r["known_issues"] if k["id"] == "KI-001")
    assert ki_out["matched"] == {"reconcile.only_left": 1}


def test_ki_unused_warn(paths, frozen):
    """known_issue_unused (WARN, or INFO once a date-range entry has elapsed, R3 N9) and
    known_issue_rule_unused (always INFO) — the safety net that flags a stale/no-longer-matching KI."""
    as_of = build_fixture(paths, DRAWS)
    frozen(paths)
    mirror = pd.read_csv(_staging_path(paths, "github_mirror"), dtype={"draw_id": str, "draw_date": str})
    mirror = mirror[mirror["draw_id"] != "00003"]  # -> a real reconcile.only_left finding on 00003
    _rewrite_staging(paths, mirror, "github_mirror")
    (paths.config).mkdir(parents=True, exist_ok=True)
    (paths.config / "known_issues.json").write_text(json.dumps({
        "schema_version": "1.0",
        "issues": [
            {   # matches nothing at all -> whole-entry known_issue_unused, WARN
                "id": "KI-001", "source": "github_mirror", "draw_id": "00099",
                "rules": ["chronological_order"], "pins": {}, "reason": "r", "evidence": "e",
                "approved_by": "a", "approved_on": "2017-08-01", "approval_ref": "ref", "review_by": "2099-01-01",
            },
            {   # one rule matches (reconcile.only_left on 00003), the other never fires -> known_issue_rule_unused, INFO
                "id": "KI-002", "source": "github_mirror", "draw_id": "00003",
                "rules": ["reconcile.only_left", "chronological_order"], "pins": {}, "reason": "r", "evidence": "e",
                "approved_by": "a", "approved_on": "2017-08-01", "approval_ref": "ref", "review_by": "2099-01-01",
            },
            {   # active (not expired: review_by is far in the future) but its date range elapsed
                # relative to as_of (2017-08-10) -> "unused" is reported as INFO, not WARN (R3 N9)
                "id": "KI-003", "source": "vietlott_official", "rules": ["freshness"],
                "draw_date_from": "2010-01-01", "draw_date_to": "2010-01-31", "pins": {},
                "reason": "r", "evidence": "e",
                "approved_by": "a", "approved_on": "2010-01-01", "approval_ref": "ref", "review_by": "2099-01-01",
            },
        ],
    }), encoding="utf-8")
    r = _report(paths, as_of)
    kf = next(c for c in r["checks"] if c["check_id"] == "known_issues.file")
    by_ki = {f["observed"]["known_issue_id"]: f for f in kf["findings"] if f["rule"] == "known_issue_unused"}

    assert by_ki["KI-001"]["level"] == "WARN"
    assert kf["status"] == "WARN"  # an unused, wholly-unmatched entry is itself a data-quality signal

    assert "KI-002" not in by_ki  # KI-002 matched at least one finding -> no whole-entry "unused"
    rule_unused = [f for f in kf["findings"] if f["rule"] == "known_issue_rule_unused"]
    ki002_unused_rules = {f["observed"]["rule"] for f in rule_unused if f["observed"]["known_issue_id"] == "KI-002"}
    assert ki002_unused_rules == {"chronological_order"}
    assert all(f["level"] == "INFO" for f in rule_unused)

    assert by_ki["KI-003"]["level"] == "INFO"  # R3 N9: elapsed date range -> INFO, not WARN

    for ki_out in r["known_issues"]:
        if ki_out["id"] == "KI-002":
            assert ki_out["matched"] == {"reconcile.only_left": 1}
        else:
            assert ki_out["matched"] == {}
