"""Tests for src/reporting/m4.py orchestration: spec gate, ceiling, banned-word guard, determinism."""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pandas as pd
import pytest

from src.config import Paths
from src.reporting import eda as eda_reporting
from src.reporting import m4 as m4_reporting
from src.transformation import tables

SPEC_TEXT = "SPECIFICATION fixture content for hashing.\n"
SPEC_SHA = hashlib.sha256(SPEC_TEXT.encode("utf-8")).hexdigest()


def _write_spec(root: Path, text: str = SPEC_TEXT) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "SPECIFICATION.md").write_bytes(text.encode("utf-8"))


def _approval_line(version="v1.2.1", sha=SPEC_SHA) -> str:
    return f"SPECIFICATION {version} APPROVED sha256={sha}"


def _default_taskboard(root: Path) -> None:
    lines = ["# Task board", "", "### Decisions (human Project Lead)", _approval_line(), "", "## Other", "x"]
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "TASKBOARD.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _gen_draws(n: int, seed: int = 0) -> pd.DataFrame:
    rng = random.Random(seed)
    rows = []
    for i in range(1, n + 1):
        nums = sorted(rng.sample(range(1, 56), 6))
        remaining = [x for x in range(1, 56) if x not in nums]
        special = rng.choice(remaining)
        year = 2017 + (i - 1) // max(1, n // 3 or 1)
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


# ---------------------------------------------------------------------------
# Spec gate / ceiling reuse (same as M3)
# ---------------------------------------------------------------------------

def test_m4_ceiling_constant_matches_eda():
    assert m4_reporting.M4_MAX_THROUGH_DRAW == eda_reporting.EDA_MAX_THROUGH_DRAW == "01190"


def test_m4_refuses_above_ceiling_even_with_override_like_ref(tmp_path, monkeypatch, caplog):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(30))
    called = []
    monkeypatch.setattr(tables, "read_fact_draw", lambda *a, **k: called.append(1) or (_ for _ in ()).throw(AssertionError))
    with caplog.at_level("WARNING"):
        code = m4_reporting.run_m4(paths, "01191", tmp_path / "out", R=5)
    assert code == 2
    assert not called
    assert not (tmp_path / "out").exists()
    events = [r.message for r in caplog.records if r.name == "src.reporting.m4"]
    assert "m4_ceiling_refused" in events


def test_m4_spec_not_approved_exits_2(tmp_path, caplog):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "TASKBOARD.md").write_text("# Task board\n\nno decisions\n", encoding="utf-8")
    _write_curated(paths, _gen_draws(30))
    with caplog.at_level("WARNING"):
        code = m4_reporting.run_m4(paths, "00030", tmp_path / "out", R=5)
    assert code == 2
    assert not (tmp_path / "out").exists()


def test_m4_runs_on_small_synthetic_dataset(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    code = m4_reporting.run_m4(paths, "00060", tmp_path / "out", R=25)
    assert code == 0
    out_dir = tmp_path / "out" / "through_00060"
    assert (out_dir / "m4_results.csv").exists()
    assert (out_dir / "m4_manifest.json").exists()
    assert (out_dir / "summary.md").exists()
    results = pd.read_csv(out_dir / "m4_results.csv")
    # n=60 has no rolling windows of W=170 (C8 not applicable, m drops to 12; see confirmatory.py).
    assert len(results) == 12
    for col in ("id", "hypothesis", "statistic", "null", "p_sim", "p_holm", "decision"):
        assert col in results.columns
    manifest = json.loads((out_dir / "m4_manifest.json").read_text())
    assert manifest["spec_version"] == "1.2.1"
    assert manifest["spec_sha256"] == SPEC_SHA
    assert manifest["seed"] == 20260924
    assert "code_version" in manifest


def test_m4_deterministic_two_runs(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    m4_reporting.run_m4(paths, "00060", tmp_path / "out1", R=25)
    m4_reporting.run_m4(paths, "00060", tmp_path / "out2", R=25)
    r1 = pd.read_csv(tmp_path / "out1" / "through_00060" / "m4_results.csv")
    r2 = pd.read_csv(tmp_path / "out2" / "through_00060" / "m4_results.csv")
    pd.testing.assert_frame_equal(r1, r2)


def test_m4_summary_has_no_banned_words(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    m4_reporting.run_m4(paths, "00060", tmp_path / "out", R=25)
    text = (tmp_path / "out" / "through_00060" / "summary.md").read_text(encoding="utf-8")
    m4_reporting.check_no_banned_words(text)  # raises if a banned word is present


def test_escalation_needed_detection():
    df = pd.DataFrame({"p_holm": [0.01, 0.05, 0.9]})
    assert m4_reporting.escalation_needed(df) is True
    df2 = pd.DataFrame({"p_holm": [0.01, 0.5, 0.9]})
    assert m4_reporting.escalation_needed(df2) is False


# ---------------------------------------------------------------------------
# M1: follow-up interpretation labels
# ---------------------------------------------------------------------------

def test_label_followups_switches_on_parent_decision():
    followups = {"C1": pd.DataFrame({"number": [1, 2], "p_raw": [0.01, 0.02]})}

    rejected = pd.DataFrame({"id": ["C1"], "decision": ["reject"], "p_holm": [0.03]})
    labeled = m4_reporting.label_followups(followups, rejected)
    assert (labeled["C1"]["interpretation"] == "parent rejected (p_holm=0.03000)").all()

    not_rejected = pd.DataFrame({"id": ["C1"], "decision": ["not_reject"], "p_holm": [0.5]})
    labeled2 = m4_reporting.label_followups(followups, not_rejected)
    assert (labeled2["C1"]["interpretation"] == "parent not rejected; not interpreted").all()

    labeled3 = m4_reporting.label_followups(followups, not_rejected, superseded=True)
    assert (labeled3["C1"]["interpretation"] == "superseded by escalation; see the escalated follow-up table").all()


def test_m1_followup_csvs_always_written_with_interpretation_column(tmp_path):
    """M1: C1/C2 (and every other) follow-up CSV is always written, with an interpretation label,
    regardless of whether the parent rejected."""
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    code = m4_reporting.run_m4(paths, "00060", tmp_path / "out", R=25)
    assert code == 0
    out_dir = tmp_path / "out" / "through_00060"
    results = pd.read_csv(out_dir / "m4_results.csv").set_index("id")

    for tid in ("C1", "C2"):
        fu_path = out_dir / f"m4_followup_{tid}.csv"
        assert fu_path.exists(), f"{tid} follow-up must always be written"
        fu = pd.read_csv(fu_path)
        assert "interpretation" in fu.columns
        decision = results.loc[tid, "decision"]
        if decision == "reject":
            assert fu["interpretation"].str.startswith("parent rejected").all()
        else:
            assert (fu["interpretation"] == "parent not rejected; not interpreted").all()


# ---------------------------------------------------------------------------
# M2: expanded results columns / OBSERVED / INTERPRETATION wording
# ---------------------------------------------------------------------------

def test_m2_results_csv_has_n_N_and_replicate_mean(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    m4_reporting.run_m4(paths, "00060", tmp_path / "out", R=25)
    results = pd.read_csv(tmp_path / "out" / "through_00060" / "m4_results.csv")
    for col in ("n", "N", "replicate_mean"):
        assert col in results.columns
    assert (results["N"] == 6 * results["n"]).all()


def test_m2_summary_observed_and_interpretation_sections(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    m4_reporting.run_m4(paths, "00060", tmp_path / "out", R=25)
    text = (tmp_path / "out" / "through_00060" / "summary.md").read_text(encoding="utf-8")
    assert "## OBSERVED" in text
    assert "C1: dispersion ratio" in text
    assert "## INTERPRETATION" in text
    results = pd.read_csv(tmp_path / "out" / "through_00060" / "m4_results.csv")
    if (results["decision"] == "reject").sum() == 0:
        assert "No confirmatory evidence against H1-H5" in text
        assert "Non-rejection is not proof" in text
        assert "does not survive the pre-registered multiplicity control" in text


# ---------------------------------------------------------------------------
# m5: escalation marks the primary table superseded and uses escalated decisions
# ---------------------------------------------------------------------------

def test_m5_escalation_marks_superseded_and_uses_escalated_decisions(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))

    monkeypatch.setattr(m4_reporting, "escalation_needed", lambda fam_df: True)
    monkeypatch.setattr(m4_reporting.conf, "R_ESCALATE", 15)  # keep the forced escalated run cheap

    code = m4_reporting.run_m4(paths, "00060", tmp_path / "out", R=10)
    assert code == 0
    out_dir = tmp_path / "out" / "through_00060"

    results = pd.read_csv(out_dir / "m4_results.csv")
    assert (results["decision"] == "superseded_by_escalation").all()
    assert (out_dir / "m4_results_escalated.csv").exists()
    results_esc = pd.read_csv(out_dir / "m4_results_escalated.csv")
    assert set(results_esc["decision"]) <= {"reject", "not_reject"}

    manifest = json.loads((out_dir / "m4_manifest.json").read_text())
    assert manifest["escalated"] is True
    assert manifest["escalation_streams"] == {"fresh": 1101, "perm": 1102}

    fu = pd.read_csv(out_dir / "m4_followup_C1.csv")
    assert (fu["interpretation"] == "superseded by escalation; see the escalated follow-up table").all()
    fu_esc = pd.read_csv(out_dir / "m4_followup_C1_escalated.csv")
    assert "interpretation" in fu_esc.columns

    text = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert "escalated: True" in text
    assert "final (m5)" in text


# ---------------------------------------------------------------------------
# n8: frozen dataset version / frozen_prefix status in the manifest
# ---------------------------------------------------------------------------

def test_n8_manifest_records_frozen_dataset_version(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    m4_reporting.run_m4(paths, "00060", tmp_path / "out", R=25)
    manifest = json.loads((tmp_path / "out" / "through_00060" / "m4_manifest.json").read_text())
    assert manifest["frozen_dataset_version"] == "ds_cbdf3834368e"
    assert "frozen_prefix_status" in manifest and manifest["frozen_prefix_status"]


# ---------------------------------------------------------------------------
# n9: exploratory scope (computed / deferred) recorded in the manifest
# ---------------------------------------------------------------------------

def test_n9_manifest_lists_computed_and_deferred_exploratory_items(tmp_path):
    paths = _paths(tmp_path)
    _write_spec(tmp_path)
    _default_taskboard(tmp_path)
    _write_curated(paths, _gen_draws(60))
    m4_reporting.run_m4(paths, "00060", tmp_path / "out", R=25)
    manifest = json.loads((tmp_path / "out" / "through_00060" / "m4_manifest.json").read_text())
    exploratory = manifest["exploratory"]
    assert "computed" in exploratory and "deferred" in exploratory
    assert "sum_chi2_m3_bins" in exploratory["computed"]
    assert exploratory["ljung_box_Q5"]["p_asymptotic"] is not None
    assert exploratory["ljung_box_Q20"]["p_asymptotic"] is not None
