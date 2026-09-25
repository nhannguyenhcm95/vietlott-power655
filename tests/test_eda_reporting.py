"""T8, T9, T10, T11, T12, T13(partial), T14: reporting/eda.py orchestration."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import Paths
from src.reporting import eda as reda
from src.transformation import tables

REPO_ROOT = Path(__file__).resolve().parent.parent

SPEC_TEXT = "SPECIFICATION fixture content for hashing.\n"
SPEC_SHA = hashlib.sha256(SPEC_TEXT.encode("utf-8")).hexdigest()


def _write_spec(root: Path, text: str = SPEC_TEXT) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "SPECIFICATION.md").write_bytes(text.encode("utf-8"))


def _write_taskboard(root: Path, lines: list[str]) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "TASKBOARD.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _approval_line(version="v1.2.1", sha=SPEC_SHA) -> str:
    return f"SPECIFICATION {version} APPROVED sha256={sha}"


def _default_taskboard(root: Path, extra_decisions: list[str] | None = None) -> None:
    lines = [
        "# Task board",
        "",
        "### Decisions (human Project Lead)",
        _approval_line(),
    ]
    if extra_decisions:
        lines += extra_decisions
    lines += ["", "## Other section", "not a decision line"]
    _write_taskboard(root, lines)


def _gen_draws(n: int, seed: int = 0) -> pd.DataFrame:
    import random
    rng = random.Random(seed)
    rows = []
    for i in range(1, n + 1):
        nums = sorted(rng.sample(range(1, 56), 6))
        remaining = [x for x in range(1, 56) if x not in nums]
        special = rng.choice(remaining)
        rows.append({
            "draw_id": f"{i:05d}", "draw_date": f"2017-08-{(i % 27) + 1:02d}",
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


# ---------------------------------------------------------------------------
# T14: spec gate
# ---------------------------------------------------------------------------

def _assert_spec_not_approved(paths, out_dir, caplog, monkeypatch):
    """nit-1: spy + caplog on every spec-gate refusal case."""
    called = []
    monkeypatch.setattr(tables, "read_fact_draw", lambda *a, **k: called.append(1) or (_ for _ in ()).throw(AssertionError))
    with caplog.at_level("WARNING"):
        code = reda.run_eda(paths, "00010", out_dir, [5], 2, 50, None)
    assert code == 2
    assert not called
    assert not out_dir.exists()
    events = [r.message for r in caplog.records if r.name == "src.reporting.eda"]
    assert "eda_spec_not_approved" in events


def test_t14_no_approval_line_exits_2(tmp_path, monkeypatch, caplog):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _write_taskboard(tmp_path, ["# Task board", "", "no decisions here"])
    _write_curated(paths, _gen_draws(10))
    _assert_spec_not_approved(paths, tmp_path / "out", caplog, monkeypatch)


@pytest.mark.parametrize("version", ["v1.1", "v1.1.9"])
def test_t14_version_below_minimum_exits_2(tmp_path, version, monkeypatch, caplog):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    text = "\n".join(["# Task board", "", "### Decisions", _approval_line(version=version)])
    (tmp_path / "docs" / "TASKBOARD.md").write_text(text + "\n", encoding="utf-8")
    _write_curated(paths, _gen_draws(10))
    _assert_spec_not_approved(paths, tmp_path / "out", caplog, monkeypatch)


def test_t14_sha_mismatch_exits_2(tmp_path, monkeypatch, caplog):
    paths = _paths(tmp_path)
    _write_spec(tmp_path, text="different content\n")
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(10))
    _assert_spec_not_approved(paths, tmp_path / "out", caplog, monkeypatch)


@pytest.mark.parametrize("version", ["v1.10", "v1.2.1", "v1.2"])
def test_t14_valid_versions_proceed(tmp_path, version):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    text = "\n".join(["# Task board", "", "### Decisions", _approval_line(version=version)])
    (tmp_path / "docs" / "TASKBOARD.md").write_text(text + "\n", encoding="utf-8")
    _write_curated(paths, _gen_draws(10))
    code = reda.run_eda(paths, "00010", tmp_path / "out", [5], 2, 50, None)
    assert code == 0
    manifest = json.loads((tmp_path / "out" / "through_00010" / "eda_manifest.json").read_text())
    assert manifest["spec_version"] == version.lstrip("v")
    assert manifest["spec_sha256"] == SPEC_SHA


# ---------------------------------------------------------------------------
# T8: range respected / ceiling
# ---------------------------------------------------------------------------

def _assert_ceiling_refused(paths, through_draw, override_ref, out_dir, caplog, monkeypatch, expect_ref_in_log=None):
    """nit-1: every refusal case gets the read_fact_draw spy, the no-files-written check, and a
    caplog assertion that `eda_ceiling_refused` was actually logged."""
    called = []
    monkeypatch.setattr(tables, "read_fact_draw", lambda *a, **k: called.append(1) or (_ for _ in ()).throw(AssertionError("read_fact_draw must not be called on refusal")))
    with caplog.at_level("WARNING"):
        code = reda.run_eda(paths, through_draw, out_dir, [5], 2, 50, override_ref)
    assert code == 2
    assert not called
    assert not out_dir.exists()
    events = [r.message for r in caplog.records if r.name == "src.reporting.eda"]
    assert "eda_ceiling_refused" in events
    if expect_ref_in_log is not None:
        matching = [r for r in caplog.records if r.message == "eda_ceiling_refused"]
        assert any(expect_ref_in_log in str(getattr(r, "detail", "")) for r in matching)


def test_t8d_ceiling_refused_without_override(tmp_path, monkeypatch, caplog):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(1191))
    _assert_ceiling_refused(paths, "01191", None, tmp_path / "out", caplog, monkeypatch)


def test_t8d_ceiling_refused_ref_not_present(tmp_path, monkeypatch, caplog):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(1191))
    _assert_ceiling_refused(paths, "01191", "D-99", tmp_path / "out", caplog, monkeypatch)


def test_t8d_ref_in_non_decisions_section_refused(tmp_path, monkeypatch, caplog):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    lines = [
        "# Task board", "", "### Decisions", _approval_line(), "",
        "## Other section",
        "D-1 EDA ceiling override should not count here",
    ]
    _write_taskboard(tmp_path, lines)
    _write_curated(paths, _gen_draws(1191))
    _assert_ceiling_refused(paths, "01191", "D-1", tmp_path / "out", caplog, monkeypatch)


def test_t8d_ref_substring_not_matched(tmp_path, monkeypatch, caplog):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    lines = [
        "# Task board", "", "### Decisions", _approval_line(),
        "D-12 EDA ceiling override approved",
    ]
    _write_taskboard(tmp_path, lines)
    _write_curated(paths, _gen_draws(1191))
    _assert_ceiling_refused(paths, "01191", "D-1", tmp_path / "out", caplog, monkeypatch)


def test_t8d_malformed_ref_exits_2(tmp_path, monkeypatch, caplog):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path, extra_decisions=["notaref EDA ceiling override"])
    _write_curated(paths, _gen_draws(1191))
    _assert_ceiling_refused(paths, "01191", "notaref", tmp_path / "out", caplog, monkeypatch)


def test_t8d_heading_with_suffix_counts(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    lines = [
        "# Task board", "", "### Decisions after the audit",
        _approval_line(),
        "D-1 EDA ceiling override approved by human",
    ]
    _write_taskboard(tmp_path, lines)
    _write_curated(paths, _gen_draws(1191))
    code = reda.run_eda(paths, "01191", tmp_path / "out", [5], 2, 50, "D-1")
    assert code == 0
    out_dir = tmp_path / "out" / "through_01191_override"
    assert out_dir.exists()
    manifest = json.loads((out_dir / "eda_manifest.json").read_text())
    assert manifest["override_ref"] == "D-1"
    df = pd.read_csv(out_dir / "draw_metrics.csv", dtype=str)
    assert (df["override_ref"] == "D-1").all()
    assert (df["draw_id"].astype(int) <= 1191).all()


def test_t8d_valid_override_real_taskboard_never_read(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    lines = ["# Task board", "", "### Decisions", _approval_line(), "D-1 EDA ceiling override approved"]
    _write_taskboard(tmp_path, lines)
    _write_curated(paths, _gen_draws(1191))

    real_taskboard = REPO_ROOT / "docs" / "TASKBOARD.md"
    original_read_text = Path.read_text

    def spy_read_text(self, *a, **k):
        assert self != real_taskboard, "the real TASKBOARD.md must never be read"
        return original_read_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    code = reda.run_eda(paths, "01191", tmp_path / "out", [5], 2, 50, "D-1")
    assert code == 0


@pytest.mark.parametrize("through_draw", ["1190", "abc", "999999", "00011"])
def test_t8e_malformed_or_nonexistent_through_draw(tmp_path, through_draw):
    """nit-1: 00011 is a real "non-existent cutoff" case (well-formed, in range, but absent from
    a 10-row fixture), not just an out-of-range value that would fail the format check anyway."""
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(10))
    code = reda.run_eda(paths, through_draw, tmp_path / "out", [5], 2, 50, None)
    assert code == 2
    assert not (tmp_path / "out").exists()


def test_t8e_noncontiguous_cutoff(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    df = _gen_draws(10)
    df = df[df["draw_id"] != "00005"]  # remove a row -> gap
    _write_curated(paths, df)
    code = reda.run_eda(paths, "00010", tmp_path / "out", [5], 2, 50, None)
    assert code == 2


def test_t8f_read_fact_draw_called_only_from_load_analysis_draws():
    eda_files = [
        REPO_ROOT / "src" / "reporting" / "eda.py",
        REPO_ROOT / "src" / "reporting" / "eda_charts.py",
        REPO_ROOT / "src" / "statistics" / "eda.py",
        REPO_ROOT / "src" / "statistics" / "mc_reference.py",
        REPO_ROOT / "src" / "statistics" / "null_model.py",
        REPO_ROOT / "src" / "statistics" / "null_reference.py",
    ]
    call_re = re.compile(r"read_fact_draw\(")
    hits = []
    for f in eda_files:
        text = f.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if call_re.search(line) and "def " not in line:
                hits.append((f.name, i, line.strip()))
    assert hits == [("eda.py", hits[0][1], hits[0][2])] if hits else hits
    assert all(h[0] == "eda.py" for h in hits)
    assert len(hits) == 1


def _range_fixture_rows(n_valid: int = 10) -> list[dict]:
    """Deterministic, RNG-free 6-distinct-ascending-number rows."""
    rows = []
    for i in range(1, n_valid + 1):
        nums = sorted({((i * 7 + j) % 55) + 1 for j in range(6)})
        j = 6
        while len(nums) < 6:
            cand = ((i * 7 + j) % 55) + 1
            if cand not in nums:
                nums.append(cand)
            nums = sorted(set(nums))
            j += 1
        special = next(x for x in range(1, 56) if x not in nums)
        rows.append({
            "draw_id": f"{i:05d}", "draw_date": "2017-08-01",
            "n1": nums[0], "n2": nums[1], "n3": nums[2], "n4": nums[3], "n5": nums[4], "n6": nums[5],
            "special_number": special, "source": "test", "retrieved_at": "2020-01-01T00:00:00+00:00",
        })
    return rows


def test_t8ab_range_respected_byte_identical_to_clean(tmp_path):
    """F3: build clean/variant-a/variant-b fixtures sharing the same first 10 rows and *one*
    constant dataset_version (never recomputed per variant, matching T8(g)); compare each variant
    against the clean fixture (not against each other); assert every CSV, eda_summary.md and
    eda_manifest.json are byte-identical; assert no output draw_id exceeds the cutoff (T8c)."""
    clean_rows = _range_fixture_rows(10)
    clean_df = pd.DataFrame(clean_rows)
    const_version = tables.dataset_version(clean_df)
    clean_df["dataset_version"] = const_version

    # (a): a different, but still-valid, tail after the cutoff
    tail_a = pd.DataFrame(_range_fixture_rows(15)[10:])
    tail_a["draw_id"] = [f"{i:05d}" for i in range(11, 16)]
    variant_a = pd.concat([clean_df.drop(columns=["dataset_version"]), tail_a], ignore_index=True)
    variant_a["dataset_version"] = const_version  # kept constant, never recomputed (F3/F4)

    # (b): an invalid tail - out-of-range content, an empty cell, and a non-numeric cell
    bad1 = {**clean_rows[0], "draw_id": "00011", "n1": 99}
    bad2 = {**clean_rows[0], "draw_id": "00012", "n1": ""}
    bad3 = {**clean_rows[0], "draw_id": "00013", "n1": "abc"}
    variant_b = pd.concat([clean_df.drop(columns=["dataset_version"]), pd.DataFrame([bad1, bad2, bad3])], ignore_index=True)
    variant_b["dataset_version"] = const_version

    variants = {"clean": clean_df, "a": variant_a, "b": variant_b}
    out_dirs = {}
    for name, df in variants.items():
        root = tmp_path / name
        paths = _paths(root)
        _write_spec(root)
        _default_taskboard(root)
        _write_curated(paths, df)
        code = reda.run_eda(paths, "00010", root / "out", [5], 2, 50, None)
        assert code == 0, name
        out_dirs[name] = root / "out" / "through_00010"

    clean_dir = out_dirs["clean"]
    clean_files = sorted(p.name for p in clean_dir.glob("*"))
    for name in ("a", "b"):
        variant_dir = out_dirs[name]
        variant_files = sorted(p.name for p in variant_dir.glob("*"))
        assert variant_files == clean_files, name
        for fname in clean_files:
            clean_bytes = (clean_dir / fname).read_bytes()
            variant_bytes = (variant_dir / fname).read_bytes()
            assert clean_bytes == variant_bytes, f"{name}/{fname} differs from the clean fixture"

        # T8(c): no output draw_id exceeds the cutoff
        draw_metrics = pd.read_csv(variant_dir / "draw_metrics.csv", dtype={"draw_id": str})
        assert (draw_metrics["draw_id"].astype(int) <= 10).all()
        assert len(draw_metrics) == 10


def test_t8g_dataset_version_column_change_only_affects_source_version(tmp_path):
    paths_a = _paths(tmp_path / "a")
    paths_b = _paths(tmp_path / "b")
    df = _gen_draws(10)
    df_a = df.copy()
    df_b = df.copy()
    df_b["dataset_version"] = "ds_different_value_ab"

    _write_spec(tmp_path / "a")
    _default_taskboard(tmp_path / "a")
    _write_curated(paths_a, df_a)
    _write_spec(tmp_path / "b")
    _default_taskboard(tmp_path / "b")
    _write_curated(paths_b, df_b)

    reda.run_eda(paths_a, "00010", tmp_path / "a" / "out", [5], 2, 50, None)
    reda.run_eda(paths_b, "00010", tmp_path / "b" / "out", [5], 2, 50, None)

    dir_a = tmp_path / "a" / "out" / "through_00010"
    dir_b = tmp_path / "b" / "out" / "through_00010"
    for f in sorted(dir_a.glob("*.csv")):
        a = pd.read_csv(f)
        b = pd.read_csv(dir_b / f.name)
        assert (a["source_dataset_version"] != b["source_dataset_version"]).all()
        pd.testing.assert_frame_equal(a.drop(columns=["source_dataset_version"]), b.drop(columns=["source_dataset_version"]))

    manifest_a = json.loads((dir_a / "eda_manifest.json").read_text())
    manifest_b = json.loads((dir_b / "eda_manifest.json").read_text())
    assert manifest_a["source_dataset_version"] != manifest_b["source_dataset_version"]
    diffs = {k for k in manifest_a if manifest_a.get(k) != manifest_b.get(k)}
    assert diffs <= {"source_dataset_version", "files"}


def test_f4_post_cutoff_empty_cell_does_not_change_analysis_version(tmp_path):
    """F4: a post-cutoff row with an empty n1 cell must not change `analysis_version` for the
    analysis rows (it would if pandas' whole-column dtype inference (float64, because of the NaN)
    leaked into `tables.dataset_version`'s serialization of the pre-cutoff rows)."""
    clean_rows = _range_fixture_rows(10)
    clean_df = pd.DataFrame(clean_rows)
    const_version = tables.dataset_version(clean_df)
    clean_df["dataset_version"] = const_version

    with_empty_tail = pd.concat(
        [clean_df.drop(columns=["dataset_version"]), pd.DataFrame([{**clean_rows[0], "draw_id": "00011", "n1": ""}])],
        ignore_index=True,
    )
    with_empty_tail["dataset_version"] = const_version

    paths_clean = _paths(tmp_path / "clean")
    _write_spec(tmp_path / "clean")
    _default_taskboard(tmp_path / "clean")
    _write_curated(paths_clean, clean_df)
    data_clean = reda.load_analysis_draws(paths_clean.curated, "00010")

    paths_tail = _paths(tmp_path / "tail")
    _write_spec(tmp_path / "tail")
    _default_taskboard(tmp_path / "tail")
    _write_curated(paths_tail, with_empty_tail)
    data_tail = reda.load_analysis_draws(paths_tail.curated, "00010")

    assert data_tail.analysis_version == data_clean.analysis_version
    assert data_tail.frame[["n1", "n2", "n3", "n4", "n5", "n6"]].dtypes.apply(lambda d: d == np.int64).all()


# ---------------------------------------------------------------------------
# T9: versions
# ---------------------------------------------------------------------------

def test_t9_every_csv_has_version_columns(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(10))
    code = reda.run_eda(paths, "00010", tmp_path / "out", [5], 2, 50, None)
    assert code == 0
    out_dir = tmp_path / "out" / "through_00010"
    for f in sorted(out_dir.glob("*.csv")):
        df = pd.read_csv(f, dtype=str)
        for col in ["source_dataset_version", "analysis_version", "through_draw", "override_ref"]:
            assert col in df.columns, f"{f.name} missing {col}"
            assert df[col].nunique() <= 1


def test_t9_real_curated_pinned_versions():
    curated = REPO_ROOT / "data" / "curated"
    data_1190 = reda.load_analysis_draws(curated, "01190")
    assert data_1190.analysis_version == "ds_16b6be697acb"
    data_980 = reda.load_analysis_draws(curated, "00980")
    assert data_980.analysis_version == "ds_523f687e20df"


# ---------------------------------------------------------------------------
# T10: determinism
# ---------------------------------------------------------------------------

def test_t10_two_runs_identical_hashes(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))

    code1 = reda.run_eda(paths, "00060", tmp_path / "out1", [10, 20], 3, 200, None)
    code2 = reda.run_eda(paths, "00060", tmp_path / "out2", [10, 20], 3, 200, None)
    assert code1 == 0 and code2 == 0

    dir1 = tmp_path / "out1" / "through_00060"
    dir2 = tmp_path / "out2" / "through_00060"
    names1 = sorted(p.name for p in dir1.glob("*"))
    names2 = sorted(p.name for p in dir2.glob("*"))
    assert names1 == names2

    for name in names1:
        # nit-2: PNGs are hashed too (identical within one environment, per spec T10).
        if name.endswith((".csv", ".md", ".json", ".png")):
            h1 = hashlib.sha256((dir1 / name).read_bytes()).hexdigest()
            h2 = hashlib.sha256((dir2 / name).read_bytes()).hexdigest()
            if name == "eda_manifest.json":
                continue  # file hashes inside will match; timestamps aren't recorded, but compare structurally below
            assert h1 == h2, f"{name} differs between runs"

    m1 = json.loads((dir1 / "eda_manifest.json").read_text())
    m2 = json.loads((dir2 / "eda_manifest.json").read_text())
    assert m1 == m2


# ---------------------------------------------------------------------------
# T11: framing guard
# ---------------------------------------------------------------------------

BANNED_PATTERNS = [
    r"\bhot\b", r"\bcold\b", r"\boverdue\b", r"\bdue\b", r"\blucky\b", r"\brecommend\w*\b",
    r"\bpredict\w*\b", r"\bsignifican\w*\b", r"\bp-value\b", r"\bpvalue\b", r"\brank\w*\b",
    r"\bbest\b", r"\btop\b", r"\banomal\w*\b", r"\bstreak\b", r"\bbet\b", r"\bbets\b",
    r"\bbetting\b", r"\bbettor\b", r"\bticket\w*\b", r"\bwager\w*\b", r"\bpick\b", r"\bpicks\b",
    r"\bpicked\b", r"\bpicking\b", r"\bdeviat\w*\b",
]
BANNED_RE = re.compile("|".join(BANNED_PATTERNS), re.IGNORECASE)


def _check_banned(text: str, allow_deviation_line: str | None = None):
    for line in text.splitlines():
        if allow_deviation_line and allow_deviation_line in line:
            line_check = re.sub(re.escape("deviation"), "", line, flags=re.IGNORECASE)
        else:
            line_check = line
        m = BANNED_RE.search(line_check)
        assert not m, f"banned word {m.group(0)!r} in line: {line!r}"


def test_t11_no_banned_words_in_summary(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    reda.run_eda(paths, "00060", tmp_path / "out", [10, 20], 3, 200, None)
    text = (tmp_path / "out" / "through_00060" / "eda_summary.md").read_text(encoding="utf-8")
    _check_banned(text)


def test_t11_no_banned_words_in_csv_headers(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    reda.run_eda(paths, "00060", tmp_path / "out", [10, 20], 3, 200, None)
    out_dir = tmp_path / "out" / "through_00060"
    for f in out_dir.glob("*.csv"):
        header = f.read_text(encoding="utf-8").splitlines()[0]
        _check_banned(header)


def _render_and_collect_titles(tmp_path, reps=200):
    """F9: collect the *actual rendered* titles (fig.axes[*].get_title(), fig._suptitle) from a
    real build, not a source-text regex - which misses f-strings and variable titles."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from src.reporting import eda_charts

    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    data = reda.load_analysis_draws(paths.curated, "00060")
    params = reda.EdaParams(windows=[10, 20], n_blocks=3, mc_reps=reps, override_ref="")
    result = reda.build_eda(data, params, "1.2.1", SPEC_SHA)

    titles: list[str] = []
    original_savefig = plt.Figure.savefig

    def spy_savefig(self, *a, **k):
        for ax in self.axes:
            t = ax.get_title()
            if t:
                titles.append(t)
        if getattr(self, "_suptitle", None) is not None:
            titles.append(self._suptitle.get_text())
        return original_savefig(self, *a, **k)

    charts_dir = tmp_path / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    import unittest.mock
    with unittest.mock.patch.object(plt.Figure, "savefig", spy_savefig):
        eda_charts.render_all(result, charts_dir)
    return titles, result


def test_t11_no_banned_words_in_chart_titles(tmp_path):
    titles, _ = _render_and_collect_titles(tmp_path)
    assert titles, "no titles were collected"
    for title in titles:
        check_title = title
        if "Cumulative count deviation" in title:
            check_title = title.replace("deviation", "")
        _check_banned(check_title)


def test_f9_mc_chart_captions_state_r_and_seed():
    """F9: spec section 0 requires MC captions to state MC(R, seed), not just 'null: MC'."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        titles, result = _render_and_collect_titles(Path(td))
    reps, seed = result.params.mc_reps, result.params.seed
    mc_marker = f"MC(R={reps}, seed={seed})"
    mc_related = [t for t in titles if ("simultaneous" in t.lower() or "envelope" in t.lower()
                                         or "stability" in t.lower() or "block" in t.lower())]
    assert mc_related, "expected at least one MC-referencing chart title"
    for t in mc_related:
        assert mc_marker in t, f"chart title missing MC(R, seed) caption: {t!r}"


def test_t11_summary_lines_match_whitelist(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    reda.run_eda(paths, "00060", tmp_path / "out", [10, 20], 3, 200, None)
    text = (tmp_path / "out" / "through_00060" / "eda_summary.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        if line in reda.FIXED_LINES:
            continue
        assert any(t.match(line) for t in reda.ALL_TEMPLATES), f"line does not match whitelist: {line!r}"


def test_t11_no_number_or_pair_identifier_rows_in_summary(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    reda.run_eda(paths, "00060", tmp_path / "out", [10, 20], 3, 200, None)
    text = (tmp_path / "out" / "through_00060" / "eda_summary.md").read_text(encoding="utf-8")
    assert "first_draw_id" not in text.lower()
    assert "last_draw_id" not in text.lower()
    assert "appearance" not in text.lower()


def test_t11_per_number_per_pair_csvs_sorted_and_have_null_cols(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    reda.run_eda(paths, "00060", tmp_path / "out", [10, 20], 3, 200, None)
    out_dir = tmp_path / "out" / "through_00060"
    freq = pd.read_csv(out_dir / "number_frequency.csv")
    assert list(freq["number"]) == sorted(freq["number"])
    for col in ["expected", "null_lo", "null_hi"]:
        assert col in freq.columns
    pairs = pd.read_csv(out_dir / "pair_cooccurrence.csv")
    assert list(zip(pairs["number_i"], pairs["number_j"])) == sorted(zip(pairs["number_i"], pairs["number_j"]))
    for col in ["expected", "null_lo", "null_hi"]:
        assert col in pairs.columns


# ---------------------------------------------------------------------------
# T12: CLI smoke (real curated data, read-only; outputs never opened/printed)
# ---------------------------------------------------------------------------

def test_t12_cli_smoke_real_data(tmp_path):
    # curated points at the real, read-only data/curated; docs (spec/taskboard) are a tmp fixture.
    paths = Paths(root=tmp_path, data=REPO_ROOT / "data")
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    real_spec_bytes = (REPO_ROOT / "docs" / "SPECIFICATION.md").read_bytes()
    (tmp_path / "docs" / "SPECIFICATION.md").write_bytes(real_spec_bytes)
    real_sha = hashlib.sha256(real_spec_bytes).hexdigest()
    _write_taskboard(tmp_path, ["# Task board", "", "### Decisions", f"SPECIFICATION v1.2.1 APPROVED sha256={real_sha}"])

    code = reda.run_eda(paths, "01190", tmp_path / "outputs", [50, 100, 200], 5, 200, None)
    assert code == 0

    out_dir = tmp_path / "outputs" / "through_01190"
    assert out_dir.exists()
    manifest = json.loads((out_dir / "eda_manifest.json").read_text())
    for fname, sha in manifest["files"].items():
        actual = hashlib.sha256((out_dir / fname).read_bytes()).hexdigest()
        assert actual == sha, f"{fname} hash mismatch"
    # every §5 file must exist
    expected_stems = [
        "draw_metrics", "draw_metric_distribution", "null_pmfs", "draw_metric_summary",
        "number_frequency", "number_frequency_by_period", "number_interarrival",
        "number_appearance", "number_cumulative", "special_frequency", "pair_cooccurrence",
        "pair_count_distribution", "stability_blocks", "mc_reference",
    ]
    for stem in expected_stems:
        assert (out_dir / f"{stem}.csv").exists()
    for w in (50, 100, 200):
        assert (out_dir / f"number_rolling_W{w}.csv").exists()
        assert (out_dir / f"number_rolling_extremes_W{w}.csv").exists()
    assert (out_dir / "eda_summary.md").exists()
    assert manifest["analysis_version"] == "ds_16b6be697acb"
