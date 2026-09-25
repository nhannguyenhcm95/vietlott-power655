"""Tests for src/reporting/m5.py orchestration:
T7 (loader truncation), T12 (gates and outputs), T13 (gate order).
Per docs/experiments/EXP-001.md r2 sections 6, 7, 10."""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pandas as pd
import pytest

from src.config import Paths
from src.evaluation import folds as ev_folds
from src.reporting import eda as eda_reporting
from src.reporting import m5 as m5r
from src.transformation import tables

SPEC_TEXT = "SPECIFICATION fixture content for hashing.\n"
SPEC_SHA = hashlib.sha256(SPEC_TEXT.encode("utf-8")).hexdigest()


def _write_spec(root: Path, text: str = SPEC_TEXT) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "SPECIFICATION.md").write_bytes(text.encode("utf-8"))


def _default_taskboard(root: Path) -> None:
    lines = ["# Task board", "", "### Decisions (human Project Lead)", f"SPECIFICATION v1.2.1 APPROVED sha256={SPEC_SHA}",
              "", "## Other", "x"]
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "TASKBOARD.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _gen_draws(n: int, seed: int = 0) -> pd.DataFrame:
    rng = random.Random(seed)
    rows = []
    for i in range(1, n + 1):
        nums = sorted(rng.sample(range(1, 56), 6))
        remaining = [x for x in range(1, 56) if x not in nums]
        special = rng.choice(remaining)
        year = 2017 + (i - 1) // 400
        rows.append({
            "draw_id": f"{i:05d}", "draw_date": f"{year}-01-{(i % 27) + 1:02d}",
            "n1": nums[0], "n2": nums[1], "n3": nums[2], "n4": nums[3], "n5": nums[4], "n6": nums[5],
            "special_number": special, "source": "test", "retrieved_at": "2020-01-01T00:00:00+00:00",
        })
    df = pd.DataFrame(rows)
    df["dataset_version"] = tables.dataset_version(df)
    return df


def _write_curated(paths: Paths, df: pd.DataFrame) -> None:
    paths.curated.mkdir(parents=True, exist_ok=True)
    df.to_csv(paths.curated / "fact_draw.csv", index=False)


def _paths(tmp_path) -> Paths:
    return Paths(root=tmp_path, data=tmp_path / "data")


def _setup_full_fixture(tmp_path, monkeypatch, n=1190, seed=0, small_bootstrap=True):
    """A full-size (n=1190) fixture with the pin monkeypatched to match, and gates cleared."""
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    df = _gen_draws(n, seed=seed)
    _write_curated(paths, df)
    data = m5r.load_m5_draws(paths.curated)
    monkeypatch.setattr(m5r, "M5_PINNED_ANALYSIS_VERSION", data.analysis_version)
    if small_bootstrap:
        monkeypatch.setattr(m5r, "BOOTSTRAP_B", 20)
    return paths


# ---------------------------------------------------------------------------
# T7: loader truncation
# ---------------------------------------------------------------------------

def test_t7_loads_exactly_1190_rows_and_ignores_malformed_tail(tmp_path):
    paths = _paths(tmp_path)
    good = _gen_draws(1190, seed=1)
    bad_tail_rows = []
    for i in range(1191, 1201):
        bad_tail_rows.append({
            "draw_id": f"{i:05d}", "draw_date": "not-a-date",
            "n1": "x", "n2": None, "n3": 3, "n4": 4, "n5": 5, "n6": 6,
            "special_number": None, "source": "test", "retrieved_at": "2020-01-01T00:00:00+00:00",
            "dataset_version": "irrelevant",
        })
    full = pd.concat([good, pd.DataFrame(bad_tail_rows)], ignore_index=True)
    _write_curated(paths, full)

    data = m5r.load_m5_draws(paths.curated)
    assert data.n_draws == 1190
    assert int(data.frame["draw_id"].astype(int).max()) == 1190

    version_with_tail = data.analysis_version
    # Alter a post-01190 row: analysis_version must not change.
    full2 = full.copy()
    full2.loc[full2["draw_id"] == "01195", "n3"] = 99
    _write_curated(paths, full2)
    data2 = m5r.load_m5_draws(paths.curated)
    assert data2.analysis_version == version_with_tail


def test_t7_m5_max_through_draw_is_01190_with_no_override():
    assert m5r.M5_MAX_THROUGH_DRAW == "01190"
    import inspect
    sig = inspect.signature(m5r.load_m5_draws)
    assert list(sig.parameters) == ["curated_dir"]  # no through_draw / override parameter at all


def test_t7_real_curated_pin_matches_ds_16b6be697acb():
    """Skipped if the real curated data is absent (agent-thread sandboxing / no local data)."""
    real_paths = Paths()
    if not (real_paths.curated / "fact_draw.csv").exists():
        pytest.skip("no real curated data available in this environment")
    data = m5r.load_m5_draws(real_paths.curated)
    assert data.analysis_version == m5r.M5_PINNED_ANALYSIS_VERSION


# ---------------------------------------------------------------------------
# T12: gates and outputs
# ---------------------------------------------------------------------------

def test_t12_spec_sha_mismatch_exits_2(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _write_spec(tmp_path, text="different content\n")
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "TASKBOARD.md").write_text(
        f"# Task board\n\n### Decisions\nSPECIFICATION v1.2.1 APPROVED sha256={SPEC_SHA}\n", encoding="utf-8")
    _write_curated(paths, _gen_draws(1190))
    code = m5r.run_m5(paths)
    assert code == 2
    assert not (tmp_path / "outputs").exists()


def test_t12_dirty_tree_refuses_without_provisional_and_writes_nothing(tmp_path, monkeypatch):
    paths = _setup_full_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(m5r.m4_reporting, "code_version", lambda root: "deadbeef-dirty")
    code = m5r.run_m5(paths, provisional=False)
    assert code == 2
    assert not (tmp_path / "outputs").exists()


def test_t12_dirty_tree_allowed_with_provisional_writes_only_under_provisional(tmp_path, monkeypatch):
    paths = _setup_full_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(m5r.m4_reporting, "code_version", lambda root: "deadbeef-dirty")
    code = m5r.run_m5(paths, provisional=True)
    assert code == 0
    prov_dir = tmp_path / "outputs" / "m5" / "provisional" / "EXP-001"
    assert prov_dir.exists()
    assert not (tmp_path / "outputs" / "m5" / "EXP-001").exists()
    runs = list(prov_dir.glob("*"))
    assert len(runs) == 1
    manifest = json.loads((runs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["provisional"] is True


def test_t12_code_version_computed_before_first_write(tmp_path, monkeypatch):
    paths = _setup_full_fixture(tmp_path, monkeypatch)
    calls = []

    def fake_code_version(root):
        calls.append("code_version")
        return "cleanhead0000000000000000000000000000000"

    monkeypatch.setattr(m5r.m4_reporting, "code_version", fake_code_version)
    monkeypatch.setattr(m5r, "write_m5", lambda *a, **k: (_ for _ in ()).throw(AssertionError("write called")))
    with pytest.raises(AssertionError):
        m5r.run_m5(paths)
    assert calls == ["code_version"]


def test_t12_existing_run_id_refused_and_files_unchanged(tmp_path, monkeypatch):
    paths = _setup_full_fixture(tmp_path, monkeypatch)
    fixed_now = __import__("datetime").datetime(2026, 9, 25, 12, 0, 0, tzinfo=__import__("datetime").timezone.utc)
    code1 = m5r.run_m5(paths, now=fixed_now)
    assert code1 == 0
    run_dir = next((tmp_path / "outputs" / "m5" / "EXP-001").glob("*"))
    before = {p.name: p.read_bytes() for p in run_dir.glob("*")}

    code2 = m5r.run_m5(paths, now=fixed_now)
    assert code2 == 2
    after = {p.name: p.read_bytes() for p in run_dir.glob("*")}
    assert before == after


def test_t12_csvs_have_version_columns_and_no_per_number_columns(tmp_path, monkeypatch):
    paths = _setup_full_fixture(tmp_path, monkeypatch)
    code = m5r.run_m5(paths, now=None)
    assert code == 0
    run_dir = next((tmp_path / "outputs" / "m5" / "EXP-001").glob("*"))
    for name in ("draw_scores", "metrics", "reliability", "w_selection"):
        df = pd.read_csv(run_dir / f"{name}.csv")
        for col in ("experiment_id", "analysis_version", "source_dataset_version", "code_version", "spec_sha256"):
            assert col in df.columns, f"{name}.csv missing {col}"
        for col in df.columns:
            assert col not in (f"p_{k}" for k in range(1, 56)), f"{name}.csv has a per-number column {col}"
            assert col not in (f"n{i}" for i in range(1, 7))


def test_t12_summary_passes_banned_word_check(tmp_path, monkeypatch):
    paths = _setup_full_fixture(tmp_path, monkeypatch)
    code = m5r.run_m5(paths)
    assert code == 0
    run_dir = next((tmp_path / "outputs" / "m5" / "EXP-001").glob("*"))
    text = (run_dir / "summary.md").read_text(encoding="utf-8")
    m5r.m4_reporting.check_no_banned_words(text)  # raises if a banned word is present


def test_t12_two_runs_give_byte_identical_csvs(tmp_path, monkeypatch):
    import datetime as dt
    paths = _setup_full_fixture(tmp_path, monkeypatch)
    code1 = m5r.run_m5(paths, now=dt.datetime(2026, 9, 25, 12, 0, 0, tzinfo=dt.timezone.utc))
    code2 = m5r.run_m5(paths, now=dt.datetime(2026, 9, 25, 12, 0, 1, tzinfo=dt.timezone.utc))
    assert code1 == 0 and code2 == 0
    run_dirs = sorted((tmp_path / "outputs" / "m5" / "EXP-001").glob("*"))
    assert len(run_dirs) == 2
    for name in ("draw_scores", "metrics", "reliability", "w_selection"):
        df1 = pd.read_csv(run_dirs[0] / f"{name}.csv")
        df2 = pd.read_csv(run_dirs[1] / f"{name}.csv")
        pd.testing.assert_frame_equal(df1, df2)


# ---------------------------------------------------------------------------
# T13: gate order
# ---------------------------------------------------------------------------

def test_t13_spec_gate_refusal_zero_spy_calls(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "TASKBOARD.md").write_text("# Task board\n\nno decisions\n", encoding="utf-8")
    _write_curated(paths, _gen_draws(1190))
    spy_calls = []
    monkeypatch.setattr(tables, "read_fact_draw", lambda *a, **k: spy_calls.append(1) or (_ for _ in ()).throw(AssertionError))
    code = m5r.run_m5(paths)
    assert code == 2
    assert spy_calls == []
    assert not (tmp_path / "outputs").exists()


def test_t13_dirty_tree_refusal_zero_spy_calls(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(1190))
    monkeypatch.setattr(m5r.m4_reporting, "code_version", lambda root: "deadbeef-dirty")
    spy_calls = []
    monkeypatch.setattr(tables, "read_fact_draw", lambda *a, **k: spy_calls.append(1) or (_ for _ in ()).throw(AssertionError))
    code = m5r.run_m5(paths, provisional=False)
    assert code == 2
    assert spy_calls == []
    assert not (tmp_path / "outputs").exists()


def test_t13_pin_mismatch_spy_called_once_no_output(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(1190, seed=42))  # analysis_version will not match the real pin
    spy_calls = []
    orig = tables.read_fact_draw

    def spy(*a, **k):
        spy_calls.append(1)
        return orig(*a, **k)
    monkeypatch.setattr(tables, "read_fact_draw", spy)
    code = m5r.run_m5(paths)
    assert code == 2
    assert spy_calls == [1]
    assert not (tmp_path / "outputs").exists()


def test_t13_n_mismatch_spy_called_once_no_output(tmp_path, monkeypatch):
    """The loader's own contiguity invariant guarantees n_draws == max(draw_id), so an n mismatch
    can only arise from data corruption after the load call; this exercises that defensive gate
    check directly, while still counting the one real read_fact_draw call underneath."""
    import dataclasses

    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    df = _gen_draws(1190, seed=1)
    _write_curated(paths, df)
    data = m5r.load_m5_draws(paths.curated)
    monkeypatch.setattr(m5r, "M5_PINNED_ANALYSIS_VERSION", data.analysis_version)

    spy_calls = []
    orig = tables.read_fact_draw

    def spy(*a, **k):
        spy_calls.append(1)
        return orig(*a, **k)
    monkeypatch.setattr(tables, "read_fact_draw", spy)

    def fake_load_m5_draws(curated_dir):
        d = m5r.load_m5_draws.__wrapped__(curated_dir) if hasattr(m5r.load_m5_draws, "__wrapped__") \
            else eda_reporting.load_analysis_draws(curated_dir, m5r.M5_MAX_THROUGH_DRAW)
        return dataclasses.replace(d, n_draws=999)
    monkeypatch.setattr(m5r, "load_m5_draws", fake_load_m5_draws)

    code = m5r.run_m5(paths)
    assert code == 2
    assert spy_calls == [1]
    assert not (tmp_path / "outputs").exists()


def test_t13_fold_table_mismatch_spy_called_once_no_output(tmp_path, monkeypatch):
    paths = _setup_full_fixture(tmp_path, monkeypatch)
    bad_table = m5r.EXPECTED_FOLD_TABLE.copy()
    bad_table.loc[0, "scored_end"] = 9999
    monkeypatch.setattr(m5r, "EXPECTED_FOLD_TABLE", bad_table)
    spy_calls = []
    orig = tables.read_fact_draw

    def spy(*a, **k):
        spy_calls.append(1)
        return orig(*a, **k)
    monkeypatch.setattr(tables, "read_fact_draw", spy)
    code = m5r.run_m5(paths)
    assert code == 2
    assert spy_calls == [1]
    assert not (tmp_path / "outputs").exists()
