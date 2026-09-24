import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from src.api.base import DrawSource
from src.api.models import RawPage
from src.ingestion.loader import build_curated, read_staging, run_ingestion
from src.ingestion.raw_archive import RawArchive

TODAY = date(2026, 9, 24)


class StubSource(DrawSource):
    """Serves draws as JSON pages of 3, newest first; honours stop_at_draw_id."""

    name = "stub"

    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r: r["id"], reverse=True)
        self.pages_served = 0

    def iter_raw_pages(self, start_date=None, end_date=None, stop_at_draw_id=None):
        for i in range(0, len(self.rows), 3):
            chunk = self.rows[i:i + 3]
            self.pages_served += 1
            yield RawPage(self.name, i // 3, "stub://", {}, 200, json.dumps(chunk), "application/json", datetime.now(timezone.utc))
            if stop_at_draw_id and min(r["id"] for r in chunk) <= stop_at_draw_id:
                return

    def parse(self, page):
        from src.api.models import DrawRecord
        return [DrawRecord(r["id"], date.fromisoformat(r["date"]), tuple(r["main"]), r["special"], self.name, page.retrieved_at)
                for r in json.loads(page.content)]


def row(no, d, main=(1, 2, 3, 4, 5, 6), special=7):
    return {"id": f"{no:05d}", "date": d, "main": list(main), "special": special}


BASE = [row(1, "2017-08-01"), row(2, "2017-08-03"), row(3, "2017-08-05"), row(4, "2017-08-08"), row(5, "2017-08-10")]


def test_full_then_rerun_is_idempotent(paths):
    r1 = run_ingestion(StubSource(BASE), paths, mode="full", today=TODAY)
    assert (r1.rows_inserted, r1.status) == (5, "success")
    staging_before = (paths.staging / "stub" / "draws.csv").read_bytes()

    r2 = run_ingestion(StubSource(BASE), paths, mode="full", today=TODAY)
    assert r2.rows_inserted == 0 and r2.rows_skipped == 5
    assert (paths.staging / "stub" / "draws.csv").read_bytes() == staging_before


def test_incremental_fetches_only_until_known_draw(paths):
    run_ingestion(StubSource(BASE), paths, mode="full", today=TODAY)
    src = StubSource(BASE + [row(6, "2017-08-12"), row(7, "2017-08-15")])
    r = run_ingestion(src, paths, mode="incremental", today=TODAY)
    assert r.rows_inserted == 2
    assert src.pages_served == 1  # page 0 = 7,6,5 reaches known draw 5
    assert list(read_staging(paths, "stub")["draw_id"]) == [f"{i:05d}" for i in range(1, 8)]


def test_raw_is_archived_with_checksums(paths):
    r = run_ingestion(StubSource(BASE), paths, mode="full", today=TODAY)
    run_dir = paths.raw / "stub" / r.run_id
    manifest = [json.loads(l) for l in (run_dir / "manifest.jsonl").read_text().splitlines()]
    assert [m["file"] for m in manifest] == ["page_00000.json", "page_00001.json"]
    assert RawArchive(paths.raw).verify("stub", r.run_id) == []
    (run_dir / "page_00000.json").write_text("tampered")
    assert RawArchive(paths.raw).verify("stub", r.run_id) == ["page_00000.json"]


def test_raw_archive_never_overwrites(paths):
    archive = RawArchive(paths.raw)
    p = RawPage("stub", 0, "u", {}, 200, "{}", "application/json", datetime.now(timezone.utc))
    archive.write("run1", p)
    with pytest.raises(FileExistsError):
        archive.write("run1", p)


def test_invalid_rows_are_rejected_and_logged(paths):
    rows = BASE + [row(6, "2017-08-12", main=(1, 2, 3, 4, 5, 60)), row(7, "2030-01-01")]
    r = run_ingestion(StubSource(rows), paths, mode="full", today=TODAY)
    assert r.status == "partial"
    assert r.rows_inserted == 5
    qlog = pd.read_csv(paths.logs / "quality_log.csv", dtype=str)
    assert {"main_range", "not_future_dated"} <= set(qlog["rule"])


def test_changed_history_is_flagged_not_overwritten(paths):
    run_ingestion(StubSource(BASE), paths, mode="full", today=TODAY)
    changed = [dict(r) for r in BASE]
    changed[0]["special"] = 9
    r = run_ingestion(StubSource(changed), paths, mode="full", today=TODAY)
    assert any(q.rule == "stored_row_conflict" and q.draw_id == "00001" for q in r.issues)
    assert read_staging(paths, "stub").iloc[0]["special_number"] == 7


def test_failed_run_is_logged(paths):
    class Broken(StubSource):
        def iter_raw_pages(self, *a, **k):
            raise ConnectionError("down")
            yield

    with pytest.raises(RuntimeError, match="failed"):
        run_ingestion(Broken([]), paths, today=TODAY)
    log = pd.read_csv(paths.logs / "ingestion_log.csv")
    assert log.iloc[-1]["status"] == "failed"
    assert "down" in log.iloc[-1]["error_message"]


def test_ingestion_log_counts(paths):
    run_ingestion(StubSource(BASE), paths, mode="full", today=TODAY)
    log = pd.read_csv(paths.logs / "ingestion_log.csv")
    assert log.iloc[0][["rows_received", "rows_inserted", "rows_skipped"]].tolist() == [5, 5, 0]


def test_build_curated_is_deterministic(paths):
    run_ingestion(StubSource(BASE), paths, mode="full", today=TODAY)
    m1 = build_curated(paths, "stub")
    fd1 = (paths.curated / "fact_draw.csv").read_bytes()
    m2 = build_curated(paths, "stub")
    assert m1["dataset_version"] == m2["dataset_version"]
    assert (paths.curated / "fact_draw.csv").read_bytes() == fd1
    assert m1["draws"] == 5 and m1["files"]["fact_draw_number.csv"] == 35
