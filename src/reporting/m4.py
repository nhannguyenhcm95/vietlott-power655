"""M4 primary confirmatory run orchestration (`docs/SPECIFICATION.md` v1.2.1 section 6).

Reuses the M3 spec-approval gate, ceiling and single-loader pattern from `src/reporting/eda.py`
(same ceiling value, 01190, per section 8.2's data-access table for "M4 primary"). Descriptive
framing rules apply to prose text only: results here ARE confirmatory (p-values, Holm, decisions),
but individual numbers are never named as "hot/cold" or a pick; no betting/selection language.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import scipy

from src.config import Paths
from src.reporting import eda as eda_reporting
from src.statistics import confirmatory as conf
from src.transformation import tables

log = logging.getLogger(__name__)

M4_MAX_THROUGH_DRAW = eda_reporting.EDA_MAX_THROUGH_DRAW  # "01190" (section 8.2: M4 primary ceiling)

# SPECIFICATION section 8.1: "The split is frozen on dataset_version = ds_cbdf3834368e (1,401 draws)."
FROZEN_DATASET_VERSION = "ds_cbdf3834368e"

BANNED_PATTERNS = [
    r"\bhot\b", r"\bcold\b", r"\boverdue\b", r"\bdue\b", r"\blucky\b", r"\brecommend\w*\b",
    r"\bpredict\w*\b", r"\bsignifican\w*\b", r"\bp-value\b", r"\bpvalue\b", r"\brank\w*\b",
    r"\bbest\b", r"\btop\b", r"\banomal\w*\b", r"\bstreak\b", r"\bbet\b", r"\bbets\b",
    r"\bbetting\b", r"\bbettor\b", r"\bticket\w*\b", r"\bwager\w*\b", r"\bpick\b", r"\bpicks\b",
    r"\bpicked\b", r"\bpicking\b", r"\bdeviat\w*\b",
]
BANNED_RE = re.compile("|".join(BANNED_PATTERNS), re.IGNORECASE)


def check_no_banned_words(text: str) -> None:
    for line in text.splitlines():
        m = BANNED_RE.search(line)
        if m:
            raise ValueError(f"banned word {m.group(0)!r} in line: {line!r}")


# ---------------------------------------------------------------------------
# Loader: same spec gate + ceiling + single-loader pattern as M3 (section 8.2: M4 primary <= 01190)
# ---------------------------------------------------------------------------

def check_spec_approval(root: Path):
    return eda_reporting.check_spec_approval(root)


def check_ceiling(through_draw: str, taskboard_path: Path) -> None:
    """M4 primary never accepts an override (section 8.2: the M4 primary ceiling is absolute; only
    the M4 replication phase, run once after M6 lock, uses draws above it, via a separate command)."""
    eda_reporting.check_ceiling(through_draw, override_ref=None, taskboard_path=taskboard_path)


def load_m4_draws(curated_dir: Path, through_draw: str) -> eda_reporting.AnalysisData:
    return eda_reporting.load_analysis_draws(curated_dir, through_draw)


# ---------------------------------------------------------------------------
# code_version (section 9.4)
# ---------------------------------------------------------------------------

def frozen_prefix_status_text(data: eda_reporting.AnalysisData) -> str:
    """n8: record the frozen dataset version next to source_dataset_version, so readers see why
    they differ when a later refresh (e.g. a live draw) changed the curated data's overall hash."""
    if data.source_dataset_version == FROZEN_DATASET_VERSION:
        return f"source_dataset_version matches the frozen split ({FROZEN_DATASET_VERSION}) directly."
    return (f"source_dataset_version is {data.source_dataset_version}, differing from the frozen split "
            f"{FROZEN_DATASET_VERSION} because later live draws were ingested. The frozen_prefix rule for "
            f"draws <=01401 is verified by the M2 quality report, not recomputed here, because the M4 loader "
            f"is ceiling-limited to draws <=01190. analysis_version {data.analysis_version} covers only "
            f"draws <=01190, which the ceiling guarantees.")


def code_version(root: Path) -> str:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception as exc:  # pragma: no cover - no git available
        return f"unknown ({exc})"


# ---------------------------------------------------------------------------
# Family table / decisions
# ---------------------------------------------------------------------------

def family_table(run: conf.ConfirmatoryRun, superseded: bool = False) -> pd.DataFrame:
    """superseded=True marks every row's decision "superseded_by_escalation" (m5): used for the
    R=10,000 table once an escalation to R=100,000 has been triggered, since section 6.1 says the
    escalated values are then final."""
    p_raw = [t.p_sim for t in run.family]
    p_holm = conf.holm(p_raw)
    rows = []
    for t, ph in zip(run.family, p_holm):
        decision = "superseded_by_escalation" if superseded else ("reject" if ph <= 0.05 else "not_reject")
        rows.append({
            "id": t.id, "hypothesis": t.hypothesis, "statistic": t.statistic, "null": t.null,
            "n": t.n, "N": t.N, "replicate_mean": t.replicate_mean,
            "R": t.R, "stream": t.stream, "p_sim": t.p_sim, "p_holm": ph,
            "decision": decision,
            "effect": json.dumps(t.effect, default=str, sort_keys=True),
        })
    return pd.DataFrame(rows)


def escalation_needed(fam_df: pd.DataFrame) -> bool:
    return bool(((fam_df["p_holm"] >= conf.ESCALATE_LO) & (fam_df["p_holm"] <= conf.ESCALATE_HI)).any())


def label_followups(followups: dict[str, pd.DataFrame], authoritative: pd.DataFrame,
                     superseded: bool = False) -> dict[str, pd.DataFrame]:
    """M1: every follow-up row carries an `interpretation` column stating whether its parent test
    rejected (with the parent's Holm-adjusted p) or not (then: "parent not rejected; not
    interpreted"). `authoritative` is the decision-bearing family table to gate on (the escalated
    table when escalation triggered, per m5)."""
    dec_map = authoritative.set_index("id")[["decision", "p_holm"]].to_dict("index")
    out: dict[str, pd.DataFrame] = {}
    for tid, fu in followups.items():
        fu = fu.copy()
        if superseded:
            label = "superseded by escalation; see the escalated follow-up table"
        else:
            info = dec_map.get(tid)
            if info is not None and info["decision"] == "reject":
                label = f"parent rejected (p_holm={info['p_holm']:.5f})"
            else:
                label = "parent not rejected; not interpreted"
        fu["interpretation"] = label
        out[tid] = fu
    return out


# ---------------------------------------------------------------------------
# Summary text (OBSERVED / STATISTICAL EVIDENCE / INTERPRETATION / LIMITATION)
# ---------------------------------------------------------------------------

_LIMITATIONS = [
    "This is a confirmatory run of pre-registered null hypotheses; a non-rejection is reported plainly and is not evidence that future draws can be forecast.",
    "No individual number or pair is named. Follow-up CSVs are always written for every parent test (not only when it rejects); each row carries an interpretation label, and only rows whose parent test rejected are interpreted, sorted by number, with no ordered list of numbers.",
    "Exploratory items (section 6.4) are unadjusted and are never a claim on their own.",
    "The MC escalation rerun (R=100000) applies only when triggered; both runs are reported when it is, and the R=100000 decisions are then final.",
    "This run uses draws 00001-01190 only; the replication on 01191-01401 and 00001-01401 happens once, after the M6 lock, and never changes this result.",
    "Nothing here is evidence that future draws can be forecast, and it never orders or selects numbers.",
]


def _observed_line(t: conf.TestResult) -> str:
    e = t.effect
    if t.id == "C1":
        return f"C1: dispersion ratio {e['dispersion_ratio']:.4f} (null approx 1); max|z| across numbers {e['max_abs_z']:.4f}."
    if t.id == "C2":
        return f"C2: ratio {e['ratio']:.4f} (null approx 1)."
    if t.id == "C3":
        vals = list(e["overlap_minus_null"].values())
        return f"C3: overlap minus null, min {min(vals):.4f} to max {max(vals):.4f} across lags 1-10 (per-lag values and CIs in the follow-up table)."
    if t.id == "C4":
        vals = list(e["overlap_minus_perm_mean"].values())
        return f"C4: overlap minus the PERM mean, min {min(vals):.4f} to max {max(vals):.4f} across lags 1-10 (per-lag values in the follow-up table)."
    if t.id == "C5":
        return f"C5: max|r_h| across lags 1-10 is {e['max_abs_r']:.4f} (per-lag CI half-width {e['ci_halfwidth']:.4f})."
    if t.id == "C6":
        return f"C6: {e['R_runs']} runs (mu={e['mu']:.2f}, n_plus={e['n_plus']}, n_minus={e['n_minus']}, ties dropped={e['n_ties']})."
    if t.id == "C7":
        return f"C7: Cramer's V {e['cramers_v']:.4f} (PERM mean {e['perm_mean_v']:.4f}, PERM 95% quantile {e['perm_q95_v']:.4f})."
    if t.id == "C8":
        return f"C8: V_roll {e['v_roll']:.4f} (PERM mean {e['perm_mean_v_roll']:.4f})."
    if t.id == "C9":
        lo, hi = e["ci95"]
        return f"C9: observed mean sum minus 168 is {e['mean_minus_168']:.4f} (95% CI {lo:.4f} to {hi:.4f})."
    if t.id == "C10":
        lo, hi = e["ci95"]
        return f"C10: observed mean range minus 40 is {e['mean_minus_40']:.4f} (95% CI {lo:.4f} to {hi:.4f})."
    if t.id in ("C11", "C12", "C13"):
        return f"{t.id}: w={e['w']:.4f}; observed mean minus expected {e['mean_minus_expected']:.4f}."
    return f"{t.id}: see the effect column of m4_results.csv."


def _interpretation_zero_reject(family: list[conf.TestResult], m: int) -> list[str]:
    """M2: fixed wording for the no-rejection case."""
    p_min = min(t.p_sim for t in family)
    min_ids = sorted(t.id for t in family if abs(t.p_sim - p_min) < 1e-12)
    holm_vals = conf.holm([t.p_sim for t in family])
    id_to_holm = {t.id: h for t, h in zip(family, holm_vals)}
    holm_for_min = [id_to_holm[i] for i in min_ids]
    approx = 1 - (1 - p_min) ** m
    lines = [
        "No confirmatory evidence against H1-H5 on 00001-01190 at family-wise error rate 0.05 (Holm).",
        "Non-rejection is not proof that the null hypotheses hold.",
        (f"The smallest raw p in the family is {p_min:.3f} ({', '.join(min_ids)}); its Holm-adjusted p "
         f"is {min(holm_for_min):.3f}"
         + (f"-{max(holm_for_min):.3f}" if max(holm_for_min) != min(holm_for_min) else "")
         + f"; it does not survive the pre-registered multiplicity control. Under {m} tests in the family, "
           f"a raw p this small occurring somewhere by chance alone has probability approximately {approx:.2f}."),
    ]
    return lines


def render_summary(run: conf.ConfirmatoryRun, fam_df: pd.DataFrame, data: eda_reporting.AnalysisData,
                    spec_version: str, spec_sha256: str, code_ver: str, escalated: bool,
                    fam_df_escalated: pd.DataFrame | None, runtime_seconds: float,
                    followups_labeled: dict[str, pd.DataFrame],
                    followups_escalated_labeled: dict[str, pd.DataFrame] | None,
                    frozen_dataset_version: str, frozen_prefix_status: str,
                    run_escalated: conf.ConfirmatoryRun | None = None) -> str:
    authoritative = fam_df_escalated if (escalated and fam_df_escalated is not None) else fam_df
    authoritative_followups = followups_escalated_labeled if (escalated and followups_escalated_labeled is not None) else followups_labeled
    authoritative_family = run_escalated.family if (escalated and run_escalated is not None) else run.family
    m = len(authoritative)

    lines = ["# M4 confirmatory summary", ""]
    lines.append("## Parameters")
    lines.append(f"source_dataset_version: {data.source_dataset_version}")
    lines.append(f"analysis_version: {data.analysis_version}")
    lines.append(f"frozen_dataset_version: {frozen_dataset_version}")
    lines.append(f"frozen_prefix_status: {frozen_prefix_status}")
    lines.append(f"through_draw: {data.through_draw}")
    lines.append(f"n_draws: {data.n_draws}")
    lines.append(f"spec_version: {spec_version}")
    lines.append(f"spec_sha256: {spec_sha256}")
    lines.append(f"code_version: {code_ver}")
    lines.append(f"seed: {run.seed}")
    lines.append(f"R: {run.R}")
    lines.append(f"streams: {run.streams}")
    lines.append(f"runtime_seconds: {runtime_seconds:.1f}")
    lines.append(f"escalated: {escalated}")
    lines.append("")

    lines.append("## OBSERVED")
    lines.append("Draw-level, number-level and year/window statistics were computed on the 00001-01190 analysis draws, "
                  "as defined in SPECIFICATION section 6.2 (C1-C13). Observed effect sizes, per test:")
    for t in run.family:
        lines.append(_observed_line(t))
    lines.append("")

    lines.append("## STATISTICAL EVIDENCE")
    for _, row in fam_df.iterrows():
        lines.append(f"{row['id']} ({row['hypothesis']}): n {row['n']}, N {row['N']}, statistic {row['statistic']:.4f}, "
                      f"replicate mean {row['replicate_mean']:.4f}, null {row['null']}, R {row['R']}, "
                      f"p_sim {row['p_sim']:.5f}, p_holm {row['p_holm']:.5f}, decision {row['decision']}.")
    if escalated and fam_df_escalated is not None:
        lines.append("")
        lines.append("MC escalation (R=100000) was triggered because a Holm-adjusted p fell in [0.04, 0.06]. "
                      "The R=10000 table above is superseded; the escalated table below is final (m5):")
        for _, row in fam_df_escalated.iterrows():
            lines.append(f"{row['id']} ({row['hypothesis']}): n {row['n']}, N {row['N']}, statistic {row['statistic']:.4f}, "
                          f"replicate mean {row['replicate_mean']:.4f}, null {row['null']}, R {row['R']}, "
                          f"p_sim {row['p_sim']:.5f}, p_holm {row['p_holm']:.5f}, decision {row['decision']}.")
    lines.append("")

    lines.append("## INTERPRETATION")
    n_reject = int((authoritative["decision"] == "reject").sum())
    if n_reject == 0:
        lines.extend(_interpretation_zero_reject(authoritative_family, m))
    else:
        lines.append(f"{n_reject} of {m} confirmatory tests reject their null at the pre-registered "
                     f"family-wise error rate of 0.05 (Holm). Rejections are reported as statistical evidence "
                     f"against the corresponding null hypothesis over the analysis period only.")
    for _, row in authoritative.iterrows():
        if row["decision"] == "reject":
            fu = authoritative_followups.get(row["id"]) if authoritative_followups else None
            if fu is not None and "p_holm" in fu.columns:
                n_fu_sig = int((fu["p_holm"] <= 0.05).sum())
                lines.append(f"{row['id']}: parent rejected; {n_fu_sig} of {len(fu)} follow-up items reject "
                             f"after Holm within that set.")
    lines.append("")

    lines.append("## LIMITATION")
    for t in _LIMITATIONS:
        lines.append(f"- {t}")
    lines.append("")

    text = "\n".join(lines)
    check_no_banned_words(text)
    return text


# ---------------------------------------------------------------------------
# Write outputs
# ---------------------------------------------------------------------------

CSV_KWARGS = dict(index=False, lineterminator="\n", float_format="%.10g", encoding="utf-8")


def _library_versions() -> dict:
    return {"numpy": np.__version__, "scipy": scipy.__version__, "pandas": pd.__version__}


def write_m4(run: conf.ConfirmatoryRun, fam_df: pd.DataFrame, data: eda_reporting.AnalysisData,
             spec_version: str, spec_sha256: str, code_ver: str, escalated: bool,
             fam_df_escalated: pd.DataFrame | None, run_escalated, runtime_seconds: float,
             out_dir: Path) -> Path:
    dirname = f"through_{data.through_draw}"
    final_dir = Path(out_dir) / dirname
    tmp_dir = Path(out_dir) / (dirname + ".tmp")
    if tmp_dir.exists():
        for p in sorted(tmp_dir.glob("*"), reverse=True):
            p.unlink()
        tmp_dir.rmdir()
    tmp_dir.mkdir(parents=True, exist_ok=True)

    file_hashes: dict[str, str] = {}

    def _write_csv(name: str, df: pd.DataFrame):
        df = df.copy()
        df["source_dataset_version"] = data.source_dataset_version
        df["analysis_version"] = data.analysis_version
        df["through_draw"] = data.through_draw
        path = tmp_dir / f"{name}.csv"
        df.to_csv(path, **CSV_KWARGS)
        file_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()

    # M1: label every follow-up row (gated on the AUTHORITATIVE decision table: the escalated one
    # once escalation triggers, per m5).
    authoritative = fam_df_escalated if (escalated and fam_df_escalated is not None) else fam_df
    followups_labeled = label_followups(run.followups, authoritative, superseded=escalated)
    followups_escalated_labeled = None

    _write_csv("m4_results", fam_df)
    for tid, fu in followups_labeled.items():
        _write_csv(f"m4_followup_{tid}", fu)
    if escalated and fam_df_escalated is not None:
        _write_csv("m4_results_escalated", fam_df_escalated)
        followups_escalated_labeled = label_followups(run_escalated.followups, fam_df_escalated, superseded=False)
        for tid, fu in followups_escalated_labeled.items():
            _write_csv(f"m4_followup_{tid}_escalated", fu)

    frozen_status = frozen_prefix_status_text(data)
    summary_text = render_summary(run, fam_df, data, spec_version, spec_sha256, code_ver, escalated,
                                   fam_df_escalated, runtime_seconds, followups_labeled,
                                   followups_escalated_labeled, FROZEN_DATASET_VERSION, frozen_status,
                                   run_escalated=run_escalated)
    summary_path = tmp_dir / "summary.md"
    summary_bytes = summary_text.encode("utf-8")
    summary_path.write_bytes(summary_bytes)
    file_hashes[summary_path.name] = hashlib.sha256(summary_bytes).hexdigest()

    def _clean_exploratory(d):
        if isinstance(d, dict):
            return {k: _clean_exploratory(v) for k, v in d.items()}
        if isinstance(d, np.floating):
            return float(d)
        if isinstance(d, np.integer):
            return int(d)
        return d

    manifest = {
        "spec_version": spec_version,
        "spec_sha256": spec_sha256,
        "code_version": code_ver,
        "source_dataset_version": data.source_dataset_version,
        "analysis_version": data.analysis_version,
        "frozen_dataset_version": FROZEN_DATASET_VERSION,
        "frozen_prefix_status": frozen_status,
        "through_draw": data.through_draw,
        "n_draws": data.n_draws,
        "seed": run.seed,
        "streams": run.streams,
        "R": run.R,
        "escalated": escalated,
        "escalation_streams": {"fresh": conf.STREAM_FRESH_ESCALATE, "perm": conf.STREAM_PERM_ESCALATE} if escalated else None,
        "runtime_seconds": runtime_seconds,
        "library_versions": _library_versions(),
        "exploratory": _clean_exploratory(run.exploratory),
        "files": {},
    }

    manifest["files"] = {k: file_hashes[k] for k in sorted(file_hashes)}
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
    manifest_path = tmp_dir / "m4_manifest.json"
    manifest_path.write_bytes(manifest_bytes)

    if final_dir.exists():
        for p in sorted(final_dir.glob("*"), reverse=True):
            p.unlink()
        final_dir.rmdir()
    os.replace(tmp_dir, final_dir)
    return final_dir


# ---------------------------------------------------------------------------
# Top-level orchestration used by the CLI
# ---------------------------------------------------------------------------

def run_m4(paths: Paths, through_draw: str, out_dir: Path, R: int = conf.R_DEFAULT) -> int:
    t0 = time.time()
    try:
        spec_version, spec_sha256 = check_spec_approval(paths.root)
    except eda_reporting.EdaSpecNotApproved as exc:
        log.warning("m4_spec_not_approved", extra={"detail": str(exc)})
        return 2

    taskboard_path = paths.root / "docs" / "TASKBOARD.md"
    try:
        check_ceiling(through_draw, taskboard_path)
    except eda_reporting.EdaCeilingRefused as exc:
        log.warning("m4_ceiling_refused", extra={"through_draw": through_draw, "detail": str(exc)})
        return 2

    try:
        data = load_m4_draws(paths.curated, through_draw)
    except eda_reporting.EdaLoadError as exc:
        log.error("m4_load_error", extra={"detail": str(exc)})
        return 2

    obs = conf.build_observed(data.frame, tables.MAIN_COLS)
    run = conf.run_family(obs, R=R, seed=conf.SEED, fresh_stream=conf.STREAM_FRESH, perm_stream=conf.STREAM_PERM)
    fam_df = family_table(run)

    escalated = escalation_needed(fam_df)
    run_escalated = None
    fam_df_escalated = None
    if escalated:
        log.warning("m4_escalation_triggered", extra={"through_draw": through_draw})
        run_escalated = conf.run_family(obs, R=conf.R_ESCALATE, seed=conf.SEED,
                                         fresh_stream=conf.STREAM_FRESH_ESCALATE, perm_stream=conf.STREAM_PERM_ESCALATE)
        fam_df_escalated = family_table(run_escalated, superseded=False)
        # m5: once escalation triggers, the R=100,000 decisions are final; the R=10,000 table's
        # own decision column is marked superseded rather than reporting its own (now-superseded)
        # reject/not_reject call.
        fam_df = family_table(run, superseded=True)

    runtime_seconds = time.time() - t0
    code_ver = code_version(paths.root)
    write_m4(run, fam_df, data, spec_version, spec_sha256, code_ver, escalated, fam_df_escalated,
             run_escalated, runtime_seconds, out_dir)
    return 0
